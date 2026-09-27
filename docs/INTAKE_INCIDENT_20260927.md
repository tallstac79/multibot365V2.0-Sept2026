# Missing Feed 1 output, 27 September 2026 at 18:56 London

The listener did not stall. All three messages reached SQLite within 0.71 seconds. The classifier returned
`PARSED_PARTIAL` because each stored Bet365 hyperlink is an in-play `#/IP/` route. No instruction was created.
The notification worker projected only instructions and downstream records, leaving no outbox entry for an
intake-only rejection. The root cause of the silence was this missing reporting path.

| Fixture | Telegram message (Feed 1 / 1645770730) | Intake ID | Source time, London | Received delay | Classifier | Instruction | Recovered outbox |
|---|---:|---:|---|---:|---|---|---:|
| RB Bragantino vs Bandeirante | 71943 | 2582 | 18:56:00 | 707 ms | PARSED_PARTIAL | none | 831 |
| CSE vs CSA | 71944 | 2583 | 18:56:02 | 680 ms | PARSED_PARTIAL | none | 832 |
| San Luis FC vs Lanus | 71945 | 2584 | 18:56:05 | 718 ms | PARSED_PARTIAL | none | 833 |

Exact stored reason for all three: `Bet365 link is an in-play page; pre-match identity cannot be verified, no executable target`.
Their URL event tokens are respectively EV151391536192C1, EV151391717852C1 and EV151391536162C1.
The payloads show a 19:00 fixture label, but this repair does not reinterpret that label or the in-play URLs.

## Repair

`core/intake_notifications.py` adds a reporting projection for production PARSED_PARTIAL / AMBIGUOUS / INVALID
rows without an instruction. Messages say `MISSED — <stored reason>` and retain fixture, source message and intake ID.
It uses the existing notification outbox, retry worker and uniqueness constraint. Namespaced `intake-<id>` outbox
keys do not create execution instructions. Duplicates, edits, samples and ordinary ignored channel messages do not notify.

A persistent baseline prevents historical flooding; it is established before the listener starts, so new catch-up
messages are covered. An explicit audited backfill queued only intake IDs 2582–2584. Retry behavior remains unchanged;
as with the existing sender, remote success followed by a local process crash cannot guarantee exactly-once Telegram delivery.

`core/telegram_intake.py` now records catch-up completion, reconciliation start/completion/count and per-feed successful
poll timestamps/latest IDs. A quiet feed now has positive heartbeat evidence. A failed poll never claims completion.

The running backend had already reloaded these reporting changes during a concurrent operator update at 19:16:25 London;
no additional backend restart was required. Both subscriptions were independently polled successfully at 19:18:30 London.
Feed 2 also delivered a fresh event at 19:18:21. Backend and listener errors were null, reconnect count zero.
All three incident notifications were accepted by Telegram on the first attempt at 19:18:20 London.
Outbox backlog, active instructions and incomplete reconciliations were all zero at verification.
No rate-limit error was recorded for these sends.

No strategy, staking, tolerance, classification, approval or phone-execution code was changed by this repair.
The pipeline configuration SHA-256 remained `d5beee900cd870658a64ddb0490af1c28d004ef3746b60613cd0f2630481682d`.
The concurrent operator's separate daily-cap commit is not part of this repair.

## Validation

116 tests passed across intake/notification, live-failure, automatic-approval, final-action and operator-command suites.
Eight new tests cover the actual three stored messages, unchanged classification/no instruction, deduplication across
restart, scoped historical repair, ignored/sample/edit exclusion, invalid/ambiguous reasons, delivery retry, both quiet
feed heartbeats and failed-poll heartbeat semantics. The existing edit-only test now isolates its event from its unrelated
50 ms reconciliation timer; reconciliation/redelivery behavior remains covered by its dedicated test.

Evidence: `evidence/intake-notifications/20260927-1856.json` (stored source/classifier records) and
`evidence/intake-notifications/delivery-verification.json` (outbox acknowledgements and live heartbeat snapshot).
