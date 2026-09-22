package com.bet365agent;

/** Composition boundary: registering an adapter never requires changes to the workflow or visual driver. */
final class SiteAdapters {
    static void validate(String name,String scenario) {
        if(name.equals("local_simulator") && java.util.Set.of("normal","empty","ambiguous","wrong_event","click_ignored","changing","suspended","unavailable","wrong_line","wrong_side","stale").contains(scenario)) return;
        if(name.equals("live_bet365") && scenario.equals("live")) return;
        throw new IllegalArgumentException("Unknown adapter or simulator scenario");
    }
    static SiteAdapter create(String name,VisualSession session,String endpoint,String scenario,String instructionId,String sport,String stake){
        if(name.equals("local_simulator"))return new LocalSimulatorAdapter(session,endpoint,scenario,instructionId,sport,stake);
        if(name.equals("live_bet365"))return new Bet365LiveAdapter(session,sport);
        throw new SiteAdapter.Failure("INVALID_INSTRUCTION","Unknown adapter");
    }
}
