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
import java.util.Set;

/** Strict JSON schema; duplicate/unknown fields, coercion and trailing data are rejected. */
final class CoordinatorInstruction {
    final String id, target, text, runId, action, adapter, scenario, market, side, sport, line, minimumPrice, stake, executionMode, confirmationStatus;
    final boolean placeBet; // true iff execution_mode=dispatch
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
                Set<String> allowed = Set.of("instruction_id","action","target_text","input_text","adapter","scenario","query","market","side","sport","line","minimum_price","stake","timeout_ms","place_bet","execution_mode","confirmation_status");
                if (!number && !allowed.contains(name)) throw new IllegalArgumentException("Unknown field: " + name);
                if ("line".equals(name) && reader.peek() == JsonToken.NULL) { reader.nextNull(); fields.put(name, ""); continue; }
                if (reader.peek() != (number ? JsonToken.NUMBER : JsonToken.STRING)) throw new IllegalArgumentException("Wrong field type: " + name);
                fields.put(name, reader.nextString());
            }
            reader.endObject();
            if (reader.peek() != JsonToken.END_DOCUMENT) throw new IllegalArgumentException("Trailing data");
        }
        id = fields.getOrDefault("instruction_id", ""); action=fields.getOrDefault("action", "");
        adapter=fields.getOrDefault("adapter", ""); scenario=fields.getOrDefault("scenario", "");
        String rawMarket = fields.getOrDefault("market", "");
        market = "TOTALS".equals(rawMarket) ? "TOTAL" : rawMarket;
        side=fields.getOrDefault("side", "");
        sport=fields.getOrDefault("sport", "");
        String resolvedLine=fields.getOrDefault("line", "");
        minimumPrice=fields.getOrDefault("minimum_price", "");
        stake=fields.getOrDefault("stake", "");
        executionMode = fields.getOrDefault("execution_mode", "").isEmpty()
            ? ("true".equals(fields.getOrDefault("place_bet", "false")) ? "dispatch" : "ready")
            : fields.get("execution_mode");
        if(action.equals("ADAPTER_WORKFLOW") && !Set.of("ready","prepare","dispatch").contains(executionMode))
            throw new IllegalArgumentException("Invalid execution_mode");
        confirmationStatus = fields.getOrDefault("confirmation_status", "NONE");
        if(action.equals("ADAPTER_WORKFLOW") && !Set.of("NONE","APPROVED").contains(confirmationStatus))
            throw new IllegalArgumentException("Invalid confirmation_status");
        if(action.equals("ADAPTER_WORKFLOW") && !"ready".equals(executionMode) && !"APPROVED".equals(confirmationStatus))
            throw new IllegalArgumentException("confirmation_status APPROVED required for prepare/dispatch");
        placeBet = "dispatch".equals(executionMode);
        if(fields.containsKey("place_bet") && !Set.of("true","false").contains(fields.get("place_bet")))
            throw new IllegalArgumentException("Invalid place_bet");
        target=fields.getOrDefault("target_text", ""); text=fields.getOrDefault(action.equals("ADAPTER_WORKFLOW")||action.equals("OPEN_SEARCH")?"query":"input_text", "");
        Set<String> expected;
        if(action.equals("OPEN_AND_TYPE")) {
            expected=Set.of("instruction_id","action","target_text","input_text","timeout_ms");
            if(!fields.keySet().equals(expected)) throw new IllegalArgumentException("Invalid OPEN_AND_TYPE schema");
        } else if(action.equals("OPEN_SEARCH")) {
            // query optional: omit for open-only; include for Searchâ†’typeâ†’results harness
            java.util.HashSet<String> openSearchBase = new java.util.HashSet<>(java.util.Arrays.asList(
                "instruction_id","action","adapter","scenario","sport","timeout_ms"));
            java.util.HashSet<String> keys = new java.util.HashSet<>(fields.keySet());
            if(!keys.containsAll(openSearchBase)) throw new IllegalArgumentException("Invalid OPEN_SEARCH schema");
            keys.removeAll(openSearchBase);
            if(!keys.isEmpty() && !(keys.size()==1 && keys.contains("query")))
                throw new IllegalArgumentException("Invalid OPEN_SEARCH extras");
        } else if(action.equals("SESSION_CHECK")) {
            expected=Set.of("instruction_id","action","adapter","scenario","sport","timeout_ms");
            if(!fields.keySet().equals(expected)) throw new IllegalArgumentException("Invalid SESSION_CHECK schema");
        } else if(action.equals("SESSION_PROBE")) {
            expected=Set.of("instruction_id","action","adapter","timeout_ms");
            if(!fields.keySet().equals(expected)) throw new IllegalArgumentException("Invalid SESSION_PROBE schema");
        } else {
            expected=Set.of("instruction_id","action","adapter","scenario","query","market","side","sport","minimum_price","stake","timeout_ms");
            java.util.HashSet<String> allowedExtra = new java.util.HashSet<>(java.util.Arrays.asList("place_bet","execution_mode","confirmation_status","line"));
            java.util.HashSet<String> keys = new java.util.HashSet<>(fields.keySet());
            keys.removeAll(expected);
            if(!allowedExtra.containsAll(keys)) throw new IllegalArgumentException("Invalid schema extras");
            java.util.HashSet<String> base = new java.util.HashSet<>(fields.keySet());
            base.removeAll(allowedExtra);
            if(!base.equals(expected)) throw new IllegalArgumentException("Invalid ADAPTER_WORKFLOW schema");
        }
        if(!Set.of("OPEN_AND_TYPE","ADAPTER_WORKFLOW","SESSION_CHECK","SESSION_PROBE","OPEN_SEARCH").contains(action)
            || !id.matches("[A-Za-z0-9_-]{1,64}") || ((action.equals("SESSION_CHECK") || action.equals("SESSION_PROBE") || action.equals("OPEN_SEARCH")) ? (action.equals("OPEN_SEARCH") ? false : !text.isEmpty()) : text.isEmpty())
            || text.length()>128 || !fields.getOrDefault("timeout_ms", "").matches("[0-9]{1,6}"))
            throw new IllegalArgumentException("Invalid schema, action, ID, text or timeout");
        if(action.equals("OPEN_AND_TYPE") && !target.matches("[A-Za-z0-9]{1,40}")) throw new IllegalArgumentException("Invalid target");
        if(action.equals("ADAPTER_WORKFLOW") || action.equals("SESSION_CHECK") || action.equals("OPEN_SEARCH")) {
            SiteAdapters.validate(adapter,scenario);
            if(!Set.of("football","basketball").contains(sport)) throw new IllegalArgumentException("Invalid sport");
        }
        if(action.equals("ADAPTER_WORKFLOW")) {
            if(!minimumPrice.matches("[0-9]+\\.[0-9]{2}") || !stake.matches("[0-9]+\\.[0-9]{2}")) throw new IllegalArgumentException("Invalid minimum_price or stake");
            if(!Set.of("MONEYLINE","SPREAD","TOTAL").contains(market)) throw new IllegalArgumentException("Invalid market");
            Set<String> sides = market.equals("TOTAL") ? Set.of("OVER","UNDER")
                : market.equals("MONEYLINE") ? Set.of("HOME","AWAY","DRAW")
                : Set.of("HOME","AWAY");
            if(!sides.contains(side)) throw new IllegalArgumentException("Invalid market/side");
            String normalizedLine = resolvedLine == null ? "" : resolvedLine.trim();
            if(market.equals("MONEYLINE")) {
                if(!normalizedLine.isEmpty() && !normalizedLine.equalsIgnoreCase("NONE") && !normalizedLine.equalsIgnoreCase("null"))
                    throw new IllegalArgumentException("line not allowed for MONEYLINE");
                resolvedLine = "";
            } else {
                if(normalizedLine.isEmpty() || normalizedLine.equalsIgnoreCase("NONE") || normalizedLine.equalsIgnoreCase("null"))
                    throw new IllegalArgumentException("line required for SPREAD/TOTALS");
                if(!normalizedLine.matches("[+-]?[0-9]+(\\.[0-9]+)?")) throw new IllegalArgumentException("Invalid line");
                resolvedLine = normalizedLine;
            }
        }
        if(!action.equals("ADAPTER_WORKFLOW")) resolvedLine = "";
        line = resolvedLine;
        timeout = Integer.parseInt(fields.get("timeout_ms"));
        if (timeout < 100 || timeout > 600000) throw new IllegalArgumentException("timeout_ms must be 100..600000");
        runId = "c_" + Base64.encodeToString(MessageDigest.getInstance("SHA-256").digest(id.getBytes(StandardCharsets.UTF_8)), Base64.NO_WRAP | Base64.URL_SAFE | Base64.NO_PADDING);
        payload = new JSONObject();for(Map.Entry<String,String> entry:fields.entrySet())payload.put(entry.getKey(),entry.getKey().equals("timeout_ms")?timeout:entry.getValue());
    }
    TextInstruction asText(long remaining) throws Exception {
        return new TextInstruction(new JSONObject().put("run_id", runId).put("field_hint", target)
            .put("text", text).put("package", "com.android.chrome").put("timeout_ms", remaining));
    }
}

