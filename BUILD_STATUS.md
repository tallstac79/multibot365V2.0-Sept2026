# MultiBot365 V2 Build Status

## Current Milestone
**C: Exact Fixture Selection** (next to test)

## Completed
 - Android phone accessibility service: enabled and reading Bet365 Chrome content ✓
 - **Milestone A: Search query entry + verification** ✓ PASS (2026-09-20 ~18:45)
   - Root cause identified: Text-based search targeting vs. native SearchView control
   - Codex fixed: `findSearchViewOrEditTextNode()` now targets `android.widget.SearchView` class
   - Test: Entered "Fulham", confirmed visible in EditText
   - Status: PASS (search_pass=true; search_detail="PASS: query 'Fulham' confirmed visible")
- Hard watchdog timeout for pending actions: implemented ✓

## Completed (cont'd)
- Milestone A Search interaction: query "Fulham" entered and confirmed visible in editable field ✓

## In Progress
- **Milestone C: Exact Fixture Selection** — SWITCHING FROM EVENT-DRIVEN TO ACTIVE POLLING
  - **Previous approach:** Event-driven (onAccessibilityEvent callbacks) — unreliable on this Samsung
  - **New approach:** Active polling loop (getWindows() every 250-500ms) while pending_action="FIXTURE_TAP"
  - **Rationale:** Earlier tests confirmed `captureAllChrome()` CAN access Chrome content when called directly
  - **Implementation:** Background polling thread that:
    1. Continuously checks getWindows() for Chrome tree
    2. On Chrome found, calls `discoverCurrentFootballFixture()` directly
    3. Writes results to prefs (fixture_name, fixture_home, fixture_away)
    4. Hard timeout after 30 seconds
  - **Status:** Codex implementing polling loop architecture
  - **Next:** Deploy polling APK, test on Samsung R5CT61TE14Z, verify fixture discovery
  - **Device compatibility:** Will be confirmed only after polling test passes or fails with real Chrome tree inspection

## Next Milestone
**B: Text Entry Verification** → **C: Exact Fixture Selection** → **D: Market/Line Selection** → **E: Betslip Validation**

## Files Modified
- `Bet365AccessibilityService.java`: added SEARCH_FLOW state machine + hard watchdog
- `ScanStore.java`: added search result storage keys
- `MainActivity.java`: added search result display + test button
- `activity_main.xml`: added search result TextViews + test button

## Test State
- Device: Samsung connected via ADB
- Service: enabled (re-confirmed via Settings toggle)
- Last test: search + text entry, verification in flight

## Blockers
None
