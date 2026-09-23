# MultiBot365 local dashboard

## Start on the Windows mini PC

From `C:\Users\WINDOWS11\Desktop\MultiBotV2.0\MultiBot365`:

```powershell
python -m pip install -r dashboard/requirements.txt
python -m dashboard
```

Open http://127.0.0.1:8780. Python 3.11 was used for acceptance. No USB, ADB,
Android rebuild, Telegram account, npm, external CDN, or frontend build is needed.
Stop with Ctrl+C when run in a terminal. This milestone does not install a startup task.

Default bind: **127.0.0.1:8780**, with host checks and same-origin configuration writes.
The phone keeps its existing private HTTP coordinator port **8767**. No device
instruction POST is available through the dashboard.

For an explicitly configured trusted LAN, bind the mini PC's private interface:

```powershell
python -m dashboard --host 192.168.1.50 --port 8780
```

Replace the example IP with the mini PC's address. That host is allowed automatically.
For a private DNS alias, set `DASHBOARD_ALLOWED_HOSTS` to a comma-separated list of
exact hostnames. LAN clients can edit rules and read evidence: this local dashboard
has no user authentication. Do not port-forward it or bind a public interface. No
firewall or Tailscale settings are changed by startup.

## Screens

- Overview: coordinator, phone, network, current instruction and latest live result.
- Incoming alerts: all requested fields, status filter and inspection dialog.
- Alert audit: raw Telegram text, unaltered parser schema v3, unresolved warnings,
  provenance, replay timestamps, configuration snapshot, instruction and copy JSON.
- Rules: global settings and football/basketball per-market overrides, validation,
  active configuration JSON and saved timestamp.
- Execution history: recorded coordinator PASS/FAIL and original stage, search,
  status/stage filter, pagination, result JSON and local evidence links/previews.
- Technical logs: bounded existing application log tail, recorded result summaries,
  configuration change log, time/component/severity/instruction/device filters,
  expandable detail (latest 100 matches).

## Architecture and source contracts

`dashboard/app.py` is a small FastAPI wrapper; `dashboard/services.py` owns adapters,
validation and preview rules. `dashboard/static/` is plain HTML/CSS/JavaScript.
The existing Android agent, site adapters, coordinator client/protocol, parser,
confirmation database and Tailscale transport are unchanged.

Health calls use the existing `tools.coordinator_client.Client.health()` and ignored
`.local/coordinator.json` pairing file. Credentials stay on the server. Polling is
10 seconds with a 5-second shared cache and the client's existing 5-second timeout.
`tailscale status --json` supplies mini PC BackendState and phone peer Online state.
Tailscale peer presence does not imply the phone HTTP coordinator is available.
No old recorded health is represented as live health.

The health endpoint exposes healthy, heartbeat_ms, uptime_ms, state,
current_instruction, last_result, app_version, version_code, endpoint and PID.
It does **not** currently expose device_id. Missing fields remain unavailable.
Latency measures the health round trip. Last communication/reconnect mean successful
polls and offline-to-reachable transitions observed during this dashboard process;
there is no invented historical network reconnect time. Dashboard and coordinator
uptimes are separate. Failed health clears current state; last successful communication
is retained. If the web backend itself fails, the UI explicitly clears live status.

History reads existing `evidence/**/*result*.json` structured result objects, preserving
status and stage without remapping backend enums. Multiple captured payload files may
represent the same ID (e.g. post-duplicate captures); their source paths distinguish
them. Missing execution timestamps are not inferred from IDs or file modification time;
file time is labelled separately in details and used only for ordering. Associated
instruction.json is used only when its ID matches. Screenshot/JSON/text evidence is
served only inside the evidence directory, with resolved path containment checks.
Historical parser/config stages absent from evidence are explicitly marked unrecorded.
The overview exposes the latest live result directly from health; the history is the
recorded repository corpus, not a new phone ledger or an automatic live archive.

Existing database structures were inspected: `core/database.py` owns the legacy bets
and balance_log tables; `tools/confirmation/store.py` owns confirmation instructions
and decision_log. Neither is rewritten or presented as a phone execution ledger.
The dashboard stores only its configuration and change history in the separate ignored
`.local/dashboard.sqlite3`, using transactional SQLite writes and explicit connection
closure. No sample alerts or synthetic outcomes enter production databases.

## Sample mode and decision support

SAMPLE DATA is the default and is always labelled. The live source selector deliberately
shows an empty disconnected feed. Fixtures come from the existing OddsNotifier manifest.
Coverage: football 1X2 HOME/DRAW/AWAY, spread and totals; basketball moneyline, spread,
totals; malformed, ambiguous, duplicate, stale and unrelated messages. The synthetic
football spread variant adapts the supplied spread fixture with fictional team names.
The two user-reported real samples retain their provenance and unresolved selections.

Only explicit synthetic selections use the existing `synthetic_order_v1` profile.
Production quote ordering remains unverified. The parser output is preserved exactly;
synthetic scenario selection is separate, never inferred from price or displayed EV.
Preview instructions include `sample: true` and `dispatchable: false`; none is sent.
The stable synthetic source channel is -999. Repeated channel/message identities are
DUPLICATE and cannot produce a second instruction. The stale scenario is older than
24 hours relative to its fixed sample receipt, not the time the dashboard is reopened.
Recorded receipt/source timestamps are fixed. Parser/rules replay timestamps indicate
when the current preview was actually calculated. Reloading previews uses the current
configuration; it does not claim to reconstruct historical production decisions.

Defaults: globally enabled, stake 1, maximum stake 10, zero slippage; all supported
markets enabled, no minimum EV. Blank market stake/slippage inherits global values;
blank minimum EV means no threshold. Slippage is an **absolute decimal-price reduction**:
minimum price = max(1.01, alert price - allowed slippage), calculated with Decimal.
The field is *displayed EV percent* exactly as parsed (e.g. 106.84), not a recomputed
edge. Minimum EV compares that displayed number. Disabled/below-threshold previews are
IGNORED with a reason. Stake must be positive and cannot exceed the configured maximum.

Configuration updates validate all fields and market keys, reject booleans in numeric
fields, non-finite values and out-of-range inputs, then atomically persist config and
change audit. Current previews include the complete applied configuration snapshot.
This configuration controls dashboard previews only, not live device execution.

## Verification

```powershell
python -m unittest tests.test_dashboard tests.test_oddsnotifier_parser tools.confirmation.tests.test_confirmation tools.complete_execution.tests.test_gate -v
```

Tests use temporary databases and fake health adapters, so no phone connection is
required. Browser acceptance exercised desktop and narrow layouts, live/offline status,
fixture rendering/filtering, normalized JSON copying, invalid/valid configuration saves,
history status filtering, audit/evidence, log filters, empty live mode, and persistence.
Screenshots and test output are under `evidence/dashboard/`.

Acceptance limitation: the live Tailscale peer was online, but the phone coordinator
port refused the health connection. This is displayed as coordinator OFFLINE and
Tailscale phone ONLINE. Dashboard offline handling and deterministic ONLINE/DEGRADED
adapter tests pass. No phone state was changed to resolve the refusal. Real Telegram
feed connection and production selection semantics remain deferred as requested.
