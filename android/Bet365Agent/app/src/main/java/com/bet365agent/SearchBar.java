package com.bet365agent;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * The open Bet365 search bar, identified by geometry rather than by the literal word "Search":
 * magnifier glyph at the far left and "Close" at the far right of one row near the top. Pure Java
 * (JVM tests: SearchBarTest, real frames from the Kyoto v Shiga live failure, 2026-09-24).
 *
 * Real failure: OCR merges the bar into one line ("Q Kyoto Hannaryz Shiga Lake Stars X Close"), so
 * the old line-level "x" match never found the clear icon, the field kept the previous query, and
 * text entry (which locates the field by its "Search" placeholder) failed.
 */
final class SearchBar {
    static final class Bar {
        final int[] field, clear, close;   // left, top, right, bottom; clear may be null
        final String text;                 // content between the magnifier and the clear icon / Close
        final boolean empty;               // only the placeholder ("Search bet365...") or nothing
        final int candidates;              // magnifier+Close rows found (must be exactly 1)
        Bar(int[] field, int[] clear, int[] close, String text, boolean empty, int candidates) {
            this.field = field; this.clear = clear; this.close = close; this.text = text; this.empty = empty; this.candidates = candidates;
        }
    }

    private SearchBar() {}

    /** The open search bar, or null if none, or if more than one row looks like one (never guess). */
    static Bar locate(List<GameLinesParser.Word> words) {
        List<GameLinesParser.Word[]> rows = new ArrayList<>();
        for (GameLinesParser.Word close : words) {
            if (!close.text.equalsIgnoreCase("Close") || close.top < 120 || close.top > 320 || close.left < 500) continue;
            for (GameLinesParser.Word mag : words)
                if (magnifier(mag.text) && mag.right < 95 && Math.abs(mag.cy() - close.cy()) <= 20) { rows.add(new GameLinesParser.Word[] {mag, close}); break; }
        }
        if (rows.size() != 1) return rows.isEmpty() ? null : new Bar(null, null, null, "", false, rows.size());
        GameLinesParser.Word mag = rows.get(0)[0], close = rows.get(0)[1];
        GameLinesParser.Word clear = null;
        List<GameLinesParser.Word> content = new ArrayList<>();
        for (GameLinesParser.Word w : words) {
            if (w == mag || w == close || Math.abs(w.cy() - close.cy()) > 20 || w.left <= mag.right || w.right >= close.left) continue;
            if (clearGlyph(w.text) && w.left > 420) { if (clear == null || w.left > clear.left) clear = w; continue; }
            // Icons at the right end are not field text: the voice icon OCRs as "Q," (2026-09-24) or as the
            // icon-sized token "HO" (2026-09-25, Norrkoping v Umea: "Search bet365... HO" refused an empty bar).
            // Typed text starts at the field's left edge, so an icon-sized token alone past x=540 is never a query.
            if (w.left > 540 && (w.text.replaceAll("[^A-Za-z0-9]", "").length() <= 1 || w.right - w.left <= 40)) continue;
            content.add(w);
        }
        content.sort((a, b) -> Integer.compare(a.left, b.left));
        StringBuilder text = new StringBuilder();
        boolean empty = true;
        for (GameLinesParser.Word w : content) {
            if (text.length() > 0) text.append(' ');
            text.append(w.text);
            String t = w.text.toLowerCase(Locale.US).replaceAll("[^a-z0-9]", "");
            if (!(t.equals("search") || t.startsWith("bet365"))) empty = false;
        }
        int right = clear != null ? clear.left - 8 : close.left - 70;
        int[] field = {mag.right + 8, close.top - 16, right, close.bottom + 16};
        int[] clearBox = clear == null ? null : new int[] {clear.left, clear.top, clear.right, clear.bottom};
        return new Bar(field, clearBox, new int[] {close.left, close.top, close.right, close.bottom}, text.toString(), empty, 1);
    }

    static boolean magnifier(String t) {
        String s = t == null ? "" : t.trim();
        return s.equals("Q") || s.equals("q") || s.equals("Q.") || s.equals("O") || s.equals("Q,");
    }

    static boolean clearGlyph(String t) {
        String s = t == null ? "" : t.trim();
        return s.equals("x") || s.equals("X") || s.equals("×") || s.equals("><") || s.equals("X|");
    }
}
