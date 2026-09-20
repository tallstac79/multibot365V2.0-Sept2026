package com.bet365agent;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.InputMethod;
import android.view.inputmethod.EditorInfo;

/** Framework input connection, not a replacement keyboard. No accessibility node queries. */
final class AgentInputMethod extends InputMethod {
    private long generation;
    AgentInputMethod(AccessibilityService service) { super(service); }
    long generation() { return generation; }
    @Override public void onStartInput(EditorInfo info, boolean restarting) {
        super.onStartInput(info, restarting);
        generation++;
    }
    @Override public void onFinishInput() {
        generation++;
        super.onFinishInput();
    }
}
