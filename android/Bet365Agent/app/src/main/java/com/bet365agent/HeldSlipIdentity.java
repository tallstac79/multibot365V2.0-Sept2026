package com.bet365agent;

import java.util.List;

/** Only a fixture inside the single slip, below its full-game market label, can authorize a tap. */
final class HeldSlipIdentity {
    static boolean matches(List<GameLinesParser.Word> lines, String home, String away, String market, int placeTop) {
        String label = "SPREAD".equals(market) ? "point spread" :
                ("TOTAL".equals(market) || "TOTALS".equals(market)) ? "game totals" : "money line";
        int marketY = -1, markets = 0, fixtures = 0;
        for (GameLinesParser.Word line : lines) {
            if (line.top < placeTop - 230 || line.bottom >= placeTop) continue;
            if (EventIdentity.plain(line.text).equals(label)) { marketY = line.bottom; markets++; }
        }
        if (markets != 1) return false;
        for (GameLinesParser.Word line : lines) {
            if (line.top <= marketY || line.top > marketY + 90 || line.bottom >= placeTop) continue;
            String[] pair = EventPage.teams(java.util.Collections.singletonList(line.text));
            if (pair != null) {
                if (!EventIdentity.normalise(home).equals(EventIdentity.normalise(pair[0])) ||
                    !EventIdentity.normalise(away).equals(EventIdentity.normalise(pair[1]))) return false;
                fixtures++;
            }
        }
        return fixtures == 1;
    }
}
