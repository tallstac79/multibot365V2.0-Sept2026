# Desktop Chrome worker (supervised build)

A second execution worker that speaks the phone coordinator's HTTP contract but drives Bet365 in desktop Chrome.
The backend remains the only source of truth. The worker receives the same instruction payloads the phone receives
(`Pipeline.build_payload`) and returns results in the phone's schema.

## Parts

| File | Role |
| --- | --- |
| `desktop_worker/chrome.py` | Installed Google Chrome with a dedicated profile (`.local/desktop-chrome-profile`) and a CDP port on 127.0.0.1:9333. Playwright uses `connect_over_cdp`. There is no Multilogin or antidetect layer. The operator signs in by hand, and the code never types or reads credentials. Chrome is started outside the caller's process tree and job object (WMI `Win32_Process.Create`, then `CREATE_BREAKAWAY_FROM_JOB`, then the old detached start), with the same flags. |
| `desktop_worker/lifecycle.py` | Chrome status (CDP probe + process list: UP / HUNG / DOWN), relaunch of the same profile, and the visual Bet365 session state (screenshot + OCR: LOGGED_IN / LOGGED_OUT / REALITY_CHECK / UNKNOWN). Never logs in and never answers Reality Check; anything but LOGGED_IN raises an `operator_alert` through `workflow.operator_notice`. CLI: `py -3.11 -m desktop_worker.lifecycle`. |
| `desktop_worker/layout.py` | Visible page text plus geometry from the DOM (a TreeWalker over text nodes; it calls none of the page's wrapped query APIs), in the phone's OCR word format. Used on the event / market pages only, before the selection click. Read-only: the page is never tagged or modified. |
| `desktop_worker/bet365_page.py` | Pure functions that turn the page into the phone's header lines and quotes. Group titles are found by font (15px bold) and columns by bold headers. |
| `desktop_worker/jvm/DesktopDecisions.java` + `decisions.py` | Decision bridge. The phone's own Java classes (EventPage / EventIdentity / CompetitionStructure / FootballLineCheck / ExecutionTolerance / FootballMarkets / HeldSlipIdentity) are compiled unchanged from `android/` into `.local/desktop-decisions/decisions.jar`. One JVM answers over stdin/stdout, and the jar is rebuilt whenever a source is newer. Identity, competition, kick-off, the football ±0.25 line band and the price/line tolerances are therefore identical to the phone's. |
| `desktop_worker/ledger.py` | SQLite at-most-once ledger. An ID is committed before it is acknowledged and is never evicted. At restart, PENDING becomes INTERNAL_ERROR and is never replayed. |
| `desktop_worker/server.py` | HTTP on 127.0.0.1:8768 with a bearer token (`.local/desktop_worker.json`). Endpoints: `/health`, `POST /instructions` (202; 409 DUPLICATE; 409 BUSY "ID not consumed"), `GET /instructions/ID` (202 pending / 200), `/evidence`, `/artifacts/NAME`. |
| `desktop_worker/workflow.py` | SESSION_CHECK, and ADAPTER_WORKFLOW hold/ready plus the supervised-only `discover`. The betslip part (empty-slip check to Place Bet check) is visual only. |
| `desktop_worker/visual_slip.py` | The betslip as a person sees it: CDP `Page.captureScreenshot`, Tesseract OCR (`C:\Program Files\Tesseract-OCR`), ordinary mouse clicks / keyboard typing at coordinates read from the screenshot, and Bet365's own `BetsWebAPI/addbet` answer read passively. No script in the page, no DOM query of the slip. It has no function that presses Place Bet. |
| `desktop_worker/final_action.py` | Supervised one-shot final action, invoked by hand only (`py -3.11 -m desktop_worker.final_action INSTRUCTION.json --confirm-one-live-bet`). Hard GBP 0.10 cap, one Place Bet click at most per key (a marker in `.local/final-action/` is written before the click). Not wired into `server.py` or any routing. See 'Supervised final action' below. |
| `desktop_worker/betslip.py` | Slip market-label vocabulary (`LABELS`, plus `GROUP_LABELS`: 'Total Goals' only for a quote from the Goals Over/Under group) and `money()`. The old DOM slip reader is removed. |
| `tools/desktop_supervised.py` | Sends one run to the desktop worker: either a payload built by `Pipeline.build_payload` from a private copy of the production row (fresh `sup-` ID), or a manual payload. It then judges the result with `execution_terms.comparisons_for_result`. |

## Safety properties

- `health.phone_final_action_armed` and `local_execution.enabled` are always false, so the automatic policy's `phone_final_action_permission` check can never pass for this worker.
- PLACE_HELD and MY_BETS are refused with `placement {tapped: false, outcome: NOT_TAPPED}`.
- The only code that clicks Place Bet is `desktop_worker/final_action.py`. It runs from the command line with `--confirm-one-live-bet`, is capped at GBP 0.10 and clicks once per key. The HTTP worker, coordinator, backend and phone paths never call it.
- Only the alert's own pre-match `#/AC/` link is used. The Search route is not implemented and fails closed.
- Prices must be decimal. Fractional odds, which a logged-out session shows, are never used as a price.
- Every step saves a text layout (`sNNN_name.txt`, the phone's OCR format) and a screenshot under `.local/desktop-evidence/<run_id>/`.

## Run

```
python -m desktop_worker.server
python -m tools.desktop_supervised --manual evidence/desktop-worker/manual_nir_ah_home.json --mode discover
python -m tools.desktop_supervised --instruction on-xxxxxxxx --mode hold
py -3.11 evidence/desktop-worker-placebet-ready/scripts/run_ready.py LABEL evidence/desktop-worker-placebet-ready/instructions/nir_ah_home_0.json ...
```

## Status, 28 Sep 2026 (supervised trials on a separate account)

- Proven: loopback worker contract, session check, event link opened (a hash-only navigation can show a stale "no
  longer available" page, so the worker reloads once), EXACT identity from the phone's decision code, market discovery
  (Popular, then Goals / Asian Lines, then the market's own alternative group), exact line first, the ±0.25 band via
  the phone's `nearest`, minimum price check, a fresh re-read of the cell before clicking, and slip reading (title,
  handicap, price, market, fixture, stake, To Return, Place Bet). One manual slip capture: AH HOME 0.0 @1.950, stake
  0.10, To Return £0.19, Place Bet enabled, removed again.
- Stopped, cause identified (bisected 28 Sep 2026, every run recording Bet365's own `BetsWebAPI/addbet` exchange):
  the `addbet` request is byte-identical in passing and failing runs. What decides is whether a script has queried
  Bet365's betslip elements beforehand:

  | evaluated in the page before the selection click | `addbet` |
  | --- | --- |
  | nothing, a 300 ms wait, reading the page text (`layout.read_words`) | accepted |
  | `document.querySelectorAll('div')` | accepted |
  | `querySelectorAll('.bss-StandardBetslip')`, even followed by a 3 s wait | `{"cs":2,"sr":-1}`: "Sorry, there has been an error" |
  | `querySelectorAll('.bss-NormalBetItem_Market')` | the same |

  A plain DOM query has no side effects, so this is Bet365 watching for scripts that inspect its betslip and refusing
  the next bet-slip addition: an anti-automation check. Reworking the worker so the check does not fire would be
  designing around Bet365's bot detection, and that is not done. The worker fails closed (`BETSLIP_ERROR`, with the
  `addbet` exchange in its evidence). Everything before the slip (event, identity, market, line, price, the click
  target found by text and geometry without modifying the page) works and stays useful for replay and verification.

### Independent re-check, 28 Sep 2026 13:05-13:40 BST (`evidence/desktop-worker-addbet/`)

Re-tested from scratch with paired runs on the same event and cell (Place Bet never touched). Result: real detection,
now with its mechanism shown.

- Bet365 replaces `document.querySelector/querySelectorAll/getElementsByClassName/getElementsByTagName` and the
  `Element.prototype` equivalents with one obfuscated wrapper that passes every call's selector into its own
  interpreter (`page_dom_api_hooks.json`).
- Plain click: 4/4 accepted. Main-world `querySelectorAll('.bss-StandardBetslip')`: refused every time. Main-world
  `querySelectorAll('.zzq-NotABet365Class')` (no betslip, matches nothing): refused. `querySelectorAll('div')`:
  accepted. The same `.bss-StandardBetslip` read through Playwright's isolated world (does not pass through the page's
  wrappers, same CDP session): accepted.
- addbet URL, POST body, header names, cookie names, slip state, timings, cookies and storage are identical between
  accepted and refused runs; only the per-request `x-net-sync-term` / `x-request-id` values differ (as they do on every
  request).
- So it is not a betslip-init race, focus, stale selection, session or CDP-domain side effect. A worker change that
  avoids the check (isolated-world or CDP-DOM reads) would work only by hiding automation from Bet365 and is not made.
  The worker remains fail-closed at BETSLIP_ERROR. The event / identity / market / line / price stages are unaffected.

## Place Bet-ready without in-page slip scripts, 28 Sep 2026 14:28-15:10 BST (`evidence/desktop-worker-placebet-ready/`)

David approved removing the flagged action instead of hiding it. The slip flow no longer runs any script in the page
and never queries the slip's DOM (no `page.evaluate`, no Playwright locator, no CDP DOM/Runtime read of the slip, no
isolated-world reads). It works the way a person does:

| step | how | verified by |
| --- | --- | --- |
| empty slip | right after the fresh event load: screenshot; if the white slip panel is showing, click its visible remove (X), then load the page afresh and check again | screenshots `slip_check`, `slip_after_remove`, `slip_after_reload`, `slip_before_click` |
| add selection | the existing fresh read of the grid and the existing click on the price cell (unchanged) | Bet365's own `addbet` response to that click (`cs:1 sr:0`, exactly one bet), read passively, plus a screenshot of the slip |
| slip terms | OCR of the slip panel: selection + handicap, price, market, fixture | each checked on the screen AND in the addbet answer (fixture, market label, selection, line, odds within 0.011), one selection on both; the price is then judged by the phone's tolerances (`fresh` / `price_ok` / `line_ok`) |
| stake | click the slip's own stake control ('Set Stake' or the Stake box) found on the screenshot, then Ctrl+A, Backspace and type the stake | OCR: the stake equals the instruction; To Return = stake x price (±0.011) |
| Place Bet | located from the 'Place' 'Bet' words; enabled = the button face is Bet365's active green (grey when disabled) | OCR + pixel colour on two frames (`slip_stake`, `slip_final`), no notice on the slip |
| stop | READY / `COMPLETE_EXECUTION_READY` in the existing result schema; `gesture_dispatched: false`, `wager_submitted: false` | the hold never clicks Place Bet; only the hand-invoked `final_action.py` can (below) |

A read that does not come out cleanly is retaken (up to 6 frames, 400 ms apart; the stake box's blinking caret can hide
a digit), and nothing is accepted from a frame that does not read cleanly. The term checks use the phone's readback
rule (up to 3 frames). Price and line changes follow MultiBot's existing rules. A slip price or line is judged by the
phone's tolerances. Any change notice fails closed, and a notice asking to accept a change fails `PRICE_CHANGED`,
because MultiBot never presses Accept Change (the phone's `PlaceBetTarget.changeNotice` rule). No change notice came up
in these runs. A Bet365 'Reality Check' dialog fails `SESSION_EXPIRED`: the operator answers it by hand, and the worker
never does.

Before the click, the event / market stages are unchanged: `layout.read_words` (a TreeWalker text read, not a wrapped
API) and `open_tab` / `expand` / `element_for` (Playwright locators on the event grid, not the slip). The paired trials
and every run below had these before the click, and Bet365 accepted every addbet, so nothing there was changed.

Result with the final code (batch `final`: 15 runs, 4 events, AH / Goal Line / Goals Over/Under / Full Time Result,
home / away / over / under): **14/15 reached Place Bet-ready and stopped**. The one miss (`final-11`, Sweden AH 0.0)
failed closed before any click with `LINE_CHANGED`. The existing discovery read the expanded Alternative Asian Handicap
while the page was still laying out (the next group's title still sat over the new rows), so the 0.0 row was assigned
to the wrong group. That is pre-existing discovery behaviour, left unchanged by instruction.

Across all 30 live runs (calibration 3, first proof batch 12, final 15), the worker clicked a selection 26 times and
Bet365 accepted all 26 addbets (`cs:1 sr:0`), with zero `{"cs":2,"sr":-1}`. Stake entry and the Place Bet checks
caused no further BetsWebAPI traffic and no slip notices, so the screenshot / OCR / passive-response verification does
not itself cause refusals. First-batch failures, fixed before `final`:

- 3 runs: Bet365 labels the Goals Over/Under group 'Total Goals' on the slip. That label is now accepted for that group only.
- 1 run: one whole-panel OCR pass missed the footer. The footer band is now read on its own, and the first slip frame must show the stake control and Place Bet.

Also seen and left unchanged (existing event / market logic): Turkiye 1X2 is never found, because the decision bridge
returns the folded name 'Turkiye' while the page shows 'Türkiye', so the Full Time Result row does not match. It fails
closed with `TARGET_NOT_FOUND`, and no click is made.

## Supervised final action (28 Sep 2026)

`desktop_worker/final_action.py` places ONE live bet under supervision. It is explicitly invoked, not part of production
routing (`/health` still reports `final_action_armed: false`, and PLACE_HELD is still refused).

1. The worker's own hold (`DesktopBet365.hold`) must reach `COMPLETE_EXECUTION_READY`. It clears the slip, adds the
   selection, types the stake and verifies. `hold` now keeps its verified context in `DesktopBet365.ready`; that is
   the only workflow change.
2. Stop-prompt scan: OCR of the centre of a fresh screenshot for Reality Check, login, verification, captcha or
   limit prompts. Any hit refuses.
3. Fresh screenshot + OCR immediately before the click. The existing `_check_slip` checks fixture, market, selection
   and line against Bet365's addbet answer, and the price against the minimum with the existing tolerances.
   `pre_click_problems` then requires: exactly one selection; no slip notice ('Accept Changes' refuses at once and is
   never pressed); stake box = 0.10 (never above the cap); 'To Return' on the Place Bet button = 0.10 x odds (within
   1p); the Place Bet button enabled; no 'Total Stake' line; and the Jackpot 365 toggle OFF (from pixels: grey track,
   white knob on the left; anything else refuses). If a mismatch persists over 3 fresh frames, it refuses.
4. ONE click through `OneClick`. The marker file is written before the click; there is no retry and no double click.
5. Receipt: screenshots + OCR of the slip panel for up to 25 s, plus Bet365's `BetsWebAPI/placebet` answer read
   passively (tokens redacted). The outcome is `PLACED` only when the screen shows 'Bet Placed' and a reference is
   read (from the screen or placebet). Anything else is `PLACEMENT_UNKNOWN`, which is reconciled on My Bets through
   ordinary clicks (header 'My Bets', then 'Unsettled') read by OCR: `PLACED` / `NOT_PLACED` / unresolved. Place Bet
   is never clicked again.

Live run, 28 Sep 2026 18:31 BST (after `recheck3`: Turkiye v Italy Draw and Sweden v Poland AH home 0.0 both
`COMPLETE_EXECUTION_READY`): Turkiye v Italy, Full Time Result, Draw at 3.50 (5/2), stake GBP 0.10, 1 click, receipt
'Bet Placed', Bet Ref BT7071586031I, To Return GBP 0.35, balance GBP 5.00 -> 4.90. Outcome `PLACED`. Evidence:
`evidence/desktop-worker-final-action/`. Tests: `tests/test_desktop_final_action.py`.

## Chrome lifecycle and recovery (28 Sep 2026)

**Incident.** The dedicated Chrome stopped between 19:14 and 19:16 BST, about 45 minutes after the supervised
placement. Root cause: it had been started at 11:11 BST by a probe script run from the Claude desktop app's shell. That
app is an MSIX package, so Chrome was inside the package's process tree and job object (`DETACHED_PROCESS` only detaches
the console). At 19:16:08 Windows updated the package (Claude 2.9939.2.0 -> 2.9939.4.0). The AppXDeploymentServer log
shows `TerminateApplications successful`, and every process in the package was killed, Chrome included. Evidence:
the profile's `exit_type` is `Crashed` (not a clean exit), there are no Crashpad reports (not a crash), the last profile
writes were at 19:14:54, Chrome's `browser_last_live_timestamp` was 19:11:37 BST, and there were no shutdown or sleep
events. Nothing in `final_action.py` / `run_ready.py` closes the browser: Playwright's `connect_over_cdp` only disconnects.

**Fix.**
- Launch: `chrome.launch` starts Chrome through WMI `Win32_Process.Create` (the parent is `WmiPrvSE.exe`, so no caller's
  tree or job). The fallbacks are `CREATE_BREAKAWAY_FROM_JOB`, then the old detached start. The flags and profile are
  unchanged (`chrome.launch_args`).
- Detection: `server.Worker.watch_once` probes CDP every 30 s. When Chrome is down and the worker is idle, it queues
  one internal recovery. Every instruction also checks CDP first, and if Chrome is down it recovers before running.
- Recovery (`lifecycle.recover`): relaunch, open Bet365 home only if no Bet365 tab is open, then read the session
  state from screenshots. LOGGED_IN leaves the worker back at IDLE. LOGGED_OUT / REALITY_CHECK / UNKNOWN / CHROME_DOWN
  keep it fail-closed. `/health` carries `operator_alert` (codes `SESSION_LOGGED_OUT`, `REALITY_CHECK_OPEN`,
  `SESSION_UNKNOWN`, `CHROME_DOWN`), the alert is logged to `logs/desktop_worker.log`, and the instruction fails
  `SESSION_REQUIRED` / `SESSION_EXPIRED` without touching the page.
- Health: new `chrome` block (`state`, `cdp_up`, `last_recovery`), `session.visual_state`, and `state: RECOVERING`
  while a recovery runs.
- Identity: `device_id` desktop-chrome, `worker_id`, the account fingerprint, the token and the ledger are never
  touched by recovery.

**Live check (20:04 BST).** Chrome was down. It was relaunched via WMI (pid 2316, parent `WmiPrvSE.exe`) with the same
profile, and the Bet365 session survived: logged in, GBP 4.90, My Bets badge 1. A Reality Check was open ("session
exceeded 08:26:31"), so the state is `REALITY_CHECK`, fail-closed, with alert `REALITY_CHECK_OPEN`. Nothing was clicked.
Evidence: `evidence/desktop-worker-lifecycle/20260928-200423/`. At 20:08 the Reality Check had been
cleared by the operator (state LOGGED_IN, `check-20260928-200800/`). A read-only My Bets check then found the placed bet
OPEN (`evidence/desktop-worker-final-action/d_9b2dbdeb76e94924a752/reconciliation/`). Tests: `tests/test_desktop_lifecycle.py`.

## Persistent supervisor and minimum safe routing (28 Sep 2026, 20:13-21:00 BST)

No live bet was placed in this work. Place Bet was never clicked: PLACE_HELD ran as a dry run only.

### Supervisor (Scheduled Task, interactive user session)

`desktop_worker.server` runs under `desktop_worker/supervisor.py`, which is started by the Windows Scheduled Task
**`MultiBot365DesktopWorker`**. It does not belong to any app.
- **Triggers:** at log on of `DESKTOP-IVUNJ9J\WINDOWS11`, plus a time trigger that repeats every 5 minutes as a backup. `MultiplePolicy=IgnoreNew`, so the 5-minute trigger does nothing while an instance is running.
- **Session:** `InteractiveToken` with least privilege. Chrome needs the desktop session. The NSSM services on this PC run as LocalSystem in session 0, which cannot reach that session.
- **Recovery and limits:** restart on failure 999 times at 1-minute intervals; no execution time limit.
- **Behaviour:** the supervisor takes a single-instance lock (`.local/desktop_supervisor.lock`). It starts `python -m desktop_worker.server` with no console window and restarts it when it exits, with backoff (2 s doubling to 60 s, reset after 5 minutes up).
- **Existing server:** it never starts a second server while port 8768 is already served.
- **Logs:** `logs/desktop_worker_supervisor.log` and `logs/desktop_worker_server.log` (rotated at 5 MB).
- **Chrome:** Chrome is launched through WMI, so it is not a child of the server or the supervisor. A server restart leaves Chrome running.

    py -3.11 -m desktop_worker.supervisor status     # task status, supervisor/server PIDs, health (no secrets)
    py -3.11 -m desktop_worker.supervisor start      # enable the task and run it now
    py -3.11 -m desktop_worker.supervisor stop       # disable the task, stop the supervisor and its server (Chrome stays)
    py -3.11 -m desktop_worker.supervisor install    # (re-)register the task from desktop_worker/supervisor.py, start it
    schtasks /Query /TN MultiBot365DesktopWorker /V /FO LIST

Proof (`evidence/desktop-worker-routing/supervisor/`):
- **Server killed (20:18:50):** the supervisor restarted it in about 3 s (new PID, `restarts: 1`). Chrome PID 2316 was unchanged.
- **Code reloads:** killing the server was also used twice to load new code. Each time it came back healthy.
- **Supervisor killed:** `supervisor_crash_proof.txt` shows the task starting a new supervisor. That supervisor adopted the orphaned server while it still served the port, and started a fresh server once the orphan was killed.

### Routing pieces (all behind flags, all OFF)

| Piece | Where | Commit |
|---|---|---|
| a. `desktop-chrome` routing target behind `desktop_routing_enabled` (default **false**). While it is false, `gateway_for` returns the phone `CoordinatorGateway` unchanged. When it is true, work goes to the desktop only if it is routable (healthy, ready, IDLE, no `blocked_reason`) **and** bound to `desktop_expected_worker_id` and `desktop_expected_account_fingerprint` (both empty, so never routed). A PLACE_HELD always goes to the device that holds its hold. Manual supervised path: `tools/desktop_route.py` | `core/device_routing.py`, `core/pipeline.py` Settings, `tools/pipeline_service.py`, `tools/desktop_route.py` | 914cb34 |
| b. HOLD stores the verified terms plus a sha256 (`holds`). Approval reuses the backend's own `Pipeline.place_held_payload` (`confirmation_status=APPROVED`). PLACE_HELD checks, in order: APPROVED, the hold exists / is unused / is no older than `hold_max_age_seconds` (115), the terms equal the hold, the caps, the intent guard and the session. It then runs a fresh visual re-verify (`final_action.Placement.verify_preclick`), checks the age again and records the intent. It is a **DRY RUN** unless `live_click_enabled=true` in `.local/desktop_worker.json` **and** env `DESKTOP_LIVE_CLICK=1`. MY_BETS is a read-only header navigation plus thresholded OCR, in the `bet_matching` shape, with a match verdict | `desktop_worker/held.py`, `server.py` | d42bc60, ecd0e78 |
| c. Per-bet cap `max_stake_per_bet` (default **0.10**), applied before the page is touched (also refuses a hold above the cap). Daily live cap `max_daily_live_stake` (0.50) counts every live intent. The backend limits (max_daily_loss etc.) still apply before any approval | `held.precheck` | d42bc60 |
| d. Durable per-instruction guard, `final_intents` in `.local/desktop_worker.sqlite3`. The intent is committed before a click. If a live intent has no confirmed receipt, it is never clicked again: `PLACEMENT_UNKNOWN`, `next_step MY_BETS`. This holds after a restart too (`reconcile_restart` no longer reports NOT_TAPPED for it). The 28 Sep day marker was imported as PLACED `BT7071586031I`; the marker file is kept | `desktop_worker/ledger.py` | d78f921 |
| e. `/health`: `healthy` / `ready` / `blocked_reason`. The reasons are `CHROME_DOWN`, `LOGGED_OUT`, `REALITY_CHECK`, `SESSION_UNKNOWN` (nothing read yet, or the read is older than 300 s) and `RECOVERING`. A visual session probe runs every 120 s while idle and after every instruction (screenshot only, no navigation). The coordinator treats anything but healthy+ready as not routable | `server.py` | d42bc60 |
| f. Telegram via `core.status_notifier.TelegramBotSender` and the `.local/pipeline.json` notifications config. One message per blocking episode (the state persists in `.local/desktop_alerts.json`, so a restart does not repeat it). A different block gets its own message; a recovery message is sent when the block clears. SESSION_UNKNOWN only alerts after 5 minutes. The token is never printed or stored, and errors are sanitised. Reality Check and login stay manual | `desktop_worker/alerts.py` | f4790d0 |

Flags now: `desktop_routing_enabled` **false** (absent from `pipeline.json`, so the default applies); `live_click_enabled`
**false** in `.local/desktop_worker.json`; `DESKTOP_LIVE_CLICK` **unset**; `max_stake_per_bet` 0.10; `hold_max_age_seconds` 115.
The phone and pipeline behaviour is unchanged. The running pipeline service was not restarted.

### Supervised E2E (20:32-20:36 BST, `evidence/desktop-worker-routing/e2e/`)

Sequence: manual target health → HOLD → approval → PLACE_HELD dry run → RESET_BETSLIP → MY_BETS.
1. **Health (manual target):** routable. Normal routing is false because the flag is OFF.
2. **HOLD** `rt-e2e-sco-sui-draw`: Scotland v Switzerland (UEFA Nations League B, Tue 29 Sep 19:45 BST, pre-match), Full Time Result, Draw @3.50, stake 0.10. Result: `COMPLETE_EXECUTION_READY` in 24 s, `terms_hash 2c58a97d...`.
3. **Approval:** `Pipeline.place_held_payload` gave `PLACE_HELD rt-e2e-sco-sui-draw-place`, APPROVED.
4. **PLACE_HELD:** the fresh re-verify passed. Result: `DRY_RUN`, `tapped=false`, `would_click (805,802)`, To Return 0.35. The intent was recorded as `DRY_RUN` and the hold consumed. **No click.**
5. **RESET_BETSLIP:** the held selection was removed from the slip.
6. **MY_BETS reconcile of BT7071586031I:** the first read was PARTIAL, because OCR read "Italy" as "ttay". After the fix (ecd0e78), `found=true`, `confidence=EXACT` (Draw 3.50, Full Time Result, Turkiye v Italy, £0.10, To Return £0.35).

The ledger snapshot is in `e2e/ledger_snapshot.json`. The worker screenshots for each step are in `e2e/runs/`.

A Telegram TEST alert (clearly labelled "TEST ONLY") was sent at 20:36 BST (`telegram_test.txt`).

### Remaining before enabling normal desktop routing (as of 21:00; superseded by the section below)
- **Per-row device binding in the pipeline:** `Store` records `settings.device_id` (the phone) for every instruction, and the PLACE_HELD pre-tap check compares `row.device_id` with `settings.device_id`. Rows sent to the desktop need their own device and worker binding before the flag is turned on. `RoutingGateway` already keeps the per-instruction target.
- **Approval policy for the desktop:** decide whether automatic approval may cover `desktop-chrome`. Its health keeps `phone_final_action_armed=false`, so today only a manual approval path would reach it.
- **Live click:** a supervised live PLACE_HELD at £0.10 with both live flags set (only with David's go-ahead), then turn them off again.
- **Settlement and reconcile via the pipeline:** the pipeline's MY_BETS/settlement jobs should target the desktop for desktop bets. The desktop result still lacks the `status` (OPEN/SETTLED) parsing that the phone's cards give.
- **Configuration:** set `desktop_expected_worker_id=dw-bde27aa2fe41` and `desktop_expected_account_fingerprint=f210d5f9dde5` in `pipeline.json` when enabling.
- **Reality Check cadence:** it appears every 60 minutes and stays manual, so the desktop is not routable until David answers it. Expect roughly 1 blocked episode per hour.

## Desktop as its own backend device, supervised target, Reality Check auto-recovery (28 Sep 2026, 21:21-23:00 BST)

Evidence: `evidence/desktop-worker-backend-placement/`.

### Backend device identity
- `devices` table (additive, `core/pipeline_store.py`): `desktop-chrome` / kind `desktop_chrome` / worker `dw-bde27aa2fe41` /
  account `f210d5f9dde5`, registered from `pipeline.json` (`desktop_expected_worker_id`, `desktop_expected_account_fingerprint`).
  A changed identity is updated and audited (`DEVICE_IDENTITY_CHANGED`). Phone records are not touched.
- The pipeline polls the desktop's `/health` every tick (only when that identity is configured) and records it in
  `device_state` / `session_state` under `desktop-chrome`, never under the phone's device ID.
- An instruction sent to the desktop is bound to it (`instructions.device_id = desktop-chrome`, audit `DEVICE_TARGET`). From then
  on everything for that row uses the desktop: result polling, the held-slip release, PLACE_HELD, the automatic checks, the bet's
  worker/account binding and My Bets.

### Choosing the target (`Pipeline._choose_target`)
- `desktop_routing_enabled` stays **OFF**. With it OFF, a new instruction goes to the desktop only through the **supervised
  target**: `py -3.11 tools/desktop_route.py target --minutes M --lead L`. This arms the control `desktop_target_next` for ONE
  instruction. That instruction must be pre-match football, received after arming, with kick-off at least L minutes ahead.
  The target expires, and it is consumed atomically when the instruction is dispatched. `untarget` cancels it.
- Even when armed, the desktop is chosen only while it is routable: healthy, ready, IDLE, no `blocked_reason`, bound to the expected
  worker and account. Its backend session must also be AUTHENTICATED within the 120 s gate, and no desktop My Bets check may be running.
  Otherwise the instruction runs on the phone as before.
- With the flag ON (not enabled), the same routable test sends new work to the desktop without a target.
- `tools.pipeline_service.gateway_for` returns the phone gateway. `desktop_gateway_for` attaches the `DesktopGateway` when the
  identity is configured.

### Automatic approval for desktop instructions
The same `FinalAction.automatic_checks` apply, with the same rules, limits and tolerances. Only the identity checks are bound to
the row's device:
- **Session and health:** from `desktop-chrome`.
- **Identity:** `worker_identity` and `account_identity` are checked against the desktop's expected values.
- **Arming:** `desktop_final_action_permission` replaces `phone_final_action_permission`. It requires the desktop health
  `final_action_armed=true` (which the worker reports only while BOTH `live_click_enabled` and `DESKTOP_LIVE_CLICK=1` are set),
  `phone_final_action_armed` not true, and `kind=desktop_chrome`.

The desktop worker's own guards (hold age 115 s, £0.10 cap, £0.50 daily live cap, durable intent, PLACEMENT_UNKNOWN on an unclear
receipt) still run on PLACE_HELD.

### Reconciliation routing
- `FinalAction.schedule(..., scope)`, `poll(gateway, desktop)`, `device_busy(scope)` and `next_reconciliation(..., scope)` route each
  My Bets check by the bet's `worker_id`. Bets placed on the desktop worker/account are verified and settled on the desktop.
  Phone bets are checked on the phone. A check never runs on the other device's account.
- The bet row's `binding_source` says `desktop worker desktop-chrome health at the placement result`.

### Reality Check auto-recovery (worker)
- **Probe cadence:** the idle probe runs every 60 s (it was 120 s), so the backend's 120 s session gate sees fresh reports. While
  `blocked_reason` is REALITY_CHECK, LOGGED_OUT or SESSION_UNKNOWN, the probe runs every `BLOCKED_PROBE_S=12` s. The probe is
  screenshot-only (a CDP `Page.captureScreenshot`); the dialog is never clicked, answered or dismissed.
- **Blocked:** health goes `healthy=false`, `ready=false`, `blocked_reason=REALITY_CHECK`, so `device_routing.routable` and the
  backend selector say not routable. One Telegram BLOCKED message is sent per episode.
- **Recovery:** when David clears the dialog, the next 12 s probe reads LOGGED_IN. Health returns to ready/IDLE by itself, with no
  restart and no worker action, and one Telegram RESUMED message is sent.
- **Before each result:** a screenshot-only session read runs before each instruction's result is published, so the backend judges
  that result against a session report taken after the run.
- **Tests:** `tests/test_desktop_reality_check.py`. It drives the real `_probe` -> `lifecycle.session_state` path on the captured
  fixtures, with a page that fails the test on anything other than a CDP screenshot.

### Live Reality Check, 28 Sep 2026 22:06 BST onwards (`evidence/desktop-worker-backend-placement/reality_check/`)
- **22:06:37:** a real Reality Check opened. Health went REALITY_CHECK / not routable at once, one Telegram BLOCKED message was sent,
  and the probe switched to 12 s (`probe_cadence.txt`: 22:10:37, :49, 22:11:01, :13). The dialog was never touched.
- **22:19-22:25 flapping:** the block flapped. Some probe frames were classified LOGGED_IN while the dialog was still open, because
  the OCR had the title and text but missed the "Remain Logged In" / "Log out" buttons. Each such frame resumed routing and sent a
  RESUMED message. Two supervised desktop targets (`on-81f1b0d1...`, `on-a75935e5...`, Genesis v Olancho) were dispatched in those
  windows. The worker met the dialog on the event page and stopped: SESSION_REQUIRED, **no click**, no bet.
- **Fixes, both live since 22:36:**
  - A dialog title plus any of its own phrases now reads REALITY_CHECK (56f2701). All 7 misread frames in `probe/hist` now read
    REALITY_CHECK.
  - A block clears only after 2 consecutive LOGGED_IN reads (b3ef231).
  - Frames around a block are kept in `.local/desktop-evidence/probe/hist`.
- **Still open:** no genuine clearance by David has been observed yet. The earlier "recoveries" were those misreads.
