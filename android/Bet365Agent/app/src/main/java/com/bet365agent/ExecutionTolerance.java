package com.bet365agent;

import java.math.BigDecimal;

/** Alert-to-live deterioration; improving either term consumes no tolerance - except the football Asian Handicap and
 *  Totals line, which must stay within the allowance of the alert line in BOTH directions (footballLine). */
final class ExecutionTolerance {
    static boolean price(String live, String minimum) {
        try {
            BigDecimal quote = new BigDecimal(live), floor = new BigDecimal(minimum);
            return floor.compareTo(BigDecimal.ONE) > 0 && quote.compareTo(floor) >= 0;
        } catch (Exception e) { return false; }
    }
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

    /** Football Asian Handicap and Totals (operator, 28 Sep 2026): the live line may differ from the alert line by at most
     *  `maximum` goals in EITHER direction. A line further away is another market price, not a move of this one: real case
     *  28 Sep 2026 Wenzhou Yincai v Qingdao Red Lions U20, alerts Over 4.25 / Over 4.5 - the Popular tab's main Over 2.5
     *  @1.20 counted as an "improvement", discovery stopped there and its price was judged against the 4.5 minimum. */
    static boolean footballLine(String market, String side, String requested, String live, String maximum) {
        try {
            BigDecimal limit = new BigDecimal(maximum);
            if (limit.signum() < 0) return false;
            boolean total = (market.equals("TOTAL") || market.equals("TOTALS")) && (side.equals("OVER") || side.equals("UNDER"));
            boolean spread = market.equals("SPREAD") && (side.equals("HOME") || side.equals("AWAY"));
            if (!total && !spread) return false;
            return new BigDecimal(requested).subtract(new BigDecimal(live)).abs().compareTo(limit) <= 0;
        } catch (Exception e) { return false; }
    }

    /** The line rule for the sport: football uses the two-sided band, every other sport (basketball) is unchanged. */
    static boolean lineForSport(String sport, String market, String side, String requested, String live, String maximum) {
        return "football".equals(sport) ? footballLine(market, side, requested, live, maximum) : line(market, side, requested, live, maximum);
    }
}
