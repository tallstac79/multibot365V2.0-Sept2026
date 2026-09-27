package com.bet365agent;

import org.json.JSONObject;

/** A final instruction can consume only its own durably successful hold. */
final class HeldInstruction {
    static boolean fresh(long received, long duration, long now) {
        long completed = received + duration;
        return received > 0 && duration >= 0 && now >= completed && now - completed <= 120_000L;
    }
    static String wireMarket(String market) {
        String m = market == null ? "" : market.replace("TOTALS", "TOTAL");
        return "1X2".equals(m) ? "MONEYLINE" : m;
    }

    static JSONObject verify(JSONObject request, JSONObject held) {
        if (held == null) throw new IllegalArgumentException("Original hold missing");
        JSONObject payload = held.optJSONObject("payload"), result = held.optJSONObject("result");
        if (payload == null || result == null || !"hold".equals(payload.optString("execution_mode"))
                || !"PASS".equals(result.optString("status")) || !result.optBoolean("held"))
            throw new IllegalArgumentException("Original hold did not complete successfully");
        if (!fresh(held.optLong("received_ms"), result.optLong("duration_ms", -1), System.currentTimeMillis()))
            throw new IllegalArgumentException("Original hold expired (120 second approval window)");
        if (!request.optString("instruction_id").equals(held.optString("instruction_id") + "-place"))
            throw new IllegalArgumentException("Final ID must consume exactly this hold");
        JSONObject context = result.optJSONObject("event_context"), selection = result.optJSONObject("selection");
        if (context == null || selection == null) throw new IllegalArgumentException("Hold has no verified context/selection");
        for (String k : new String[]{"home","away","competition","kickoff_utc","period"})
            if (context.optString(k).isEmpty() || !context.optString(k).equals(request.optString(k)))
                throw new IllegalArgumentException("Held event changed: " + k);
        for (String k : new String[]{"sport","stake","minimum_price"})
            if (!payload.optString(k).equals(request.optString(k))) throw new IllegalArgumentException("Held terms changed: " + k);
        for (String k : new String[]{"side","line","price","selection_name"})
            if (!selection.optString(k).equals(request.optString(k))) throw new IllegalArgumentException("Held selection changed: " + k);
        // football 1X2 is the phone's three-way MONEYLINE (the hold records MONEYLINE; the pipeline sends the wire name 1X2)
        if (!wireMarket(request.optString("market")).equals(wireMarket(selection.optString("market")))) throw new IllegalArgumentException("Held market changed");
        CoordinatorAgent.put(context, "requested_line", payload.optString("line"));
        CoordinatorAgent.put(context, "max_line_deterioration", payload.optString("max_line_deterioration"));
        return context;
    }
}
