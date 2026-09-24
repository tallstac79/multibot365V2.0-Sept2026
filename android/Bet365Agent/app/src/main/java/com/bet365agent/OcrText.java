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
}
