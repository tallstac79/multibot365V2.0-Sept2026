# MultiBot365 rules: FAVOURABLE_LINE_SIGNAL for verified unequal-line targets: PASS

Verified 2026-09-23. Based on 5c82664. Backend rules and interpretation only. **175 tests PASS**
(`evidence/market-interpretation/tests-favourable-line.txt`).

- **CLEAR_VALUE_SIGNAL** is unchanged: an equal-line, verified price/EV edge.
- **FAVOURABLE_LINE_SIGNAL** (new) needs all of: a highlighted verified target side, verified
  ordering, a quantified favourable Bet365 line for that exact side, and both prices present.
  No synthetic EV is calculated.
- **Rules:** rules-3 accepts both signals. Line signals must also meet `min_line_advantage`
  (default 1.0 point; the compared lines in this feed differ in minimum 1-point steps; configurable 0.5 to 50 in Rules & configuration) and the market's min/max price
  rules; `minimum_ev` is recorded as not applicable.
- **Interpretation:** a highlighted target on unequal lines is now PARSED, so it reaches the
  rules. Without a highlight it stays PARSED_PARTIAL / POTENTIAL_VALUE, and Kipina never
  picks UNDER.
- **Dashboard:** the Signal explanation line and the min line advantage setting.
- **Live corpus:** all 140 genuine Feed 2 alerts have no highlighted target on unequal lines,
  so they are unchanged (33 CLEAR_VALUE_SIGNAL, 90 PARSED_PARTIAL, 17 AMBIGUOUS).
- **Live service:** PID 6780 was started by the operator at 17:17:08, after cb3e703 (17:13:48)
  and after these rule files were saved (17:16:01). It is therefore already running cb3e703
  plus this change. It was **not** restarted again, because dispatch was armed for the
  operator's single READY-only live cycle at that moment.

---
# MultiBot365 Search UI re-home 5/5 OPEN_SEARCH PASS (0.6.24-search vc36) - READY_FOR_LIVE_REPROOF YES

Verified 2026-09-23 ~17:00 Europe/London. App **0.6.24-search (36)** on Samsung R5CT61TE14Z / galaxy-a13-5g. Coordinator Tailscale `http://100.114.45.68:8767` / MagicDNS `galaxy-a13-5g.taila8257e.ts.net:8767`. Session **AUTHENTICATED**.

- **Prior FAIL fixed:** live ready-only dispatch hit `TARGET_NOT_FOUND` ("Live Bet365 search UI not visible after Search tap") on 0.6.22-login (34). Root cause: home chrome / wrong tab after prior reset; Search control not reliably visible. Fix: Search re-home + session re-probe in Bet365LiveAdapter / SearchOpenWorkflow (and SessionCheck/SessionProbe workflows).
- **Proof (evidence/search-ui-fix/proof-summary.json):**
  - **5/5 OPEN_SEARCH PASS** consecutive: `open-search-1790178324-1` ... `open-search-1790179344-5` (all status PASS, detail OPEN_SEARCH).
  - **Fulham OPEN_SEARCH_QUERY PASS:** `search-fulham-1790179552` - query 'Fulham' entered and results verified; reset afterward.
  - Flags: `SEARCH_OPEN=PASS`, `5X_REPEAT=PASS`, `SEARCH_TEXT_ENTRY=PASS`, `RESET_STATE=PASS`, **`READY_FOR_LIVE_REPROOF=YES`**.
- **APK match:** installed package versionName `0.6.24-search` versionCode `36`; `/health` same; sha256 of installed base.apk equals Desktop `Bet365Agent-0.6.24-search.apk` and `app/build/outputs/apk/debug/app-debug.apk` (`965FCF78466569E9EA8DB3D97288CC6B8120B67DE55A735C38B9B70A5856F2B7`).
- **gradle.kts:** versionCode 36 / versionName 0.6.24-search.
- **Safety unchanged:** ready-only path; `wager_submitted=false`; Place Bet / final action not engaged in these proofs.
- **Next:** enable READY-only `dispatch_enabled` for one live OddsNotifier PARSED->QUEUED->DISPATCHED cycle, then disable immediately after first terminal READY or FAIL.

---
# MultiBot365 live ready-only reproof on 0.6.24-search - FAIL (FOCUS_FAILED); dispatch re-disabled

Verified 2026-09-23 ~18:22 Europe/London. App **0.6.24-search (36)** (commit `5c82664`). Coordinator Tailscale `http://100.114.45.68:8767`. Session kept **AUTHENTICATED** via session keepalive (120s max-age). David override: Place Bet not force-disabled; pipeline still sends `execution_mode=ready` (no confirmation_status).

- **Dispatch:** `.local/pipeline.json` `pipeline.dispatch_enabled=true` then false after watch. Keys set: only `pipeline.dispatch_enabled`. No Place Bet lock keys.
- **Near-misses before dispatch:** several CLEAR_VALUE PARSED alerts went `SESSION_REQUIRED` (stale/UNKNOWN session before keepalive) or `STALE` (`event_not_started` ? rules require pre-match tip-off).
- **Live instruction (ONE):** `on-85a1398083a603180851685a` msg path OddsNotifier ? PARSED ? rules ACCEPT (CLEAR_VALUE_SIGNAL) ? QUEUED ? **DISPATCHED** 17:12:54Z ? DEVICE_ACTIVE ? terminal **UNKNOWN**/FAIL `FOCUS_FAILED: No fresh input session for the visually tapped field` (completed 17:13:39Z).
- **Alert:** basketball SPREAD Atletico Boca Juniors vs NBA G League United HOME line **15.5** min 1.83 stake 1.00.
- **READY not reached.** `wager_submitted=false`. `execution_mode=ready`. Place Bet never engaged.
- **Post:** `dispatch_enabled=false` verified; intake LISTENING; session AUTHENTICATED.
- Evidence: `evidence/ready-reproof-20260923/` (instruction full/transitions/audit, final-summary, apk-match, session keepalive, poll logs).

---

# MultiBot365 market interpretation and alert normalisation: PASS

Verified 2026-09-23. Based on a3d19a1 (backend base 444793f). Backend parsing/analysis only.
There were no Android, Bet365, coordinator, Tailscale or dispatch changes, and Grok's
uncommitted Android work is left untouched. **168 automated tests PASS** (141 existing + 27
new). Output: `evidence/market-interpretation/tests.txt`.

- **New layer** `core/market_interpretation.py`, used by `core/alert_classifier.py` (classifier-2):
  - Two-sided alerts, with optional `P -> L` line updates, alt lines, linked or unlinked
    rows, and 🟢 or 🔵 Opening markers.
  - Side-labelled alerts, with `Limit`, `Opening: Side`, `Spread (L): Side price ↓ [x%]`,
    `Fair Odds` and an empty `Bet365` section.
- **Normalised schema 5:** `selection_*`, `reference`, `comparison` (equal_line, line
  difference/advantage, line/price quality, ev_status, supplied EV), `movement`,
  `market_movement`, `limit` and per-side `sides[]`. Legacy fields are unchanged; the four
  snapshot alerts match the verified parser field-for-field.
- **Direction rules:** totals (OVER lower is better, UNDER higher is better), spread
  normalised to the selected team's signed handicap (AWAY is the inverse of the displayed
  HOME line), and moneyline/1X2 compared by price on the same outcome only.
- **Unequal lines:** `EV: None (not equal lines)` gives `NOT_AVAILABLE_UNEQUAL_LINES`,
  `price_quality NOT_COMPARABLE`, per-side directional line quality and `PARSED_PARTIAL`
  (no longer INVALID). Kipina: OVER 2 points worse (UNFAVOURABLE), UNDER 2 points better
  (FAVOURABLE, POTENTIAL_VALUE).
- **Football production format** (HJK Helsinki vs Brann): PARSED_PARTIAL. Brann AWAY -1.5,
  2.030 → 1.724 SHORTENED, supplied -11.7 %, fair 1.850, limit €200 → €400, Bet365 absent.
- **Bet quality** is separate from line/price quality. CLEAR_VALUE_SIGNAL only for a
  verified, highlighted, equal-line alert with a better Bet365 price and supplied EV above
  100 %. The rules engine (rules-2) now requires it.
- **Live corpus:** 140 genuine Feed 2 alerts are kept as a regression fixture. 90
  previously INVALID unequal-line alerts are now PARSED_PARTIAL; 4 unlinked-fixture and 3
  heavily-bolded alerts are now PARSED. Nothing valid is INVALID.
- **Store schema v2** (PARSED_PARTIAL) uses a transactional migration, verified on a copy
  of the live store. The running pipeline service (PID 17744) applies it on its next
  restart.
- **Fixed a race** in the pipeline (from 444793f): a losing concurrent delivery retried
  while holding its own write lock.
- **Dashboard:** a *Market interpretation* block in the alert detail (reference, selection,
  movement, fair odds, limit, Bet365 or "No comparable offer captured", EV text, per-side
  table) and a PARSED_PARTIAL filter. Browser check:
  `evidence/market-interpretation/browser-checks.json`.
- **Docs:** `docs/MARKET_INTERPRETATION.md`.

Remaining ambiguities:
- Bet365 spread sign reference: three live WNBA-type alerts show equal displayed lines with
  "not equal lines". These are AMBIGUOUS.
- The base of OddsNotifier's supplied `[x%]` is unspecified.
- The meaning of the parenthesised Pinnacle price is unconfirmed.
- Football two-sided ordering and all moneyline ordering are unverified.
- The spread-line attribution in the side-labelled layout rests on a single example.

---
# MultiBot365 live ready-only dispatch E2E - FAIL (TARGET_NOT_FOUND); dispatch re-disabled

Verified 2026-09-23 ~15:00 Europe/London. App **0.6.22-login (34)** on Samsung galaxy-a13-5g. Coordinator Tailscale `http://100.114.45.68:8767` / MagicDNS `galaxy-a13-5g.taila8257e.ts.net:8767`.

- **Session before dispatch:** AUTHENTICATED (post `session-login-1790175250` PASS). Notifications disabled.
- **Dispatch enable:** `.local/pipeline.json` `dispatch_enabled=true`; `pipeline_service` LISTENING; one live OddsNotifier alert PARSED→QUEUED→DISPATCHED.
- **Live alert:** `on-f24902a9a6dc166b07e79880` msg 68009 **Japan vs Thailand** basketball SPREAD HOME **-56.5** @1.80 stake 1.00 `execution_mode=ready`.
- **Device result:** FAIL `TARGET_NOT_FOUND` — "Live Bet365 search UI not visible after Search tap" (33.8s). **READY not reached.** `wager_submitted` absent/false.
- **Post-fail health:** session **AUTHENTICATED** (workflow); Place Bet never engaged.
- **Dispatch disabled after:** `dispatch_enabled=false` + pipeline restart; status confirms false, intake LISTENING, notifications DISABLED.
- **LTE / Tailscale recovery (no ADB):** Wi-Fi state **unknown without ADB**. OPEN_AND_TYPE over MagicDNS **PASS** (`ts-recovery-1790175562-open-type` Exact editor value verified). Network path: MagicDNS → endpoint `http://100.114.45.68:8767`.
- **App restart:** **NO_ADB_BLOCKER** (cannot force-stop). Strongest check: AUTHENTICATED after dispatch FAIL; final idle probe UNKNOWN after recovery typing.
- **Phone reboot:** **NO_ADB_BLOCKER** (needs human). Prior dual-bind reboot evidence retained.
- Evidence: `evidence/live-ready-dispatch/` (instruction/result/transitions/health + recovery OPEN_AND_TYPE + `session-summary.json`). No `.local` secrets committed.

**Remaining:** fix Bet365 search UI visibility for ready-only path; re-enable dispatch only after operator approval; human phone reboot / optional ADB for Wi-Fi-off LTE and app-restart if required.

---
# MultiBot365 live Telegram intake + session contract - PASS (ready-only; dispatch still off)

Verified 2026-09-23 15:11 Europe/London. Backend on `444793f` + this commit. App **0.6.21-session (33)** on Samsung R5CT61TE14Z. Dashboard **2.0-dashboard.3**. **141 automated tests PASS** (128 under `tests/` + 13 under `tools/`).

- **Telegram login:** Telethon user session for OddsNotifier Feed 2 (`oddsnotifierfeed2bot` / peer 1475314653). Channel-form `-1001475314653` is incorrect for this peer.
- **Intake:** `tools.pipeline_service run` LISTENING; real `event` deliveries persist to `.local/pipeline.sqlite3` with entities + production Markdown via `render_oddsnotifier`. Live PARSED basketball Spread/Totals with bold Bet365 target proven (e.g. message 67960 → PARSED HOME 1.74); older alerts correctly STALE; EV:None / missing fixture URL / unsupported layouts fail closed (INVALID/AMBIGUOUS/IGNORED).
- **Config:** `.local/pipeline.json` (untracked) `dispatch_enabled=false`, notifications disabled. Rules `event_timezone=Europe/London`.
- **Startup:** Task Scheduler `MultiBot365Pipeline` ONLOGON → `tools\run_pipeline_service.cmd` (Python 3.11, project cwd). Status Ready.
- **Dashboard:** REAL DATA mode shows live intake/lifecycle; coordinator ONLINE; Python 3.11 only (Hermes dashboard stopped).
- **Android session contract:** `GET /health` includes stable `device_id=galaxy-a13-5g` and `session{state,observed_at_ms,detail}` refreshed ≥60s (idle OCR probe). Observed `AUTHENTICATED` via idle probe. Accepts wire `TOTALS`→`TOTAL` and required `line` for Spread/Totals; missing line → HTTP 400 INVALID_INSTRUCTION. Preserves `ready_state.session`, observed price, `wager_submitted`. Dual Tailscale/LAN bind from a292373 preserved (endpoint `http://100.114.45.68:8767`).
- **Ready-only:** `dispatch_enabled` remains false — no coordinator dispatch of live alerts. Milestone stays `wager_submitted=false`.

**Remaining:** enable dispatch only after operator approval; prove a fresh in-window alert through READY on device; Wi‑Fi-off LTE / phone-reboot / app-restart re-verification not re-run this session (prior a292373 evidence stands).

---
# MultiBot365 unattended backend pipeline: PASS (tests); live Telegram connection pending login

Verified 2026-09-23. Based on a292373. Dashboard **2.0-dashboard.3**. **141 automated tests PASS**
(84 existing + 57 new). Output: `evidence/pipeline/tests.txt`.

- **Telegram intake** (`core/telegram_intake.py`, `tools/pipeline_service.py`): a Telethon
  user-session listener. Covers live events, startup catch-up after restart, periodic
  reconciliation of missed messages, and reconnect with backoff forever. Stores the exact
  plain text, all entities, and Markdown rebuilt from the entities (round-trips all four
  genuine messages). Also stores message ID, source time, receipt time and a deterministic
  instruction_id. Every message is classified PARSED, AMBIGUOUS, INVALID, DUPLICATE or
  IGNORED, with a reason. Edits are recorded, never executed.
- **Parser hardening** (`core/alert_classifier.py`): only production-verified basketball
  Totals/Spread with a bold target is PARSED. Football and basketball ML are AMBIGUOUS
  `UNSUPPORTED_MAPPING`. Nothing is guessed. The existing parser and fixtures are
  unchanged. Regression tests cover every genuine format.
- **Stale/duplicate protection:** message identity is enforced by a unique index;
  content duplicates use a selection key; a new price supersedes a pending instruction;
  alerts over the age limit or with a started event become STALE; an unknown event
  timezone is REJECTED (fail closed). Checks run at ingest and again before dispatch.
- **Rules engine** (`core/rules_engine.py`): uses the existing decision-support config.
  Global/per-market enable, stake, max stake, slippage, min EV, min/max price, stale limit
  and event timezone. Every check result is stored.
- **Lifecycle and idempotency** (`core/lifecycle.py`, `core/pipeline_store.py`,
  `core/pipeline.py`): one canonical state machine with timestamped transitions.
  Coordinator and confirmation enums are mapped, not duplicated. DISPATCHED is committed
  before sending; a restart only polls; terminal is final; late results are audited and
  ignored.
- **Session contract** (`core/session_contract.py`): only a fresh AUTHENTICATED report
  proceeds; everything else is SESSION_REQUIRED. The wire format for Android is in
  `docs/SESSION_CONTRACT.md`.
- **Result/audit storage:** `.local/pipeline.sqlite3` (`docs/RESULT_SCHEMA.md`). Existing
  evidence structure is preserved and referenced by path.
- **Dashboard:** read-only wiring of intake, lifecycle, rules decision, session, device,
  failure reason, evidence and notification preview. REAL and SAMPLE are separated by
  origin. No redesign. Browser check: `evidence/pipeline/browser-checks.json`.
- **Telegram notifications** (`core/status_notifier.py`): an outbox built from stored rows,
  unique per (instruction, state), claimed before sending, with retry backoff. Disabled
  until configured.
- **Safety:** `dispatch_enabled=false` by default. When enabled, it sends only the existing
  live adapter's READY-only request (`execution_mode: "ready"`, never `confirmation_status`).
  No Android, live-adapter, visual-control, login-UI, Tailscale or final-action code was
  changed.

Not yet live: `.local/pipeline.json` and the one-time `python -m tools.pipeline_service
telegram-login` (the account owner's phone code) are needed before the listener connects
to the real feed. `event_timezone` must be confirmed and set, or every alert fails closed.
Until Android reports a `session` object in `/health`, every dispatch ends as
SESSION_REQUIRED. Docs: `docs/TELEGRAM_INGESTION.md`, `docs/INSTRUCTION_LIFECYCLE.md`,
`docs/SESSION_CONTRACT.md`, `docs/RULES_ENGINE.md`, `docs/RESULT_SCHEMA.md`,
`docs/DASHBOARD.md`.

---
# MultiBot365 coordinator Tailscale dual-bind (Wi-Fi + LTE MagicDNS) - PASS

Verified 2026-09-23 13:28 Europe/London. App **0.6.20-ts** (32) on Samsung SM-A136B R5CT61TE14Z.

- **Root cause:** `CoordinatorHttp.localAddress()` preferred wlan/eth RFC1918 over Tailscale tun; with Wi-Fi ON the listener bound only `192.168.4.x`. Dashboard/client MagicDNS -> `100.114.45.68:8767` -> ConnectionRefused.
- **Fix:** Dual `ServerSocket` bind (LAN + Tailscale) when both interfaces exist; Tailscale-only when Wi-Fi is down. Never bind `0.0.0.0` / public / rmnet. Reported `endpoint` is a clean primary URL preferring Tailscale (safe for fixture open); dual detail only in LISTEN log.
- **Wi-Fi ON:** TCP MagicDNS + `100.114.45.68` + `192.168.4.108` :8767 OK; health PASS; OPEN_AND_TYPE PASS; DUPLICATE execution_count unchanged; app force-stop/restart rebind + instruction PASS; dashboard coordinator ONLINE.
- **LTE (Wi-Fi OFF, mobile data ON, Tailscale ON):** TCP MagicDNS + `100.114.45.68` OK; LAN refused as expected; health PASS endpoint `http://100.114.45.68:8767`; OPEN_AND_TYPE PASS (`ts-lte-dualbind-1790169666-open-type`); DUPLICATE 409; app restart pid 10851->11563 then instruction PASS (`ts-lte-restart-1790169702-after`); dashboard ONLINE.
- **Phone reboot:** PASS after David reboot (wifi_on=0, mobile data ON, Tailscale ON, accessibility on). Coordinator rebound pid 4417 endpoint `http://100.114.45.68:8767`; OPEN_AND_TYPE PASS (`ts-phone-reboot-1790166469-open-type`); DUPLICATE 409; dashboard coordinator ONLINE.
- Evidence: `evidence/coordinator-tailscale-bind/` (incl. `phone-reboot-*.json`, updated `summary.json`). No `.local/coordinator.json` or gradle junk committed. Live-site adapter/parser/OCR untouched.

---
# MultiBot365 V2 real operations console + production basketball parser â€” PASS

Verified 2026-09-23. Dashboard **2.0-dashboard.2**, based on 2aac0c4.

- Same five screens/layout; REAL DATA default, SAMPLE DATA retained and isolated.
- Existing coordinator GET health and Tailscale read-only status supply actual state,
  hostnames and explicitly labelled identity. No phone execution endpoints added.
- Real alerts consume the generic parser observation store read-only; absent store is
  empty, unreadable store reports an error. Mode changes do not mutate records.
- Four genuine Feed 2 messages captured from the user's signed-in Telegram UI, numeric
  bold verified, and imported as a local production snapshot (not a continuous feed).
- Production basketball Totals/Spread profile, schema v4: OVER/UNDER and HOME/AWAY
  inverse spread lines, retained alternate-line metadata, current Bet365 target line.
  Required Melbourne OVER190.5 @2.20 EV113.52 and Rytas HOME-18.5 @1.83 EV108.47 pass.
  Raw pasted originals retained; independent browser evidence confirms bold targets.
  Basketball Moneyline and football mapping semantics remain unchanged.
- REAL history: 4 persisted production results. SAMPLE history: 67 existing test
  captures. Timelines contain only matching stored stages/timestamps/evidence.
- Generic core decision-support config validates/persists rules; recommendations
  are human-readable, separately labelled, and never dispatched. Plain-text Telegram
  result formatter is preview-only and preserves existing backend enums.
- Technical logs read bounded existing application logs plus configuration audit.
- **84 automated tests PASS**, including 11 strict production basketball cases and
  parser/config/health/source/history/log regressions. Browser checks and screenshots
  in evidence/dashboard/real-*. Documentation: docs/DASHBOARD.md.

Live limitation: mini PC Tailscale Running, Samsung peer ONLINE, coordinator HTTP
connection refused. Correctly shown coordinator OFFLINE / Samsung DEGRADED. Health
available/offline/reconnect cases pass deterministic tests. No Android engine,
live-site adapter, coordinator execution protocol, Tailscale transport or proven
phone workflow changes. Real Telegram continuous intake remains deferred; imported
messages are a genuine recorded snapshot, never synthetic production data.

---

# MultiBot365 V2 local dashboard â€” PASS

Verified 2026-09-23. Dashboard build **2.0-dashboard.1**, based on cfb267c.

- Local FastAPI + plain HTML/CSS/JavaScript operations dashboard at http://127.0.0.1:8780.
- Overview with coordinator/phone/Tailscale health, current activity and latest live result.
- Clearly labelled sample alerts: all requested football/basketball markets, 1X2 sides,
  malformed, ambiguous, duplicate, stale and ignored cases; no synthetic production feed.
- Configurable global/per-market stakes, slippage and displayed-EV thresholds; validated
  transactional SQLite persistence and change timestamps. Rules affect previews only.
- Normalized instruction, copy JSON, original parser output, raw text, warnings,
  provenance, applied configuration and audit timeline.
- Recorded backend execution history with original status/stage, filters, pagination,
  result JSON, evidence links/previews; compact filterable technical logs.
- **59 automated tests PASS**: 14 dashboard, 32 parser, 9 confirmation, 4 execution gates.
  Browser checks cover rendering, filters, copy, validation/save, empty live source,
  backend failure and recovery; screenshots: `evidence/dashboard/`.
- Start/configuration/ports/architecture/limitations: `docs/DASHBOARD.md`.
- No Android phone agent, live-site adapter, coordinator protocol, parser, confirmation
  infrastructure or Tailscale transport modifications. Existing dirty Android build
  artifacts remain excluded from this milestone.

Live verification limitation: mini PC Tailscale Running and Samsung peer ONLINE,
but phone coordinator HTTP connection refused. Dashboard correctly reports coordinator
OFFLINE independently of peer connectivity. No USB/ADB connection was required. Real
Telegram integration and verified production quote/selection semantics remain deferred.
Device ID and historical pipeline timestamps missing from existing schemas are labelled
unavailable rather than invented. Dashboard implementation has no remaining blocker.

---

# MultiBot365 networking milestone - LTE/Tailscale coordinator path

**Status:** PASS (full post-reboot recovery verified)
**Date:** 2026-09-23 ~09:11 Europe/London
**App:** 0.6.19-ts (31) on Samsung SM-A136B R5CT61TE14Z
**HEAD before this work:** a06f3b4 COMPLETE_EXECUTION_READY

## Architecture correction (CoS hostname)

- Intended data path remains **Windows client -> phone coordinator** (HTTP :8767).
- CoS named `desktop-ivunj9j.taila8257e.ts.net` (mini PC). That is the **client**, not the coordinator host.
- Correct MagicDNS used in `.local/coordinator.json`: **`galaxy-a13-5g.taila8257e.ts.net`** (Samsung, Tailscale IP 100.114.45.68).
- Mini PC Tailscale IP 100.69.205.34 remains the Windows peer.

## Code / config changes (networking only)

- `android/Bet365Agent/app/src/main/java/com/bet365agent/CoordinatorHttp.java`
  - Accept Tailscale CGNAT `100.64.0.0/10` as trusted private peers.
  - Bind preference: Wi-Fi/Ethernet RFC1918 first; **fall back to Tailscale `tun*`** when Wi-Fi is off.
  - Still never binds carrier `rmnet` / public / wildcard.
- `CoordinatorSettingsActivity.java` - UI hint mentions Tailscale.
- `app/build.gradle.kts` - versionCode 31 / versionName `0.6.19-ts`.
- `.local/coordinator.json` url -> `http://galaxy-a13-5g.taila8257e.ts.net:8767` (token unchanged; **not committed**).
- `tools/COORDINATOR.md` - documents Tailscale bind/peers and MagicDNS URL form.
- No Bet365LiveAdapter / AdapterWorkflow / Place Bet logic changes.

## Proven on physical devices (Wi-Fi OFF, mobile/LTE ON, Tailscale ON)

Evidence: `evidence/tailscale-lte-coordinator/`

| Check | Result |
|---|---|
| Agent health via MagicDNS | PASS - endpoint `http://100.114.45.68:8767`, app 0.6.19-ts |
| Coordinator request reaches phone | PASS - `ts-lte-1790150005-open-type` ACCEPTED |
| Phone returns result | PASS - stage PASS, execution_count 1 |
| Duplicate after success | PASS - HTTP 409 DUPLICATE, execution_count stays 1 |
| App restart recovers (Tailscale rebind) | PASS - pid 13574->14148, same TS endpoint |
| No duplicate / no replay after app restart | PASS - pending -> INTERNAL_ERROR count 1; re-POST DUPLICATE; fresh after-restart PASS |
| Phone reboot recovers | PASS - after David reboot; health + OPEN_AND_TYPE `ts-lte-postreboot-1790151061-open-type` PASS; duplicate 409; wifi_on=0 LTE; Tailscale + accessibility up |
| Mini PC reboot recovers | PASS - after David reboot; `tailscale status` shows galaxy-a13-5g; MagicDNS Resolve-DnsName -> 100.114.45.68; client health/instruction over MagicDNS |

## Post-reboot verification notes

- David confirmed Samsung phone AND mini PC restarted before this pass.
- After phone reboot the screen was locked once; unlocked via adb wake + dismiss-keyguard, then instruction PASS (not a networking failure).
- `settings get global wifi_on` = 0; active default network MOBILE[LTE] (`uk.lebara.mobi`).
- LAN `nslookup` does not resolve MagicDNS; Tailscale Resolve-DnsName / Magicsock does (expected).

## Not claimed

- Any change to live-site Place Bet / READY_STATE business logic.
- Permanent unlocked-after-reboot guarantee (phone may need unlock after cold boot).

---
# MultiBot365 build status

## Current milestone: COMPLETE_EXECUTION_READY + ?0 Place Bet dispatch ? PASS on physical Samsung

Verified 2026-09-22 ~21:56 Europe/London. App **0.6.18-cer (30)**.

### A) COMPLETE_EXECUTION_READY (prepare, no dispatch)
Evidence: `evidence/live-bet365-complete-execution-ready/` ? PASS.
- Locates Place Bet, records bounds + prepared gesture payload + validation_hash
- `gesture_dispatched`: false, `wager_submitted`: false
- Sample CER bounds: Place Bet `[478,1324,604,1346]`

### B) Real Place Bet dispatch on ?0 account
Evidence: `evidence/live-bet365-place-bet-insufficient/` ? PASS.
- `execution_mode=dispatch` + `confirmation_status=APPROVED`
- Real Place Bet gesture **dispatched** (`place_bet_tapped` true, `gesture_dispatched` true)
- `wager_submitted`: **false** (no settled wager)
- Post-tap UI: betslip cleared / page reload with header balance still **?0.00** ? classified **INSUFFICIENT_BALANCE** (equivalent reject)

### Protections
`tools/complete_execution/` gate unit tests **4/4**: duplicate, stale, price-change, restart recovery.

### Notes
- Does not modify Confirmation Worker (`tools/confirmation/`).
- READY_STATE / Search / 1X2 / OCR column bind unchanged in design; extended with prepare+dispatch only.
- Instruction fields: `execution_mode` = ready|prepare|dispatch; `confirmation_status` = NONE|APPROVED (APPROVED required for prepare/dispatch).

---

# Confirmation worker companion - live poll + chat APPROVE PASS

**Status:** PASS on DESKTOP-IVUNJ9J (chat APPROVE/REJECT card + live coordinator poll).
**Date:** 2026-09-22 ~21:37 Europe/London
**Commits:** scaffold 6a3a7f9, derive fields 82c55b7, plus this milestone commit.

## Proven

- Live poll: coordinator GET /instructions/live-ready-1790108608 (+ evidence) â†’ 
eady_state.state=READY (app **0.6.16-ready**).
- Normalize/derive: device_id=samsung-R5CT61TE14Z, ISO alidated_at, SHA-256 alidation_hash (main bot omits these).
- Chat card shown: READY / Fixture / Market / Selection / Line / Price / Minimum / Stake / APPROVE|REJECT.
- Human **APPROVE** â†’ outbox status **APPROVED**; second approve â†’ **DUPLICATE**.
- Evidence: evidence/confirmation-live-poll/ (poll.json, card.json, decision.json).
- Unit tests: 9/9 still pass. No Place Bet. No main-bot / Android source edits.

## Not claimed

- Continuous always-on poller daemon (manual/CLI + this chat card path proven).
- Main-bot automatic read of confirmation outbox (INTERFACE documents the file contract).

---

# OddsNotifier real linked ML sample - parser PASS

Verified 2026-09-22 from b3639aa: 32 deterministic parser tests pass. Added the
user-reported real Banks OÂ´Dee vs Aberdeen B sample, including Markdown/bare URLs,
Unicode arrows and emoji headings. ML comes from the explicit fixture URL query.
No source URL was fetched. Source provenance remains separate from verification
of quote ordering.

Three current/comparison quotes and the two-value opening row are preserved.
Opening is flagged as an outcome-count mismatch and remains unmapped even with
the synthetic side-order profile. No draw price, target side or price is invented.
Schema v3 adds links, format/market-label source, per-group mappings and opening
count consistency. Existing labeled-format count checks still fail closed.

Evidence: `evidence/oddsnotifier-parser/v3/`. Tests: 32 PASS plus CLI smoke PASS.
Corpus: two user-reported real alerts and five synthetic examples. Remaining:
real totals/basketball samples and confirmation of side/parenthetical semantics.
No Android, coordinator, Telegram listener or database changes in this milestone.

---

# Confirmation worker companion - scaffold milestone

**Status:** Scaffold complete on DESKTOP-IVUNJ9J under `tools/confirmation/`. Deployed from box staging; tests re-run on Windows.
**Date:** 2026-09-22 ~21:30 Europe/London
**Commit intent:** Separate milestone - confirmation companion only; do not mix with main-bot stake/READY_STATE work.

## What landed

- `tools/confirmation/` Python 3 package (stdlib-only): schema, normalize, store (SQLite), revalidate, worker, CLI
- `tools/confirmation/INTERFACE.md` - ingest inbox / `python -m tools.confirmation ingest`, outbox contract, normalizer note, **no Place Bet**
- SQLite under `tools/confirmation/data/` (gitignored), separate from phone coordinator DB
- Human CLI: `ingest`, `pending`, `approve`, `reject`, `expire`, `status` (default stale window 120s)
- Tests: duplicate, stale->EXPIRED, malformed->STATE_INVALID, price->PRICE_INVALID, restart persistence, re-approve->DUPLICATE
- `.gitignore` entries for `data/`, runtime inbox/outbox JSON; keep `INTERFACE.md`, sources, `.gitkeep`

## What is NOT claimed

- No live READY_STATE PASS yet (main bot stake focus still failing)
- No Place Bet / wager submit (confirmation never places; main bot must not submit without APPROVED)
- Chat UI for APPROVE/REJECT not built (CLI only)
- Android / CoordinatorAgent / Bet365LiveAdapter / AdapterWorkflow / main.py / plugins / core **unchanged**

## Paths

- Package: `tools/confirmation/`
- Interface: `tools/confirmation/INTERFACE.md`
- DB: `tools/confirmation/data/confirmation.sqlite3`
- Inbox / outbox: `tools/confirmation/inbox/`, `tools/confirmation/outbox/`

## How to run tests

From repo root (`MultiBot365`):

```
python -m unittest tools.confirmation.tests.test_confirmation -v
```

---
# OddsNotifier offline multi-market parser - sample tests PASS

Verified 2026-09-22 from commit 443ac94: 24 deterministic tests pass for one
user-reported real Spread alert and five explicitly synthetic ML/Spread/Total
examples. This does not establish their exact production formatting.

Football ML is three-outcome 1X2; basketball ML is two-outcome MONEYLINE.
Spread and totals preserve independent displayed lines and decimal strings.
Quote sides remain unmapped by default. The opt-in `synthetic_order_v1` profile
explicitly tests HOME/DRAW/AWAY, HOME/AWAY and OVER/UNDER ordering; all mapped
output is marked production_verified=false. No target is inferred from EV/prices.
Invalid counts, headers, lines and mapping profiles fail closed.

Evidence: `evidence/oddsnotifier-parser/v2/`; provenance manifest and supplied
samples: `tests/fixtures/oddsnotifier_manifest.json`. Usage and assumptions:
`tools/ODDSNOTIFIER_PARSER.md`. Android, Telegram listener, coordinator and database
were not changed. Remaining limitation: production format/order confirmation
requires additional real samples. Earlier milestone records follow unchanged.

---

# OddsNotifier standalone parser - supplied Spread sample PASS

Verified with 12 deterministic unit tests on 2026-09-22, based on commit 81fcd4a.
`core/oddsnotifier_parser.py` and `tools/parse_oddsnotifier.py` extract observations
from the user-supplied Spread alert. Exact decimal strings, signed lines, both
Pinnacle quote positions and parenthesized values, opening/comparison prices,
fixture date and displayed EV are preserved. Optional Telegram metadata creates
a stable channel-scoped observation ID. Missing selection, timestamp timezone
and quote-side semantics are not guessed. No instruction is emitted.

Evidence: `evidence/oddsnotifier-parser/`. Format and usage:
`tools/ODDSNOTIFIER_PARSER.md`. Tests: `tests/test_oddsnotifier_parser.py`.
This is parser-only acceptance; no live Telegram, persistent deduplication,
coordinator, database or Android changes were made by this milestone. Existing
uncommitted Android changes were left untouched. Actual examples of 1X2,
moneyline, totals and basketball are still needed for their format validation.

---

# MultiBot365 build status

## Current milestone: LIVE BET365 1X2 IDENTITY FIX ? PASS on the physical Samsung

Verified 2026-09-22 ~20:52 Europe/London. App **0.6.15-live (27)**. Evidence: `evidence/live-bet365/` with verified `moneyline_map`:

- HOME ? Arsenal @ **1.33**
- DRAW ? Draw @ **5.00**
- AWAY ? Leeds @ **8.00**

Prior `565b132` PASS (HOME @ 8.00) **rejected** as side-association bug; fixed and re-proven. STOP before Place Bet held. See `BUILD_STATUS_LIVE.md`.

---
## Current milestone: LIVE BET365 ADAPTER VALIDATION ? PASS on the physical Samsung

Verified 2026-09-22 ~20:42 Europe/London on Samsung SM-A136B `R5CT61TE14Z`. App **0.6.14-live (26)**. Evidence: `evidence/live-bet365/` (**PASS**). See `BUILD_STATUS_LIVE.md`.

- Fixture: Arsenal v Leeds
- Market / side / line: MONEYLINE / HOME / NONE
- Live price (structured): 8.00
- Final: NOSUBMIT, wager_submitted false (stopped before Place Bet)
- Parent commit: `68dea3e` (M5 simulator). Live work committed on top.

No LocalSimulator substitute. Login wall cleared after David logged in on phone Chrome.

---
Ã¯Â»Â¿# MultiBot365 build status

## Current milestone: 5 Ã¢â‚¬â€ PASS on the physical Samsung (multi-sport local simulator)

Verified 2026-09-22 on Samsung SM-A136B `R5CT61TE14Z`. App **0.5.6-sim (11)**. Evidence: `evidence/fixture-m5/` (**25/25**). See `BUILD_STATUS_M5.md` for the full case table and OCR notes. Baseline commit `9133319`.

Hard stop unchanged: fictional LocalSimulator only; no live Bet365 wager path.

---
## Current milestone: 4 ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â PASS on the physical Samsung (local simulator adapter)

Built from e88b9b8 and verified on the physical Samsung SM-A136B, R5CT61TE14Z, Android 14/API 34. App **0.4.0-adapter (4)**. APK identity is recorded in evidence/fixture/build.json.

### Implemented and proven

- SiteAdapter defines all twelve requested operations. AdapterWorkflow sequences them without site labels, selectors or layout rules. VisualSession provides reusable capture, OCR geometry, gestures, query entry, deadlines and durable evidence. SiteAdapters is the composition/validation registry; LocalSimulatorAdapter contains the site-specific rules.
- ADAPTER_WORKFLOW uses the existing authenticated private-LAN coordinator, strict schema, SQLite instruction ledger and single-active-run reservation. Existing OPEN_AND_TYPE remains supported. No permanent ADB connection is required.
- Chrome opens the phone-hosted fictional simulator, visually opens search, enters the supplied query with exact editor and screenshot readback, discovers runtime-generated fixtures, selects the exact code/teams/competition, verifies the event, discovers all six quotes, reads the requested market/side/line/price, opens a dry-run review and independently verifies its exact final values.
- Every UI observation comes from screenshots/OCR; interactions use dispatchGesture and the existing Android text-input mechanism. The new adapter path uses no AccessibilityNodeInfo tree, DOM, JavaScript evaluation or simulator data API.
- Generic per-token OCR refinement and bounded numeric-region OCR preserve signs/decimals. Simulator typography/column spacing and field focus outlines were adjusted after physical OCR evidence exposed merged tokens and obscured borders. Expected numeric values are never supplied to OCR or used to repair its output.
- Every phase, detected bounds, gesture intent, query input evidence, screenshot/OCR reference, discovered fixture/quote and result timing is persisted. Each successful workflow has five outer gestures plus the separately recorded query-focus gesture and one input attempt.
- The simulator generates fictional teams, event codes and varying prices per load. Multiple Town/Youth fixtures, exact duplicates, all three market types, both spread signs, suspended/unavailable rows and deliberate event/side/line/price faults are exercised. There is no account, stake, transaction or wager action.

### Physical acceptance

**evidence/fixture/results.json: 19/19 cases passed their assertions.** The suite communicated Windows -> Samsung -> Windows solely over LAN HTTP with the PC ADB server stopped at both ends. Successful commands took 31.8ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Å“32.6 seconds. The 200ms timeout returned TIMEOUT in 229ms; no instruction remained pending.

| Case | Observed stage | Duration ms |
| --- | --- | --- |
| moneyline | PASS | 32605 |
| spread | PASS | 32238 |
| spread_home | PASS | 32068 |
| total | PASS | 31929 |
| empty | NO_FIXTURE_FOUND | 13086 |
| query_empty | NO_FIXTURE_FOUND | 12947 |
| query_unverified | TEXT_NOT_VERIFIED | 12017 |
| ambiguous | AMBIGUOUS_FIXTURE | 13512 |
| wrong_event | WRONG_EVENT | 16715 |
| click_ignored | CLICK_FAILED | 16847 |
| suspended | SUSPENDED | 20928 |
| unavailable | UNAVAILABLE | 20500 |
| changing | PRICE_CHANGED | 31180 |
| wrong_line | LINE_CHANGED | 30967 |
| wrong_side | SELECTION_CHANGED | 30478 |
| timeout | TIMEOUT | 229 |
| restart | INTERNAL_ERROR | 29849 |
| after_restart | PASS | 32070 |
| lost_response | PASS | 31816 |

Six successful runs include Elm Town v Willow City (moneyline HOME, NONE, 1.92), River Town v Maple City (spread AWAY +1.5/1.88, HOME -1.5/1.96; total OVER 2.5/1.82), Meadow Town v Elm City (total UNDER 2.5/2.02 after restart), and Harbor Town v River City (moneyline HOME/NONE/1.92 after a lost response). These were discovered from screenshots, not configured fixture names. All six final screenshots were independently visually reviewed against their structured results (evidence/fixture/visual_review.json).

Each successful instruction was resubmitted with the same ID: DUPLICATE, execution_count=1, unchanged result and gesture count. Killing the process after durable final-tap intent produced INTERNAL_ERROR after rebind, retained five gesture attempts and rejected replay. A fresh instruction then passed. Dropping the HTTP response and retrying the same ID likewise executed once. Unknown adapters were rejected before admission.

Existing coordinator regression: **11 recorded cases PASS**, plus unauthorized-access and busy-admission assertions (evidence/fixture/coordinator-regression/). Existing screenshot/OCR/gesture regression: **8/8 cases PASS their expected outcomes**, including exact screenshot failure code, successful action verification, ambiguous/missing targets, unchanged-page rejection and process recovery (evidence/fixture/visual-regression/). ADB forwarding was removed and its server stopped afterward; final-health.json records a healthy idle agent over LAN. No remaining blocker for this local simulator milestone.

Reproduction and protocol: tools/SITE_ADAPTER.md; tools/test_site_adapter.py. Evidence includes original PNGs, OCR, submitted instructions, acknowledgements, results, duplicates and restart records under evidence/fixture/.

Scope: fictional local simulator, currently visible English layouts and the proven Samsung/API33+ text-entry mechanism. Arbitrary sites, scrolling coverage and unseen layouts are not claimed. Future site implementations belong behind SiteAdapter. No live sportsbook adapter was added. Trusted-LAN pairing/security limitations from milestone 3 still apply.

---

## Milestone 3 ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â PASS on the physical Samsung

Verified 2026-09-20 on the physical Samsung SM-A136B, R5CT61TE14Z, Android 14 / API 34, starting from commit 1a20c51. App version **0.3.0-coordinator (3)**.

### Coordinator transport and execution

- Windows talks directly to the phone at its private Wi-Fi address using authenticated HTTP on port 8767. No ADB, port forwarding, desktop server or keyboard injection is required in the execution path.
- The phone exposes health/heartbeat, current state/instruction, last result, version, durable receipt acknowledgements, result polling and protected acceptance artifacts.
- OPEN_AND_TYPE validates the strict five-field schema, durably admits the ID, opens the configured Chrome page, visually finds the supplied target, taps pixel-derived bounds, enters supplied text once, and requires exact editor readback plus screenshot OCR.
- SQLite persists admission and results before effects/acknowledgement. Unique IDs remain permanent no-replay tombstones. One reserved runner accepts work at a time; duplicates return DUPLICATE and reference the original result.
- Lost communication retries use the same ID. Restart reconciles terminal text evidence or marks uncertain work INTERNAL_ERROR without replay. A new instruction can then run normally.
- The server binds only an RFC1918 IPv4 address on Wi-Fi/Ethernet, accepts private peers, requires a per-install shared token, rejects browser-origin API requests, and bounds framing, bodies, concurrency and socket lifetimes. HTTP is for a trusted LAN, not an encrypted/public deployment.
- The app's Coordinator connection screen displays its address/token and permits local start-page/token configuration. Private Windows credentials live under ignored .local/; no token is committed.
- Result status is PASS or FAIL; stage distinguishes PASS, INVALID_INSTRUCTION, DUPLICATE, TARGET_NOT_FOUND, FOCUS_FAILED, INPUT_FAILED, TEXT_NOT_VERIFIED, TIMEOUT and INTERNAL_ERROR. Busy is a rejected INTERNAL_ERROR/BUSY detail with the new ID unconsumed.

### Physical acceptance evidence

**evidence/coordinator/results.json**: all 11 recorded cases passed their assertions, plus unauthorized access and concurrent busy-admission checks. Evidence includes submitted instructions, acknowledgements, result JSON, original phone PNGs/OCR, exact text readback, detected bounds, timings, duplicate responses, and before/after restart state.

| Case | Observed |
| --- | --- |
| Search / Fulham | PASS: Windows -> Samsung visual focus/input/verification -> Windows |
| Spaces, mixed case, numbers | PASS with exact readback and screenshot OCR |
| Same instruction ID | DUPLICATE, execution_count=1, input_attempts=1, original result unchanged |
| Malformed JSON/schema | Five variants rejected INVALID_INSTRUCTION; unauthorized token rejected HTTP 401 |
| Unreachable target | TARGET_NOT_FOUND, no input attempt |
| 200ms instruction deadline | TIMEOUT (207ms observed), no input attempt |
| Discard response then retry same ID | DUPLICATE, original command PASS, one input attempt |
| Concurrent distinct instruction | Rejected BUSY, new ID not consumed |
| Kill phone process after INPUT_SENT | New PID/service rebind; INTERNAL_ERROR/no replay; same ID DUPLICATE |
| Fresh command after restart | PASS / Recovered 42 |

The suite uses only HTTP and asserts the PC ADB server port is closed at both ends. All forwarding was removed before testing. ADB was used only for build/deployment, setup and later regression/audit work. The process-kill endpoint is authenticated and available only in debuggable builds.

### Regressions diagnosed during this milestone

Mixed-case Search exposed full-page OCR merging the placeholder with its enclosing rule. Only when the normal OCR pass has no matching hint, a bounded fallback removes long rules from an OCR copy and uses sparse-text segmentation. Target bounds still come from the original screenshot; the existing focus, input and exact verification architecture remains intact. Pixel preprocessing uses bulk arrays for Samsung performance.

Chrome creates idle speculative HTTP connections. Responding to an idle read timeout with HTTP 400 left a stale response for its next navigation. The listener now silently closes idle/incomplete connections and applies a separate absolute five-second socket deadline. Repeat navigations passed afterward. Legacy accessibility tree event processing is suppressed throughout coordinator reservation and execution.

All **13 text regression cases** and **8 visual regression cases** passed on the same final APK. Evidence: **evidence/coordinator/text-regression/results.json** and **evidence/coordinator/visual-regression/results.json**. Final LAN health remained healthy/IDLE after regression process restarts and after ADB was stopped again. No blocker remains for Milestone 3.

Final APK SHA256: **7dfb8590adcb823331ded1142467c8059598396b6ea8f07b6839c87bd84e4fd7** (also evidence/coordinator/build.json).

Reproduction, pairing, schema limits and endpoint contract: **tools/COORDINATOR.md**. Windows CLI: **tools/coordinator_client.py**. LAN-only acceptance: **tools/test_coordinator.py**.

The current supported field/text contract remains the bounded Milestone 2 contract below. Recovery is at-most-once execution, not guaranteed completion after interruption. Clearing application data removes the ledger. The enabled accessibility service must be running and the phone awake/unlocked. Broader layouts, sessions and future action types remain subsequent milestones.

---

## Milestone 2 ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â PASS on the physical Samsung

Verified 2026-09-20 on Samsung SM-A136B, R5CT61TE14Z, Android 14 / API 34. Built and deployed from milestone 1 commit 7611e27.

**Generic configurable text entry + exact state verification passed.** All 13 text acceptance cases met their expected outcomes. The existing 8-case visual-control suite also passed on the same final APK.

### Mechanism and behavior

- The requested text, field hint, expected editor package and deadline come from a JSON instruction; no payload string is hardcoded in Android.
- Screenshot OCR locates the hint; pixel analysis derives the enclosing field border. dispatchGesture focuses that rectangle.
- Android's API 33+ accessibility InputMethod / AccessibilityInputConnection is enabled with flagInputMethodEditor. It commits the supplied string directly without clipboard use, ADB typing, a custom keyboard, or changing Samsung HoneyBoard.
- A fresh editor session and matching package are required before input. Existing text is selected using the input connection; a commit is attempted at most once.
- No AccessibilityNodeInfo trees are used by the text path. Legacy tree scanning is bypassed while it runs. The proven capture/OCR/gesture components are reused through small extension hooks.
- Verification requires both exact input-connection readback (including case and every space) and case-sensitive screenshot OCR from inside the detected field. OCR collapses word spacing only for the visual comparison; the independent exact readback verifies whitespace.
- Deadline, duplicate/busy admission and no-replay recovery extend the existing runner. Failures release the run for a fresh request. Pending text work becomes INTERRUPTED after service/process restart.
- Evidence is persisted atomically in files/text/<run_id>/result.json and mirrored in text_agent preferences. It includes requested/observed text, actual field bounds, screenshot references, verification flags, attempt count and phase/total timings. Before/focused/after screenshots and field crops are stored under files/visual/<run_id>/.

### Final physical acceptance

Evidence: **evidence/text-final/results.json**, per-run instructions/results/screenshots and logcat. Reproduction and API references: **tools/neutral-visual/TEXT_ENTRY.md**.

| Test | Expected and observed |
| --- | --- |
| normal: orchard | PASS |
| spaces: clear blue sky | PASS |
| mixed case: MiXeD Case | PASS |
| numbers: 907314 | PASS |
| repeated spaces: Alpha  beta 42 | PASS; both spaces preserved in exact readback |
| absent field | FIELD_NOT_FOUND; zero input attempts |
| disabled field | FOCUS_FAILED; zero input attempts |
| input connection disappears after focus | INPUT_FAILED; zero input attempts |
| page rejects the inserted value | TEXT_NOT_VERIFIED; no second commit |
| configured 200ms deadline | TIMEOUT; zero input attempts; late OCR cannot act |
| fresh instruction after failures | PASS |
| kill app after INPUT_SENT / before verification | INTERRUPTED; persisted input_attempts=1; same ID rejected |
| new instruction after process restart: Recovered 42 | PASS |

Successful final cases completed in 4.773ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Å“5.071 seconds. Example pixel-derived field bounds: [57,395,664,521]. Each completed ID was re-submitted and its result remained unchanged. The selected keyboard stayed com.samsung.android.honeyboard/.service.HoneyBoardService.

Failure states include an after screenshot when the deadline permits. Timeout and process interruption may prevent an after-frame; those references are explicitly null with a persisted reason. They never imply successful observation.

Milestone 1 regression evidence: **evidence/text-visual-regression/results.json** ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â all eight cases passed their assertions, including capture error code 4, visual tap/state verification, ambiguity rejection, duplicate protection and process recovery.

Final tested APK SHA256: **5C08D1AC852A2A8C49EF32F390C80334B4CA57E809972D961A79C61E453E2EA4**.

### Scope and next work

No blocker remains for Milestone 2. The current bounded contract supports visible outlined fields with a unique single-word hint and 1ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Å“128 UTF-16 units of supplied text on API 33+. Borderless/ambiguous/unidentifiable or unprovably focused fields fail explicitly. Password fields are excluded. Multiline, clipped text and non-English visual recognition are not claimed by this acceptance proof.

Next: session handling, production coordinator intake, broader visual selectors and a neutral end-to-end instruction workflow. No production coordinator endpoint or keyboard replacement was introduced.

---

Updated: 2026-09-20 21:40 Europe/London.

## Milestone 1 ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â PASS on the physical Samsung

Accessibility screenshot -> OCR target bounds -> dispatchGesture tap -> second screenshot -> verified neutral page state change.

Device: Samsung SM-A136B, R5CT61TE14Z, Android 14 / API 34, 720x1600.
App: existing com.bet365agent / Bet365Agent. Chrome: com.android.chrome.

## Exact diagnosis

The inherited captureScreenshotAsset() returned null on every Android version and never called takeScreenshot(). The historical ÃƒÂ¢Ã¢â€šÂ¬Ã…â€œFailed to capture initial screenshotÃƒÂ¢Ã¢â€šÂ¬Ã‚Â therefore had **no Android result/error code**. It was not evidence of a Samsung restriction.

Service XML also omitted android:canTakeScreenshot="true". Bound capabilities were 33 (content + gestures); after deployment Android rebound with capabilities=161 (33 + screenshot capability 128).

Other inherited gaps: missing bundled OCR model, estimated coordinates, main-thread sleep, dispatch acceptance treated as completion, and a verification fallback returning true without observing changed state. These were replaced in the neutral visual test path.

## Implemented and deployed

- Real API 30+ asynchronous takeScreenshot callback with software bitmap copy and hardware-buffer cleanup.
- Exact onSuccess timestamp or onFailure numeric code/symbolic name logged. Success has no Android error code; the persisted error key is removed on success.
- Errors 1 and 3 retry at most twice, 700ms apart. Other capture errors terminate the run.
- Tesseract OCR and PNG writing on a worker. Existing tess-two and AccessibilityService/dispatchGesture architecture retained.
- Official English legacy model bundled and atomically installed in private storage. Automatic page segmentation returns actual word bounds; sparse mode missed bordered labels.
- One exact NEPTUNE match required. Precondition: exact words ÃƒÂ¢Ã¢â€šÂ¬Ã…â€œNeutral visual testÃƒÂ¢Ã¢â€šÂ¬Ã‚Â and READY. Postcondition: COMPLETE and READY absent. No guessed bounds or success heuristic.
- Gesture completion/cancellation callbacks; bounded readiness and verification retries; 30-second overall deadline and late-callback guards.
- Durable consumed IDs before effects, busy/duplicate rejection, persisted phase/result, restart interruption without replay. This is currently specific to the neutral runner, not a general coordinator/session protocol.
- Service connect/unbind/destroy cleanup. A killed process recovers as INTERRUPTED on rebind.
- Shell test receiver requires android.permission.DUMP and exists only in debug builds.
- App visual-test button opens the neutral localhost page before starting.

MediaProjection was not added: repeated Accessibility captures succeeded on this Samsung, including after process restart, so the requested fallback condition was not met. Other devices, API levels below 30, and secure windows are not covered by this proof.

## Physical acceptance evidence

All eight final suite cases met their assertions; evidence/visual-final/results.json records them. Negative cases intentionally report FAIL.

| Case | Observed result |
| --- | --- |
| Invalid display 999 | Android onFailure **4 / ERROR_TAKE_SCREENSHOT_INVALID_DISPLAY**, persisted exactly |
| Neutral flow, twice | PASS: captures, OCR bounds, completed gesture, changed-state verification |
| Duplicate target labels | FAIL: found 2; no gesture |
| Missing target | FAIL: found 0; no gesture |
| Page ignores tap | Gesture completes; verification FAIL, no false PASS |
| Kill app while RUNNING | New process/rebind, INTERRUPTED, same ID rejected |
| Fresh run after restart | PASS |

Duplicate successful run IDs were also resubmitted and rejected without another gesture.
The actual app button was tapped through ADB using UI-discovered bounds; manual-1789936815011 passed.

Measured NEPTUNE bounds: [246,701][476,738]; gesture center (361,719.5). These came from OCR, not DOM or fixed coordinates. The new screenshot contained COMPLETE at [55,869][341,909] and no READY.

Evidence contains app-captured PNGs, OCR rectangles, persisted results and AgentVisual logs. Final tested APK SHA256: ADC62DF46B14DDB481D6CFB48991494F8373C3216A3521629097E2215962A669.

The deadline and transient-error retries are implemented; forced timeout/transient-error injection were not part of this suite. A real error callback was exercised with invalid display 999.

## Reproduce

See tools/neutral-visual/README.md for local build/deploy commands.
Run tools/test_android_visual.py --adb <adb.exe> --serial R5CT61TE14Z --output evidence/<new-run>.
The script serves local HTML, forwards an ephemeral port, launches Chrome, triggers the debug receiver, verifies results and saves evidence. Screenshot/OCR/target gestures/state verification all run on the phone. The host never taps the webpage target.

The app button expects the page served on host port 8765 and adb reverse tcp:8765 tcp:8765. The suite closes its own server/forwarding when finished.

## Remaining milestones

1. Production coordinator intake and dispatch protocol; text instructions currently enter through the protected debug receiver.
2. Broader visual selectors and layouts beyond the now-verified outlined text field and two-button fixtures.
3. General state verification, session handling, coordinator intake and neutral end-to-end workflow.
4. Extend persistence/idempotency/recovery to all generic coordinator actions.

Earlier BUILD_STATUS reported the legacy search query ÃƒÂ¢Ã¢â€šÂ¬Ã…â€œFulhamÃƒÂ¢Ã¢â€šÂ¬Ã‚Â passed on 2026-09-20. This historical result is preserved as context, not revalidated here. Existing legacy search/fixture code remains.

No physical-action or credential blocker remains for this milestone. Tracked Gradle/build artifacts were already dirty at takeover and are excluded from the source milestone commit.



