package com.bet365agent;

import org.json.JSONObject;

/** Bounded instruction values; no text interpolation into shell commands or page scripts. */
final class TextInstruction {
    final String id, text, fieldHint, targetPackage;
    final long timeoutMs;
    TextInstruction(JSONObject value) throws Exception {
        id = value.getString("run_id");
        text = value.getString("text");
        fieldHint = value.getString("field_hint");
        targetPackage = value.getString("package");
        timeoutMs = value.optLong("timeout_ms", 30000);
        if (!id.matches("[A-Za-z0-9_-]{1,64}") || text.isEmpty() || text.length() > 128
                || !fieldHint.matches("[A-Za-z0-9.]{1,40}") || targetPackage.isEmpty()
                || timeoutMs < 100 || timeoutMs > 60000) {
            throw new IllegalArgumentException("Invalid id, text (1..128 UTF-16 units), single-word field hint, package or deadline");
        }
    }
}
