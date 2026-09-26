package com.bet365agent;

import java.util.List;
import java.util.Locale;

/** Exact same-account recognition. Never infer an account from an email-shaped token. */
final class LoginAccount {
    enum State { EMPTY, MATCH, DIFFERENT, UNKNOWN }
    static GameLinesParser.Word clearControl(List<GameLinesParser.Word> words) {
        GameLinesParser.Word found = null;
        for (GameLinesParser.Word w : words) {
            if (w.top <= 250 || w.top >= 400 || w.left < 550 || w.right > 640
                    || !(w.text.equalsIgnoreCase("x") || w.text.equals("×"))) continue;
            // Hybrid OCR can report the same control twice, one pixel apart.
            if (found != null && (Math.abs(found.left-w.left)>5 || Math.abs(found.top-w.top)>5)) return null;
            found = w;
        }
        return found;
    }
    /** The clear control by geometry when OCR did not read the "X" glyph (real: 2026-09-26 19:02 after a reboot, the
     *  icon was on screen at x 575-600 but no word came back): the icon sits at the right end of the remembered
     *  value's own row. Null unless that row holds a non-placeholder value. A miss taps inside the field, and the
     *  caller still requires the empty placeholder before typing anything. */
    static GameLinesParser.Word clearControlByGeometry(List<GameLinesParser.Word> words) {
        GameLinesParser.Word first = null, last = null;
        for (GameLinesParser.Word w : words) {
            if (w.top <= 250 || w.top >= 400 || w.left < 70 || w.left > 570) continue;
            if (w.text.equalsIgnoreCase("x") || w.text.equals("×")) continue;
            if (first == null) first = w;
            last = w;
        }
        if (first == null) return null;
        String lower = joinRow(words).toLowerCase(Locale.US);
        if (lower.isEmpty() || lower.equals("username or email address") || lower.equals("username or email") || lower.equals("username") || lower.equals("email")) return null;
        return new GameLinesParser.Word("×", 566, Math.min(first.top, last.top) - 4, 610, Math.max(first.bottom, last.bottom) + 4);
    }
    private static String joinRow(List<GameLinesParser.Word> words) {
        StringBuilder value = new StringBuilder();
        for (GameLinesParser.Word w : words) {
            if (w.top <= 250 || w.top >= 400 || w.left < 70 || w.left > 570) continue;
            String t = w.text.trim();
            if (t.equalsIgnoreCase("x") || t.equals("×")) continue;
            if (value.length() > 0) value.append(' ');
            value.append(t);
        }
        return value.toString().trim();
    }
    static State inspect(List<GameLinesParser.Word> words, String expected) {
        if (expected == null || expected.trim().isEmpty()) return State.UNKNOWN;
        StringBuilder value = new StringBuilder();
        boolean clear = false;
        for (GameLinesParser.Word w : words) {
            if (w.top <= 250 || w.top >= 400) continue;
            String t = w.text.trim();
            if (t.equalsIgnoreCase("x") || t.equals("×")) { clear = true; continue; }
            if (w.left < 70 || w.left > 570) continue;
            if (value.length() > 0) value.append(' ');
            value.append(t);
        }
        String text = value.toString().trim();
        String lower = text.toLowerCase(Locale.US);
        if (lower.equals("username or email address") || lower.equals("username or email") || lower.equals("username") || lower.equals("email")) return State.EMPTY;
        if (text.equalsIgnoreCase(expected.trim())) return State.MATCH;
        return clear && !text.isEmpty() ? State.DIFFERENT : State.UNKNOWN;
    }
}
