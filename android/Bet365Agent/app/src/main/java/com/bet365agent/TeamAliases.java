package com.bet365agent;

import java.util.Collections;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;

/**
 * Explicit, team-specific canonical names: feed (Pinnacle/OddsHub) name -> Bet365 name. Exact
 * full-name matches only (after case/space normalisation); no fuzzy matching, no partial words.
 * Every entry needs evidence that both names are the same club.
 *
 *  - "Shiga Lake Stars" -> "Shiga Lakes": live alert on-03419b83 (B League, 25.09.2026 09:35 UTC)
 *    vs Bet365 search "Kyoto Hannaryz vs Shiga Lakes, Fri 25 Sep 10:35" (UK time = 09:35 UTC),
 *    same home team, Bet365's Kyoto team page lists only this fixture; the club rebranded
 *    from Shiga Lakestars to Shiga Lakes in 2023.
 */
final class TeamAliases {
    private static final Map<String, String> CANONICAL;
    static {
        Map<String, String> m = new HashMap<>();
        m.put("shiga lake stars", "shiga lakes");
        m.put("shiga lakestars", "shiga lakes");
        CANONICAL = Collections.unmodifiableMap(m);
    }

    private TeamAliases() {}

    /** Canonical lower-case identity for an already normalised (lower-case, single-spaced) name. */
    static String canonical(String normalised) {
        if (normalised == null) return "";
        String key = normalised.trim().toLowerCase(Locale.US).replaceAll("\\s+", " ");
        return CANONICAL.getOrDefault(key, key);
    }
}
