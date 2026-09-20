# Android Accessibility PoC — Bet365Agent

Date: 2026-09-20  
Device: Samsung (ADB serial R5CT61TE14Z)  
Project: `MultiBotV2.0/MultiBot365/android/Bet365Agent`  
APK: `android/Bet365Agent/Bet365Agent-debug.apk` (also `app/build/outputs/apk/debug/app-debug.apk`)

## Goal

Prove a minimal AccessibilityService can inspect Chrome → Bet365 UI **without** permanent ADB/CDP control.  
Read-only: no clicks, typing, login automation, or betting.

## Build result

| Step | Result |
|------|--------|
| OpenJDK 17 install (winget) | PASS |
| Android SDK cmdline-tools + platform 34 + build-tools 34.0.0 | PASS |
| Gradle 8.7 `assembleDebug` | PASS |
| `adb install -r` on R5CT61TE14Z | PASS |
| App launches (`com.bet365agent/.MainActivity`) | PASS |

Toolchain notes (mini PC):
- `JAVA_HOME`: `C:\Program Files\Microsoft\jdk-17.0.20.101-hotspot`
- SDK: `%LOCALAPPDATA%\Android\Sdk`

## Manual step required (Samsung)

ADB can write `enabled_accessibility_services`, but the in-app check still showed **NO** until the user confirms in Settings. Do this on the phone:

1. Open **Bet365Agent** (or tap **Open Accessibility settings** in the app).
2. Go to **Settings → Accessibility → Installed apps** (Samsung wording may be **Installed services** / **Downloaded apps**).
3. Tap **Bet365Agent Inspector**.
4. Turn the service **ON**.
5. Accept the system warning (service can read screen content).
6. Return to **Bet365Agent** — status should show **Accessibility service enabled: YES**.
7. Open **Chrome** with **bet365.com** in the foreground.
8. Return to **Bet365Agent** and tap **Refresh status / last scan**.
9. Confirm the on-screen dump shows Chrome package / Bet365 texts.

Optional USB-off check (after the above works): disable USB debugging, keep using the in-app YES/package/timestamp/dump UI as proof the service still runs.

## What the service captures

Per node (when visible / interesting):
- depth, clickable, editable
- class name, view id
- bounds
- text, content-description

Also: active package, window title (when exposed).

## Findings so far (pre–manual enable confirmation)

Observed while Chrome had Bet365 open (partial captures via accessibility events / window title):

| Signal | Seen? | Notes |
|--------|-------|-------|
| Chrome package `com.android.chrome` | YES | Appeared in scan reason / package fields |
| Window title containing “Bet with bet365…” | YES | Exposed on application window title |
| In-app “Accessibility enabled: YES” after adb-only toggle | NO | Samsung requires manual enable in Accessibility settings |
| Full Bet365 node dump (Log In, Football, odds, etc.) | PENDING | Needs confirmed service enable + Refresh while Chrome is open |

### Keyword checklist (fill after you enable + Refresh)

- [ ] Log In / Join  
- [ ] Members / balance / £  
- [ ] Search  
- [ ] Football / Basketball  
- [ ] Market / team names  
- [ ] Odds  

After a good scan, dump also lands at:

`/storage/emulated/0/Android/data/com.bet365agent/files/last_chrome_dump.txt`

Pull (while USB still on):  
`adb shell cat /sdcard/Android/data/com.bet365agent/files/last_chrome_dump.txt`

## Architecture note

This PoC is step 1 of: Mini PC → BetInstruction → Android APK → Accessibility Service → Chrome → Bet365.  
No MultiBot365 betting code was modified. No stake / Place Bet automation.

## Stop

Waiting on David to enable **Bet365Agent Inspector** in Accessibility settings, open Chrome/Bet365, Refresh in-app, then confirm the dump looks useful (or say when to pull `last_chrome_dump.txt`).

## Basketball click test (pending-Chrome flow) — 2026-09-20

Tap **Test: Click Basketball in Chrome** while Accessibility is ON:

1. Sets pending action `CLICK_BASKETBALL` (does **not** click while Bet365Agent is foreground).
2. Launches/switches to Bet365 in Chrome (`com.android.chrome`).
3. AccessibilityService waits until active package is `com.android.chrome` and the tree is available.
4. Finds a visible node matching text/desc **Basketball**, walks parents until clickable, `ACTION_CLICK` only (no coordinates).
5. Waits for tree update; validates basketball-specific content.
6. Return to Bet365Agent to read:
   - `CLICK_BASKETBALL: PASS/FAIL`
   - `TARGET_FOUND: YES/NO`
   - `CLICKABLE_NODE_FOUND: YES/NO`
   - `POST_CLICK_VALIDATION: PASS/FAIL`

No login automation, no bet selection, no betslip, no Place Bet.
