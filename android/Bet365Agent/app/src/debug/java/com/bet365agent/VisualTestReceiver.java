package com.bet365agent;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.util.Log;

/** Shell-only debug test entry point. Not included in release builds. */
public final class VisualTestReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        String id = intent.getStringExtra("run_id");
        if (id == null || !Bet365AccessibilityService.isRunning()) {
            Log.e("AgentVisual", "TEST_REJECTED missing run_id or service not connected");
            setResultCode(1); return;
        }
        Bet365AccessibilityService.triggerVisualControlTest(id, intent.getBooleanExtra("capture_only", false),
            intent.getIntExtra("display_id", android.view.Display.DEFAULT_DISPLAY));
        setResultCode(0);
    }
}
