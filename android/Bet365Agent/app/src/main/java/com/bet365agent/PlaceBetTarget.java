package com.bet365agent;

import java.util.List;
import java.util.Locale;

/**
 * The Place Bet tap target, located from the actual "Place" and "Bet" WORD boxes on the betslip (pure Java; JVM test
 * PlaceBetTargetTest on the real 27 Sep 2026 frames).
 *
 * Root cause it replaces (UD Leiria v Sampaense, 27 Sep 2026 12:09Z): OCR merged "Stake ... Place Bet" into one line
 * (x 20-604); after a stake is typed the label reads "Stake", not "Set Stake", so the old rule used the whole merged line
 * and the gesture landed on its centre (x~312) - the stake field. The stake keypad opened and no bet was submitted.
 *
 * Rules: the lowest "Place" + "Bet" word pair on one row (the slip's button; the page never shows another), the box
 * padded for a finger but never overlapping a stake word ("Stake", "Set", an amount "£0.10"); null when the words are not
 * both read (the caller fails closed instead of guessing).
 */
final class PlaceBetTarget {
    private PlaceBetTarget() {}

    /** {left, top, right, bottom} of the tap box, or null. */
    static int[] locate(List<GameLinesParser.Word> words) {
        GameLinesParser.Word place = null, bet = null;
        for (GameLinesParser.Word p : words) {
            if (!clean(p.text).equals("place")) continue;
            for (GameLinesParser.Word b : words) {
                if (b == p || !clean(b.text).equals("bet")) continue;
                boolean sameRow = Math.abs(b.cy() - p.cy()) <= 14, rightOf = b.left >= p.right - 4 && b.left - p.right <= 40;
                if (!sameRow || !rightOf) continue;
                if (place == null || p.top > place.top) { place = p; bet = b; }
            }
        }
        if (place == null) return null;
        int left = place.left - 16, right = bet.right + 16, top = Math.min(place.top, bet.top) - 14, bottom = Math.max(place.bottom, bet.bottom) + 14;
        for (GameLinesParser.Word w : words) {
            if (w == place || w == bet || !stakeWord(w.text)) continue;
            boolean rowOverlap = w.bottom > top && w.top < bottom;
            if (!rowOverlap) continue;
            if (w.right <= place.left && w.right > left) left = w.right + 2;       // a stake word left of the button
            if (w.left >= bet.right && w.left < right) right = w.left - 2;         // (never expected) right of it
        }
        if (right - left < 20 || bottom - top < 10) return null;
        return new int[] {left, top, right, bottom};
    }

    /** The stake keypad is open (digit grid + "Remember Stake"/"Done"): Place Bet must not be tapped over it, and a tap
     *  that opens it did not press Place Bet. */
    static boolean keypadOpen(List<GameLinesParser.Word> words) {
        boolean remember = false, done = false;
        int digits = 0;
        for (GameLinesParser.Word w : words) {
            String t = clean(w.text);
            if (t.equals("remember")) remember = true;
            if (t.equals("done")) done = true;
            if (w.top > 800 && w.text.trim().matches("[0-9]")) digits++;
        }
        return (remember || done) && digits >= 5;
    }

    /** Bet365 shows a change notice on the slip ("The line and price of your selection changed") and relabels the
     *  button "Accept Change and Place Bet": tapping it would ACCEPT the new terms, so it is never a Place Bet target
     *  (27 Sep 2026 Pantery Lancut, -8.5 moved to -10.0). Any "Accept" word in the lower half (slip / banner) counts. */
    static boolean changeNotice(List<GameLinesParser.Word> words) {
        boolean selection = false, changed = false;
        for (GameLinesParser.Word w : words) {
            String t = clean(w.text);
            if (t.startsWith("accept") && w.top > 800) return true;
            if (t.equals("selection")) selection = true;
            if (t.equals("changed")) changed = true;
        }
        return selection && changed;
    }

    private static boolean stakeWord(String text) {
        String t = clean(text);
        return t.equals("stake") || t.equals("set") || text.trim().matches("[£€$]\\s?\\d+(?:[.,]\\d{1,2})?");
    }

    private static String clean(String s) { return s == null ? "" : s.trim().toLowerCase(Locale.US).replaceAll("[^a-z]", ""); }
}
