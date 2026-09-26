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
    final String id, target, text, runId, action, adapter, scenario, market, side, sport, line, minimumPrice, stake, executionMode, confirmationStatus, view;
    final String eventUrl, kickoffUtc, selectionName, price;
    final String competition, period, lineTolerance, heldInstructionId, home, away;
    final java.util.Map<String, String> aliases;
    final boolean competitionWomen;
    final String frames, engine;
    final boolean placeBet; // true iff execution_mode=dispatch
    final int timeout;
    final JSONObject payload;

    /** "aliases": a small JSON object {feed name: bookmaker name}; at most 8 entries of plain team-name text. */
    static java.util.Map<String, String> parseAliases(String json) {
        java.util.Map<String, String> out = new java.util.LinkedHashMap<>();
        if (json == null || json.trim().isEmpty()) return out;
        JSONObject o;
        try { o = new JSONObject(json); } catch (Exception e) { throw new IllegalArgumentException("Invalid aliases"); }
        if (o.length() > 8) throw new IllegalArgumentException("Too many aliases");
        for (java.util.Iterator<String> it = o.keys(); it.hasNext(); ) {
            String k = it.next(); Object v = o.opt(k);
            if (!(v instanceof String) || !k.matches("[A-Za-z0-9 ./'&()-]{2,64}") || !((String) v).matches("[A-Za-z0-9 ./'&()-]{2,64}"))
                throw new IllegalArgumentException("Invalid alias entry");
            out.put(EventIdentity.plain(k), (String) v);
        }
        return out;
    }

    static final Set<String> WORKFLOW_BASE = Set.of("instruction_id","action","adapter","scenario","query","market","side","sport","minimum_price","stake","timeout_ms");

    /**
     * ADAPTER_WORKFLOW schema: the base fields plus only these extras. Pure (JVM-tested: CoordinatorInstructionTest).
     * competition_women (0.9.14-women) is the backend's competition-aware women's marker flag. Real failure
     * 2026-09-25 12:15 UTC (on-42935974, KSC Szekszard v NKA Universitas Pecs, "Nemzeti Bajnoksag I.A Women"): the
     * field was on the global whitelist but not here, so every women's-competition hold run was refused with
     * "Invalid schema extras".
     */
    static void checkWorkflowExtras(Map<String, String> fields) {
        java.util.HashSet<String> allowedExtra = new java.util.HashSet<>(java.util.Arrays.asList("place_bet","execution_mode","confirmation_status","line","event_url","kickoff_utc","aliases","competition_women","competition","period","max_line_deterioration"));
        if(fields.containsKey("event_url") && !EventPage.validUrl(fields.get("event_url"))) throw new IllegalArgumentException("Invalid event_url");
        if(fields.containsKey("kickoff_utc") && !fields.get("kickoff_utc").matches("[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}"))
            throw new IllegalArgumentException("Invalid kickoff_utc");
        if(fields.containsKey("competition_women") && !Set.of("true","false").contains(fields.get("competition_women")))
            throw new IllegalArgumentException("Invalid competition_women");
        java.util.HashSet<String> keys = new java.util.HashSet<>(fields.keySet());
        keys.removeAll(WORKFLOW_BASE);
        if(!allowedExtra.containsAll(keys)) throw new IllegalArgumentException("Invalid schema extras");
        java.util.HashSet<String> base = new java.util.HashSet<>(fields.keySet());
        base.removeAll(allowedExtra);
        if(!base.equals(WORKFLOW_BASE)) throw new IllegalArgumentException("Invalid ADAPTER_WORKFLOW schema");
    }

    CoordinatorInstruction(String json) throws Exception {
        Map<String, String> fields = new HashMap<>();
        try (JsonReader reader = new JsonReader(new StringReader(json))) {
            reader.setLenient(false);
            reader.beginObject();
            while (reader.hasNext()) {
                String name = reader.nextName();
                if (fields.containsKey(name)) throw new IllegalArgumentException("Duplicate field: " + name);
                boolean number = "timeout_ms".equals(name);
                Set<String> allowed = Set.of("instruction_id","action","target_text","input_text","adapter","scenario","query","market","side","sport","line","minimum_price","stake","timeout_ms","place_bet","execution_mode","confirmation_status","view","event_url","kickoff_utc","selection_name","price","aliases","frames","engine","competition_women","competition","period","max_line_deterioration","held_instruction_id","home","away");
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
        if(action.equals("ADAPTER_WORKFLOW") && !Set.of("ready","hold","prepare","dispatch").contains(executionMode))
            throw new IllegalArgumentException("Invalid execution_mode");
        if(action.equals("PLACE_HELD") && !Set.of("prepare","dispatch").contains(executionMode))
            throw new IllegalArgumentException("Invalid PLACE_HELD execution_mode");
        confirmationStatus = fields.getOrDefault("confirmation_status", "NONE");
        if(action.equals("ADAPTER_WORKFLOW") && !Set.of("NONE","APPROVED").contains(confirmationStatus))
            throw new IllegalArgumentException("Invalid confirmation_status");
        // hold never taps (it stops with the verified bet on the slip), so it needs no approval.
        if(action.equals("ADAPTER_WORKFLOW") && !"ready".equals(executionMode) && !"hold".equals(executionMode) && !"APPROVED".equals(confirmationStatus))
            throw new IllegalArgumentException("confirmation_status APPROVED required for prepare/dispatch");
        if(action.equals("PLACE_HELD") && !"APPROVED".equals(confirmationStatus))
            throw new IllegalArgumentException("confirmation_status APPROVED required for PLACE_HELD");
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
        } else if(action.equals("MY_BETS")) {
            expected=Set.of("instruction_id","action","adapter","scenario","view","timeout_ms");
            if(!fields.keySet().equals(expected)) throw new IllegalArgumentException("Invalid MY_BETS schema");
            if(!Set.of("OPEN","SETTLED").contains(fields.get("view"))) throw new IllegalArgumentException("Invalid MY_BETS view");
        } else if(action.equals("PLACE_HELD")) {
            expected=Set.of("instruction_id","action","adapter","scenario","sport","market","side","line","selection_name","price",
                    "minimum_price","stake","execution_mode","confirmation_status","timeout_ms","held_instruction_id","home","away","competition","period","kickoff_utc");
            if(!fields.keySet().equals(expected)) throw new IllegalArgumentException("Invalid PLACE_HELD schema");
            if(!fields.get("price").matches("[0-9]+\\.[0-9]{2}")) throw new IllegalArgumentException("Invalid price");
            if(!fields.get("selection_name").matches("[A-Za-z0-9 ./'&()-]{2,64}")) throw new IllegalArgumentException("Invalid selection_name");
        } else if(action.equals("OCR_BENCH")) {
            expected=Set.of("instruction_id","action","adapter","scenario","frames","engine","timeout_ms");
            if(!fields.keySet().equals(expected)) throw new IllegalArgumentException("Invalid OCR_BENCH schema");
            if(!Set.of("legacy","fast","hybrid").contains(fields.get("engine"))) throw new IllegalArgumentException("Invalid engine");
            if(fields.get("frames").length()>3600 || !fields.get("frames").trim().startsWith("[")) throw new IllegalArgumentException("Invalid frames");
        } else if(action.equals("RESET_BETSLIP")) {
            expected=Set.of("instruction_id","action","adapter","scenario","timeout_ms");
            if(!fields.keySet().equals(expected)) throw new IllegalArgumentException("Invalid RESET_BETSLIP schema");
        } else if(action.equals("OBSERVE")) {
            expected=Set.of("instruction_id","action","adapter","timeout_ms");
            if(!fields.keySet().equals(expected)) throw new IllegalArgumentException("Invalid OBSERVE schema");
        } else if(action.equals("SESSION_PROBE")) {
            expected=Set.of("instruction_id","action","adapter","timeout_ms");
            if(!fields.keySet().equals(expected)) throw new IllegalArgumentException("Invalid SESSION_PROBE schema");
        } else {
            expected = WORKFLOW_BASE;
            checkWorkflowExtras(fields);
        }
        boolean noText = Set.of("SESSION_CHECK","SESSION_PROBE","MY_BETS","OBSERVE","RESET_BETSLIP","PLACE_HELD","OCR_BENCH").contains(action);
        if(!Set.of("OPEN_AND_TYPE","ADAPTER_WORKFLOW","SESSION_CHECK","SESSION_PROBE","OPEN_SEARCH","MY_BETS","OBSERVE","RESET_BETSLIP","PLACE_HELD","OCR_BENCH").contains(action)
            || !id.matches("[A-Za-z0-9_-]{1,64}") || (noText ? !text.isEmpty() : (!action.equals("OPEN_SEARCH") && text.isEmpty()))
            || text.length()>128 || !fields.getOrDefault("timeout_ms", "").matches("[0-9]{1,6}"))
            throw new IllegalArgumentException("Invalid schema, action, ID, text or timeout");
        if(action.equals("OPEN_AND_TYPE") && !target.matches("[A-Za-z0-9]{1,40}")) throw new IllegalArgumentException("Invalid target");
        if(action.equals("MY_BETS") || action.equals("RESET_BETSLIP") || action.equals("OCR_BENCH")) SiteAdapters.validate(adapter,scenario);
        if(action.equals("PLACE_HELD")) {
            SiteAdapters.validate(adapter,scenario);
            if(!Set.of("football","basketball").contains(sport)) throw new IllegalArgumentException("Invalid sport");
        }
        if(action.equals("ADAPTER_WORKFLOW") || action.equals("SESSION_CHECK") || action.equals("OPEN_SEARCH")) {
            SiteAdapters.validate(adapter,scenario);
            if(!Set.of("football","basketball").contains(sport)) throw new IllegalArgumentException("Invalid sport");
        }
        if(action.equals("ADAPTER_WORKFLOW") || action.equals("PLACE_HELD")) {
            if(!minimumPrice.matches("[0-9]+\\.[0-9]{2}") || !stake.matches("[0-9]+\\.[0-9]{2}")) throw new IllegalArgumentException("Invalid minimum_price or stake");
            if(!Set.of("MONEYLINE","SPREAD","TOTAL").contains(market)) throw new IllegalArgumentException("Invalid market");
            Set<String> sides = market.equals("TOTAL") ? Set.of("OVER","UNDER")
                : market.equals("MONEYLINE") ? Set.of("HOME","AWAY","DRAW")
                : Set.of("HOME","AWAY");
            if(!sides.contains(side)) throw new IllegalArgumentException("Invalid market/side");
            if(market.equals("MONEYLINE") && !MoneylineTerms.validSide(sport, side))
                throw new IllegalArgumentException("Invalid sport/moneyline outcome");
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
        if(!action.equals("ADAPTER_WORKFLOW") && !action.equals("PLACE_HELD")) resolvedLine = "";
        line = resolvedLine;
        view = fields.getOrDefault("view", "");
        eventUrl = fields.getOrDefault("event_url", "");
        kickoffUtc = fields.getOrDefault("kickoff_utc", "");
        competition = fields.getOrDefault("competition", "");
        period = fields.getOrDefault("period", "");
        lineTolerance = fields.getOrDefault("max_line_deterioration", "");
        heldInstructionId = fields.getOrDefault("held_instruction_id", "");
        home = fields.getOrDefault("home", ""); away = fields.getOrDefault("away", "");
        if (action.equals("PLACE_HELD") && (!id.equals(heldInstructionId + "-place") || home.isEmpty() || away.isEmpty()
                || competition.isEmpty() || !"FULL_GAME".equals(period) || kickoffUtc.isEmpty()))
            throw new IllegalArgumentException("Complete original held event context required");
        selectionName = fields.getOrDefault("selection_name", "");
        price = fields.getOrDefault("price", "");
        aliases = parseAliases(fields.getOrDefault("aliases", ""));
        competitionWomen = "true".equals(fields.getOrDefault("competition_women", "false"));
        frames = fields.getOrDefault("frames", "");
        engine = fields.getOrDefault("engine", "");
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

