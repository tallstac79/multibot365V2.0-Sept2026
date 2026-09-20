package com.bet365agent;

import android.content.Context;
import android.content.SharedPreferences;

/** Persistent store for last scan, Chrome retain, and pending click tests. */
public final class ScanStore {
    private static final String PREFS = "bet365agent_poc";

    private static final String KEY_PACKAGE = "foreground_package";
    private static final String KEY_TITLE = "window_title";
    private static final String KEY_TS = "last_scan_ts";
    private static final String KEY_DUMP = "last_dump";

    private static final String KEY_CHROME_PACKAGE = "chrome_package";
    private static final String KEY_CHROME_TITLE = "chrome_title";
    private static final String KEY_CHROME_TS = "chrome_scan_ts";
    private static final String KEY_CHROME_DUMP = "chrome_dump";
    private static final String KEY_CHROME_VISIBLE = "chrome_visible_text";
    private static final String KEY_CHROME_CLICKABLE = "chrome_clickable";

    private static final String KEY_PENDING = "pending_action";
    private static final String PENDING_CLICK_FOOTBALL = "CLICK_FOOTBALL";

    private static final String KEY_CLICK_FB_PASS = "click_fb_pass";
    private static final String KEY_CLICK_FB_TARGET = "click_fb_target";
    private static final String KEY_CLICK_FB_CLICKABLE = "click_fb_clickable";
    private static final String KEY_CLICK_FB_POST = "click_fb_post";
    private static final String KEY_CLICK_FB_EXCERPT = "click_fb_excerpt";
    private static final String KEY_CLICK_FB_DETAIL = "click_fb_detail";
    private static final String KEY_CLICK_FB_TS = "click_fb_ts";
    private static final String KEY_CLICK_FB_STATUS = "click_fb_status";

    private static final String PENDING_SEARCH_FLOW = "SEARCH_FLOW";
    private static final String KEY_SEARCH_PASS = "search_pass";
    private static final String KEY_SEARCH_STAGE = "search_stage";
    private static final String KEY_SEARCH_DETAIL = "search_detail";
    private static final String KEY_SEARCH_EXCERPT = "search_excerpt";
    private static final String KEY_SEARCH_TS = "search_ts";
    private static final String KEY_SEARCH_STATUS = "search_status";

    private ScanStore() {}

    private static SharedPreferences prefs(Context ctx) {
        return ctx.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    public static void saveScan(Context ctx, String pkg, String title, String dump, long ts) {
        prefs(ctx).edit()
                .putString(KEY_PACKAGE, pkg == null ? "" : pkg)
                .putString(KEY_TITLE, title == null ? "" : title)
                .putString(KEY_DUMP, dump == null ? "" : dump)
                .putLong(KEY_TS, ts)
                .apply();
    }

    public static void saveChromeSnapshot(
            Context ctx, String pkg, String title, String fullDump,
            String visibleText, String clickableSummary, long ts) {
        prefs(ctx).edit()
                .putString(KEY_CHROME_PACKAGE, pkg == null ? "" : pkg)
                .putString(KEY_CHROME_TITLE, title == null ? "" : title)
                .putString(KEY_CHROME_DUMP, fullDump == null ? "" : fullDump)
                .putString(KEY_CHROME_VISIBLE, visibleText == null ? "" : visibleText)
                .putString(KEY_CHROME_CLICKABLE, clickableSummary == null ? "" : clickableSummary)
                .putLong(KEY_CHROME_TS, ts)
                .apply();
    }

    public static boolean shouldIgnoreForChromeRetain(String pkg) {
        if (pkg == null) return true;
        return pkg.equals("com.bet365agent") || pkg.startsWith("com.android.settings");
    }

    public static boolean isChromePackage(String pkg) {
        return pkg != null && pkg.equals("com.android.chrome");
    }

    public static void setPendingClickFootball(Context ctx) {
        prefs(ctx).edit()
                .putString(KEY_PENDING, PENDING_CLICK_FOOTBALL)
                .putString(KEY_CLICK_FB_STATUS, "PENDING — switching to Chrome…")
                .putBoolean(KEY_CLICK_FB_PASS, false)
                .putBoolean(KEY_CLICK_FB_TARGET, false)
                .putBoolean(KEY_CLICK_FB_CLICKABLE, false)
                .putBoolean(KEY_CLICK_FB_POST, false)
                .putString(KEY_CLICK_FB_EXCERPT, "")
                .putString(KEY_CLICK_FB_DETAIL, "queued")
                .putLong(KEY_CLICK_FB_TS, System.currentTimeMillis())
                .apply();
    }

    public static String getPendingAction(Context ctx) {
        return prefs(ctx).getString(KEY_PENDING, "");
    }

    public static boolean hasPendingClickFootball(Context ctx) {
        return PENDING_CLICK_FOOTBALL.equals(getPendingAction(ctx));
    }

    public static void clearPendingAction(Context ctx) {
        prefs(ctx).edit().putString(KEY_PENDING, "").apply();
    }

    public static void saveFootballClickResult(
            Context ctx,
            boolean overallPass,
            boolean targetFound,
            boolean clickableFound,
            boolean postValidation,
            String excerpt,
            String detail,
            long ts
    ) {
        prefs(ctx).edit()
                .putBoolean(KEY_CLICK_FB_PASS, overallPass)
                .putBoolean(KEY_CLICK_FB_TARGET, targetFound)
                .putBoolean(KEY_CLICK_FB_CLICKABLE, clickableFound)
                .putBoolean(KEY_CLICK_FB_POST, postValidation)
                .putString(KEY_CLICK_FB_EXCERPT, excerpt == null ? "" : excerpt)
                .putString(KEY_CLICK_FB_DETAIL, detail == null ? "" : detail)
                .putString(KEY_CLICK_FB_STATUS, "DONE")
                .putLong(KEY_CLICK_FB_TS, ts)
                .putString(KEY_PENDING, "")
                .apply();
    }

    public static void setFootballStatus(Context ctx, String status) {
        prefs(ctx).edit().putString(KEY_CLICK_FB_STATUS, status == null ? "" : status).apply();
    }

    public static String getPackage(Context ctx) { return prefs(ctx).getString(KEY_PACKAGE, ""); }
    public static String getTitle(Context ctx) { return prefs(ctx).getString(KEY_TITLE, ""); }
    public static String getDump(Context ctx) { return prefs(ctx).getString(KEY_DUMP, ""); }
    public static long getTs(Context ctx) { return prefs(ctx).getLong(KEY_TS, 0L); }

    public static String getChromePackage(Context ctx) { return prefs(ctx).getString(KEY_CHROME_PACKAGE, ""); }
    public static String getChromeTitle(Context ctx) { return prefs(ctx).getString(KEY_CHROME_TITLE, ""); }
    public static String getChromeDump(Context ctx) { return prefs(ctx).getString(KEY_CHROME_DUMP, ""); }
    public static String getChromeVisible(Context ctx) { return prefs(ctx).getString(KEY_CHROME_VISIBLE, ""); }
    public static String getChromeClickable(Context ctx) { return prefs(ctx).getString(KEY_CHROME_CLICKABLE, ""); }
    public static long getChromeTs(Context ctx) { return prefs(ctx).getLong(KEY_CHROME_TS, 0L); }

    public static boolean hasFootballClickResult(Context ctx) {
        return prefs(ctx).getLong(KEY_CLICK_FB_TS, 0L) > 0
                && !PENDING_CLICK_FOOTBALL.equals(getPendingAction(ctx));
    }
    public static boolean getFootballClickPass(Context ctx) { return prefs(ctx).getBoolean(KEY_CLICK_FB_PASS, false); }
    public static boolean getFootballTargetFound(Context ctx) { return prefs(ctx).getBoolean(KEY_CLICK_FB_TARGET, false); }
    public static boolean getFootballClickableFound(Context ctx) { return prefs(ctx).getBoolean(KEY_CLICK_FB_CLICKABLE, false); }
    public static boolean getFootballPostValidation(Context ctx) { return prefs(ctx).getBoolean(KEY_CLICK_FB_POST, false); }
    public static String getFootballClickExcerpt(Context ctx) { return prefs(ctx).getString(KEY_CLICK_FB_EXCERPT, ""); }
    public static String getFootballClickDetail(Context ctx) { return prefs(ctx).getString(KEY_CLICK_FB_DETAIL, ""); }
    public static String getFootballStatus(Context ctx) { return prefs(ctx).getString(KEY_CLICK_FB_STATUS, ""); }
    public static long getFootballClickTs(Context ctx) { return prefs(ctx).getLong(KEY_CLICK_FB_TS, 0L); }

    // --- Milestone A/B: Search interaction + text entry proof ---

    public static void setPendingSearchFlow(Context ctx, String query) {
        prefs(ctx).edit()
                .putString(KEY_PENDING, PENDING_SEARCH_FLOW)
                .putString(KEY_SEARCH_STATUS, "PENDING — switching to Chrome…")
                .putString(KEY_SEARCH_STAGE, "queued")
                .putBoolean(KEY_SEARCH_PASS, false)
                .putString(KEY_SEARCH_DETAIL, "queued query=" + query)
                .putString(KEY_SEARCH_EXCERPT, "")
                .putLong(KEY_SEARCH_TS, System.currentTimeMillis())
                .putString("search_query", query == null ? "" : query)
                .apply();
    }

    public static String getSearchQuery(Context ctx) { return prefs(ctx).getString("search_query", ""); }

    public static boolean hasPendingSearchFlow(Context ctx) {
        return PENDING_SEARCH_FLOW.equals(getPendingAction(ctx));
    }

    public static void setSearchStatus(Context ctx, String stage, String status) {
        prefs(ctx).edit()
                .putString(KEY_SEARCH_STAGE, stage == null ? "" : stage)
                .putString(KEY_SEARCH_STATUS, status == null ? "" : status)
                .apply();
    }

    public static void saveSearchResult(
            Context ctx, boolean pass, String stage, String detail, String excerpt, long ts) {
        prefs(ctx).edit()
                .putBoolean(KEY_SEARCH_PASS, pass)
                .putString(KEY_SEARCH_STAGE, stage == null ? "" : stage)
                .putString(KEY_SEARCH_DETAIL, detail == null ? "" : detail)
                .putString(KEY_SEARCH_EXCERPT, excerpt == null ? "" : excerpt)
                .putString(KEY_SEARCH_STATUS, "DONE")
                .putLong(KEY_SEARCH_TS, ts)
                .putString(KEY_PENDING, "")
                .apply();
    }

    public static boolean hasSearchResult(Context ctx) {
        return prefs(ctx).getLong(KEY_SEARCH_TS, 0L) > 0 && !PENDING_SEARCH_FLOW.equals(getPendingAction(ctx));
    }
    public static boolean getSearchPass(Context ctx) { return prefs(ctx).getBoolean(KEY_SEARCH_PASS, false); }
    public static String getSearchStage(Context ctx) { return prefs(ctx).getString(KEY_SEARCH_STAGE, ""); }
    public static String getSearchDetail(Context ctx) { return prefs(ctx).getString(KEY_SEARCH_DETAIL, ""); }
    public static String getSearchExcerpt(Context ctx) { return prefs(ctx).getString(KEY_SEARCH_EXCERPT, ""); }
    public static String getSearchStatus(Context ctx) { return prefs(ctx).getString(KEY_SEARCH_STATUS, ""); }
    public static long getSearchTs(Context ctx) { return prefs(ctx).getLong(KEY_SEARCH_TS, 0L); }
}
