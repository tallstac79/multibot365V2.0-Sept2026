package com.bet365agent;

import android.accessibilityservice.AccessibilityServiceInfo;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.view.accessibility.AccessibilityManager;
import android.widget.Button;
import android.widget.TextView;
import android.widget.Toast;

import androidx.appcompat.app.AppCompatActivity;

import java.text.DateFormat;
import java.util.Date;
import java.util.List;

public class MainActivity extends AppCompatActivity {
    private final Handler main = new Handler(Looper.getMainLooper());

    private TextView statusAccessibility;
    private TextView statusPackage;
    private TextView statusTimestamp;
    private TextView scanOutput;
    private TextView chromeTimestamp;
    private TextView chromeTitle;
    private TextView chromeVisible;
    private TextView chromeClickable;
    private TextView chromeDump;
    private TextView clickFbResult;
    private TextView clickFbExcerpt;
    private TextView searchResult;
    private TextView searchExcerpt;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        statusAccessibility = findViewById(R.id.statusAccessibility);
        statusPackage = findViewById(R.id.statusPackage);
        statusTimestamp = findViewById(R.id.statusTimestamp);
        scanOutput = findViewById(R.id.scanOutput);
        chromeTimestamp = findViewById(R.id.chromeTimestamp);
        chromeTitle = findViewById(R.id.chromeTitle);
        chromeVisible = findViewById(R.id.chromeVisible);
        chromeClickable = findViewById(R.id.chromeClickable);
        chromeDump = findViewById(R.id.chromeDump);
        clickFbResult = findViewById(R.id.clickFbResult);
        clickFbExcerpt = findViewById(R.id.clickFbExcerpt);
        searchResult = findViewById(R.id.searchResult);
        searchExcerpt = findViewById(R.id.searchExcerpt);

        findViewById(R.id.btnOpenSettings).setOnClickListener(v -> {
            Intent intent = new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS);
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(intent);
        });

        findViewById(R.id.btnRefresh).setOnClickListener(v -> {
            Bet365AccessibilityService.requestScan();
            v.postDelayed(this::refreshUi, 500);
        });

        findViewById(R.id.btnClickFootball).setOnClickListener(v -> {
            if (!isServiceEnabled()) {
                Toast.makeText(this, "Enable Accessibility first", Toast.LENGTH_LONG).show();
                return;
            }
            ScanStore.setPendingClickFootball(this);
            refreshUi();
            Toast.makeText(this, "Queued CLICK_FOOTBALL — opening Bet365 HO/ in Chrome", Toast.LENGTH_SHORT).show();

            Intent chrome = new Intent(Intent.ACTION_VIEW, Uri.parse("https://www.bet365.com/#/HO/"));
            chrome.setPackage("com.android.chrome");
            chrome.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            try {
                startActivity(chrome);
            } catch (Exception e) {
                Intent any = new Intent(Intent.ACTION_VIEW, Uri.parse("https://www.bet365.com/#/HO/"));
                any.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                startActivity(any);
            }

            main.postDelayed(Bet365AccessibilityService::notifyPendingFootballClickArmed, 400);
        });

        findViewById(R.id.btnTestSearch).setOnClickListener(v -> {
            if (!isServiceEnabled()) {
                Toast.makeText(this, "Enable Accessibility first", Toast.LENGTH_LONG).show();
                return;
            }
            // Milestone A+B: open Search and enter a known fixture query.
            ScanStore.setPendingSearchFlow(this, "Fulham");
            refreshUi();
            Toast.makeText(this, "Queued SEARCH_FLOW — opening Bet365 HO/ in Chrome", Toast.LENGTH_SHORT).show();

            Intent chrome = new Intent(Intent.ACTION_VIEW, Uri.parse("https://www.bet365.com/#/HO/"));
            chrome.setPackage("com.android.chrome");
            chrome.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            try {
                startActivity(chrome);
            } catch (Exception e) {
                Intent any = new Intent(Intent.ACTION_VIEW, Uri.parse("https://www.bet365.com/#/HO/"));
                any.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                startActivity(any);
            }

            main.postDelayed(Bet365AccessibilityService::notifyPendingSearchFlowArmed, 400);
        });
    }

    @Override
    protected void onResume() {
        super.onResume();
        refreshUi();
        if (ScanStore.hasPendingClickFootball(this)
                || (ScanStore.getFootballStatus(this) != null
                && (ScanStore.getFootballStatus(this).startsWith("PENDING")
                || ScanStore.getFootballStatus(this).startsWith("RUNNING")))
                || ScanStore.hasPendingSearchFlow(this)
                || (ScanStore.getSearchStatus(this) != null
                && (ScanStore.getSearchStatus(this).startsWith("PENDING")
                || ScanStore.getSearchStatus(this).startsWith("RUNNING")))) {
            main.postDelayed(this::refreshUi, 1500);
            main.postDelayed(this::refreshUi, 4000);
            main.postDelayed(this::refreshUi, 8000);
            main.postDelayed(this::refreshUi, 12000);
        }
    }

    private void refreshUi() {
        boolean enabled = isServiceEnabled();
        statusAccessibility.setText("Accessibility service enabled: " + (enabled ? "YES" : "NO"));

        String pkg = ScanStore.getPackage(this);
        String title = ScanStore.getTitle(this);
        statusPackage.setText("Foreground / last scan package: " + (pkg.isEmpty() ? "(none yet)" : pkg)
                + (title.isEmpty() ? "" : ("\nWindow title: " + title)));

        long ts = ScanStore.getTs(this);
        statusTimestamp.setText(ts <= 0 ? "Last scan: (none yet)"
                : "Last scan: " + DateFormat.getDateTimeInstance().format(new Date(ts)));

        String dump = ScanStore.getDump(this);
        scanOutput.setText((dump == null || dump.isEmpty()) ? "No scan yet." : dump);

        long cts = ScanStore.getChromeTs(this);
        if (cts <= 0) {
            chromeTimestamp.setText("Timestamp: (none yet)");
            chromeTitle.setText("Window title: (none yet)");
            chromeVisible.setText("(none yet)");
            chromeClickable.setText("(none yet)");
            chromeDump.setText("(none yet)");
        } else {
            chromeTimestamp.setText("Timestamp: " + DateFormat.getDateTimeInstance().format(new Date(cts))
                    + "\nPackage: " + ScanStore.getChromePackage(this));
            String ct = ScanStore.getChromeTitle(this);
            chromeTitle.setText("Window title: " + (ct.isEmpty() ? "(empty)" : ct));
            chromeVisible.setText(empty(ScanStore.getChromeVisible(this), "(no text nodes)"));
            chromeClickable.setText(empty(ScanStore.getChromeClickable(this), "(no clickable nodes)"));
            chromeDump.setText(empty(ScanStore.getChromeDump(this), "(empty dump)"));
        }

        String status = ScanStore.getFootballStatus(this);
        if (!ScanStore.hasFootballClickResult(this) && (status == null || status.isEmpty())) {
            clickFbResult.setText("CLICK_FOOTBALL: (not run)\nTARGET_FOUND: —\nCLICKABLE_NODE_FOUND: —\nPOST_CLICK_VALIDATION: —");
            clickFbExcerpt.setText("POST_CLICK_CHROME_TEXT: (none)");
        } else if (ScanStore.hasPendingClickFootball(this) || (status != null && status.startsWith("PENDING"))
                || (status != null && status.startsWith("RUNNING"))) {
            clickFbResult.setText("CLICK_FOOTBALL: " + status
                    + "\nTARGET_FOUND: (pending)"
                    + "\nCLICKABLE_NODE_FOUND: (pending)"
                    + "\nPOST_CLICK_VALIDATION: (pending)");
            clickFbExcerpt.setText("POST_CLICK_CHROME_TEXT: (waiting — return here after Chrome test)");
        } else {
            boolean pass = ScanStore.getFootballClickPass(this);
            clickFbResult.setText(
                    "CLICK_FOOTBALL: " + (pass ? "PASS" : "FAIL")
                            + "\nTARGET_FOUND: " + yn(ScanStore.getFootballTargetFound(this))
                            + "\nCLICKABLE_NODE_FOUND: " + yn(ScanStore.getFootballClickableFound(this))
                            + "\nPOST_CLICK_VALIDATION: " + (ScanStore.getFootballPostValidation(this) ? "PASS" : "FAIL")
                            + "\n" + ScanStore.getFootballClickDetail(this)
            );
            clickFbExcerpt.setText("POST_CLICK_CHROME_TEXT:\n" + ScanStore.getFootballClickExcerpt(this));
        }

        String searchStatus = ScanStore.getSearchStatus(this);
        if (!ScanStore.hasSearchResult(this) && (searchStatus == null || searchStatus.isEmpty())) {
            searchResult.setText("SEARCH_FLOW: (not run)\nSTAGE: —");
            searchExcerpt.setText("SEARCH_CHROME_TEXT: (none)");
        } else if (ScanStore.hasPendingSearchFlow(this) || (searchStatus != null && searchStatus.startsWith("PENDING"))
                || (searchStatus != null && searchStatus.startsWith("RUNNING"))) {
            searchResult.setText("SEARCH_FLOW: " + searchStatus + "\nSTAGE: " + ScanStore.getSearchStage(this));
            searchExcerpt.setText("SEARCH_CHROME_TEXT: (waiting — return here after Chrome test)");
        } else {
            boolean pass = ScanStore.getSearchPass(this);
            searchResult.setText("SEARCH_FLOW: " + (pass ? "PASS" : "FAIL")
                    + "\nSTAGE: " + ScanStore.getSearchStage(this)
                    + "\n" + ScanStore.getSearchDetail(this));
            searchExcerpt.setText("SEARCH_CHROME_TEXT:\n" + ScanStore.getSearchExcerpt(this));
        }
    }

    private static String yn(boolean v) { return v ? "YES" : "NO"; }
    private static String empty(String s, String fb) { return s == null || s.isEmpty() ? fb : s; }

    private boolean isServiceEnabled() {
        if (Bet365AccessibilityService.isRunning()) return true;
        AccessibilityManager am = (AccessibilityManager) getSystemService(Context.ACCESSIBILITY_SERVICE);
        if (am == null) return false;
        List<AccessibilityServiceInfo> enabled =
                am.getEnabledAccessibilityServiceList(AccessibilityServiceInfo.FEEDBACK_ALL_MASK);
        if (enabled == null) return false;
        for (AccessibilityServiceInfo info : enabled) {
            if (info != null && info.getId() != null && info.getId().contains("Bet365AccessibilityService")) {
                return true;
            }
        }
        return false;
    }
}
