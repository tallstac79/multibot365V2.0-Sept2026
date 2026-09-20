package com.bet365agent;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.app.ActivityManager;
import android.graphics.Bitmap;
import android.graphics.Rect;
import android.os.Handler;
import android.os.Looper;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.accessibility.AccessibilityWindowInfo;
import android.util.Log;


import java.util.Queue;
import java.util.LinkedList;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * Read-only inspect + pending CLICK_FOOTBALL in Chrome.
 * Never clicks while Bet365Agent is foreground.
 * No login, betslip, stake, Place Bet, or fixed coordinates.
 */
public class Bet365AccessibilityService extends AccessibilityService {
    private static final int MAX_NODES = 500;
    private static final int MAX_DUMP_CHARS = 16000;
    private static final long PENDING_RETRY_WINDOW_MS = 10000;
    // Hard failsafe: always fires regardless of event traffic, guarantees no infinite PENDING.
    private static final long HARD_DEADLINE_MS = 11000;
    private static final long WATCHDOG_INTERVAL_MS = 800;
    private static final long TREE_SETTLE_MS = 350;
    private static final long POST_CLICK_WAIT_MS = 2500;
    private static final String TARGET_LABEL = "Football";
    private static final String EXCLUDE_CONTEXT_LABEL = "virtual";

    private static volatile Bet365AccessibilityService instance;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private volatile boolean footballClickInFlight = false;
    private volatile long pendingArmedAt = 0L;
    private volatile boolean settlePosted = false;
    private volatile boolean hardDeadlinePosted = false;
    private volatile int watchdogGeneration = 0;

    // Debug/diagnostic fields persisted on every failure per BUILD_STATUS requirements.
    private volatile long lastEventTs = 0L;
    private volatile String lastEventPkg = "";
    private volatile int lastWindowsInspected = 0;
    private volatile int lastCandidatesFound = 0;

    public static boolean isRunning() {
        return instance != null;
    }

    @Override
    public void onServiceConnected() {
        super.onServiceConnected();
        instance = this;
        if (visualRunner != null) visualRunner.close();
        visualRunner = new VisualControlRunner(this);
        scanAndStore("onServiceConnected");
        tryPendingFootballOnEvent("onServiceConnected");
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        if (event == null) return;
        
        // DEBUG: Log every event to confirm service is receiving them
        Log.d("Bet365A11y", ">>> onAccessibilityEvent fired: type=" + event.getEventType() + " pkg=" + event.getPackageName());
        
        // DEBUG/BYPASS: Force fixture discovery if marker file exists
        if (checkForceFixtureDiscoveryMode() && !ScanStore.getPendingAction(this).equals("FIXTURE_TAP")) {
            clearForceFixtureDiscoveryMode();
            ScanStore.setPendingAction(this, "FIXTURE_TAP");
            ScanStore.setFixtureStatus(this, "BYPASS_MODE_ARMED - forcing fixture discovery");
            notifyPendingFixtureTapArmed();
        }
        
        int type = event.getEventType();
        if (type != AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED
                && type != AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED
                && type != AccessibilityEvent.TYPE_WINDOWS_CHANGED
                && type != AccessibilityEvent.TYPE_VIEW_SCROLLED) {
            return;
        }
        scanAndStore("event:" + type);

        CharSequence pkgCs = event.getPackageName();
        String eventPkg = pkgCs == null ? "" : pkgCs.toString();
        boolean chromeEvent = ScanStore.isChromePackage(eventPkg)
                || type == AccessibilityEvent.TYPE_WINDOWS_CHANGED
                || type == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED
                || type == AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED;

        if (ScanStore.hasPendingClickFootball(this)) {
            if (chromeEvent) tryPendingFootballOnEvent("a11y:" + type + " pkg=" + eventPkg);
            return;
        }
        if (ScanStore.hasPendingSearchFlow(this)) {
            if (chromeEvent) tryPendingSearchOnEvent("a11y:" + type + " pkg=" + eventPkg);
            return;
        }
        if (ScanStore.getPendingAction(this).equals("FIXTURE_TAP")) {
            if (chromeEvent) tryPendingFixtureTap("a11y:" + type + " pkg=" + eventPkg);
        }
    }

    @Override
    public void onInterrupt() {
    }

    @Override
    public boolean onUnbind(android.content.Intent intent) {
        instance = null;
        if (visualRunner != null) visualRunner.close();
        visualRunner = null;
        return super.onUnbind(intent);
    }

    @Override
    public void onDestroy() {
        instance = null;
        if (visualRunner != null) visualRunner.close();
        super.onDestroy();
    }

    public static void requestScan() {
        Bet365AccessibilityService svc = instance;
        if (svc != null) svc.scanAndStore("manual");
    }

    /** Called from UI after queuing pending action and launching Chrome HO/. */
    public static void notifyPendingFootballClickArmed() {
        Bet365AccessibilityService svc = instance;
        if (svc == null) return;
        svc.pendingArmedAt = System.currentTimeMillis();
        svc.settlePosted = false;
        svc.footballClickInFlight = false;
        svc.hardDeadlinePosted = false;
        svc.lastEventTs = svc.pendingArmedAt;
        svc.lastEventPkg = "";
        svc.lastWindowsInspected = 0;
        svc.lastCandidatesFound = 0;
        final int generation = ++svc.watchdogGeneration;
        ScanStore.setFootballStatus(svc, "PENDING — waiting for Chrome + Bet365 tree (up to 10s)…");
        svc.tryPendingFootballOnEvent("armed");
        // Also schedule periodic retries in case events are sparse
        svc.mainHandler.postDelayed(() -> svc.tryPendingFootballOnEvent("timer:1s"), 1000);
        svc.mainHandler.postDelayed(() -> svc.tryPendingFootballOnEvent("timer:2s"), 2000);
        svc.mainHandler.postDelayed(() -> svc.tryPendingFootballOnEvent("timer:4s"), 4000);
        svc.mainHandler.postDelayed(() -> svc.tryPendingFootballOnEvent("timer:7s"), 7000);
        svc.mainHandler.postDelayed(() -> svc.tryPendingFootballOnEvent("timer:10s"), 10000);
        // Absolute failsafe watchdog: fires on a fixed schedule independent of any
        // Accessibility event traffic, so a queued action can NEVER remain PENDING
        // indefinitely (this was the "stuck >2 minutes" bug). It repeatedly checks
        // elapsed time itself, not relying on being invoked by an event/timer chain.
        svc.scheduleHardWatchdog(generation);
    }

    private void scheduleHardWatchdog(int generation) {
        mainHandler.postDelayed(() -> {
            if (generation != watchdogGeneration) return; // superseded by a newer run
            if (!ScanStore.hasPendingClickFootball(this) || hardDeadlinePosted) return;
            long armed = pendingArmedAt <= 0 ? System.currentTimeMillis() : pendingArmedAt;
            long elapsed = System.currentTimeMillis() - armed;
            if (elapsed >= HARD_DEADLINE_MS) {
                hardDeadlinePosted = true;
                footballClickInFlight = false;
                ChromeSnapshot snap = captureAllChrome();
                failWithChromeDump(false, false, false,
                        "FAIL: TIMEOUT (hard watchdog) after " + elapsed
                                + "ms | lastEventTs=" + lastEventTs
                                + " lastEventPkg=" + lastEventPkg
                                + " windowsInspected=" + lastWindowsInspected
                                + " candidatesFound=" + lastCandidatesFound
                                + " reason=no valid non-virtual clickable Football target reached in time",
                        snap);
                recycleRoots(snap.roots);
                ScanStore.clearPendingAction(this);
                return;
            }
            scheduleHardWatchdog(generation);
        }, WATCHDOG_INTERVAL_MS);
    }

    private void tryPendingFootballOnEvent(String reason) {
        if (!ScanStore.hasPendingClickFootball(this)) return;
        if (footballClickInFlight) return;
        if (hardDeadlinePosted) return;

        long armed = pendingArmedAt;
        if (armed <= 0) {
            pendingArmedAt = System.currentTimeMillis();
            armed = pendingArmedAt;
        }
        long elapsed = System.currentTimeMillis() - armed;
        if (elapsed > PENDING_RETRY_WINDOW_MS) {
            hardDeadlinePosted = true;
            ChromeSnapshot snap = captureAllChrome();
            failWithChromeDump(false, false, false,
                    "FAIL: TIMEOUT after " + elapsed + "ms waiting for Chrome/Bet365 tree (" + reason + ")"
                            + " | lastEventTs=" + lastEventTs + " lastEventPkg=" + lastEventPkg
                            + " windowsInspected=" + lastWindowsInspected + " candidatesFound=" + lastCandidatesFound,
                    snap);
            recycleRoots(snap.roots);
            ScanStore.clearPendingAction(this);
            return;
        }

        String activePkg = currentActivePackage();
        lastEventTs = System.currentTimeMillis();
        lastEventPkg = activePkg;
        if ("com.bet365agent".equals(activePkg)) {
            ScanStore.setFootballStatus(this,
                    "PENDING — Bet365Agent still foreground (" + elapsed + "ms)");
            return;
        }
        if (!ScanStore.isChromePackage(activePkg) && !anyChromeWindowPresent()) {
            ScanStore.setFootballStatus(this,
                    "PENDING — waiting for Chrome foreground (now: "
                            + (activePkg.isEmpty() ? "?" : activePkg) + ", " + elapsed + "ms)");
            return;
        }

        ChromeSnapshot snap = captureAllChrome();
        if (!snap.hasTree) {
            ScanStore.setFootballStatus(this,
                    "PENDING — Chrome present but accessibility tree empty (" + elapsed + "ms)");
            return;
        }
        if (!snap.looksLikeBet365) {
            ScanStore.setFootballStatus(this,
                    "PENDING — Chrome tree loaded, waiting for Bet365 content (" + elapsed + "ms)");
            // keep retrying within window
            return;
        }

        // Tree is ready — settle briefly then click (don't spam clicks)
        if (settlePosted) return;
        settlePosted = true;
        footballClickInFlight = true;
        ScanStore.setFootballStatus(this,
                "RUNNING — Chrome+Bet365 ready, searching Football… (" + elapsed + "ms, " + reason + ")");
        mainHandler.postDelayed(this::executeFootballClick, TREE_SETTLE_MS);
    }

    // ============================================================================
    // Milestone A/B: Bet365 Search interaction + text entry
    // Per authoritative build direction, generic Football/Basketball top-nav
    // clicking is abandoned. Search is more deterministic: locate the Search
    // control by class+description, click it, wait for an editable field to
    // appear, type the target query, and verify the text landed. No coordinate
    // fallback; same hard-watchdog pattern as CLICK_FOOTBALL guards against
    // infinite PENDING.
    // ============================================================================
    private volatile boolean searchFlowInFlight = false;
    private volatile long searchArmedAt = 0L;
    private volatile boolean searchHardDeadlinePosted = false;
    private volatile int searchWatchdogGeneration = 0;
    private static final long SEARCH_HARD_DEADLINE_MS = 11000;
    private static final String SEARCH_LABEL = "Search";

    /** Called from UI after queuing SEARCH_FLOW and launching Chrome HO/. */
    public static void notifyPendingSearchFlowArmed() {
        Bet365AccessibilityService svc = instance;
        if (svc == null) return;
        svc.searchArmedAt = System.currentTimeMillis();
        svc.searchFlowInFlight = false;
        svc.searchHardDeadlinePosted = false;
        final int generation = ++svc.searchWatchdogGeneration;
        ScanStore.setSearchStatus(svc, "opening_chrome", "PENDING — waiting for Chrome + Bet365 tree (up to 10s)…");
        svc.tryPendingSearchOnEvent("armed");
        svc.mainHandler.postDelayed(() -> svc.tryPendingSearchOnEvent("timer:1s"), 1000);
        svc.mainHandler.postDelayed(() -> svc.tryPendingSearchOnEvent("timer:2s"), 2000);
        svc.mainHandler.postDelayed(() -> svc.tryPendingSearchOnEvent("timer:4s"), 4000);
        svc.mainHandler.postDelayed(() -> svc.tryPendingSearchOnEvent("timer:7s"), 7000);
        svc.mainHandler.postDelayed(() -> svc.tryPendingSearchOnEvent("timer:10s"), 10000);
        svc.scheduleSearchHardWatchdog(generation);
    }

    private void scheduleSearchHardWatchdog(int generation) {
        mainHandler.postDelayed(() -> {
            if (generation != searchWatchdogGeneration) return;
            if (!ScanStore.hasPendingSearchFlow(this) || searchHardDeadlinePosted) return;
            long armed = searchArmedAt <= 0 ? System.currentTimeMillis() : searchArmedAt;
            long elapsed = System.currentTimeMillis() - armed;
            if (elapsed >= SEARCH_HARD_DEADLINE_MS) {
                searchHardDeadlinePosted = true;
                searchFlowInFlight = false;
                ChromeSnapshot snap = captureAllChrome();
                failSearch("open_search", "FAIL: TIMEOUT (hard watchdog) after " + elapsed
                        + "ms | lastEventTs=" + lastEventTs + " lastEventPkg=" + lastEventPkg
                        + " windowsInspected=" + lastWindowsInspected, snap);
                recycleRoots(snap.roots);
                ScanStore.clearPendingAction(this);
                return;
            }
            scheduleSearchHardWatchdog(generation);
        }, WATCHDOG_INTERVAL_MS);
    }

    private void tryPendingSearchOnEvent(String reason) {
        if (!ScanStore.hasPendingSearchFlow(this)) return;
        if (searchFlowInFlight) return;
        if (searchHardDeadlinePosted) return;

        long armed = searchArmedAt;
        if (armed <= 0) {
            searchArmedAt = System.currentTimeMillis();
            armed = searchArmedAt;
        }
        long elapsed = System.currentTimeMillis() - armed;
        if (elapsed > PENDING_RETRY_WINDOW_MS) {
            searchHardDeadlinePosted = true;
            ChromeSnapshot snap = captureAllChrome();
            failSearch("open_search", "FAIL: TIMEOUT after " + elapsed
                    + "ms waiting for Chrome/Bet365 tree (" + reason + ")", snap);
            recycleRoots(snap.roots);
            ScanStore.clearPendingAction(this);
            return;
        }

        String activePkg = currentActivePackage();
        lastEventTs = System.currentTimeMillis();
        lastEventPkg = activePkg;
        if ("com.bet365agent".equals(activePkg)) {
            ScanStore.setSearchStatus(this, "opening_chrome",
                    "PENDING — Bet365Agent still foreground (" + elapsed + "ms)");
            return;
        }
        if (!ScanStore.isChromePackage(activePkg) && !anyChromeWindowPresent()) {
            ScanStore.setSearchStatus(this, "opening_chrome",
                    "PENDING — waiting for Chrome foreground (" + elapsed + "ms)");
            return;
        }

        ChromeSnapshot snap = captureAllChrome();
        if (!snap.hasTree || !snap.looksLikeBet365) {
            ScanStore.setSearchStatus(this, "opening_chrome",
                    "PENDING — Chrome tree loading, waiting for Bet365 content (" + elapsed + "ms)");
            return;
        }

        if (searchFlowInFlight) return;
        searchFlowInFlight = true;
        ScanStore.setSearchStatus(this, "locate_search",
                "RUNNING — Chrome+Bet365 ready, locating Search control… (" + elapsed + "ms)");
        mainHandler.postDelayed(this::executeOpenSearch, TREE_SETTLE_MS);
    }

    /** Step A: locate the Search control (SearchView or EditText) and click it. */
    private void executeOpenSearch() {
        try {
            String activePkg = currentActivePackage();
            if ("com.bet365agent".equals(activePkg)) {
                searchFlowInFlight = false;
                ScanStore.setSearchStatus(this, "opening_chrome", "PENDING — lost Chrome foreground, retrying…");
                return;
            }
            ChromeSnapshot snap = captureAllChrome();
            if (!snap.hasTree || !snap.looksLikeBet365) {
                searchFlowInFlight = false;
                ScanStore.setSearchStatus(this, "opening_chrome", "PENDING — Bet365 tree not ready, retrying…");
                return;
            }
            ScanStore.saveChromeSnapshot(this, snap.packageName, snap.title, snap.dump,
                    snap.visibleText, snap.clickableSummary, System.currentTimeMillis());

            // Try to find SearchView or EditText in toolbar area
            AccessibilityNodeInfo searchNode = findSearchViewOrEditText(snap.roots);
            if (searchNode == null) {
                failSearch("locate_search", "FAIL: SEARCHVIEW_NOT_FOUND — no SearchView or toolbar EditText"
                        + " found in Chrome accessibility tree", snap);
                recycleRoots(snap.roots);
                searchFlowInFlight = false;
                return;
            }

            boolean clicked = searchNode.performAction(AccessibilityNodeInfo.ACTION_CLICK);
            String detail = "searchNode=" + describeNode(searchNode) + " ACTION_CLICK=" + clicked;
            searchNode.recycle();
            recycleRoots(snap.roots);

            if (!clicked) {
                ChromeSnapshot fresh = captureAllChrome();
                failSearch("locate_search", "FAIL: EDITTEXT_NOT_ACTIVATED — "
                        + "SearchView found but ACTION_CLICK failed: " + detail, fresh);
                recycleRoots(fresh.roots);
                searchFlowInFlight = false;
                return;
            }

            ScanStore.setSearchStatus(this, "verify_search_open",
                    "RUNNING — clicked Search, waiting for search UI to open…");
            mainHandler.postDelayed(this::verifySearchOpened, POST_CLICK_WAIT_MS);
        } catch (Exception e) {
            ChromeSnapshot snap = captureAllChrome();
            failSearch("locate_search", "FAIL: exception " + e, snap);
            recycleRoots(snap.roots);
            searchFlowInFlight = false;
        }
    }

    /** Step: verify search UI opened (an editable field is now present and visible). */
    private void verifySearchOpened() {
        ChromeSnapshot snap = captureAllChrome();
        ScanStore.saveChromeSnapshot(this, snap.packageName, snap.title, snap.dump,
                snap.visibleText, snap.clickableSummary, System.currentTimeMillis());

        AccessibilityNodeInfo editable = findEditableSearchField(snap.roots);
        if (editable == null) {
            failSearch("verify_search_open",
                    "FAIL: search UI did not open — no visible editable field found after click", snap);
            recycleRoots(snap.roots);
            searchFlowInFlight = false;
            return;
        }

        String query = ScanStore.getSearchQuery(this);
        if (query == null || query.trim().isEmpty()) {
            // Milestone A only: prove Search opens. Stop here successfully.
            ScanStore.saveSearchResult(this, true, "verify_search_open",
                    "PASS: search UI opened, editable field=" + describeNode(editable),
                    snap.visibleText, System.currentTimeMillis());
            editable.recycle();
            recycleRoots(snap.roots);
            searchFlowInFlight = false;
            return;
        }

        // Milestone B: enter the query text into the field.
        android.os.Bundle args = new android.os.Bundle();
        args.putCharSequence(
                AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, query);
        boolean focusOk = editable.performAction(AccessibilityNodeInfo.ACTION_FOCUS);
        boolean setOk = editable.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args);
        String detail = "editable=" + describeNode(editable)
                + " focusOk=" + focusOk + " setTextOk=" + setOk + " query=" + query;
        editable.recycle();
        recycleRoots(snap.roots);

        if (!setOk) {
            ChromeSnapshot fresh = captureAllChrome();
            failSearch("enter_text", "FAIL: " + detail, fresh);
            recycleRoots(fresh.roots);
            searchFlowInFlight = false;
            return;
        }

        ScanStore.setSearchStatus(this, "verify_text", "RUNNING — text entered, verifying…");
        final String detailOk = detail;
        mainHandler.postDelayed(() -> verifyTextEntered(detailOk, query), POST_CLICK_WAIT_MS);
    }

    /** Step B verification: confirm the typed query is now visible in the field / results. */
    private void verifyTextEntered(String detail, String query) {
        ChromeSnapshot snap = captureAllChrome();
        ScanStore.saveChromeSnapshot(this, snap.packageName, snap.title, snap.dump,
                snap.visibleText, snap.clickableSummary, System.currentTimeMillis());

        String blob = snap.visibleText == null ? "" : snap.visibleText;
        boolean found = query != null && !query.trim().isEmpty()
                && blob.toLowerCase(Locale.US).contains(query.trim().toLowerCase(Locale.US));

        if (!found) {
            failSearch("enter_text", "FAIL: entered query \"" + query
                    + "\" not found in visible text after entry | " + detail, snap);
        } else {
            ScanStore.saveSearchResult(this, true, "verify_text",
                    "PASS: query \"" + query + "\" confirmed visible | " + detail,
                    snap.visibleText, System.currentTimeMillis());
        }
        recycleRoots(snap.roots);
        searchFlowInFlight = false;
    }

    private void failSearch(String stage, String detail, ChromeSnapshot snap) {
        if (snap != null && snap.hasTree) {
            ScanStore.saveChromeSnapshot(this, snap.packageName, snap.title, snap.dump,
                    snap.visibleText, snap.clickableSummary, System.currentTimeMillis());
        }
        String excerpt = "";
        if (snap != null) {
            excerpt = snap.visibleText;
            if (excerpt == null || excerpt.trim().isEmpty()) excerpt = snap.dump;
            if (excerpt != null && excerpt.length() > 6000) excerpt = excerpt.substring(0, 6000) + "…";
            if (excerpt == null) excerpt = "(no chrome dump)";
        } else {
            excerpt = "(no chrome snapshot)";
        }
        ScanStore.saveSearchResult(this, false, stage, detail, excerpt, System.currentTimeMillis());
    }

    /** Find SearchView or EditText in toolbar area (class-based search, not text-based). */
    private AccessibilityNodeInfo findSearchViewOrEditText(List<AccessibilityNodeInfo> roots) {
        for (AccessibilityNodeInfo root : roots) {
            AccessibilityNodeInfo found = findSearchViewOrEditTextNode(root);
            if (found != null) return found;
        }
        return null;
    }

    private AccessibilityNodeInfo findSearchViewOrEditTextNode(AccessibilityNodeInfo node) {
        if (node == null) return null;
        
        // Get the class name of this node
        CharSequence classSeq = node.getClassName();
        String className = classSeq == null ? "" : classSeq.toString();
        
        // Check if this is a SearchView (the container) or EditText in toolbar area
        boolean isSearchView = "android.widget.SearchView".equals(className);
        boolean isEditText = "android.widget.EditText".equals(className);
        
        // If it's a SearchView that's visible, try to use it directly
        if (isSearchView && node.isVisibleToUser()) {
            // Found the SearchView - return a copy so caller can click it
            return AccessibilityNodeInfo.obtain(node);
        }
        
        // If it's an EditText that's visible, focused, and in toolbar area (y < 300), use it
        if (isEditText && node.isVisibleToUser()) {
            Rect bounds = new Rect();
            node.getBoundsInScreen(bounds);
            // Toolbar is typically in top 200-250 pixels; check if this EditText is there
            if (bounds.top < 300) {
                return AccessibilityNodeInfo.obtain(node);
            }
        }
        
        // Recursively search children
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo c = node.getChild(i);
            if (c != null) {
                AccessibilityNodeInfo found = findSearchViewOrEditTextNode(c);
                c.recycle();
                if (found != null) return found;
            }
        }
        return null;
    }

    /** Find the clickable Search control: Button/View with text or desc == "Search" (legacy fallback). */
    private AccessibilityNodeInfo findSearchControl(List<AccessibilityNodeInfo> roots) {
        for (AccessibilityNodeInfo root : roots) {
            AccessibilityNodeInfo found = findSearchControlNode(root);
            if (found != null) return found;
        }
        return null;
    }

    private AccessibilityNodeInfo findSearchControlNode(AccessibilityNodeInfo node) {
        if (node == null) return null;
        CharSequence t = node.getText();
        CharSequence d = node.getContentDescription();
        String ts = t == null ? "" : t.toString().trim();
        String ds = d == null ? "" : d.toString().trim();
        if (node.isVisibleToUser() && node.isClickable()
                && (SEARCH_LABEL.equalsIgnoreCase(ts) || SEARCH_LABEL.equalsIgnoreCase(ds))) {
            return AccessibilityNodeInfo.obtain(node);
        }
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo c = node.getChild(i);
            if (c != null) {
                AccessibilityNodeInfo found = findSearchControlNode(c);
                c.recycle();
                if (found != null) return found;
            }
        }
        return null;
    }

    /** Find the first visible editable node (the search input box once opened). */
    private AccessibilityNodeInfo findEditableSearchField(List<AccessibilityNodeInfo> roots) {
        for (AccessibilityNodeInfo root : roots) {
            AccessibilityNodeInfo found = findEditableNode(root);
            if (found != null) return found;
        }
        return null;
    }

    private AccessibilityNodeInfo findEditableNode(AccessibilityNodeInfo node) {
        if (node == null) return null;
        if (node.isVisibleToUser() && node.isEditable()) {
            return AccessibilityNodeInfo.obtain(node);
        }
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo c = node.getChild(i);
            if (c != null) {
                AccessibilityNodeInfo found = findEditableNode(c);
                c.recycle();
                if (found != null) return found;
            }
        }
        return null;
    }

    private void executeFootballClick() {
        long ts = System.currentTimeMillis();
        try {
            // Re-check we are not on our own app
            String activePkg = currentActivePackage();
            if ("com.bet365agent".equals(activePkg)) {
                footballClickInFlight = false;
                settlePosted = false;
                ScanStore.setFootballStatus(this, "PENDING — lost Chrome, Bet365Agent foreground again");
                return;
            }

            ChromeSnapshot snap = captureAllChrome();
            if (!snap.hasTree || !snap.looksLikeBet365) {
                footballClickInFlight = false;
                settlePosted = false;
                ScanStore.setFootballStatus(this, "PENDING — Bet365 tree not ready at click time, retrying…");
                return;
            }

            // Persist latest chrome snapshot for UI
            ScanStore.saveChromeSnapshot(this, snap.packageName, snap.title, snap.dump,
                    snap.visibleText, snap.clickableSummary, ts);

            List<FootballHit> candidates = new ArrayList<>();
            findFootballCandidatesAcrossChrome(snap.roots, candidates);
            lastCandidatesFound = candidates.size();

            if (candidates.isEmpty()) {
                failWithChromeDump(false, false, false,
                        "FAIL: TARGET_NOT_FOUND — no visible case-insensitive \"Football\" node"
                                + " in the real sports navigation area of any Chrome root"
                                + " (any Virtual Sports matches were explicitly excluded)",
                        snap);
                recycleRoots(snap.roots);
                for (FootballHit h : candidates) h.target.recycle();
                footballClickInFlight = false;
                return;
            }

            if (candidates.size() > 1) {
                StringBuilder paths = new StringBuilder();
                for (FootballHit h : candidates) {
                    paths.append("[").append(describeNode(h.target))
                            .append(" ancestry=").append(h.ancestryContext).append("] ");
                }
                failWithChromeDump(true, false, false,
                        "FAIL: AMBIGUOUS_TARGET — " + candidates.size()
                                + " non-virtual Football candidates found, refusing to click. Candidates: "
                                + paths,
                        snap);
                recycleRoots(snap.roots);
                for (FootballHit h : candidates) h.target.recycle();
                footballClickInFlight = false;
                return;
            }

            FootballHit hit = candidates.get(0);

            AccessibilityNodeInfo clickable = findClickableAncestor(hit.target);
            if (clickable == null) {
                String detail = "FAIL: Football found but no clickable ancestor; "
                        + describeNode(hit.target) + " ancestry=" + hit.ancestryContext;
                hit.target.recycle();
                failWithChromeDump(true, false, false, detail, snap);
                recycleRoots(snap.roots);
                footballClickInFlight = false;
                return;
            }

            Rect bounds = new Rect();
            clickable.getBoundsInScreen(bounds);
            final String detail = "target=" + describeNode(hit.target)
                    + " ancestry=" + hit.ancestryContext
                    + " clickable=" + describeNode(clickable)
                    + " bounds=" + bounds.toShortString()
                    + " rootPkg=" + hit.rootPackage;

            boolean clicked = clickable.performAction(AccessibilityNodeInfo.ACTION_CLICK);
            if (clickable != hit.target) clickable.recycle();
            hit.target.recycle();
            recycleRoots(snap.roots);

            if (!clicked) {
                failWithChromeDump(true, true, false,
                        detail + "; ACTION_CLICK=false",
                        snap);
                footballClickInFlight = false;
                return;
            }

            ScanStore.setFootballStatus(this, "RUNNING — clicked Football, waiting for tree update…");
            final String detailOk = detail + "; ACTION_CLICK=true";
            mainHandler.postDelayed(() -> {
                try {
                    validatePostFootballClick(detailOk);
                } finally {
                    footballClickInFlight = false;
                }
            }, POST_CLICK_WAIT_MS);
        } catch (Exception e) {
            ChromeSnapshot snap = captureAllChrome();
            failWithChromeDump(false, false, false, "FAIL: exception " + e, snap);
            recycleRoots(snap.roots);
            footballClickInFlight = false;
        }
    }

    private void validatePostFootballClick(String detail) {
        ChromeSnapshot snap = captureAllChrome();
        ScanStore.saveChromeSnapshot(this, snap.packageName, snap.title, snap.dump,
                snap.visibleText, snap.clickableSummary, System.currentTimeMillis());

        String blob = (snap.visibleText + "\n" + snap.dump).toLowerCase(Locale.US);
        boolean postOk = blob.contains("football")
                || blob.contains("soccer")
                || blob.contains("1x2")
                || blob.contains("premier")
                || blob.contains("champions league")
                || blob.contains("full time result")
                || blob.contains("match odds")
                || blob.contains("goal line")
                || blob.contains("asian handicap");

        String excerpt = snap.visibleText;
        if (excerpt == null || excerpt.trim().isEmpty()) excerpt = snap.dump;
        if (excerpt.length() > 4000) excerpt = excerpt.substring(0, 4000) + "…";

        if (!postOk) {
            // failure: save entire chrome tree/text
            ScanStore.saveFootballClickResult(this, false, true, true, false,
                    excerpt,
                    detail + " | POST_CLICK_VALIDATION FAIL | chromeDumpChars="
                            + (snap.dump == null ? 0 : snap.dump.length()),
                    System.currentTimeMillis());
        } else {
            ScanStore.saveFootballClickResult(this, true, true, true, true,
                    excerpt,
                    detail + " | POST_CLICK_VALIDATION PASS",
                    System.currentTimeMillis());
        }
        recycleRoots(snap.roots);
    }

    private void failWithChromeDump(
            boolean targetFound, boolean clickableFound, boolean postOk,
            String detail, ChromeSnapshot snap) {
        if (snap != null && snap.hasTree) {
            ScanStore.saveChromeSnapshot(this, snap.packageName, snap.title, snap.dump,
                    snap.visibleText, snap.clickableSummary, System.currentTimeMillis());
        }
        String excerpt = "";
        if (snap != null) {
            excerpt = snap.visibleText;
            if (excerpt == null || excerpt.trim().isEmpty()) excerpt = snap.dump;
            if (excerpt != null && excerpt.length() > 6000) {
                excerpt = excerpt.substring(0, 6000) + "…";
            }
            if (excerpt == null) excerpt = "(no chrome dump)";
        } else {
            excerpt = "(no chrome snapshot)";
        }
        ScanStore.saveFootballClickResult(this, false, targetFound, clickableFound, postOk,
                excerpt, detail, System.currentTimeMillis());
    }

    private String currentActivePackage() {
        AccessibilityNodeInfo active = getRootInActiveWindow();
        if (active == null) return "";
        CharSequence p = active.getPackageName();
        String ps = p == null ? "" : p.toString();
        active.recycle();
        return ps;
    }

    private boolean anyChromeWindowPresent() {
        StringBuilder debugLog = new StringBuilder();
        debugLog.append("=== anyChromeWindowPresent() DEBUG ===\n");
        debugLog.append("Timestamp: ").append(System.currentTimeMillis()).append("\n");
        
        // STEP 1: Try getWindows()
        List<AccessibilityWindowInfo> windows = getWindows();
        debugLog.append("getWindows() returned: ").append(windows == null ? "NULL" : "List(" + windows.size() + ")\n");
        
        if (windows == null || windows.isEmpty()) {
            // FALLBACK: Try getRootInActiveWindow()
            debugLog.append("\n--- ATTEMPTING FALLBACK: getRootInActiveWindow() ---\n");
            AccessibilityNodeInfo fallbackRoot = getRootInActiveWindow();
            if (fallbackRoot != null) {
                CharSequence pkg = fallbackRoot.getPackageName();
                String pkgStr = pkg == null ? "" : pkg.toString();
                debugLog.append("Fallback root package: ").append(pkgStr).append("\n");
                boolean isChrome = ScanStore.isChromePackage(pkgStr);
                debugLog.append("Is Chrome (fallback): ").append(isChrome).append("\n");
                fallbackRoot.recycle();
                
                // Write debug log
                writeDebugLog(debugLog.toString());
                return isChrome;
            } else {
                debugLog.append("Fallback root is NULL\n");
                writeDebugLog(debugLog.toString());
                return false;
            }
        }
        
        // STEP 2: Inspect each window
        int totalWindows = windows.size();
        int chromeCount = 0;
        debugLog.append("\nInspecting ").append(totalWindows).append(" window(s):\n");
        
        for (int i = 0; i < windows.size(); i++) {
            AccessibilityWindowInfo w = windows.get(i);
            if (w == null) {
                debugLog.append("  [").append(i).append("] NULL window\n");
                continue;
            }
            
            int windowType = w.getType();
            String typeStr = getWindowTypeString(windowType);
            debugLog.append("  [").append(i).append("] Type: ").append(typeStr).append(" (").append(windowType).append(")");
            
            AccessibilityNodeInfo root = w.getRoot();
            if (root == null) {
                debugLog.append(" | Root: NULL\n");
                continue;
            }
            
            CharSequence p = root.getPackageName();
            String ps = p == null ? "" : p.toString();
            CharSequence t = w.getTitle();
            String ts = t == null ? "" : t.toString();
            
            debugLog.append(" | Package: ").append(ps).append(" | Title: ").append(ts).append("\n");
            
            root.recycle();
            
            if (ScanStore.isChromePackage(ps)) {
                chromeCount++;
                debugLog.append("     ^^^ CHROME FOUND ^^^\n");
            }
        }
        
        boolean foundChrome = chromeCount > 0;
        
        // FALLBACK: If no Chrome found in window list, check getRootInActiveWindow()
        if (chromeCount == 0) {
            debugLog.append("\n--- NO CHROME IN WINDOW LIST, ATTEMPTING FALLBACK ---\n");
            AccessibilityNodeInfo fallbackRoot = getRootInActiveWindow();
            if (fallbackRoot != null) {
                CharSequence pkg = fallbackRoot.getPackageName();
                String pkgStr = pkg == null ? "" : pkg.toString();
                debugLog.append("Fallback root package: ").append(pkgStr).append("\n");
                if (ScanStore.isChromePackage(pkgStr)) {
                    foundChrome = true;
                    debugLog.append("CHROME FOUND VIA FALLBACK ROOT\n");
                } else {
                    debugLog.append("Fallback root is NOT Chrome\n");
                }
                fallbackRoot.recycle();
            } else {
                debugLog.append("Fallback root is NULL\n");
            }
        }
        
        // SECONDARY FALLBACK: If still no Chrome, check if Chrome process is running
        if (!foundChrome && isChromeRunning()) {
            foundChrome = true;
            debugLog.append("CHROME FOUND VIA PROCESS CHECK\n");
        }
        
        debugLog.append("\n--- SUMMARY ---\n");
        debugLog.append("Total windows: ").append(totalWindows).append("\n");
        debugLog.append("Chrome windows: ").append(chromeCount).append("\n");
        debugLog.append("Result: ").append(foundChrome ? "CHROME FOUND" : "NO CHROME").append("\n");
        
        // Write debug log
        writeDebugLog(debugLog.toString());
        
        return foundChrome;
    }
    
    private String getWindowTypeString(int type) {
        switch (type) {
            case AccessibilityWindowInfo.TYPE_APPLICATION: return "APPLICATION";
            case AccessibilityWindowInfo.TYPE_INPUT_METHOD: return "INPUT_METHOD";
            case AccessibilityWindowInfo.TYPE_SYSTEM: return "SYSTEM";
            case AccessibilityWindowInfo.TYPE_ACCESSIBILITY_OVERLAY: return "ACCESSIBILITY_OVERLAY";
            default: return "UNKNOWN(" + type + ")";
        }
    }
    
    /**
     * Check if Chrome process is running via ActivityManager.
     * This is a fallback method to detect Chrome even when getWindows() doesn't return it.
     */
    private boolean isChromeRunning() {
        try {
            ActivityManager am = (ActivityManager) getSystemService(android.content.Context.ACTIVITY_SERVICE);
            if (am == null) {
                Log.w("Bet365A11y", "ActivityManager is null");
                return false;
            }
            
            List<ActivityManager.RunningAppProcessInfo> processes = am.getRunningAppProcesses();
            if (processes == null) {
                Log.w("Bet365A11y", "No running app processes available");
                return false;
            }
            
            for (ActivityManager.RunningAppProcessInfo process : processes) {
                if (process != null && process.processName != null) {
                    if (ScanStore.isChromePackage(process.processName)) {
                        Log.d("Bet365A11y", "Chrome process found: " + process.processName);
                        return true;
                    }
                }
            }
            
            Log.d("Bet365A11y", "Chrome process not found in running processes");
            return false;
        } catch (SecurityException e) {
            // getRunningAppProcesses() requires GET_TASKS permission
            Log.w("Bet365A11y", "SecurityException in isChromeRunning(): " + e.getMessage());
            return false;
        } catch (Exception e) {
            Log.e("Bet365A11y", "Error checking Chrome process: " + e);
            return false;
        }
    }
    
    private void writeDebugLog(String content) {
        try {
            java.io.File debugFile = new java.io.File(getFilesDir(), "debug_windows.txt");
            java.io.FileWriter fw = new java.io.FileWriter(debugFile, false); // overwrite each time
            fw.write(content);
            fw.close();
            Log.d("Bet365A11y", "Debug log written to: " + debugFile.getAbsolutePath());
        } catch (Exception e) {
            Log.e("Bet365A11y", "Error writing debug log: " + e);
        }
    }

    private static final class ChromeSnapshot {
        boolean hasTree;
        boolean looksLikeBet365;
        String packageName = "com.android.chrome";
        String title = "";
        String dump = "";
        String visibleText = "";
        String clickableSummary = "";
        List<AccessibilityNodeInfo> roots = new ArrayList<>();
    }

    private static final class FootballHit {
        AccessibilityNodeInfo target;
        String rootPackage = "";
        String ancestryContext = "";
    }

    /** Collect all Chrome roots (active + every application window). Caller recycles roots. */
    private ChromeSnapshot captureAllChrome() {
        ChromeSnapshot snap = new ChromeSnapshot();
        List<String> allDump = new ArrayList<>();
        List<String> allVisible = new ArrayList<>();
        List<String> allClickable = new ArrayList<>();
        int windowsInspected = 0;

        // Prefer getWindows() so we do not rely only on rootInActiveWindow
        List<AccessibilityWindowInfo> windows = getWindows();
        if (windows != null) {
            for (AccessibilityWindowInfo w : windows) {
                if (w == null) continue;
                windowsInspected++;
                if (w.getType() != AccessibilityWindowInfo.TYPE_APPLICATION
                        && w.getType() != AccessibilityWindowInfo.TYPE_SYSTEM) {
                    // still allow application primarily
                }
                if (w.getType() != AccessibilityWindowInfo.TYPE_APPLICATION) continue;
                AccessibilityNodeInfo root = w.getRoot();
                if (root == null) continue;
                CharSequence p = root.getPackageName();
                String ps = p == null ? "" : p.toString();
                if (!ScanStore.isChromePackage(ps)) {
                    root.recycle();
                    continue;
                }
                snap.roots.add(root);
                CharSequence t = w.getTitle();
                if (t != null && t.length() > 0 && snap.title.isEmpty()) {
                    snap.title = t.toString();
                }
                snap.packageName = ps;
                WalkResult walk = walkTree(root, "chrome_window", ps, snap.title);
                allDump.add(walk.dump);
                if (walk.visibleText.length() > 0) allVisible.add(walk.visibleText);
                if (walk.clickable.length() > 0) allClickable.add(walk.clickable);
            }
        }

        // Also include active root if Chrome and not already captured
        AccessibilityNodeInfo active = getRootInActiveWindow();
        if (active != null) {
            CharSequence p = active.getPackageName();
            String ps = p == null ? "" : p.toString();
            if (ScanStore.isChromePackage(ps)) {
                boolean already = false;
                for (AccessibilityNodeInfo r : snap.roots) {
                    // identity not reliable; just always walk active as extra dump
                    already = true;
                    break;
                }
                WalkResult walk = walkTree(active, "chrome_active", ps, findTitleForPackage(ps));
                allDump.add("--- ACTIVE ROOT ---\n" + walk.dump);
                if (walk.visibleText.length() > 0) allVisible.add(walk.visibleText);
                if (walk.clickable.length() > 0) allClickable.add(walk.clickable);
                if (!already) {
                    snap.roots.add(active);
                } else {
                    // keep a copy for search if roots empty
                    if (snap.roots.isEmpty()) snap.roots.add(active);
                    else active.recycle();
                }
                snap.packageName = ps;
            } else {
                active.recycle();
            }
        }

        snap.hasTree = !snap.roots.isEmpty();
        StringBuilder dump = new StringBuilder();
        for (String d : allDump) {
            if (dump.length() + d.length() > MAX_DUMP_CHARS) {
                dump.append("… truncated …\n");
                break;
            }
            dump.append(d).append('\n');
        }
        StringBuilder visible = new StringBuilder();
        for (String v : allVisible) {
            if (visible.length() + v.length() > 8000) break;
            visible.append(v).append('\n');
        }
        StringBuilder clickable = new StringBuilder();
        for (String c : allClickable) {
            if (clickable.length() + c.length() > 8000) break;
            clickable.append(c).append('\n');
        }
        snap.dump = dump.toString();
        snap.visibleText = visible.toString();
        snap.clickableSummary = clickable.toString();

        String blob = (snap.visibleText + "\n" + snap.dump).toLowerCase(Locale.US);
        snap.looksLikeBet365 = blob.contains("bet365")
                || blob.contains("football")
                || blob.contains("in-play")
                || blob.contains("in play")
                || blob.contains("sports")
                || blob.contains("basketball")
                || blob.contains("tennis")
                || blob.contains("join now")
                || blob.contains("log in")
                || blob.contains("login")
                || (snap.visibleText.length() > 80 && blob.contains("odds"));

        lastWindowsInspected = windowsInspected;
        
        // DEBUG: Log captureAllChrome results
        StringBuilder captureDebug = new StringBuilder();
        captureDebug.append("=== captureAllChrome() SUMMARY ===\n");
        captureDebug.append("hasTree: ").append(snap.hasTree).append("\n");
        captureDebug.append("looksLikeBet365: ").append(snap.looksLikeBet365).append("\n");
        captureDebug.append("packageName: ").append(snap.packageName).append("\n");
        captureDebug.append("roots count: ").append(snap.roots.size()).append("\n");
        captureDebug.append("dump length: ").append(snap.dump.length()).append(" chars\n");
        captureDebug.append("visibleText length: ").append(snap.visibleText.length()).append(" chars\n");
        captureDebug.append("clickableSummary length: ").append(snap.clickableSummary.length()).append(" chars\n");
        captureDebug.append("title: ").append(snap.title).append("\n");
        Log.d("Bet365A11y", captureDebug.toString());
        
        return snap;
    }

    /**
     * Find all visible, case-insensitive "Football" candidates across the given
     * Chrome roots, EXCLUDING any node whose ancestor chain mentions "virtual"
     * (e.g. "Virtual Sports"). This fixes the misrouting bug where a global
     * text search matched the Virtual Sports entry instead of the real Football
     * sports-navigation entry. For each candidate we record a short ancestry
     * context string for disambiguation logging.
     */
    private void findFootballCandidatesAcrossChrome(List<AccessibilityNodeInfo> roots, List<FootballHit> out) {
        if (roots == null) return;
        for (AccessibilityNodeInfo root : roots) {
            if (root == null) continue;
            CharSequence p = root.getPackageName();
            String rootPkg = p == null ? "" : p.toString();
            collectFootballCandidates(root, rootPkg, out);
        }
    }

    private void collectFootballCandidates(AccessibilityNodeInfo node, String rootPkg, List<FootballHit> out) {
        if (node == null) return;
        CharSequence t = node.getText();
        CharSequence d = node.getContentDescription();
        String ts = t == null ? "" : t.toString().trim();
        String ds = d == null ? "" : d.toString().trim();
        if (TARGET_LABEL.equalsIgnoreCase(ts) || TARGET_LABEL.equalsIgnoreCase(ds)) {
            boolean visible = node.isVisibleToUser();
            String ancestry = buildAncestryContext(node);
            boolean excluded = ancestry.toLowerCase(Locale.US).contains(EXCLUDE_CONTEXT_LABEL);
            Log.d("Bet365Agent", "footballCandidate ts=" + ts + " visible=" + visible
                    + " excluded=" + excluded + " ancestry=" + ancestry);
            if (visible && !excluded) {
                FootballHit hit = new FootballHit();
                hit.target = AccessibilityNodeInfo.obtain(node);
                hit.rootPackage = rootPkg;
                hit.ancestryContext = ancestry;
                out.add(hit);
            }
        }
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo c = node.getChild(i);
            if (c != null) {
                collectFootballCandidates(c, rootPkg, out);
                c.recycle();
            }
        }
    }

    /** Walk up to 6 ancestors collecting text/desc/id/class for context-based disambiguation. */
    private String buildAncestryContext(AccessibilityNodeInfo node) {
        StringBuilder sb = new StringBuilder();
        AccessibilityNodeInfo cur = node.getParent();
        int hops = 0;
        while (cur != null && hops < 6) {
            CharSequence t = cur.getText();
            CharSequence d = cur.getContentDescription();
            CharSequence id = cur.getViewIdResourceName();
            String piece = (t != null && t.length() > 0 ? t.toString() : "")
                    + (d != null && d.length() > 0 ? "/" + d : "")
                    + (id != null && id.length() > 0 ? "#" + id : "");
            if (piece.length() > 0) {
                if (sb.length() > 0) sb.append(" < ");
                sb.append(piece);
            }
            AccessibilityNodeInfo parent = cur.getParent();
            cur.recycle();
            cur = parent;
            hops++;
        }
        if (cur != null) cur.recycle();
        return sb.length() == 0 ? "(no ancestry text)" : sb.toString();
    }

    private static void recycleRoots(List<AccessibilityNodeInfo> roots) {
        if (roots == null) return;
        for (AccessibilityNodeInfo r : roots) {
            if (r != null) {
                try { r.recycle(); } catch (Exception ignored) {}
            }
        }
        roots.clear();
    }

    private static String describeNode(AccessibilityNodeInfo n) {
        if (n == null) return "(null)";
        CharSequence t = n.getText();
        CharSequence d = n.getContentDescription();
        CharSequence c = n.getClassName();
        return "text=" + (t == null ? "" : t)
                + " desc=" + (d == null ? "" : d)
                + " class=" + (c == null ? "?" : c)
                + " clickable=" + n.isClickable()
                + " visible=" + n.isVisibleToUser();
    }

    private void scanAndStore(String reason) {
        try {
            long ts = System.currentTimeMillis();
            AccessibilityNodeInfo active = getRootInActiveWindow();
            String activePkg = "";
            if (active != null && active.getPackageName() != null) {
                activePkg = active.getPackageName().toString();
            }
            String activeTitle = findTitleForPackage(activePkg);
            WalkResult activeWalk = walkTree(active, reason, activePkg, activeTitle);
            if (active != null) active.recycle();
            ScanStore.saveScan(this, activePkg, activeTitle, activeWalk.dump, ts);

            ChromeSnapshot chrome = captureAllChrome();
            if (chrome.hasTree) {
                ScanStore.saveChromeSnapshot(this, chrome.packageName, chrome.title, chrome.dump,
                        chrome.visibleText, chrome.clickableSummary, ts);
            }
            recycleRoots(chrome.roots);
        } catch (Exception e) {
            ScanStore.saveScan(this, "error", "", "scan failed: " + e, System.currentTimeMillis());
        }
    }

    private String findTitleForPackage(String pkg) {
        List<AccessibilityWindowInfo> windows = getWindows();
        if (windows == null) return "";
        for (AccessibilityWindowInfo w : windows) {
            if (w == null) continue;
            if (w.getType() != AccessibilityWindowInfo.TYPE_APPLICATION) continue;
            AccessibilityNodeInfo root = w.getRoot();
            if (root == null) continue;
            CharSequence p = root.getPackageName();
            String ps = p == null ? "" : p.toString();
            root.recycle();
            if (pkg != null && pkg.equals(ps)) {
                CharSequence t = w.getTitle();
                return t == null ? "" : t.toString();
            }
        }
        return "";
    }

    // NOTE: the legacy findFootballNode/collectFootball global-search helpers were
    // removed. They caused the Virtual Sports misrouting bug (matched any visible
    // "Football" text anywhere in the tree, including inside the Virtual Sports
    // module). Target discovery now goes exclusively through
    // findFootballCandidatesAcrossChrome() / collectFootballCandidates(), which
    // scope-excludes any node whose ancestry mentions "virtual" and require exactly
    // one disambiguated candidate before any click occurs.

    private AccessibilityNodeInfo findClickableAncestor(AccessibilityNodeInfo target) {
        AccessibilityNodeInfo cur = AccessibilityNodeInfo.obtain(target);
        int climbs = 0;
        while (cur != null && climbs < 10) {
            if (cur.isClickable() && cur.isVisibleToUser()) {
                return cur;
            }
            AccessibilityNodeInfo parent = cur.getParent();
            cur.recycle();
            cur = parent;
            climbs++;
        }
        if (cur != null) cur.recycle();
        return null;
    }

    private static final class WalkResult {
        String dump = "";
        String visibleText = "";
        String clickable = "";
    }

    private WalkResult walkTree(AccessibilityNodeInfo root, String reason, String pkg, String title) {
        WalkResult result = new WalkResult();
        StringBuilder dump = new StringBuilder();
        dump.append("reason=").append(reason).append('\n');
        dump.append("package=").append(pkg).append('\n');
        dump.append("title=").append(title).append('\n');
        dump.append("--- nodes ---\n");
        List<String> nodeLines = new ArrayList<>();
        List<String> visibleTexts = new ArrayList<>();
        List<String> clickableLines = new ArrayList<>();
        if (root != null) {
            walk(root, 0, nodeLines, visibleTexts, clickableLines);
        } else {
            dump.append("(no root)\n");
        }
        for (String line : nodeLines) {
            if (dump.length() + line.length() + 1 > MAX_DUMP_CHARS) {
                dump.append("… truncated …\n");
                break;
            }
            dump.append(line).append('\n');
        }
        StringBuilder visible = new StringBuilder();
        for (String t : visibleTexts) {
            if (visible.length() + t.length() + 1 > 8000) break;
            visible.append(t).append('\n');
        }
        StringBuilder clickable = new StringBuilder();
        for (String c : clickableLines) {
            if (clickable.length() + c.length() + 1 > 8000) break;
            clickable.append(c).append('\n');
        }
        result.dump = dump.toString();
        result.visibleText = visible.toString();
        result.clickable = clickable.toString();
        return result;
    }

    private void walk(AccessibilityNodeInfo node, int depth,
                      List<String> out, List<String> visibleTexts, List<String> clickableLines) {
        if (node == null || out.size() >= MAX_NODES) return;
        CharSequence text = node.getText();
        CharSequence desc = node.getContentDescription();
        CharSequence cls = node.getClassName();
        CharSequence viewId = node.getViewIdResourceName();
        boolean clickable = node.isClickable();
        boolean editable = node.isEditable();
        boolean visible = node.isVisibleToUser();
        String textStr = text == null ? "" : text.toString().replace('\n', ' ').trim();
        String descStr = desc == null ? "" : desc.toString().replace('\n', ' ').trim();
        boolean interesting = textStr.length() > 0 || descStr.length() > 0 || clickable || depth <= 2;
        if (interesting && visible) {
            Rect bounds = new Rect();
            node.getBoundsInScreen(bounds);
            String line = String.format(Locale.US,
                    "d=%d click=%s edit=%s class=%s id=%s bounds=%s text=%s desc=%s",
                    depth, clickable ? "Y" : "N", editable ? "Y" : "N",
                    cls == null ? "?" : cls.toString(),
                    viewId == null ? "-" : viewId.toString(),
                    bounds.toShortString(),
                    truncate(textStr, 80), truncate(descStr, 60));
            out.add(line);
            if (textStr.length() > 0) visibleTexts.add(textStr);
            else if (descStr.length() > 0) visibleTexts.add("[" + descStr + "]");
            if (clickable) clickableLines.add(line);
        }
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child != null) {
                walk(child, depth + 1, out, visibleTexts, clickableLines);
                child.recycle();
            }
            if (out.size() >= MAX_NODES) break;
        }
    }

    private static String truncate(String s, int max) {
        if (s == null) return "";
        if (s.length() <= max) return s;
        return s.substring(0, max) + "…";
    }

    // Milestone C: Fixture selection via search result tap
    // Active polling fields (replaces event-dependent trigger)
    private volatile boolean fixturePollingActive = false;
    private volatile long fixtureArmedAt = 0L;
    private volatile long fixturePollingStartedAt = 0L;
    private Thread fixturePollingThread = null;
    private static final long FIXTURE_POLLING_TIMEOUT_MS = 30000;  // Hard timeout after 30 seconds
    private static final long FIXTURE_POLLING_INTERVAL_MS = 350;   // Poll every 350ms

    public static void notifyPendingFixtureTapArmed() {
        Bet365AccessibilityService svc = instance;
        if (svc == null) return;
        svc.fixtureArmedAt = System.currentTimeMillis();
        svc.fixturePollingActive = false;
        svc.fixturePollingStartedAt = 0L;
        ScanStore.setFixtureStatus(svc, "PENDING — Starting active polling for Chrome fixture discovery…");
        // Immediately start the polling thread (no dependency on accessibility events)
        svc.startFixturePollingThread();
    }

    /**
     * Spawn a background polling thread to actively search for Chrome content
     * and execute fixture discovery independent of accessibility events.
     * This replaces reliance on onAccessibilityEvent callbacks which may be
     * unreliable on some Samsung devices.
     */
    private void startFixturePollingThread() {
        if (fixturePollingThread != null) {
            Log.w("Bet365A11y", "Fixture polling thread already running, skipping start");
            return;
        }
        
        fixturePollingThread = new Thread(() -> {
            try {
                fixturePollingStartedAt = System.currentTimeMillis();
                long pollingStart = fixturePollingStartedAt;
                
                Log.d("Bet365A11y", "Fixture polling thread started");
                ScanStore.setFixtureStatus(Bet365AccessibilityService.this, 
                    "POLLING — Active discovery thread started");
                
                while (ScanStore.getPendingAction(Bet365AccessibilityService.this).equals("FIXTURE_TAP")) {
                    long elapsed = System.currentTimeMillis() - pollingStart;
                    
                    // Hard timeout after 30 seconds
                    if (elapsed > FIXTURE_POLLING_TIMEOUT_MS) {
                        Log.d("Bet365A11y", "Fixture polling timeout after " + elapsed + "ms");
                        ScanStore.setFixtureStatus(Bet365AccessibilityService.this, 
                            "TIMEOUT — No Chrome fixture found after 30 seconds of polling");
                        ScanStore.saveFixtureResult(Bet365AccessibilityService.this, false, 
                            "polling_timeout", 
                            "FAIL: Active polling timeout after 30s — no Chrome tree with fixtures found",
                            "", System.currentTimeMillis());
                        break;
                    }
                    
                    // Update status every second
                    if (elapsed % 1000 < FIXTURE_POLLING_INTERVAL_MS) {
                        ScanStore.setFixtureStatus(Bet365AccessibilityService.this,
                            "POLLING — Scanning for Chrome content (" + elapsed / 1000 + "s)…");
                    }
                    
                    // Poll for Chrome windows and attempt fixture discovery
                    try {
                        if (pollAndDiscoverFixture()) {
                            // Success! Fixture discovered and saved to prefs
                            Log.d("Bet365A11y", "Fixture discovery succeeded via polling");
                            break;
                        }
                    } catch (Exception e) {
                        Log.w("Bet365A11y", "Error during fixture polling: " + e);
                    }
                    
                    // Poll interval
                    Thread.sleep(FIXTURE_POLLING_INTERVAL_MS);
                }
            } catch (InterruptedException e) {
                Log.d("Bet365A11y", "Fixture polling thread interrupted");
            } catch (Exception e) {
                Log.e("Bet365A11y", "Unexpected error in fixture polling thread: " + e);
                ScanStore.setFixtureStatus(Bet365AccessibilityService.this,
                    "ERROR — Polling thread exception: " + e.getMessage());
            } finally {
                Log.d("Bet365A11y", "Fixture polling thread finished");
                fixturePollingThread = null;
            }
        }, "FixturePollingThread");
        
        fixturePollingThread.start();
    }
    
    /**
     * Single poll cycle: Check for Chrome window + accessibility tree,
     * attempt fixture discovery if tree is present.
     * 
     * Returns true if fixture was successfully discovered and saved, false otherwise.
     */
    private boolean pollAndDiscoverFixture() {
        String activePkg = currentActivePackage();
        
        // Check if Bet365Agent is still foreground (should not proceed)
        if ("com.bet365agent".equals(activePkg)) {
            return false;
        }
        
        // Try to capture Chrome content
        ChromeSnapshot snap = captureAllChrome();
        
        // If no Chrome tree, return false and continue polling
        if (!snap.hasTree || snap.roots.isEmpty()) {
            return false;
        }
        
        try {
            // Check if content looks like Bet365
            if (!snap.looksLikeBet365) {
                return false;
            }
            
            // ATTEMPT FIXTURE DISCOVERY
            ScanStore.setFixtureStatus(Bet365AccessibilityService.this,
                "DISCOVERING — Found Chrome tree, scanning for fixtures…");
            
            FixtureCandidate discovered = discoverCurrentFootballFixture(snap.roots);
            
            if (discovered == null) {
                return false;  // No fixture found yet, continue polling
            }
            
            // ✓ FIXTURE DISCOVERED!
            Log.d("Bet365A11y", "Fixture discovered via polling: " + discovered.fixtureName);
            
            // Save discovered fixture info to prefs
            ScanStore.saveDiscoveredFixture(Bet365AccessibilityService.this,
                discovered.fixtureName, discovered.homeTeam, discovered.awayTeam);
            
            // Update status
            ScanStore.setFixtureStatus(Bet365AccessibilityService.this,
                "DISCOVERED — " + discovered.fixtureName + " (via polling)");
            
            // Now execute the click on discovered fixture via main handler
            executeFixtureClickFromPolling(discovered, snap);
            
            return true;  // Stop polling
            
        } finally {
            recycleRoots(snap.roots);
        }
    }
    
    /**
     * Execute fixture click after polling has found and discovered a fixture.
     * Posts the click operation to the main handler thread.
     */
    private void executeFixtureClickFromPolling(FixtureCandidate discovered, ChromeSnapshot snap) {
        mainHandler.post(() -> {
            try {
                Log.d("Bet365A11y", "Executing fixture click from polling discovery");
                
                // Find clickable ancestor
                AccessibilityNodeInfo clickable = findClickableAncestor(discovered.targetNode);
                if (clickable == null) {
                    String detail = "FAIL: Fixture '" + discovered.fixtureName + "' found but no clickable ancestor";
                    discovered.targetNode.recycle();
                    failFixture("NO_CLICKABLE_ANCESTOR", detail, snap);
                    ScanStore.clearPendingAction(Bet365AccessibilityService.this);
                    return;
                }
                
                String detail = "fixture=" + discovered.fixtureName
                        + " target=" + describeNode(discovered.targetNode)
                        + " clickable=" + describeNode(clickable);
                boolean clicked = clickable.performAction(AccessibilityNodeInfo.ACTION_CLICK);
                
                if (clickable != discovered.targetNode) clickable.recycle();
                discovered.targetNode.recycle();
                
                if (!clicked) {
                    failFixture("CLICK_FAILED", detail + "; ACTION_CLICK returned false", snap);
                    ScanStore.clearPendingAction(Bet365AccessibilityService.this);
                    return;
                }
                
                ScanStore.setFixtureStatus(Bet365AccessibilityService.this,
                    "RUNNING — clicked " + discovered.fixtureName + ", waiting for fixture page…");
                
                // Schedule verification after click settles
                mainHandler.postDelayed(() -> {
                    try {
                        verifyFixturePage(detail + "; ACTION_CLICK=true",
                            discovered.homeTeam, discovered.awayTeam);
                    } finally {
                        ScanStore.clearPendingAction(Bet365AccessibilityService.this);
                    }
                }, POST_CLICK_WAIT_MS);
                
            } catch (Exception e) {
                Log.e("Bet365A11y", "Error executing fixture click from polling: " + e);
                discovered.targetNode.recycle();
                failFixture("CLICK_EXCEPTION", "FAIL: Exception during click: " + e, snap);
                ScanStore.clearPendingAction(Bet365AccessibilityService.this);
            }
        });
    }
    
    /**
     * Deprecated: tryPendingFixtureTap() - kept for compatibility but now replaced
     * by active polling mechanism. This method is only called from event handler.
     */
    private void tryPendingFixtureTap(String reason) {
        // Event-based method now mostly disabled; active polling takes over
        // Keep minimal event handling in case polling thread hasn't started
        if (!ScanStore.getPendingAction(this).equals("FIXTURE_TAP")) return;
        if (fixturePollingThread == null || !fixturePollingThread.isAlive()) {
            Log.d("Bet365A11y", "Polling thread not active, starting now");
            startFixturePollingThread();
        }
    }

    /**
     * DEPRECATED: This method has been replaced by active polling mechanism.
     * Kept as a stub for backward compatibility.
     * All fixture discovery now happens in the polling thread via pollAndDiscoverFixture().
     */
    @Deprecated
    private void executeFixtureTap() {
        Log.d("Bet365A11y", "executeFixtureTap() called but deprecated; polling should handle this");
        // Do nothing - active polling thread has taken over
    }
    
    /**
     * Data class representing a discovered football fixture candidate.
     */
    private static final class FixtureCandidate {
        String fixtureName;      // e.g., "Arsenal v Liverpool"
        String homeTeam;         // e.g., "Arsenal"
        String awayTeam;         // e.g., "Liverpool"
        AccessibilityNodeInfo targetNode;  // The node containing the fixture text
    }
    
    /**
     * Dynamically discover a current football fixture by scanning the accessibility tree.
     * Looks for patterns like "Team A v Team B" or "Team A vs Team B" in the sports navigation area.
     * Prefers fixtures that are not in Virtual Sports and have visible market data.
     * 
     * Returns null if no suitable fixture found.
     */
    private FixtureCandidate discoverCurrentFootballFixture(List<AccessibilityNodeInfo> roots) {
        if (roots == null || roots.isEmpty()) return null;
        
        // Pattern recognition: look for "Team v Team" or "Team vs Team" format
        // Common team name patterns: (usually 3-15 chars, starts with capital letter)
        String[] commonPatterns = {
            "v ", "vs ", " v ", " vs ", "-"  // separators between teams
        };
        
        // First, collect all potential fixture candidates from the tree
        List<FixtureCandidate> candidates = new ArrayList<>();
        for (AccessibilityNodeInfo root : roots) {
            collectFixtureCandidates(root, candidates);
        }
        
        // If we found candidates, return the most likely one
        // (typically the first visible fixture that's not in Virtual Sports)
        if (!candidates.isEmpty()) {
            return candidates.get(0);
        }
        
        return null;
    }
    
    /**
     * Recursively collect fixture candidates from the accessibility tree.
     * Looks for text nodes matching football fixture patterns.
     */
    private void collectFixtureCandidates(AccessibilityNodeInfo node, List<FixtureCandidate> candidates) {
        if (node == null || candidates.size() > 20) return;  // Limit to avoid expensive scanning
        
        if (node.isVisibleToUser()) {
            CharSequence text = node.getText();
            CharSequence desc = node.getContentDescription();
            String textStr = (text == null ? "" : text.toString()).toLowerCase(Locale.US);
            String descStr = (desc == null ? "" : desc.toString()).toLowerCase(Locale.US);
            String content = textStr + " " + descStr;
            
            // Exclude Virtual Sports and other non-live content
            if (!content.contains("virtual") && !content.contains("esports")) {
                // Look for fixture patterns: "Team v Team", "Team vs Team"
                FixtureCandidate candidate = tryParseFixture(textStr, node);
                if (candidate == null) {
                    candidate = tryParseFixture(descStr, node);
                }
                
                if (candidate != null) {
                    // Additional validation: verify we have reasonable team names
                    if (isValidTeamName(candidate.homeTeam) && isValidTeamName(candidate.awayTeam)) {
                        candidates.add(candidate);
                    }
                }
            }
        }
        
        // Recurse to children
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child != null) {
                collectFixtureCandidates(child, candidates);
                child.recycle();
            }
        }
    }
    
    /**
     * Attempt to parse a fixture name from text in "Team A v Team B" format.
     * Returns a FixtureCandidate if matched, null otherwise.
     */
    private FixtureCandidate tryParseFixture(String text, AccessibilityNodeInfo sourceNode) {
        if (text == null || text.length() < 5) return null;
        
        // Try various separators
        String[] separators = {"v ", "vs ", " v ", " vs ", "-"};
        for (String sep : separators) {
            int sepIdx = text.indexOf(sep);
            if (sepIdx > 0) {
                String home = text.substring(0, sepIdx).trim();
                String away = text.substring(sepIdx + sep.length()).trim();
                
                // Check if we got reasonable team names
                if (home.length() >= 3 && away.length() >= 3 && away.length() <= 50) {
                    // Extract just the team names (remove time/date if present)
                    home = extractTeamName(home);
                    away = extractTeamName(away);
                    
                    if (!home.isEmpty() && !away.isEmpty()) {
                        FixtureCandidate candidate = new FixtureCandidate();
                        candidate.homeTeam = home;
                        candidate.awayTeam = away;
                        candidate.fixtureName = home + " v " + away;
                        candidate.targetNode = AccessibilityNodeInfo.obtain(sourceNode);
                        return candidate;
                    }
                }
            }
        }
        return null;
    }
    
    /**
     * Extract team name from a string, removing time/score info.
     * E.g., "Arsenal 14:00" -> "Arsenal"
     */
    private String extractTeamName(String str) {
        if (str == null) return "";
        str = str.trim();
        
        // Remove common suffixes like time, scores, odds indicators
        String[] tokens = str.split("\\s+");
        if (tokens.length == 0) return "";
        
        // Take the first significant token(s) that form a team name
        StringBuilder name = new StringBuilder();
        for (String token : tokens) {
            // Stop if we hit a time pattern (HH:MM or numbers with colons)
            if (token.matches("\\d{1,2}:\\d{2}.*")) break;
            // Stop if we hit pure numbers (scores, odds)
            if (token.matches("\\d+") && token.length() < 4) break;
            
            if (name.length() > 0) name.append(" ");
            name.append(token);
            
            // Team names are typically 1-3 words
            if (name.toString().split("\\s+").length >= 3) break;
        }
        
        return name.toString();
    }
    
    /**
     * Validate that a string is a reasonable team name.
     */
    private boolean isValidTeamName(String name) {
        if (name == null || name.isEmpty()) return false;
        if (name.length() < 3 || name.length() > 40) return false;
        
        // Team names should start with a letter
        if (!Character.isLetter(name.charAt(0))) return false;
        
        // Should not be all numbers or special chars
        if (name.matches(".*\\d+.*") && name.matches("\\d+")) return false;
        
        return true;
    }

    private void verifyFixturePage(String detail, String expectedHomeTeam, String expectedAwayTeam) {
        try {
            ChromeSnapshot snap = captureAllChrome();
            ScanStore.saveChromeSnapshot(this, snap.packageName, snap.title, snap.dump,
                    snap.visibleText, snap.clickableSummary, System.currentTimeMillis());
            
            String blob = (snap.visibleText + "\n" + snap.dump).toLowerCase(Locale.US);
            String homeTeamLc = (expectedHomeTeam == null ? "" : expectedHomeTeam).toLowerCase(Locale.US);
            String awayTeamLc = (expectedAwayTeam == null ? "" : expectedAwayTeam).toLowerCase(Locale.US);
            
            // Fixture page should have:
            // 1. Both team names visible
            // 2. Market data visible (odds, lines, market names)
            boolean hasHomeTeam = !homeTeamLc.isEmpty() && blob.contains(homeTeamLc);
            boolean hasAwayTeam = !awayTeamLc.isEmpty() && blob.contains(awayTeamLc);
            
            // Look for market indicators: odds, separators between teams, standard Bet365 markers
            boolean hasMarketData = blob.contains("vs") || blob.contains("v ")
                    || (blob.contains("1") && blob.contains("x") && blob.contains("2"))
                    || blob.contains("odds") || blob.contains("match") || blob.contains("market");
            
            String excerpt = snap.visibleText;
            if (excerpt == null || excerpt.trim().isEmpty()) excerpt = snap.dump;
            if (excerpt.length() > 4000) excerpt = excerpt.substring(0, 4000) + "…";
            
            boolean fixtureValid = hasHomeTeam && hasAwayTeam && hasMarketData;
            
            if (!fixtureValid) {
                // failure
                String failDetail = detail + " | POST_CLICK_VALIDATION FAIL - ";
                if (!hasHomeTeam) failDetail += "home team '" + expectedHomeTeam + "' not found; ";
                if (!hasAwayTeam) failDetail += "away team '" + expectedAwayTeam + "' not found; ";
                if (!hasMarketData) failDetail += "no market data found";
                
                ScanStore.saveFixtureResult(this, false, "verify_page", failDetail, excerpt, System.currentTimeMillis());
            } else {
                // success
                String passDetail = detail + " | POST_CLICK_VALIDATION PASS - fixture page loaded with "
                        + expectedHomeTeam + " v " + expectedAwayTeam + " and market data visible";
                ScanStore.saveFixtureResult(this, true, "verify_page", passDetail, excerpt, System.currentTimeMillis());
            }
            recycleRoots(snap.roots);
        } catch (Exception e) {
            ChromeSnapshot snap = captureAllChrome();
            failFixture("VERIFY_EXCEPTION", "FAIL verify: " + e, snap);
            recycleRoots(snap.roots);
        }
    }
    
    /**
     * DEBUG/BYPASS mode: Check if a marker file exists that forces fixture discovery.
     * If /data/data/com.bet365agent/.fixture_test_now exists, immediately force fixture discovery
     * on the next accessibility event, bypassing normal button-press mechanism.
     */
    private boolean checkForceFixtureDiscoveryMode() {
        try {
            java.io.File markerFile = new java.io.File(getFilesDir(), ".fixture_test_now");
            return markerFile.exists();
        } catch (Exception e) {
            Log.d("Bet365A11y", "Error checking bypass marker: " + e);
            return false;
        }
    }
    
    /**
     * Remove the bypass marker file after processing.
     */
    private void clearForceFixtureDiscoveryMode() {
        try {
            java.io.File markerFile = new java.io.File(getFilesDir(), ".fixture_test_now");
            if (markerFile.exists()) {
                markerFile.delete();
            }
        } catch (Exception e) {
            Log.d("Bet365A11y", "Error clearing bypass marker: " + e);
        }
    }

    private void failFixture(String stage, String detail, ChromeSnapshot snap) {
        if (snap != null && snap.hasTree) {
            ScanStore.saveChromeSnapshot(this, snap.packageName, snap.title, snap.dump,
                    snap.visibleText, snap.clickableSummary, System.currentTimeMillis());
        }
        String excerpt = "";
        if (snap != null) {
            excerpt = snap.visibleText;
            if (excerpt == null || excerpt.trim().isEmpty()) excerpt = snap.dump;
            if (excerpt != null && excerpt.length() > 4000) {
                excerpt = excerpt.substring(0, 4000) + "…";
            }
            if (excerpt == null) excerpt = "(no chrome dump)";
        } else {
            excerpt = "(no chrome snapshot)";
        }
        ScanStore.saveFixtureResult(this, false, stage, detail, excerpt, System.currentTimeMillis());
    }

    // Neutral visual proof uses the same AccessibilityService and dispatchGesture transport.
    private VisualControlRunner visualRunner;

    public static void triggerVisualControlTest() {
        triggerVisualControlTest("manual-" + System.currentTimeMillis(), false);
    }

    public static void triggerVisualControlTest(String id, boolean captureOnly) {
        triggerVisualControlTest(id, captureOnly, android.view.Display.DEFAULT_DISPLAY);
    }

    static void triggerVisualControlTest(String id, boolean captureOnly, int displayId) {
        Bet365AccessibilityService svc = instance;
        if (svc != null) svc.mainHandler.post(() -> {
            if (svc.visualRunner != null) svc.visualRunner.start(id, captureOnly, displayId);
        });
    }
}
