# Automatic approval (approval_mode)

Code: `core/final_action.py` (`automatic_checks`, `auto_approve`, `decision_record`), `core/pipeline.py`
(`Settings.approval_mode`, hold freshness and worker binding at dispatch, `PRE_TAP_REJECTED` / `PLACED`
records), `core/pipeline_store.py` (schema v7), `core/status_notifier.py` (concise messages),
`tools/pipeline_service.py` (`mode`, `decision`). Phone: `WorkerIdentity.java`, health fields `worker_id`
and `account_fingerprint`. Tests: `tests/test_automatic_approval.py`.

## Modes

| `pipeline.approval_mode` | Behaviour after the phone verified a slip (READY / SLIP_READY) |
|---|---|
| `manual` (default) | `AWAITING_APPROVAL`; Telegram "APPROVAL NEEDED"; the operator replies `/approve` within `approval_timeout_seconds` |
| `automatic` | the backend evaluates `automatic_checks`; all pass: `APPROVED` by `automatic-policy` with a durable `AUTO_APPROVED` audit record and the `PLACE_HELD` final action is sent on the same tick; any failure: `REJECTED` (`AUTO_APPROVAL_REFUSED: <checks>`), nothing sent |

`auto_approve: true` is the legacy spelling of `approval_mode: automatic`. `AWAITING_APPROVAL` is never
entered in automatic mode and no Telegram reply is ever waited for. `/approve` and `/reject` stay available
for manual mode; in automatic mode a bare `/approve` answers "nothing is awaiting approval".

## Flow

```
ALERT -> QUALIFIED (QUEUED) -> hold run on the phone (event link, identity, grid, slip, stake, To Return)
      -> SLIP_READY (READY) -> AUTO_APPROVED (APPROVED, actor automatic-policy, audit AUTO_APPROVED)
      -> PLACE_HELD "<id>-place" (fresh pre-tap verification on the phone: login, one selection, both teams and
         full-game market inside the slip, current line and price against the ORIGINAL alert's tolerance, stake and
         To Return, competition and kick-off in the header, event not started, Place Bet present)
      -> ONE tap -> receipt (audit PLACED) -> My Bets verification (audit RECONCILED) -> HOME / IDLE -> next alert
```

A pre-tap refusal ends in the categorical terminal state the phone reported (`PRICE_CHANGED`, `TARGET_NOT_FOUND`,
`REJECTED`, `SESSION_REQUIRED` ...) with `failure_reason` prefixed `PRE_TAP_REJECTED:` and an audit event
`PRE_TAP_REJECTED`; the held slip is released with `RESET_BETSLIP`. No new lifecycle state was added: the
state machine is unchanged (`READY -> APPROVED` existed for auto-approval); the decision source is recorded
in `approved_by`, `approval_mode`, `auto_approved_at`, `execution_job_id`, `strategy_version`, `rules_version`
and the audit events.

## What the automatic policy checks (all from persisted records, before anything is sent)

authorised production source and chat; sharp signal IDENTIFIED from Pinnacle opening -> current and its side equals
the selection; production-verified basketball market mapping; rules re-evaluated at the verification time (market
enabled, not stale, event not started, price bounds); the hold succeeded (`held`, `PASS`); identity verdict
EXACT / CANONICAL_MATCH / ALIAS_MATCH / HIGH_CONFIDENCE_EVENT_MATCH with home, away, competition, kick-off and period;
period FULL_GAME; market and side equal the instruction; the alert-to-live comparison acceptable (net-payout 10 %,
spread min(1.0, 10 % of |handicap|), totals 1.0 point, improvements accepted, always against the original alert);
slip stake equals the instruction stake; session AUTHENTICATED and fresh; worker ONLINE and healthy;
`worker_id` equals `expected_worker_id`; `account_fingerprint` equals `expected_account_fingerprint`; the phone's
own final-action permission armed; kill switch off; dispatch and final action enabled; stake and daily limits;
no other execution of the same selection; no unresolved placement (PLACEMENT_UNKNOWN / UNKNOWN bets) and nothing
else in flight. Unset `expected_worker_id` / `expected_account_fingerprint` refuse every automatic approval.

The phone then repeats its own verification on `PLACE_HELD` (`Bet365LiveAdapter.place_held`), consumes only its
own durable hold (`HeldInstruction.verify`, within 120 s; the backend refuses older holds at
`hold_max_age_seconds` = 115 s), requires its local final-action permission (`CoordinatorConfig.finalActionArmed`)
and taps once (`tapPlaceBetOnce`: intent persisted first, `t_tap_ms`, never repeated).

## Persistence

`instructions`: `approval_mode`, `auto_approved_at`, `approved_by`, `execution_job_id` (`<instruction_id>-place`,
the durable device job id), `strategy_version`, `rules_version`, `intent_at` (phone `t_tap_ms`),
`reconciliation_result` (`FOUND_IN_MY_BETS`, `NOT_FOUND_IN_MY_BETS`, `MANUAL_CHECK_REQUIRED`). `bets`: requested,
pre-tap verified and receipt-confirmed line / odds / stake, reference, status. `audit_events`: `AUTO_APPROVED`
(the complete record: mode, decided_by, versions, worker, account, requested and device-verified terms, stake,
every check), `AUTO_APPROVAL_REFUSED`, `PRE_TAP_REJECTED`, `PLACED`, `RECONCILED`.
`python -m tools.pipeline_service decision <id>` prints the whole record.

## Telegram (notification and emergency control only)

QUALIFIED, AUTO APPROVED, PRE-TAP REJECTED (with reason), BET PLACED (receipt terms and reference), REJECTED and the
other terminal states, SESSION REQUIRED, PLACEMENT UNCERTAIN, RECONCILED, BET SETTLED. Each is one outbox row per
(instruction, state), so restarts never double-send. `/stop`, `/resume`, `/status` remain.

## Idempotency (proved in tests/test_automatic_approval.py and tests/test_final_action.py)

duplicate OddsNotifier delivery and the same selection from a new message are intake DUPLICATE; a backend restart
between approval and action sends exactly one final action and a restart after the dispatch only polls; a phone
that echoes DUPLICATE for the job id is waited for, never resent; a lost result after the action becomes
PLACEMENT_UNKNOWN and is reconciled through My Bets, never re-executed; a stale hold is refused.

## Switching modes and arming (configuration only, no code change)

```bash
python -m tools.pipeline_service mode automatic     # or: mode manual   (edits .local/pipeline.json)
```
then restart the service so it re-reads the file. Continuous automatic operation needs, in `.local/pipeline.json`
`pipeline`: `approval_mode: "automatic"`, `dispatch_enabled: true`, `final_action_enabled: true`,
`final_action_one_shot: false`, `expected_worker_id` and `expected_account_fingerprint` copied from the phone's
health (`worker_id`, `account_fingerprint`); the kill switch released (`python -m tools.pipeline_service resume`);
and the phone's persistent local execution permission enabled on the phone's settings screen (`LocalExecution`,
0.9.22: stays enabled across app, Chrome and phone restarts until disabled there; revoked automatically when the
worker id or the account fingerprint it was granted for changes; never settable over HTTP, by the backend, Telegram or
session recovery; reported in `/health` as `local_execution` and on the dashboard). Manual mode: `approval_mode:
"manual"` with the same switches; the operator replies `/approve`.

## Search fallback (0.9.22)

Direct event links stay the primary route. When the phone must search, the ladder is deterministic and logged
(`search_query_ladder`, `search_candidate_used` with `source`): the raw feed names, then the bookmaker's own names
supplied with the instruction as `aliases` (the backend's event cache for this fixture and kick-off, and approved
competition-scoped aliases; e.g. Landstede Hammers -> Landstede Zwolle recorded from a verified page on 26 Sep 2026),
then club-prefix forms. Nothing is promoted because Search returned something; every result still passes the strict
event identity (both teams, kick-off, competition, markers, sport) and more than one plausible fixture fails closed.
The competition gate accepts the bookmaker's country-prefixed header ("Mexico Liga ABE" for feed "Liga ABE" from
Mexico, sent as `country`) and the approved table `EventIdentity.COMPETITION_ALIASES` (Poland "1. Liga" -> "Poland 1st
Division"); nothing fuzzy.
