package com.bet365agent;

import java.util.*;
import java.util.regex.*;

/** Read terms only from the selection row immediately above the slip's full-game label. */
final class HeldSlipQuote {
    final String line, price;
    HeldSlipQuote(String line, String price) { this.line=line; this.price=price; }
    static HeldSlipQuote read(List<GameLinesParser.Word> lines, String name, String market, int placeTop) {
        String label = market.equals("SPREAD") ? "point spread" : market.equals("MONEYLINE") ? "money line" : "game totals";
        int y = -1;
        for (GameLinesParser.Word l : lines) if (l.top > placeTop-230 && l.bottom < placeTop && EventIdentity.plain(l.text).equals(label)) {
            if (y >= 0) return null;
            y = l.top;
        }
        if (y < 0) return null;
        String part = market.equals("MONEYLINE") ? "" : "([+-]?\\d+(?:\\.\\d+)?)\\s+";
        Pattern p = Pattern.compile("(?i)^(?:[x><×]+\\s*)?"+Pattern.quote(name)+"\\s+"+part+"(\\d+\\.\\d{2})$");
        HeldSlipQuote found = null;
        for (GameLinesParser.Word l : lines) if (l.top >= y-65 && l.bottom <= y+5) {
            Matcher m=p.matcher(OcrText.normalize(l.text).trim());
            if (m.matches()) {
                if (found != null) return null;
                found = new HeldSlipQuote(market.equals("MONEYLINE") ? "" : m.group(1), m.group(m.groupCount()));
            }
        }
        return found;
    }
}
