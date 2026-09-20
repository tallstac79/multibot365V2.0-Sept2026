# MultiBot365 build status

## Current milestone: 3 — PASS on the physical Samsung

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

## Milestone 2 — PASS on the physical Samsung

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

Successful final cases completed in 4.773–5.071 seconds. Example pixel-derived field bounds: [57,395,664,521]. Each completed ID was re-submitted and its result remained unchanged. The selected keyboard stayed com.samsung.android.honeyboard/.service.HoneyBoardService.

Failure states include an after screenshot when the deadline permits. Timeout and process interruption may prevent an after-frame; those references are explicitly null with a persisted reason. They never imply successful observation.

Milestone 1 regression evidence: **evidence/text-visual-regression/results.json** — all eight cases passed their assertions, including capture error code 4, visual tap/state verification, ambiguity rejection, duplicate protection and process recovery.

Final tested APK SHA256: **5C08D1AC852A2A8C49EF32F390C80334B4CA57E809972D961A79C61E453E2EA4**.

### Scope and next work

No blocker remains for Milestone 2. The current bounded contract supports visible outlined fields with a unique single-word hint and 1–128 UTF-16 units of supplied text on API 33+. Borderless/ambiguous/unidentifiable or unprovably focused fields fail explicitly. Password fields are excluded. Multiline, clipped text and non-English visual recognition are not claimed by this acceptance proof.

Next: session handling, production coordinator intake, broader visual selectors and a neutral end-to-end instruction workflow. No production coordinator endpoint or keyboard replacement was introduced.

---

Updated: 2026-09-20 21:40 Europe/London.

## Milestone 1 — PASS on the physical Samsung

Accessibility screenshot -> OCR target bounds -> dispatchGesture tap -> second screenshot -> verified neutral page state change.

Device: Samsung SM-A136B, R5CT61TE14Z, Android 14 / API 34, 720x1600.
App: existing com.bet365agent / Bet365Agent. Chrome: com.android.chrome.

## Exact diagnosis

The inherited captureScreenshotAsset() returned null on every Android version and never called takeScreenshot(). The historical “Failed to capture initial screenshot” therefore had **no Android result/error code**. It was not evidence of a Samsung restriction.

Service XML also omitted android:canTakeScreenshot="true". Bound capabilities were 33 (content + gestures); after deployment Android rebound with capabilities=161 (33 + screenshot capability 128).

Other inherited gaps: missing bundled OCR model, estimated coordinates, main-thread sleep, dispatch acceptance treated as completion, and a verification fallback returning true without observing changed state. These were replaced in the neutral visual test path.

## Implemented and deployed

- Real API 30+ asynchronous takeScreenshot callback with software bitmap copy and hardware-buffer cleanup.
- Exact onSuccess timestamp or onFailure numeric code/symbolic name logged. Success has no Android error code; the persisted error key is removed on success.
- Errors 1 and 3 retry at most twice, 700ms apart. Other capture errors terminate the run.
- Tesseract OCR and PNG writing on a worker. Existing tess-two and AccessibilityService/dispatchGesture architecture retained.
- Official English legacy model bundled and atomically installed in private storage. Automatic page segmentation returns actual word bounds; sparse mode missed bordered labels.
- One exact NEPTUNE match required. Precondition: exact words “Neutral visual test” and READY. Postcondition: COMPLETE and READY absent. No guessed bounds or success heuristic.
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

Earlier BUILD_STATUS reported the legacy search query “Fulham” passed on 2026-09-20. This historical result is preserved as context, not revalidated here. Existing legacy search/fixture code remains.

No physical-action or credential blocker remains for this milestone. Tracked Gradle/build artifacts were already dirty at takeover and are excluded from the source milestone commit.
