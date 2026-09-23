package com.bet365agent;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.InputMethod;
import android.os.SystemClock;
import android.view.inputmethod.EditorInfo;

/** Framework input connection, not a replacement keyboard. No accessibility node queries. */
final class AgentInputMethod extends InputMethod {
    private long generation;
    private long lastStartElapsedMs;
    private long lastFinishElapsedMs;
    private String lastPackage = "";

    AgentInputMethod(AccessibilityService service) { super(service); }

    long generation() { return generation; }
    long lastStartElapsedMs() { return lastStartElapsedMs; }
    long lastFinishElapsedMs() { return lastFinishElapsedMs; }
    String lastPackage() { return lastPackage; }

    @Override public void onStartInput(EditorInfo info, boolean restarting) {
        super.onStartInput(info, restarting);
        generation++;
        lastStartElapsedMs = SystemClock.elapsedRealtime();
        lastPackage = info != null && info.packageName != null ? info.packageName : "";
    }

    @Override public void onFinishInput() {
        generation++;
        lastFinishElapsedMs = SystemClock.elapsedRealtime();
        super.onFinishInput();
    }
}