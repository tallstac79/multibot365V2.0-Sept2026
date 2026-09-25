package com.bet365agent;

import java.text.Normalizer;

/** OCR text normalisation (pure; JVM tests: OcrTextTest). */
final class OcrText {
    private OcrText() {}

    /**
     * Unicode NFKC: ligatures and compatibility forms to plain letters. Real (live alert on-e5072bbf,
     * 2026-09-24): Tesseract returned "Dragonﬂies" (the "fl" ligature) for "Dragonflies", so the
     * team never matched "Hiroshima Dragonflies" on the event header or in search results.
     */
    static String normalize(String s) {
        return s == null ? null : Normalizer.normalize(s, Normalizer.Form.NFKC);
    }

    /**
     * An OCR word matches a placeholder hint. A hint ending in "..." (Bet365's "Search bet365...") matches the
     * same word with any run of trailing dots or an ellipsis: real search frame 2026-09-25 01:09 read the
     * placeholder as "bet365." (the caret over the dots) and the exact match found no field. The word itself
     * must still be identical, so "bet365.com/#/AX/" (Chrome's URL bar) never matches.
     */
    static boolean placeholderMatches(String word, String hint) {
        if (word == null || hint == null) return false;
        if (word.equals(hint)) return true;
        if (!hint.endsWith("...")) return false;
        String stem = hint.substring(0, hint.length() - 3);
        String w = normalize(word);
        return w.length() > stem.length() && w.startsWith(stem) && w.substring(stem.length()).matches("[.…]+");
    }
}
