# Instruction lifecycle and idempotency

Code: `core/lifecycle.py` (states, transition rules, mappings), `core/pipeline_store.py`
(persistence), `core/pipeline.py` (orchestration). The database `.local/pipeline.sqlite3`
is the single source of truth. Telegram notifications and the dashboard only read it.

## States

```
RECEIVED -> PARSED -> RULES_APPLIED -> QUEUED -> DISPATCHED -> [DEVICE_ACTIVE] -> READY
                                  \          \            \                    \
                                   +----------+------------+--------------------+--> TERMINAL
```

Terminal states: `COMPLETED`, `REJECTED`, `PRICE_CHANGED`, `SUSPENDED`, `STALE`,
`TARGET_NOT_FOUND`, `AMBIGUOUS_TARGET`, `SESSION_REQUIRED`, `DEVICE_OFFLINE`, `TIMEOUT`,
`DUPLICATE`, `UNKNOWN`.

* Progress only moves forward. Any non-terminal state may end in any terminal state.
* Terminal is final. A refused transition is recorded in `audit_events`
  (`TRANSITION_REFUSED`) and changes nothing.
* Every transition is a row in `transitions` with `from_state`, `to_state`, `at` (UTC ms),
  `actor` and `reason`. It also sets the matching column on the instruction row
  (`parsed_at`, `queued_at`, `dispatched_at`, `ready_at`, `completed_at`, ...).
  `duration_ms` = `completed_at` minus `received_at`.
* Instructions exist only for `PARSED` intake. The other intake statuses (AMBIGUOUS,
  INVALID, DUPLICATE, IGNORED) are kept on the intake row with their reason.

| Step | Actor | Outcome |
|---|---|---|
| Ingest | intake/parser | RECEIVED → PARSED |
| Rules | rules engine | RULES_APPLIED, then QUEUED, REJECTED or STALE |
| Pre-dispatch recheck | dispatcher | Stale/rules checks again: STALE or REJECTED |
| Device gate | dispatcher | Unreachable or unhealthy coordinator → DEVICE_OFFLINE |
| Session gate | dispatcher | Anything but a fresh AUTHENTICATED report → SESSION_REQUIRED |
| Dispatch | dispatcher | DISPATCHED is committed **before** the request is sent |
| Acknowledgement | coordinator | ACCEPTED → DEVICE_ACTIVE; refused admission → REJECTED |
| Device result | coordinator | See the mapping table below |
| READY expiry | dispatcher | Not confirmed within `ready_timeout_seconds` (default 300 s) → STALE |
| No result | dispatcher | No result within `result_timeout_seconds` (default 240 s) → TIMEOUT, never re-dispatched |
| Confirmation | confirmation worker | The DecisionStatus is mapped (below). APPROVED is outside this pipeline. |

## Mapping existing backend enums (reused, not duplicated)

The original device `stage` is always kept in `device_stage`, and the full payload in
`result_payload`. The failure reason is `STAGE: detail`, exactly as the device sent it.

| Coordinator/live-adapter result | Canonical state |
|---|---|
| PASS with `wager_submitted: true` | COMPLETED |
| PASS with a READY state or READY_STATE / COMPLETE_EXECUTION_READY | READY |
| PASS with neither | UNKNOWN (no evidence) |
| DUPLICATE | Not terminal. It echoes the original; polling continues. |
| PRICE_CHANGED, BELOW_MINIMUM, LINE_CHANGED, SELECTION_CHANGED | PRICE_CHANGED |
| SUSPENDED, UNAVAILABLE | SUSPENDED |
| TARGET_NOT_FOUND, NO_FIXTURE_FOUND, WRONG_EVENT, EVENT_NOT_VERIFIED | TARGET_NOT_FOUND |
| AMBIGUOUS_FIXTURE | AMBIGUOUS_TARGET |
| INVALID_INSTRUCTION, STAKE_REJECTED, INSUFFICIENT_BALANCE | REJECTED |
| LOGIN_FAILED, SESSION_REQUIRED | SESSION_REQUIRED |
| TIMEOUT | TIMEOUT |
| INTERNAL_ERROR, CLICK_FAILED, FOCUS_FAILED, INPUT_FAILED, TEXT_NOT_VERIFIED, anything new | UNKNOWN |
| Malformed payload (not an object, no PASS/FAIL+stage, mismatched ID) | UNKNOWN, with `MALFORMED_RESULT` audited |

| Confirmation `DecisionStatus` | Canonical state |
|---|---|
| REJECTED | REJECTED |
| EXPIRED | STALE |
| DUPLICATE | DUPLICATE |
| PRICE_INVALID | PRICE_CHANGED |
| STATE_INVALID, INTERNAL_ERROR | UNKNOWN |
| TIMEOUT | TIMEOUT |

## Idempotency guarantees

`instruction_id` is authoritative and deterministic:
`on-` + sha256(["OddsNotifier", origin, chat_id, message_id])[:24]. Sample origin uses
`sample-on-`. The same Telegram message always yields the same ID, on any machine, after
any restart. The ID satisfies the coordinator ID rule (letters, digits and hyphens, at most
64 characters).

| Hazard | Protection |
|---|---|
| Duplicate Telegram delivery | Unique intake identity. The repeat is recorded as DUPLICATE; no second instruction. |
| Same alert re-posted as a new message | Selection key (sport, fixture, time, market, side, line). DUPLICATE if the selection is pending at the same price, dispatched, READY or COMPLETED. A different price supersedes a *pending* instruction (the old one becomes STALE). |
| Retry after uncertain send | The same ID only (coordinator client). After a restart nothing is resent; in-flight work is only polled. |
| Crash after dispatch | DISPATCHED is committed before sending. The restart polls; it never resends (tested with a simulated crash). |
| Lost device response | Polling repeats GET for the same ID. No result by the deadline → TIMEOUT (terminal). |
| Late or duplicate result | A terminal row is never changed. `LATE_OR_DUPLICATE_RESULT_IGNORED` is audited. |
| Concurrent processes | `BEGIN IMMEDIATE` transactions plus compare-and-set `UPDATE ... WHERE state=? AND terminal=0` |
| Notification repeats | Outbox is `UNIQUE(instruction_id, state)`, and the row is claimed before it is sent |

## Dispatch safety

`dispatch_enabled` is **false** by default. When it is false, nothing is sent and queued
work ages out as STALE. When it is enabled, the pipeline sends only the existing live
adapter's READY-only request: `execution_mode: "ready"`, never `confirmation_status`. The
proven adapter therefore stops before its final action. Final action and confirmation stay
with the existing, separately gated components. One instruction is in flight at a time.
