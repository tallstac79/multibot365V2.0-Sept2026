package com.bet365agent;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Basketball "Game Lines" grid (Spread | Total | Money Line, one row per team) from OCR words.
 * Pure Java (no Android types) so it is covered by JVM tests on real OCR (GameLinesParserTest).
 *
 * Real layout (Euroleague, 2026-09-24):
 *                     Spread      Total       Money Li...
 *   Hapoel Tel Aviv   -8.0        O 173.5     1.23
 *                     1.83        1.83
 *   Bayern Munich     +8.0        U 173.5     3.75
 *                     1.83        1.83
 * OCR drops signs ("8.0"), reads O as "0", splits prices ("1." ".23") and "1,83". Anything that
 * cannot be read unambiguously is left out, so the selection is "not found" instead of guessed:
 * a spread sign is only inferred from the opposite row's explicit sign with the same magnitude.
 */
final class GameLinesParser {
    static final class Word {
        final String text; final int left, top, right, bottom;
        Word(String text, int left, int top, int right, int bottom) {
            this.text = text == null ? "" : text.trim(); this.left = left; this.top = top; this.right = right; this.bottom = bottom;
        }
        int cx() { return (left + right) / 2; }
        int cy() { return (top + bottom) / 2; }
    }

    static final class Cell {
        final String market, side, line, price, name;
        final int[] bounds; // left, top, right, bottom of the whole cell (tap target)
        Cell(String market, String side, String line, String price, String name, int[] bounds) {
            this.market = market; this.side = side; this.line = line; this.price = price; this.name = name; this.bounds = bounds;
        }
        @Override public String toString() { return market + "/" + side + "/" + line + "@" + price; }
    }

    static final class Result {
        final List<Cell> cells = new ArrayList<>();
        final List<String> notes = new ArrayList<>();
        boolean grid;           // header + both team rows found
    }

    // Lines are always shown with one decimal (x.0 / x.5) and prices with two, so a dot that OCR turned
    // into a gap ("8 0", "173 5", "1 83") is restored only in exactly those shapes; "80" or "375" are rejected.
    private static final Pattern PRICE = Pattern.compile("^(\\d{1,3})[. ](\\d{2})$");
    private static final Pattern SPREAD = Pattern.compile("^([+-]?)\\s*(\\d{1,2})[. ]([05])$");
    private static final Pattern TOTAL = Pattern.compile("^([OoUu0])?\\s*(\\d{2,3})[. ]([05])$");

    private GameLinesParser() {}

    static Result parse(List<Word> rawWords, String home, String away) {
        Result r = new Result();
        // Drop OCR specks (e.g. "L." 3x3 px next to a price) that would corrupt a joined price.
        List<Word> words = new ArrayList<>();
        for (Word w : rawWords) if (w.bottom - w.top >= 8 && w.right - w.left >= 5 && !w.text.isEmpty()) words.add(w);
        Word spreadH = header(words, "spread"), totalH = header(words, "total"), moneyH = header(words, "money");
        if (spreadH == null || totalH == null || Math.abs(spreadH.cy() - totalH.cy()) > 25) { r.notes.add("no Spread/Total header"); return r; }
        int headerBottom = Math.max(spreadH.bottom, totalH.bottom);
        int spreadX = spreadH.cx(), totalX = totalH.cx();
        // The price sits right of the "Money Li..." label's first word.
        Integer moneyX = moneyH != null && Math.abs(moneyH.cy() - spreadH.cy()) <= 25 ? Math.max(moneyH.cx() + 20, totalX + 120) : null;
        int labelLimit = spreadX - 80;
        int[] homeRow = labelRow(words, home, labelLimit, headerBottom), awayRow = labelRow(words, away, labelLimit, headerBottom);
        if (homeRow == null || awayRow == null || awayRow[0] <= homeRow[0] || homeRow[0] == awayRow[0]) {
            r.notes.add("team rows not identified home=" + (homeRow != null) + " away=" + (awayRow != null)); return r;
        }
        int pitch = awayRow[0] - homeRow[0];
        if (pitch < 50 || pitch > 200) { r.notes.add("row pitch " + pitch); return r; }
        r.grid = true;
        int split = (homeRow[0] + awayRow[0]) / 2;
        int[][] bands = {{headerBottom + 2, split}, {split, awayRow[0] + pitch / 2}};
        String[] names = {home, away};
        String[][] spread = new String[2][], total = new String[2][];
        int[][] spreadBox = new int[2][], totalBox = new int[2][], moneyBox = new int[2][];
        String[] money = new String[2];
        for (int row = 0; row < 2; row++) {
            List<List<Word>> sp = groups(inColumn(words, spreadX, bands[row]));
            List<List<Word>> to = groups(inColumn(words, totalX, bands[row]));
            spread[row] = lineAndPrice(sp, SPREAD);
            total[row] = lineAndPrice(to, TOTAL);
            spreadBox[row] = box(sp); totalBox[row] = box(to);
            if (moneyX != null) {
                List<List<Word>> mo = groups(inColumn(words, moneyX, bands[row]));
                for (List<Word> g : mo) { String p = price(joined(g)); if (p != null) { money[row] = p; break; } }
                moneyBox[row] = box(mo);
            }
        }
        // Spread: magnitudes equal, signs opposite; one missing sign is taken from the other row only.
        if (spread[0] != null && spread[1] != null) {
            String a = repairMinus(spread[0][0], spread[1][0]), b = repairMinus(spread[1][0], spread[0][0]);
            String sa = sign(a), sb = sign(b);
            BigDecimal ma = new BigDecimal(a.replaceAll("^[+-]", "")), mb = new BigDecimal(b.replaceAll("^[+-]", ""));
            if (ma.compareTo(mb) != 0) r.notes.add("spread magnitudes differ " + a + " / " + b);
            else if (ma.signum() == 0) { add(r, "SPREAD", "HOME", "0", spread[0][1], names[0], spreadBox[0]); add(r, "SPREAD", "AWAY", "0", spread[1][1], names[1], spreadBox[1]); }
            else {
                if (sa.isEmpty() && !sb.isEmpty()) sa = sb.equals("+") ? "-" : "+";
                if (sb.isEmpty() && !sa.isEmpty()) sb = sa.equals("+") ? "-" : "+";
                if (sa.isEmpty() || sb.isEmpty()) r.notes.add("spread signs unreadable " + a + " / " + b);
                else if (sa.equals(sb)) r.notes.add("spread signs not opposite " + a + " / " + b);
                else {
                    add(r, "SPREAD", "HOME", sa + ma.toPlainString(), spread[0][1], names[0], spreadBox[0]);
                    add(r, "SPREAD", "AWAY", sb + mb.toPlainString(), spread[1][1], names[1], spreadBox[1]);
                }
            }
        } else r.notes.add("spread cell unreadable");
        // Totals: first row Over, second Under, same line. An explicit letter must agree.
        if (total[0] != null && total[1] != null) {
            String la = total[0][0], lb = total[1][0];
            String xa = total[0][2], xb = total[1][2];
            boolean lettersOk = (xa.isEmpty() || xa.equals("O")) && (xb.isEmpty() || xb.equals("U"));
            if (new BigDecimal(la).compareTo(new BigDecimal(lb)) != 0) r.notes.add("total lines differ " + la + " / " + lb);
            else if (!lettersOk) r.notes.add("total O/U letters unexpected " + xa + " / " + xb);
            else {
                add(r, "TOTAL", "OVER", la, total[0][1], "Over", totalBox[0]);
                add(r, "TOTAL", "UNDER", lb, total[1][1], "Under", totalBox[1]);
            }
        } else r.notes.add("total cell unreadable");
        for (int row = 0; row < 2; row++)
            if (money[row] != null) add(r, "MONEYLINE", row == 0 ? "HOME" : "AWAY", "NONE", money[row], names[row], moneyBox[row]);
        return r;
    }

    /**
     * Cells agreed by several OCR reads of the same grid. OCR varies frame to frame and can misread a digit
     * ("1 82" for 1.83), so a cell (market/side) is kept only if one line+price value was read at least
     * twice AND more often than any other value for that cell. Bounds come from the latest agreeing read.
     */
    static List<Cell> consensus(List<List<Cell>> reads) {
        java.util.LinkedHashMap<String, java.util.LinkedHashMap<String, Integer>> votes = new java.util.LinkedHashMap<>();
        java.util.HashMap<String, Cell> latest = new java.util.HashMap<>();
        for (List<Cell> read : reads) for (Cell c : read) {
            String key = c.market + "/" + c.side, value = c.line + "@" + c.price;
            votes.computeIfAbsent(key, k -> new java.util.LinkedHashMap<>()).merge(value, 1, Integer::sum);
            latest.put(key + "=" + value, c);
        }
        List<Cell> out = new ArrayList<>();
        for (java.util.Map.Entry<String, java.util.LinkedHashMap<String, Integer>> e : votes.entrySet()) {
            String best = null; int top = 0, second = 0;
            for (java.util.Map.Entry<String, Integer> v : e.getValue().entrySet()) {
                if (v.getValue() > top) { second = top; top = v.getValue(); best = v.getKey(); }
                else if (v.getValue() > second) second = v.getValue();
            }
            if (top >= 2 && top > second) out.add(latest.get(e.getKey() + "=" + best));
        }
        return out;
    }

    private static void add(Result r, String market, String side, String line, String price, String name, int[] box) {
        if (price == null || box == null) { r.notes.add(market + "/" + side + " price unreadable"); return; }
        r.cells.add(new Cell(market, side, line, price, name, box));
    }

    /** Real misread: "-2.5" OCR'd as "12.5" opposite "+2.5". Spread magnitudes are always equal, so a leading
     *  "1" is read as "-" only when the rest equals the other row's "+" magnitude. The betslip line check backs this. */
    static String repairMinus(String v, String other) {
        if (v.startsWith("1") && other.startsWith("+") && v.substring(1).equals(other.substring(1))) return "-" + v.substring(1);
        return v;
    }

    private static String sign(String v) { return v.startsWith("+") ? "+" : v.startsWith("-") ? "-" : ""; }

    /** [line, price, letter] from a cell's word groups: one group is the line, one the price. */
    private static String[] lineAndPrice(List<List<Word>> groups, Pattern linePattern) {
        String line = null, price = null, letter = "";
        for (List<Word> g : groups) {
            String text = joined(g);
            String p = price(text);
            if (p != null && price == null) { price = p; continue; }
            Matcher m = linePattern.matcher(tidy(text));
            if (m.matches() && line == null) {
                if (linePattern == TOTAL) {
                    String l = m.group(1) == null ? "" : m.group(1).toUpperCase(Locale.US);
                    letter = l.equals("0") ? "O" : l;
                    line = m.group(2) + "." + m.group(3);
                } else line = m.group(1) + m.group(2) + "." + m.group(3);
            }
        }
        return line == null || price == null ? null : new String[] {line, price, letter};
    }

    static String price(String text) {
        Matcher m = PRICE.matcher(tidy(text));
        return m.matches() ? m.group(1) + "." + m.group(2) : null;
    }

    /** "1. .23" / "1 .83" / "1,83" -> "1.23" / "1.83"; single spaces elsewhere are kept for the patterns. */
    static String tidy(String text) {
        return text.trim().replace(',', '.').replaceAll("\\s*\\.\\s*", ".").replaceAll("\\.{2,}", ".").replaceAll("\\s+", " ");
    }

    private static Word header(List<Word> words, String prefix) {
        for (Word w : words) if (w.text.toLowerCase(Locale.US).startsWith(prefix)) return w;
        return null;
    }

    /** [centerY] of the row whose left-column label words spell the team name, or null. */
    private static int[] labelRow(List<Word> words, String team, int labelLimit, int belowY) {
        if (team == null || team.trim().isEmpty()) return null;
        List<Word> labels = new ArrayList<>();
        for (Word w : words) if (w.right < labelLimit && w.top > belowY) labels.add(w);
        // Exact first; else the first label row that fuzzily spells the team. Real dim labels OCR in pieces:
        // "Cr )rvena Z» ZveZ( zdz la" for "Crvena Zvezda", "Zalg )iris" for "Zalgiris".
        for (List<Word> g : groups(labels)) if (norm(joined(g)).equals(norm(team))) return new int[] {g.get(0).cy()};
        for (List<Word> g : groups(labels)) if (fuzzyTeam(joined(g), team)) return new int[] {g.get(0).cy()};
        return null;
    }

    /** The team's letters appear in order in the OCR text (>= 85% of them) with limited extra noise. */
    static boolean fuzzyTeam(String ocr, String team) {
        String a = ocr.toLowerCase(Locale.US).replaceAll("[^a-z]", ""), t = team.toLowerCase(Locale.US).replaceAll("[^a-z]", "");
        if (t.length() < 4 || a.isEmpty() || a.length() > t.length() * 17 / 10 + 2) return false;
        return lcs(a, t) * 100 >= t.length() * 85;
    }

    private static int lcs(String a, String b) {
        int[][] d = new int[a.length() + 1][b.length() + 1];
        for (int i = 1; i <= a.length(); i++)
            for (int j = 1; j <= b.length(); j++)
                d[i][j] = a.charAt(i - 1) == b.charAt(j - 1) ? d[i - 1][j - 1] + 1 : Math.max(d[i - 1][j], d[i][j - 1]);
        return d[a.length()][b.length()];
    }

    private static String norm(String s) { return s.toLowerCase(Locale.US).replaceAll("[^a-z0-9]", ""); }

    private static List<Word> inColumn(List<Word> words, int cx, int[] band) {
        List<Word> out = new ArrayList<>();
        for (Word w : words) if (Math.abs(w.cx() - cx) <= 75 && w.cy() >= band[0] && w.cy() < band[1]) out.add(w);
        return out;
    }

    /** Words on the same visual line (centre within 8 px), left to right. */
    private static List<List<Word>> groups(List<Word> words) {
        List<Word> sorted = new ArrayList<>(words);
        sorted.sort(Comparator.comparingInt(Word::cy));
        List<List<Word>> out = new ArrayList<>();
        for (Word w : sorted) {
            List<Word> hit = null;
            for (List<Word> g : out) if (Math.abs(g.get(0).cy() - w.cy()) <= 8) { hit = g; break; }
            if (hit == null) { hit = new ArrayList<>(); out.add(hit); }
            hit.add(w);
        }
        for (List<Word> g : out) g.sort(Comparator.comparingInt(w -> w.left));
        return out;
    }

    private static String joined(List<Word> g) {
        StringBuilder b = new StringBuilder();
        for (Word w : g) { if (b.length() > 0) b.append(' '); b.append(w.text); }
        return b.toString();
    }

    private static int[] box(List<List<Word>> groups) {
        int[] b = null;
        for (List<Word> g : groups) for (Word w : g) {
            if (b == null) b = new int[] {w.left, w.top, w.right, w.bottom};
            else { b[0] = Math.min(b[0], w.left); b[1] = Math.min(b[1], w.top); b[2] = Math.max(b[2], w.right); b[3] = Math.max(b[3], w.bottom); }
        }
        return b;
    }
}
