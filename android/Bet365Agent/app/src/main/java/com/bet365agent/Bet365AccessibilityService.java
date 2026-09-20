package com.bet365agent;

import android.accessibilityservice.AccessibilityService;
import android.graphics.Rect;
import android.os.Handler;
import android.os.Looper;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.accessibility.AccessibilityWindowInfo;
import android.util.Log;

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
        scanAndStore("onServiceConnected");
        tryPendingFootballOnEvent("onServiceConnected");
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        if (event == null) return;
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
        }
    }

    @Override
    public void onInterrupt() {
    }

    @Override
    public void onDestroy() {
        instance = null;
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

    /** Step A: locate the Search control (Button/desc="Search") and click it. */
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

            AccessibilityNodeInfo searchNode = findSearchControl(snap.roots);
            if (searchNode == null) {
                failSearch("locate_search", "FAIL: TARGET_NOT_FOUND — no clickable node with"
                        + " text/desc=\"Search\" found in Chrome tree", snap);
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
                failSearch("locate_search", "FAIL: " + detail, fresh);
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

    /** Find the clickable Search control: Button/View with text or desc == "Search". */
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
        List<AccessibilityWindowInfo> windows = getWindows();
        if (windows == null) return false;
        for (AccessibilityWindowInfo w : windows) {
            if (w == null) continue;
            AccessibilityNodeInfo root = w.getRoot();
            if (root == null) continue;
            CharSequence p = root.getPackageName();
            String ps = p == null ? "" : p.toString();
            root.recycle();
            if (ScanStore.isChromePackage(ps)) return true;
        }
        return false;
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
}
