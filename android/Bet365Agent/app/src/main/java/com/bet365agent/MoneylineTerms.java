package com.bet365agent;

import java.math.BigDecimal;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Moneyline has a named outcome and odds, never an implied zero handicap. */
final class MoneylineTerms {
    static boolean validSide(String sport, String side) {
        return "HOME".equals(side) || "AWAY".equals(side) || ("football".equals(sport) && "DRAW".equals(side));
    }
    static String receiptPrice(List<String> receiptLines, String selectionName) {
        if (selectionName == null || selectionName.isEmpty()) return null;
        Pattern row = Pattern.compile("(?i)^" + Pattern.quote(selectionName) + "\\s+(\\d+\\.\\d{2})$");
        String found = null;
        for (String text : receiptLines) {
            Matcher match = row.matcher(OcrText.normalize(text).trim());
            if (!match.matches()) continue;
            if (found != null || new BigDecimal(match.group(1)).compareTo(BigDecimal.ONE) <= 0) return null;
            found = match.group(1);
        }
        return found;
    }
}
