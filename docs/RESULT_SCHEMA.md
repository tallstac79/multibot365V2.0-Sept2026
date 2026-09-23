# Result and audit storage schema

Store: `.local/pipeline.sqlite3` (untracked, WAL mode). The schema is defined in
`core/pipeline_store.py`, and the version is kept in `meta.schema_version` (currently 1).
The dashboard opens it read-only. Existing evidence files and ledgers are untouched: result
evidence is referenced by relative path under `evidence/`.

## `instructions` (one row per instruction_id; the audit record)

| Column | Source |
|---|---|
| instruction_id | Deterministic ID (primary key) |
| origin | `production` or `sample` |
| intake_id, chat_id, message_id | Telegram source identity (message ID = Telegram source ID) |
| raw_alert | Exact formatted source text |
| normalized_alert | The parser output, unaltered (JSON) |
| rules_result | The full rules decision with all checks (JSON) |
| selection_key | Content dedupe key |
| sport, competition, fixture, home, away, event_time | From the parsed alert |
| market, selection, selection_name, line, alternate_line | Target (`selection` = side) |
| alert_price, minimum_price, observed_price, stake, displayed_ev | Prices are decimal strings with their original precision |
| device_id, session_state | Device, and the session observed at dispatch or in the result |
| state, terminal, failure_reason, device_stage | Canonical state, the exact stored reason, and the original device stage |
| dispatch_payload | The exact coordinator request sent (JSON) |
| result_payload | The exact device result received (JSON) |
| evidence | Evidence paths reported by the device (JSON list) |
| received_at, parsed_at, rules_applied_at, queued_at, dispatched_at, device_active_at, ready_at, completed_at | Stage timestamps (UTC, ms) |
| duration_ms | completed_at − received_at |
| dispatch_attempts | Always 0 or 1 |

## Other tables

| Table | Content |
|---|---|
| intake_messages | Every delivered message. See [TELEGRAM_INGESTION.md](TELEGRAM_INGESTION.md). |
| transitions | Every state change: from, to, at, actor, reason, detail |
| audit_events | TRANSITION_REFUSED, TRANSITION_CONFLICT, SUBMIT_UNCERTAIN, COORDINATOR_ACK, RESULT_POLL_FAILED, MALFORMED_RESULT, LATE_OR_DUPLICATE_RESULT_IGNORED, MALFORMED_SESSION_REPORT, PIPELINE_START, ... |
| device_state | Latest coordinator health per device (ONLINE, DEGRADED or OFFLINE, with error and payload) |
| session_state / session_history | Latest session per device, plus each change |
| intake_checkpoint | Per-chat first-start mark (history below it is out of scope) |
| notifications | Outbox: (instruction_id, state) unique, text, attempts, sent_at, last_error |

## Useful queries

```sql
SELECT instruction_id, state, failure_reason, fixture, market, selection, line, alert_price,
       observed_price, stake, received_at, completed_at, duration_ms
FROM instructions ORDER BY received_at DESC LIMIT 50;

SELECT * FROM transitions WHERE instruction_id = 'on-…' ORDER BY id;
```

`python -m tools.pipeline_service status` prints counts by intake status and lifecycle
state, device and session state, and the number of pending notifications.
