package com.bet365agent;

import android.util.JsonReader;
import android.util.JsonToken;
import android.util.Base64;
import org.json.JSONObject;
import java.io.StringReader;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HashMap;
import java.util.Map;

/** Strict JSON schema; duplicate/unknown fields, coercion and trailing data are rejected. */
final class CoordinatorInstruction {
    final String id, target, text, runId;
    final int timeout;
    final JSONObject payload;
    CoordinatorInstruction(String json) throws Exception {
        Map<String, String> fields = new HashMap<>();
        try (JsonReader reader = new JsonReader(new StringReader(json))) {
            reader.setLenient(false);
            reader.beginObject();
            while (reader.hasNext()) {
                String name = reader.nextName();
                if (fields.containsKey(name)) throw new IllegalArgumentException("Duplicate field: " + name);
                boolean number = "timeout_ms".equals(name);
                if (!number && !name.equals("instruction_id") && !name.equals("action")
                        && !name.equals("target_text") && !name.equals("input_text")) throw new IllegalArgumentException("Unknown field: " + name);
                if (reader.peek() != (number ? JsonToken.NUMBER : JsonToken.STRING)) throw new IllegalArgumentException("Wrong field type: " + name);
                fields.put(name, reader.nextString());
            }
            reader.endObject();
            if (reader.peek() != JsonToken.END_DOCUMENT || fields.size() != 5) throw new IllegalArgumentException("Exactly five fields required");
        }
        id = fields.get("instruction_id"); target = fields.get("target_text"); text = fields.get("input_text");
        if (!"OPEN_AND_TYPE".equals(fields.get("action")) || !id.matches("[A-Za-z0-9_-]{1,64}")
                || !target.matches("[A-Za-z0-9]{1,40}") || text.isEmpty() || text.length() > 128
                || !fields.get("timeout_ms").matches("[0-9]{1,5}")) throw new IllegalArgumentException("Invalid action, ID, target, text or timeout");
        timeout = Integer.parseInt(fields.get("timeout_ms"));
        if (timeout < 100 || timeout > 60000) throw new IllegalArgumentException("timeout_ms must be 100..60000");
        runId = "c_" + Base64.encodeToString(MessageDigest.getInstance("SHA-256").digest(id.getBytes(StandardCharsets.UTF_8)), Base64.NO_WRAP | Base64.URL_SAFE | Base64.NO_PADDING);
        payload = new JSONObject().put("instruction_id", id).put("action", "OPEN_AND_TYPE")
            .put("target_text", target).put("input_text", text).put("timeout_ms", timeout);
    }
    TextInstruction asText(long remaining) throws Exception {
        return new TextInstruction(new JSONObject().put("run_id", runId).put("field_hint", target)
            .put("text", text).put("package", "com.android.chrome").put("timeout_ms", remaining));
    }
}
