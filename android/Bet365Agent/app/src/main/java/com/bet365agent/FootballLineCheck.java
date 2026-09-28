package com.bet365agent;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

/**
 * Football market discovery outcome when the requested line is not on the final frame (pure Java; FootballLineCheckTest).
 * Real case 27 Sep 2026 16:16Z (on-ee666445, Santa Cruz RJ v Cardoso Moreira): alert AWAY +0.5 with a 0.25 allowance,
 * the Asian Lines tab showed AWAY 0.0 @2.050, the last-resort scroll frame was empty, and the run reported
 * EVENT_NOT_VERIFIED "No live football market quotes parsed" instead of the genuine line refusal.
 */
final class FootballLineCheck {
    private FootballLineCheck() {}

    /** One read quote: {market, side, line, price}. */
    static String[] quote(String market, String side, String line, String price) { return new String[] {market, side, line, price}; }

    static boolean withinAllowance(String market, String side, String requested, String live, String allowance) {
        if ("MONEYLINE".equals(market) || requested == null || requested.isEmpty() || requested.equalsIgnoreCase("NONE")) return true;
        if (live != null && live.equals(requested)) return true;
        try { if (live != null && new BigDecimal(live).compareTo(new BigDecimal(requested)) == 0) return true; } catch (Exception ignored) { }
        return ExecutionTolerance.line(market, side, requested, live, allowance);
    }

    /** The configured tolerances applied to a FRESH football quote (the pre-selection re-read and the slip): null when
     *  acceptable (same or better line and price, or deterioration inside the original alert allowance and at or above
     *  the minimum price); otherwise {stage, detail} with the fresh terms. Real case 28 Sep 2026 06:31Z (on-f4d9aa2d,
     *  Jiangxi Lushan U20 HOME -0.25): discovery read 1.850, the pre-selection re-read 1.800 >= minimum 1.77, and the old
     *  exact-price comparison refused it as PRICE_CHANGED. The tolerance values themselves come from the instruction. */
    static String[] freshTerms(String market, String side, String requestedLine, String liveLine, String livePrice,
                               String allowance, String minimum) {
        if (!withinAllowance(market, side, requestedLine, liveLine, allowance))
            return new String[] {"LINE_CHANGED", "Fresh " + market + " " + side + " " + liveLine + " @ " + livePrice + "; alert line "
                    + requestedLine + " with allowance " + allowance + ": line deterioration exceeds the original alert allowance"};
        if (!ExecutionTolerance.price(livePrice, minimum))
            return new String[] {"BELOW_MINIMUM", "Fresh price " + livePrice + " (" + market + " " + side + " " + liveLine
                    + ") is below minimum " + minimum};
        return null;
    }

    /** Index of the fresh quote for a re-read: the same market/side at the same line if shown, else the first at a line
     *  inside the allowance; -1 when none (a moved line outside the allowance is never substituted). */
    static int pick(List<String[]> quotes, String market, String side, String currentLine, String requestedLine, String allowance) {
        int within = -1;
        for (int i = 0; i < quotes.size(); i++) {
            String[] q = quotes.get(i);
            if (!q[0].equals(market) || !q[1].equals(side)) continue;
            if ("MONEYLINE".equals(market) || sameLine(q[2], currentLine)) return i;
            if (within < 0 && withinAllowance(market, side, requestedLine, q[2], allowance)) within = i;
        }
        return within;
    }

    private static boolean sameLine(String a, String b) {
        if (a == null || b == null) return a == b;
        if (a.equals(b)) return true;
        try { return new BigDecimal(a).compareTo(new BigDecimal(b)) == 0; } catch (Exception e) { return false; }
    }

    /** Null when there is no line reason (target in range, or never read at all). Otherwise the LINE_CHANGED detail: the
     *  requested market/side was read, but only at lines outside the original alert allowance. */
    static String lineRefusal(List<String[]> seen, String market, String side, String requested, String allowance) {
        List<String> lines = new ArrayList<>();
        boolean any = false;
        for (String[] q : seen) {
            if (!q[0].equals(market) || !q[1].equals(side)) continue;
            any = true;
            if (withinAllowance(market, side, requested, q[2], allowance)) return null;
            String t = q[2] + " @ " + q[3];
            if (!lines.contains(t)) lines.add(t);
        }
        if (!any) return null;
        return "Bet365 " + market + " " + side + " shows " + String.join(", ", lines) + "; alert line " + requested + " with allowance "
                + allowance + ": line deterioration exceeds the original alert allowance";
    }
}
