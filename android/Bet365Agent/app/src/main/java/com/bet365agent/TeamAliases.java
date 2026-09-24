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
 *  - "Berck Fliers Range" -> "Berck/Rang du Fliers": live alert on-a9f4768d (France Nationale 1,
 *    25.09.2026 18:00 UTC, v Pays Salonais Basket 13) vs Bet365 search "Berck/Rang du Fliers vs Pays
 *    Salonais Basket 13, Fri 25 Sep 19:00" (UK time = 18:00 UTC); same opponent, same kick-off; the club
 *    is Berck / Rang-du-Fliers (the feed's "Fliers Range" is its reordered name).
 *  - "Soproni KC" -> "Sopron KC" and "Debreceni EAC" -> "DEAC Debreceni": live alert on-baaa1c7f (Hungary NB
 *    I.A, 25.09.2026 17:00 UTC) whose own Bet365 link opened "Hungary NB 1.A - 25 Sep 18:00" (UK = 17:00 UTC),
 *    header "Sopron KC vs DEAC Debreceni" (evidence/live-soproni). Sopron is the city, Soproni its adjective;
 *    DEAC = Debreceni Egyetemi Atletikai Club.
 */
final class TeamAliases {
    private static final Map<String, String> CANONICAL;
    static {
        Map<String, String> m = new HashMap<>();
        m.put("shiga lake stars", "shiga lakes");
        m.put("shiga lakestars", "shiga lakes");
        m.put("berck fliers range", "berck/rang du fliers");
        m.put("soproni kc", "sopron kc");
        m.put("debreceni eac", "deac debreceni");
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
