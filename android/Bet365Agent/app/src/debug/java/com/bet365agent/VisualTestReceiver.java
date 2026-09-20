package com.bet365agent;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.util.Log;

/** Shell-only debug test entry point. Not included in release builds. */
public final class VisualTestReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        if (intent.hasExtra("text_instruction")) {
            try {
                if (!Bet365AccessibilityService.isRunning()) throw new IllegalStateException("Service not connected");
                byte[] json = android.util.Base64.decode(intent.getStringExtra("text_instruction"), android.util.Base64.DEFAULT);
                TextInstruction instruction = new TextInstruction(new org.json.JSONObject(new String(json, java.nio.charset.StandardCharsets.UTF_8)));
                Bet365AccessibilityService.triggerTextEntry(instruction);
                setResultCode(0);
            } catch (Exception e) {
                Log.e("AgentText", "Instruction rejected", e);
                setResultCode(1);
            }
            return;
        }
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
