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
