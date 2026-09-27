package com.bet365agent;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.*;
import java.util.regex.*;

/** Read terms only from the selection row immediately above the slip's full-game label. */
final class HeldSlipQuote {
    final String line, price;
    HeldSlipQuote(String line, String price) { this.line=line; this.price=price; }

    static HeldSlipQuote read(List<GameLinesParser.Word> lines, String name, String market, int placeTop) {
        return read(lines, name, market, placeTop, "basketball");
    }

    /** Football rows (real slips 27 Sep 2026): "X HauPa 0.0,+0.5 1.850", "X Over 2.0,2.5 1.900", "X HauPa 2.50". A quarter
     *  line is Bet365's split pair and is returned as its decimal (the held selection's spelling: 0.0,+0.5 -> 0.25,
     *  2.0,2.5 -> 2.25); prices may carry three decimals. Basketball is unchanged. */
    static HeldSlipQuote read(List<GameLinesParser.Word> lines, String name, String market, int placeTop, String sport) {
        boolean football = "football".equals(sport), moneyline = market.equals("MONEYLINE") || market.equals("1X2");
        List<String> labels = HeldSlipIdentity.labels(moneyline ? "MONEYLINE" : market, football);
        int window = football ? 160 : 230;
        int y = -1;
        for (GameLinesParser.Word l : lines) if (l.top > placeTop-window && l.bottom < placeTop && labels.contains(EventIdentity.plain(l.text))) {
            if (y >= 0) return null;
            y = l.top;
        }
        if (y < 0) return null;
        String number = "[+-]?\\d+(?:\\.\\d+)?";
        String part = moneyline ? "" : football ? "(" + number + "(?:,\\s?" + number + ")?)\\s+" : "(" + number + ")\\s+";
        String priceRe = football ? "(\\d+\\.\\d{2,3})" : "(\\d+\\.\\d{2})";
        Pattern p = Pattern.compile("(?i)^(?:[x><×]+\\s*)?"+Pattern.quote(name)+"\\s+"+part+priceRe+"$");
        HeldSlipQuote found = null;
        for (GameLinesParser.Word l : lines) if (l.top >= y-65 && l.bottom <= y+5) {
            Matcher m=p.matcher(OcrText.normalize(l.text).trim());
            if (m.matches()) {
                if (found != null) return null;
                String line = moneyline ? "" : m.group(1);
                if (football && line.contains(",")) line = quarter(line);
                if (line == null) return null;
                found = new HeldSlipQuote(line, m.group(m.groupCount()));
            }
        }
        return found;
    }

    /** "0.0,+0.5" -> "0.25", "-1.5,-2.0" -> "-1.75", "2.0,2.5" -> "2.25"; null unless the halves are 0.5 apart. */
    static String quarter(String pair) {
        String[] parts = pair.split(",\\s?");
        if (parts.length != 2) return null;
        try {
            BigDecimal a = new BigDecimal(parts[0]), b = new BigDecimal(parts[1]);
            if (a.subtract(b).abs().compareTo(new BigDecimal("0.5")) != 0) return null;
            return a.add(b).divide(new BigDecimal(2), 2, RoundingMode.UNNECESSARY).stripTrailingZeros().toPlainString();
        } catch (ArithmeticException | NumberFormatException e) { return null; }
    }
}
