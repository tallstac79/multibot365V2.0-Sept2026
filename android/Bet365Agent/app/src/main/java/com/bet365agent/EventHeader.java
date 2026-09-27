package com.bet365agent;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;

/**
 * Event-page header lines from raw OCR words (pure Java, the exact grouping VisualScreen applies on the phone), so the
 * direct-link identity decision can be replayed on stored captures through the same code (EventIdentityV2ReplayTest).
 * A word joins the first line whose vertical centre is within max(8, min(line height, word height) / 2) of its own; lines
 * are ordered by top; the header is every line with top in [120, 480] that is not the bet365 logo/balance row.
 */
final class EventHeader {
    private EventHeader() {}

    private static final class Line {
        int left = Integer.MAX_VALUE, top = Integer.MAX_VALUE, right = Integer.MIN_VALUE, bottom = Integer.MIN_VALUE;
        final List<GameLinesParser.Word> words = new ArrayList<>();
        boolean empty() { return words.isEmpty(); }
        int centerY() { return (top + bottom) / 2; }
        int height() { return bottom - top; }
        void add(GameLinesParser.Word w) {
            words.add(w);
            left = Math.min(left, w.left); top = Math.min(top, w.top); right = Math.max(right, w.right); bottom = Math.max(bottom, w.bottom);
        }
        String text() {
            List<GameLinesParser.Word> sorted = new ArrayList<>(words);
            sorted.sort(Comparator.comparingInt(w -> w.left));
            StringBuilder b = new StringBuilder();
            for (GameLinesParser.Word w : sorted) { if (b.length() > 0) b.append(' '); b.append(w.text); }
            return b.toString();
        }
    }

    /** All OCR lines, top to bottom, as {text, top} pairs (text only here; top is used for the header window). */
    static List<String[]> lines(List<GameLinesParser.Word> raw) {
        List<GameLinesParser.Word> words = new ArrayList<>();
        for (GameLinesParser.Word w : raw) {
            String t = OcrText.normalize(w.text);
            if (t != null && !t.isEmpty()) words.add(new GameLinesParser.Word(t, w.left, w.top, w.right, w.bottom));
        }
        words.sort(Comparator.comparingInt(GameLinesParser.Word::cy));
        List<Line> lines = new ArrayList<>();
        for (GameLinesParser.Word w : words) {
            Line chosen = null;
            int h = w.bottom - w.top;
            for (Line line : lines) if (Math.abs(line.centerY() - w.cy()) <= Math.max(8, Math.min(line.height(), h) / 2)) { chosen = line; break; }
            if (chosen == null) { chosen = new Line(); lines.add(chosen); }
            chosen.add(w);
        }
        lines.sort(Comparator.comparingInt(l -> l.top));
        List<String[]> out = new ArrayList<>();
        for (Line l : lines) out.add(new String[] {l.text(), Integer.toString(l.top)});
        return out;
    }

    /** The event header: lines with top in [120, 480] that are not the bet365 logo/balance row. */
    static List<String> header(List<GameLinesParser.Word> raw) {
        List<String> out = new ArrayList<>();
        for (String[] line : lines(raw)) {
            int top = Integer.parseInt(line[1]);
            if (top >= 120 && top <= 480 && !line[0].toLowerCase(Locale.US).contains("bet365")) out.add(line[0]);
        }
        return out;
    }
}
