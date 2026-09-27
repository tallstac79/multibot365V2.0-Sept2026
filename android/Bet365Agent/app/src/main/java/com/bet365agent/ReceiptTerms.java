package com.bet365agent;

import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Line and odds printed on a Bet365 receipt for a spread/total selection (pure Java; ReceiptTermsTest). Receipts use the
 * slip's spelling: "KB Prishtina +5.5 1.83", "Under 166.5 1.83", and for football quarter lines the split pair with a
 * three-decimal price, "Auto Esporte 0.0,-0.5 1.900" (27 Sep 2026 CT4705359181W, whose actual terms were left empty).
 * A split pair is returned as its decimal line (-0.25), the spelling the rest of the pipeline uses.
 */
final class ReceiptTerms {
    private ReceiptTerms() {}

    /** {line, odds} from the first receipt row "<name> <line> <odds>", or null. */
    static String[] parse(List<String> receiptLines, String name) {
        if (name == null || name.isEmpty() || receiptLines == null) return null;
        String number = "[+-]?\\d+(?:\\.\\d+)?";
        Pattern term = Pattern.compile("(?i)^(?:[x><×•]+\\s*)?" + Pattern.quote(name) + "\\s+(" + number + "(?:,\\s?" + number + ")?)\\s+(\\d+\\.\\d{2,3})$");
        for (String receiptLine : receiptLines) {
            Matcher m = term.matcher(OcrText.normalize(receiptLine).trim());
            if (!m.matches()) continue;
            String line = m.group(1).contains(",") ? HeldSlipQuote.quarter(m.group(1)) : m.group(1);
            if (line == null) continue;
            return new String[] {line, m.group(2)};
        }
        return null;
    }
}
