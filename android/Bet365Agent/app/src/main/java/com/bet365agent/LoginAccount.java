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
