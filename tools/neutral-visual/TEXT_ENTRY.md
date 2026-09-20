# Milestone 2: visual text entry

The Android agent locates the instruction's `field_hint` by screenshot OCR, measures the enclosing field border from pixels, and focuses it with `dispatchGesture`. The text path does not call `AccessibilityNodeInfo`, inspect node trees, use clipboard contents, or invoke ADB typing. Legacy accessibility tree scanning is skipped while a text run is active.

## Input mechanism

On API 33+, `flagInputMethodEditor` enables the AccessibilityService's framework `InputMethod`. Its `AccessibilityInputConnection.commitText` accepts a Java string directly. This avoids changing the user's selected IME, clipboard replacement, simulated key layouts, and shell text escaping. The physical Samsung runs API 34; acceptance checks that its selected HoneyBoard IME is unchanged.

The agent requires a new editor-session generation after the visual focus tap and the configured editor package. It reads the complete existing editor value, selects that range, and commits the supplied text once. If editor identity changes or a complete readback is unavailable, it stops. It does not replay an uncertain commit. Password editor types are excluded from this plaintext evidence workflow.

References: [Android accessibility InputMethod](https://developer.android.com/reference/android/accessibilityservice/InputMethod), [AccessibilityInputConnection](https://developer.android.com/reference/android/accessibilityservice/InputMethod.AccessibilityInputConnection).

## Instruction

```json
{
  "run_id": "unique-command-id",
  "field_hint": "SEARCH",
  "text": "Your supplied value 42",
  "package": "com.android.chrome",
  "timeout_ms": 30000
}
```

The current bounded contract accepts a single-word alphanumeric field hint, 1–128 UTF-16 code units of text, and a 100–60000ms deadline. It targets a unique visible outlined field containing that hint. Borderless, ambiguous, already-filled/unidentifiable, or unprovably focused fields fail rather than receive a guessed tap or input. The transport supports string values directly, but a PASS also requires the text to be visible and recognizable with the bundled English OCR model. Multiline, clipped, masked, and other scripts are not acceptance claims.

For the debug shell receiver, encode the JSON as UTF-8 Base64 and pass it as `--es text_instruction <base64>` to `com.bet365agent/.VisualTestReceiver`. The existing debug-only DUMP permission restriction remains. This is not yet a network coordinator interface.

## Verification and evidence

A successful commit call is insufficient. The agent captures a new screen and requires:

1. Exact, case-sensitive `String.equals` equality between the requested text and the complete current input-connection readback, including every space.
2. Matching case-sensitive OCR words from a crop inside the pixel-detected field border. OCR word spacing is collapsed only for this visual comparison; exact whitespace is independently checked by the input connection.

Evidence is written atomically to `files/text/<run_id>/result.json` and mirrored in `shared_prefs/text_agent.xml`. It includes the requested value, target/focused bounds, screenshot references, observed text, visual text, verification flags, input-attempt count, wall-clock times, duration, and phase timings. PNGs/full-screen OCR are saved by the proven runner under `files/visual/<run_id>/`. `field_after.png` is the OCR verification crop.

States: `PASS`, `FIELD_NOT_FOUND`, `FOCUS_FAILED`, `INPUT_FAILED`, `TEXT_NOT_VERIFIED`, `TIMEOUT`, and `INTERRUPTED`. Missing fields receive one visual rediscovery retry; verification receives one further capture/read retry. Text is committed at most once per accepted run ID. Deadlines stop late callbacks from causing actions. Process restart marks pending text work INTERRUPTED and preserves the consumed ID. A new request can run normally.

Failures receive an after-state screenshot when the deadline permits. Timeout/process termination may prevent an after-frame; its reference is explicitly null with a reason, never represented as a successful observation.

## Physical acceptance

Build and install using the commands in [README.md](README.md), then run from the project root:

```powershell
python tools/test_android_text.py --adb $adb --serial R5CT61TE14Z --output evidence/text-final
```

Payloads come from `tools/text_acceptance_cases.json`; `--cases` accepts another JSON file and `--case` selects one named case. The host serves `text.html`, opens Chrome, submits instructions, and collects results. It never focuses or types into the test field itself.

The suite checks ordinary text, spaces, mixed case, numbers, repeated spaces, missing/disabled fields, a disappearing input connection, page-rejected text, hard timeout, fresh work after failures, duplicates, and app-process restart after text has been sent. It preserves the keyboard selection and closes its temporary HTTP server/ADB forwarding. Run the existing `tools/test_android_visual.py` separately for Milestone 1 regression acceptance.
