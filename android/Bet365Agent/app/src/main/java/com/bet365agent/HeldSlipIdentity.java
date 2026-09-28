package com.bet365agent;

import java.util.Arrays;
import java.util.List;

/** Only a fixture inside the single slip, below its full-game market label, can authorize a tap. */
final class HeldSlipIdentity {
    static boolean matches(List<GameLinesParser.Word> lines, String home, String away, String market, int placeTop) {
        return matches(lines, home, away, market, placeTop, "basketball");
    }

    /** Football slips carry Bet365's football market names ("Full Time Result", "Asian Handicap", "Goal Line" /
     *  "Goals Over/Under"; real slips 27 Sep 2026). The page's own section heading can sit just above the slip (EGS Gafsa:
     *  "Goal Line" 190 px above Place Bet, the slip's label 101 px), so football labels are searched only inside the
     *  slip (160 px above Place Bet); basketball keeps its 230 px window and labels unchanged. */
    static boolean matches(List<GameLinesParser.Word> lines, String home, String away, String market, int placeTop, String sport) {
        boolean football = "football".equals(sport);
        List<String> labels = labels(market, football);
        int window = football ? 160 : 230;
        int marketY = -1, markets = 0, fixtures = 0;
        for (GameLinesParser.Word line : lines) {
            if (line.top < placeTop - window || line.bottom >= placeTop) continue;
            if (labels.contains(EventIdentity.plain(line.text))) { marketY = line.bottom; markets++; }
        }
        if (markets != 1) return false;
        for (GameLinesParser.Word line : lines) {
            if (line.top <= marketY || line.top > marketY + 90 || line.bottom >= placeTop) continue;
            String[] pair = EventPage.teams(java.util.Collections.singletonList(line.text));
            if (pair != null) {
                if (!sameSlipName(home, pair[0]) || !sameSlipName(away, pair[1])) return false;
                fixtures++;
            }
        }
        return fixtures == 1;
    }

    /** The slip's team name is the page's held name, read again by OCR. Equal after normalisation, or equal once the glyphs
     *  OCR swaps in this font are folded on BOTH sides (capital I / lower-case l / j / 1, and 0 / O): real case 28 Sep 2026
     *  (Brujos de Izalco BC v Santa Ana, on-d5a1b6dd): the held page name was "Brujos Izalco", the slip line read
     *  "Brujos lzalco vs Santa Ana", and the slip check refused the correct slip three times; 27 Sep 2026 Goianesia v
     *  Mineiros (on-ca9b37ac8): the pre-tap slip read "Gojanesia v Mineiros" and the run reported "line and price unreadable"
     *  instead of the real reason (the slip price had dropped to 1.775, below the 1.86 minimum). Only the character shapes are
     *  folded: token count, order and every other letter must still agree, so a different team is still refused. */
    static boolean sameSlipName(String held, String slip) {
        String a = EventIdentity.normalise(held), b = EventIdentity.normalise(slip);
        return a.equals(b) || (a.length() == b.length() && glyphs(a).equals(glyphs(b)));
    }

    private static String glyphs(String normalised) {
        StringBuilder sb = new StringBuilder(normalised.length());
        for (char c : normalised.toCharArray()) sb.append(c == 'l' || c == 'j' || c == '1' ? 'i' : c == '0' ? 'o' : c);
        return sb.toString();
    }

    /** Slip market labels (EventIdentity.plain form) for a wire market; 1X2 is the phone's three-way MONEYLINE. */
    static List<String> labels(String market, boolean football) {
        boolean spread = "SPREAD".equals(market), total = "TOTAL".equals(market) || "TOTALS".equals(market);
        if (!football) return Arrays.asList(spread ? "point spread" : total ? "game totals" : "money line");
        if (spread) return Arrays.asList("asian handicap", "alternative asian handicap");
        if (total) return Arrays.asList("goal line", "goals over/under", "alternative goal line", "alternative total goals");
        return Arrays.asList("full time result");
    }
}
