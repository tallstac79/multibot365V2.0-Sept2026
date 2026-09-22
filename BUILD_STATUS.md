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
﻿# MultiBot365 build status

## Current milestone: 5 — PASS on the physical Samsung (multi-sport local simulator)

Verified 2026-09-22 on Samsung SM-A136B `R5CT61TE14Z`. App **0.5.6-sim (11)**. Evidence: `evidence/fixture-m5/` (**25/25**). See `BUILD_STATUS_M5.md` for the full case table and OCR notes. Baseline commit `9133319`.

Hard stop unchanged: fictional LocalSimulator only; no live Bet365 wager path.

---
## Current milestone: 4 â€” PASS on the physical Samsung (local simulator adapter)

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

**evidence/fixture/results.json: 19/19 cases passed their assertions.** The suite communicated Windows -> Samsung -> Windows solely over LAN HTTP with the PC ADB server stopped at both ends. Successful commands took 31.8â€“32.6 seconds. The 200ms timeout returned TIMEOUT in 229ms; no instruction remained pending.

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

## Milestone 3 â€” PASS on the physical Samsung

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

## Milestone 2 â€” PASS on the physical Samsung

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

Successful final cases completed in 4.773â€“5.071 seconds. Example pixel-derived field bounds: [57,395,664,521]. Each completed ID was re-submitted and its result remained unchanged. The selected keyboard stayed com.samsung.android.honeyboard/.service.HoneyBoardService.

Failure states include an after screenshot when the deadline permits. Timeout and process interruption may prevent an after-frame; those references are explicitly null with a persisted reason. They never imply successful observation.

Milestone 1 regression evidence: **evidence/text-visual-regression/results.json** â€” all eight cases passed their assertions, including capture error code 4, visual tap/state verification, ambiguity rejection, duplicate protection and process recovery.

Final tested APK SHA256: **5C08D1AC852A2A8C49EF32F390C80334B4CA57E809972D961A79C61E453E2EA4**.

### Scope and next work

No blocker remains for Milestone 2. The current bounded contract supports visible outlined fields with a unique single-word hint and 1â€“128 UTF-16 units of supplied text on API 33+. Borderless/ambiguous/unidentifiable or unprovably focused fields fail explicitly. Password fields are excluded. Multiline, clipped text and non-English visual recognition are not claimed by this acceptance proof.

Next: session handling, production coordinator intake, broader visual selectors and a neutral end-to-end instruction workflow. No production coordinator endpoint or keyboard replacement was introduced.

---

Updated: 2026-09-20 21:40 Europe/London.

## Milestone 1 â€” PASS on the physical Samsung

Accessibility screenshot -> OCR target bounds -> dispatchGesture tap -> second screenshot -> verified neutral page state change.

Device: Samsung SM-A136B, R5CT61TE14Z, Android 14 / API 34, 720x1600.
App: existing com.bet365agent / Bet365Agent. Chrome: com.android.chrome.

## Exact diagnosis

The inherited captureScreenshotAsset() returned null on every Android version and never called takeScreenshot(). The historical â€œFailed to capture initial screenshotâ€ therefore had **no Android result/error code**. It was not evidence of a Samsung restriction.

Service XML also omitted android:canTakeScreenshot="true". Bound capabilities were 33 (content + gestures); after deployment Android rebound with capabilities=161 (33 + screenshot capability 128).

Other inherited gaps: missing bundled OCR model, estimated coordinates, main-thread sleep, dispatch acceptance treated as completion, and a verification fallback returning true without observing changed state. These were replaced in the neutral visual test path.

## Implemented and deployed

- Real API 30+ asynchronous takeScreenshot callback with software bitmap copy and hardware-buffer cleanup.
- Exact onSuccess timestamp or onFailure numeric code/symbolic name logged. Success has no Android error code; the persisted error key is removed on success.
- Errors 1 and 3 retry at most twice, 700ms apart. Other capture errors terminate the run.
- Tesseract OCR and PNG writing on a worker. Existing tess-two and AccessibilityService/dispatchGesture architecture retained.
- Official English legacy model bundled and atomically installed in private storage. Automatic page segmentation returns actual word bounds; sparse mode missed bordered labels.
- One exact NEPTUNE match required. Precondition: exact words â€œNeutral visual testâ€ and READY. Postcondition: COMPLETE and READY absent. No guessed bounds or success heuristic.
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

Earlier BUILD_STATUS reported the legacy search query â€œFulhamâ€ passed on 2026-09-20. This historical result is preserved as context, not revalidated here. Existing legacy search/fixture code remains.

No physical-action or credential blocker remains for this milestone. Tracked Gradle/build artifacts were already dirty at takeover and are excluded from the source milestone commit.

