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
    final String id, target, text, runId, action, adapter, scenario, market, side;
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
                        && !name.equals("target_text") && !name.equals("input_text") && !java.util.Set.of("adapter","scenario","query","market","side").contains(name)) throw new IllegalArgumentException("Unknown field: " + name);
                if (reader.peek() != (number ? JsonToken.NUMBER : JsonToken.STRING)) throw new IllegalArgumentException("Wrong field type: " + name);
                fields.put(name, reader.nextString());
            }
            reader.endObject();
            if (reader.peek() != JsonToken.END_DOCUMENT) throw new IllegalArgumentException("Trailing data");
        }
        id = fields.getOrDefault("instruction_id", ""); action=fields.getOrDefault("action", "");
        adapter=fields.getOrDefault("adapter", ""); scenario=fields.getOrDefault("scenario", "");
        market=fields.getOrDefault("market", ""); side=fields.getOrDefault("side", "");
        target=fields.getOrDefault("target_text", ""); text=fields.getOrDefault(action.equals("ADAPTER_WORKFLOW")?"query":"input_text", "");
        java.util.Set<String> expected=action.equals("OPEN_AND_TYPE")?java.util.Set.of("instruction_id","action","target_text","input_text","timeout_ms"):
            java.util.Set.of("instruction_id","action","adapter","scenario","query","market","side","timeout_ms");
        if(!fields.keySet().equals(expected) || !java.util.Set.of("OPEN_AND_TYPE","ADAPTER_WORKFLOW").contains(action)
            || !id.matches("[A-Za-z0-9_-]{1,64}") || text.isEmpty() || text.length()>128 || !fields.getOrDefault("timeout_ms", "").matches("[0-9]{1,5}")) throw new IllegalArgumentException("Invalid schema, action, ID, text or timeout");
        if(action.equals("OPEN_AND_TYPE") && !target.matches("[A-Za-z0-9]{1,40}")) throw new IllegalArgumentException("Invalid target");
        if(action.equals("ADAPTER_WORKFLOW")) {
            SiteAdapters.validate(adapter,scenario);
            if(!java.util.Set.of("MONEYLINE","SPREAD","TOTAL").contains(market) || !(market.equals("TOTAL")?java.util.Set.of("OVER","UNDER"):java.util.Set.of("HOME","AWAY")).contains(side)) throw new IllegalArgumentException("Invalid market/side");
        }
        timeout = Integer.parseInt(fields.get("timeout_ms"));
        if (timeout < 100 || timeout > 60000) throw new IllegalArgumentException("timeout_ms must be 100..60000");
        runId = "c_" + Base64.encodeToString(MessageDigest.getInstance("SHA-256").digest(id.getBytes(StandardCharsets.UTF_8)), Base64.NO_WRAP | Base64.URL_SAFE | Base64.NO_PADDING);
        payload = new JSONObject();for(Map.Entry<String,String> entry:fields.entrySet())payload.put(entry.getKey(),entry.getKey().equals("timeout_ms")?timeout:entry.getValue());
    }
    TextInstruction asText(long remaining) throws Exception {
        return new TextInstruction(new JSONObject().put("run_id", runId).put("field_hint", target)
            .put("text", text).put("package", "com.android.chrome").put("timeout_ms", remaining));
    }
}
