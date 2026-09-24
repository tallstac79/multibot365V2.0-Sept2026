package com.bet365agent;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Betslip stake keypad and stake verification from OCR words. Pure Java (JVM tests: StakePadTest).
 *
 * Real failure (READY proof 2026-09-24): the keypad digits OCR'd as one line "1 2 3", the old code
 * fell back to guessed offsets from "Done" and typed "0.10" as 8-7-1-8 (stake £8,718). So:
 *  - key positions come only from OCR'd digit words and must fit a consistent 3 x 4 grid;
 *  - the stake is accepted only if BOTH the stake digits and the "To Return" digits agree with
 *    stake and stake x price. The stake box OCR is poor (£ read as "1"), so one leading stray
 *    character is tolerated on each reading, but a wrong stake cannot satisfy both at once.
 *  - After Done the slip collapses and OCR can drop the green stake amount entirely (real frame).
 *    Only then, the return alone is accepted: it must match EXACTLY and the price must be >= 1.10,
 *    so neighbouring stakes (0.09 / 0.11) give different returns at 2 dp. A stake that is read but
 *    wrong always fails.
 */
final class StakePad {
    static final char BACKSPACE = 'B';
    private static final String[] GRID = {"123", "456", "789", ".0B"};

    private StakePad() {}

    /** Key centres ('0'-'9', '.', 'B' backspace) or null if the keypad cannot be located without guessing. */
    static Map<Character, int[]> keypad(List<GameLinesParser.Word> words, int minTop) {
        Map<Integer, List<Integer>> colXs = new HashMap<>(), rowYs = new HashMap<>();
        List<int[]> seen = new ArrayList<>(); // col, row, cx, cy
        for (GameLinesParser.Word w : words) {
            if (w.top < minTop || w.text.length() != 1 || !Character.isDigit(w.text.charAt(0))) continue;
            if (w.bottom - w.top < 18) continue; // keypad digits are large; ignore small text
            int[] pos = gridPos(w.text.charAt(0));
            colXs.computeIfAbsent(pos[0], k -> new ArrayList<>()).add(w.cx());
            rowYs.computeIfAbsent(pos[1], k -> new ArrayList<>()).add(w.cy());
            seen.add(new int[] {pos[0], pos[1], w.cx(), w.cy()});
        }
        Integer[] cx = new Integer[3], cy = new Integer[4];
        for (int c = 0; c < 3; c++) cx[c] = mean(colXs.get(c));
        for (int r = 0; r < 4; r++) cy[r] = mean(rowYs.get(r));
        if (!fill(cx) || !fill(cy)) return null;
        for (int c = 1; c < 3; c++) { int d = cx[c] - cx[c - 1]; if (d < 150 || d > 320) return null; }
        for (int r = 1; r < 4; r++) { int d = cy[r] - cy[r - 1]; if (d < 60 || d > 130) return null; }
        if (Math.abs((cx[1] - cx[0]) - (cx[2] - cx[1])) > 30) return null;
        for (int[] s : seen) if (Math.abs(s[2] - cx[s[0]]) > 40 || Math.abs(s[3] - cy[s[1]]) > 25) return null;
        Map<Character, int[]> keys = new HashMap<>();
        for (int r = 0; r < 4; r++) for (int c = 0; c < 3; c++) keys.put(GRID[r].charAt(c), new int[] {cx[c], cy[r]});
        return keys;
    }

    private static int[] gridPos(char digit) {
        for (int r = 0; r < 4; r++) { int c = GRID[r].indexOf(digit); if (c >= 0) return new int[] {c, r}; }
        throw new IllegalArgumentException(String.valueOf(digit));
    }

    private static Integer mean(List<Integer> values) {
        if (values == null || values.isEmpty()) return null;
        long sum = 0; for (int v : values) sum += v; return (int) (sum / values.size());
    }

    /** Fill at most one missing entry by equal spacing from its neighbours. False if not possible. */
    private static boolean fill(Integer[] a) {
        int missing = 0; for (Integer v : a) if (v == null) missing++;
        if (missing == 0) return true;
        if (missing > 1) return false;
        for (int i = 0; i < a.length; i++) {
            if (a[i] != null) continue;
            if (i >= 2) a[i] = a[i - 1] + (a[i - 1] - a[i - 2]);
            else if (i + 2 < a.length) a[i] = a[i + 1] - (a[i + 2] - a[i + 1]);
            else if (i == 1 && a.length == 3) a[i] = (a[0] + a[2]) / 2;
            else return false;
        }
        return true;
    }

    static final class Check {
        final boolean ok; final String detail, stakeDigits, returnDigits;
        Check(boolean ok, String detail, String stakeDigits, String returnDigits) {
            this.ok = ok; this.detail = detail; this.stakeDigits = stakeDigits; this.returnDigits = returnDigits;
        }
    }

    /** Stake box (left of Place Bet) and "To Return" (inside Place Bet) must both agree with stake / price. */
    static Check check(List<GameLinesParser.Word> words, String stake, String price) {
        GameLinesParser.Word place = null, bet = null;
        for (GameLinesParser.Word w : words) if (w.text.equalsIgnoreCase("Place")) {
            for (GameLinesParser.Word b : words)
                if (b.text.equalsIgnoreCase("Bet") && Math.abs(b.cy() - w.cy()) <= 10 && b.left > w.right && b.left - w.right < 40) { place = w; bet = b; }
            if (place != null) break;
        }
        if (place == null) return new Check(false, "Place Bet button not read", null, null);
        int top = place.top - 40, bottom = place.bottom + 60, split = place.left - 30;
        StringBuilder stakeText = new StringBuilder(), returnText = new StringBuilder();
        GameLinesParser.Word returnWord = null;
        for (GameLinesParser.Word w : words)
            if (isReturnWord(w.text) && w.cy() > place.cy() && w.cy() < bottom && w.left > split - 60) returnWord = w;
        for (GameLinesParser.Word w : sortedByLeft(words)) {
            if (w.cy() < top || w.cy() > bottom) continue;
            if (w.right < Math.min(split, 360) && !w.text.equalsIgnoreCase("Stake")) stakeText.append(w.text);
            if (returnWord != null && w.left > returnWord.right && Math.abs(w.cy() - returnWord.cy()) <= 10) returnText.append(w.text);
        }
        String sd = digits(stakeText.toString()), rd = digits(returnText.toString());
        String wantStake = digits(new BigDecimal(stake).setScale(2, RoundingMode.UNNECESSARY).toPlainString());
        boolean stakeUnread = sd.isEmpty();
        if (!stakeUnread && !agrees(sd, wantStake)) return new Check(false, "Stake box reads '" + stakeText + "' not " + stake, sd, rd);
        if (returnWord == null || rd.isEmpty()) return new Check(false, "To Return not read", sd, rd);
        BigDecimal raw = new BigDecimal(stake).multiply(new BigDecimal(price));
        String down = digits(raw.setScale(2, RoundingMode.DOWN).toPlainString());
        String half = digits(raw.setScale(2, RoundingMode.HALF_UP).toPlainString());
        rd = dotReadAsOne(rd, down, half);
        if (stakeUnread) {
            if (new BigDecimal(price).compareTo(new BigDecimal("1.10")) < 0)
                return new Check(false, "Stake box unread and price below 1.10: return alone is not conclusive", sd, rd);
            if (!rd.equals(down) && !rd.equals(half))
                return new Check(false, "Stake box unread; To Return reads '" + returnText + "' not exactly " + stake + " x " + price, sd, rd);
            return new Check(true, "stake box unread; To Return exactly " + stake + " x " + price, sd, rd);
        }
        if (!agrees(rd, down) && !agrees(rd, half))
            return new Check(false, "To Return reads '" + returnText + "' not " + stake + " x " + price, sd, rd);
        return new Check(true, "stake " + stake + " and return agree", sd, rd);
    }

    /**
     * Real slips (Besancon, Berck): "£0.18" OCR'd as "£0118", the decimal point read as "1". Only for amounts
     * under £1 ("0" integer part) and only at the exact decimal position: "0" + "1" + the two decimals. A
     * real Bet365 amount is never shown as "01.18", so this cannot turn a different amount into the expected one.
     */
    static String dotReadAsOne(String ocr, String... wants) {
        for (String want : wants)
            if (want.startsWith("0") && want.length() == 3 && ocr.equals("0" + "1" + want.substring(1))) return want;
        return ocr;
    }

    /** OCR digits equal the expected digits, or have exactly one stray leading character (a misread £). */
    static boolean agrees(String ocr, String want) {
        return ocr.equals(want) || (ocr.length() == want.length() + 1 && ocr.endsWith(want));
    }

    /** "Return", also as OCR'd on the real slip: "Re‘urn". */
    static boolean isReturnWord(String text) {
        String t = text.toLowerCase(java.util.Locale.US).replaceAll("[^a-z]", "");
        return t.equals("return") || (t.length() >= 5 && t.length() <= 6 && t.startsWith("re") && t.endsWith("urn"));
    }

    private static String digits(String s) { return s.replaceAll("[^0-9]", ""); }

    private static List<GameLinesParser.Word> sortedByLeft(List<GameLinesParser.Word> words) {
        List<GameLinesParser.Word> out = new ArrayList<>(words);
        out.sort((a, b) -> Integer.compare(a.left, b.left));
        return out;
    }
}
