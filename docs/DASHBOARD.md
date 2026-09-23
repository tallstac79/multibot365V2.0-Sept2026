# MultiBot365 read-only operations dashboard

## Start

From `C:\Users\WINDOWS11\Desktop\MultiBotV2.0\MultiBot365`:

```powershell
python -m pip install -r dashboard/requirements.txt
python -m dashboard
```

Open http://127.0.0.1:8780. Python 3.11 was used for acceptance. No USB/ADB,
Android rebuild, npm or external CDN is required. Ctrl+C stops a foreground server.
No startup task is installed. The existing five sections/layout are retained.

Default bind: **127.0.0.1:8780**. The existing phone endpoint remains private HTTP
**8767**. There are no execution, approval, notification-send, or phone-control APIs.
The only dashboard write endpoint saves decision-support configuration.

Explicit trusted LAN use: `python -m dashboard --host 192.168.1.50 --port 8780`
(replace with the mini PC private IP). That host is allowed automatically. Optional
`DASHBOARD_ALLOWED_HOSTS` accepts comma-separated exact private DNS names. Host checks
and same-origin browser writes remain enforced. LAN clients can read evidence and
edit recommendations; there is no authentication. Do not expose/port-forward publicly.
Startup does not alter firewall or Tailscale configuration.

## Data sources and modes

**REAL DATA is the default.** Alerts read `.local/oddsnotifier.sqlite3` using SQLite
`mode=ro`. Opening the dashboard does not create or populate an alert database.
Missing source means empty; corrupt/unreadable source returns an explicit error,
never sample fallback. `core/observation_store.py` provides the optional producer
boundary around the existing parser; the Telegram listener/legacy bets database
are untouched. Production records are distinguished from sample records by origin;
synthetic provenance or mapping profiles are excluded even in mislabeled envelopes.

Four genuine Feed 2 messages were read from the user's signed-in Telegram tab and
captured in `evidence/dashboard/telegram-basketball-observed.json`: message IDs
67894, 67895, 67897, 67898 in chat 1475314653. They are now stored locally and appear
in REAL DATA. This is an **explicit recorded snapshot**, not an always-on feed.
The snapshot contains only relevant message text, links, numeric bold emphasis and
source metadata, not account credentials or other chats. Browser-rendered links
and numeric bold are represented as Markdown. The original pasted fixtures remain
unaltered in `tests/fixtures/`.

Reproduce the snapshot import from a clean local database:

```powershell
python -m tools.import_oddsnotifier_records evidence/dashboard/telegram-basketball-observed.json
```

Import is a separate producer operation, never a side effect of mode switching or
refresh. Reimporting the same chat/message identity records DUPLICATE and yields no
new recommendation. Unknown Telegram source timestamps stay null: the browser
exposed only a local date/time label. Received time is explicitly the snapshot's
local ingestion time, with original displayed time retained in provenance. No
coordinator instruction ID has been assigned to these observations.

The future producer can call `core.observation_store.record_alert` with raw text,
explicit production/sample origin, chat/message IDs, received time, source timestamp
(if known), parser profile and provenance. Only recorded stages enter its timeline.
There is no network listener added in this milestone.

**SAMPLE DATA** replays the manifest fixtures, including genuine captured examples
clearly identified as fixture replays. It also includes synthetic football 1X2
HOME/DRAW/AWAY, spread/totals, basketball markets and malformed/ambiguous/duplicate/
stale/ignored cases. It never inserts into the production alert store. SAMPLE history
contains existing backend test captures. Live health and actual application logs
remain real in either mode.

## Health and device status

`dashboard.services.Health` calls the existing `tools.coordinator_client.Client`
GET /health using ignored `.local/coordinator.json`. Tokens never reach the UI.
Health polling: 10 seconds; shared cache: 5 seconds; existing HTTP timeout: 5 seconds.
The existing Tailscale CLI's read-only `status --json` supplies peer status, node ID,
and MagicDNS names. No transport or phone-side changes are made.

Coordinator ONLINE means reachable and healthy; DEGRADED means reachable but unhealthy;
OFFLINE means unreachable. Samsung is DEGRADED when its Tailscale peer is online but
the agent endpoint is unavailable, OFFLINE when neither can establish availability,
and follows the agent health when reachable. Agent and network states stay separate.
Device identity uses coordinator device_id when exposed; otherwise the Tailscale
node ID is labelled **Tailscale node ID**, never presented as an Android serial.
Mini PC and Samsung MagicDNS names come from current network/config data.

Coordinator version, heartbeat, uptime, agent state, current instruction and latest
result are rendered directly from health when available. Unexposed fields remain
unavailable. Latency measures the HTTP round trip. Last successful communication and
reconnect are transitions observed within this dashboard process (not invented
historical network events). The UI clears live status if its own backend fails;
independent source errors persist until that source succeeds.

Physical acceptance: Tailscale mini PC Running and phone peer ONLINE; coordinator
connection refused, correctly displayed OFFLINE and Samsung DEGRADED. Deterministic
available/unavailable/reconnect tests pass. No attempt was made to modify/restart the
phone workflow to resolve the refusal.

## History, audit and evidence

History adapts existing `evidence/**/*result*.json`. REAL results require a matching
instruction/evidence identifying `live_bet365` or explicit `record_origin=production`;
file names alone are insufficient. Other captured results stay in SAMPLE mode.
Four existing live-site result records were found. Original status/stage values are
preserved, with fixture/selection/stake and other fields drawn from matching records.
Unknown values remain null; alert prices are never confused with observed prices.

Timelines include only actual source events: parser receipt/normalization records,
matching coordinator acknowledgement/state, recorded workflow events, and device
results. No placeholder PARSED or RULES_APPLIED events are invented for historical
results. Events carry stored timestamps; event times may be calculated from recorded
started_at_ms + elapsed_ms, and completion from started_at_ms + duration_ms. File
modification times are separately labelled and used for ordering only. Confirmation
metadata is joined only by exact instruction ID, not guessed from the machine name.

The overview displays current_instruction and last_result from live health. It does
not automatically archive a new phone ledger. Screenshot/JSON/text references resolve
only inside the evidence directory; traversal/outside links are rejected. Existing
backend SQLite ledgers, confirmation state, and phone results remain untouched.

## Recommendations and notification formatting

`core/decision_support.py` owns configuration defaults, validation, transactional
persistence and recommendation calculations. `.local/dashboard.sqlite3` retains the
existing config/change audit. Global: enabled, default suggested stake 1, maximum 10,
slippage 0. Football: 1X2/SPREAD/TOTALS; basketball: MONEYLINE/SPREAD/TOTALS. Per-market
enable, stake, slippage, and optional minimum displayed-EV overrides are supported.
Blank stake/slippage inherits global; blank EV means no threshold.

Slippage is an absolute decimal-price reduction: minimum = max(1.01, target price -
slippage). Decimal arithmetic preserves source precision. EV compares the displayed
number (e.g. 113.52), not a recalculated profit edge. Inputs must be finite, stakes
positive, and suggested stakes <= maximum. Config save and change audit are atomic.

Real recommendations require an explicit target and verified production mapping.
They are shown separately from stored historical instructions/configuration, include
the current applied config and calculation timestamp, and are `dispatchable=false`.
Unmapped football or Moneyline observations do not acquire guessed selections. A
recommendation calculation does not fabricate a historical RULES_APPLIED event.

`core/notification_formatter.format_result` returns concise plain text for an existing
result. The result audit shows this Telegram-style preview. Backend status/stage and
failure reasons are preserved; source/device fields are omitted when unknown.
No message is sent and no Telegram transport/listener is started.

## Production basketball profile

`oddsnotifier_basketball_v1` supports the observed linked Totals/Spread message layout,
including flattened chat pastes. Schema v4 preserves original raw text, links, all
quote groups, signed lines, movement, parenthetical values, EV, and alternate-line
metadata. Totals positions = OVER/UNDER. Spread positions = HOME at displayed line,
AWAY at inverse line, independently for current, opening and Bet365 groups.

Exactly one bold Bet365 quote identifies the target. The target uses **current
Bet365 line**, never Opening or a different Pinnacle line. If bold was lost, an
explicit `target_position=1|2` confirmation is supported and labelled separately;
missing targets stay unresolved and conflicting/multiple targets are rejected.
The browser observation confirms bold-first targets for all four supplied messages.
Raw pasted fixtures retain their text; manifest stores independent confirmations.

Required assertions: Melbourne TOTALS 190.5 OVER @2.20 EV113.52%; Rytas HOME -18.5
@1.83 EV108.47% with alternate-line metadata retained. Additional real examples:
Melbourne OVER190 @2.15 EV110.69%; Prague OVER176 @2.20 EV116.64%.

```powershell
python tools/parse_oddsnotifier.py tests/fixtures/oddsnotifier_basketball_rytas_real.txt --ordering-profile oddsnotifier_basketball_v1 --sample-provenance user_reported_real --target-position 1
```

Basketball Moneyline mappings are unchanged. A genuine ML message was visible in Feed
2, but no additional semantic mapping is inferred. Feed 1 currently exposed setup
notices; football mappings remain unchanged. Unsupported line-transition/EV:None
layouts seen in the feed fail closed; this profile is not a claim of full-feed coverage.

## Technical logs and verification

Technical logs read existing `logs/*.log`: bounded 64 KiB tail, up to 300 lines/file,
20 files, maximum 100 filtered rows in the response. Existing textual logger format
and structured JSON lines are supported. Instruction/device IDs are extracted only
when explicitly logged. Invalid lines are skipped. Config change audit is included;
result file modification times are not manufactured into log timestamps. Filters
cover time, component, severity, instruction_id and device_id.

```powershell
python -m unittest tests.test_dashboard tests.test_dashboard_real tests.test_oddsnotifier_parser tests.test_oddsnotifier_basketball_production tools.confirmation.tests.test_confirmation tools.complete_execution.tests.test_gate -v
```

84 tests pass: dashboard/source/health/config/log tests, strict production fixtures,
legacy parser regressions and confirmation/execution gate regressions. Browser checks
cover four real alerts, recommendation detail/copy, four production results versus
67 sample captures, real audit/evidence/notification preview, config, mode switching
and refresh/error behavior. Evidence: `evidence/dashboard/real-*`.
