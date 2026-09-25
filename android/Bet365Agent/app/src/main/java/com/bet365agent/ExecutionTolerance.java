package com.bet365agent;

import java.math.BigDecimal;

/** Alert-to-live deterioration; improving either term consumes no tolerance. */
final class ExecutionTolerance {
    static boolean line(String market, String side, String requested, String live, String maximum) {
        try {
            BigDecimal limit = new BigDecimal(maximum);
            if (limit.signum() < 0) return false;
            BigDecimal loss = new BigDecimal(requested).subtract(new BigDecimal(live));
            if ((market.equals("TOTAL") || market.equals("TOTALS")) && side.equals("OVER")) loss = loss.negate();
            else if (!market.equals("SPREAD") && !side.equals("UNDER")) return false;
            return loss.max(BigDecimal.ZERO).compareTo(limit) <= 0;
        } catch (Exception e) { return false; }
    }
}
