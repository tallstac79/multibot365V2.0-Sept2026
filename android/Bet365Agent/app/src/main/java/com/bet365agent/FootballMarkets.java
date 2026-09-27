package com.bet365agent;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Locale;
import java.util.regex.Pattern;

/**
 * Bet365 mobile FOOTBALL event page markets from OCR words. Pure Java (JVM tests FootballMarketsTest on real OCR
 * captured 27 Sep 2026, evidence/football/captures and evidence/football/pages).
 *
 * Popular tab:
 *   Full Time Result        home team | Draw | away team   (labels above three price boxes, left to right)
 *   Goals Over/Under        header "Over" "Under"; rows "2.5  1.36  3.00" (line, Over price, Under price)
 * Asian Lines tab:
 *   Asian Handicap          header home team | away team; rows "+0.5 1.850   -0.5 1.950" (line+price under each team)
 *   Goal Line               header "Over" "Under"; rows "2.5  2.025  1.775" (quarter lines shown as "2.5,3.0" = 2.75)
 * Goals tab: Goals Over/Under with every line. Anything not read unambiguously is left out (fail closed).
 *
 * Cells use the same market names as the live adapter: MONEYLINE (HOME/DRAW/AWAY, line NONE), SPREAD (HOME/AWAY,
 * signed line from that team's perspective), TOTAL (OVER/UNDER). Prices are kept as displayed (1.36 / 1.850 / 2.025).
 */
final class FootballMarkets {
    static final class Cell {
        final String market, side, line, price, name;
        final int[] bounds;
        Cell(String market, String side, String line, String price, String name, int[] bounds) {
            this.market = market; this.side = side; this.line = line; this.price = price; this.name = name; this.bounds = bounds;
        }
        @Override public String toString() { return market + "/" + side + "/" + line + "@" + price + (name == null ? "" : " (" + name + ")"); }
    }

    static final class Result {
        final List<Cell> cells = new ArrayList<>();
        final List<String> notes = new ArrayList<>();
        boolean fullTimeResult, goalsOverUnder, asianHandicap, goalLine;
    }

    private static final class Row {
        final int cy; final List<GameLinesParser.Word> words = new ArrayList<>();
        Row(int cy) { this.cy = cy; }
        String text() { StringBuilder b = new StringBuilder(); for (GameLinesParser.Word w : words) b.append(w.text).append(' '); return b.toString().trim().toLowerCase(Locale.US); }
    }

    private static final Pattern PRICE = Pattern.compile("^\\d{1,2}[.,]\\d{2,3}$");
    private static final Pattern LINE = Pattern.compile("^[+-]?\\d{1,2}(?:[.,]\\d{1,2})?$");
    private static final Pattern QUARTER = Pattern.compile("^([+-]?\\d{1,2}(?:[.,]\\d)?),([+-]?\\d{1,2}(?:[.,]\\d)?)$");
    /** Rows that end a market section (the next heading). */
    private static final String[] HEADINGS = {"full time result", "double chance", "goals over/under", "correct score", "asian handicap",
            "goal line", "half time", "1st half", "2nd half", "draw no bet", "both teams to score", "others on request", "result &",
            "team goals", "alternative", "handicap result", "exact goals", "winning margin", "bet builder", "to qualify", "to win"};

    private FootballMarkets() {}

    static Result parse(List<GameLinesParser.Word> rawWords, String home, String away) {
        Result r = new Result();
        List<Row> rows = rows(rawWords);
        for (int i = 0; i < rows.size(); i++) {
            String t = rows.get(i).text();
            if (t.startsWith("1st") || t.startsWith("2nd") || t.contains("half")) continue;
            if (t.contains("full time result")) { r.fullTimeResult = true; ftr(rows, i, home, away, r); }
            else if (t.contains("goals over/under") || t.contains("goals over") || t.contains("over/under")) { r.goalsOverUnder = true; overUnder(rows, i, r, "goals_over_under"); }
            else if (t.contains("asian handicap")) { r.asianHandicap = true; asianHandicap(rows, i, home, away, r); }
            else if (t.contains("goal line")) { r.goalLine = true; overUnder(rows, i, r, "goal_line"); }
        }
        return r;
    }

    /** The market tab whose label starts with `prefix` ("asia", "goals", "popular") on the tab strip (the row holding "Popular"), or null. */
    static GameLinesParser.Word tab(List<GameLinesParser.Word> rawWords, String prefix) {
        Row strip = tabStrip(rawWords);
        if (strip == null) return null;
        for (GameLinesParser.Word w : strip.words) if (w.text.toLowerCase(Locale.US).startsWith(prefix)) return w;
        return null;
    }

    /** {cy, left, right} of the tab strip, or null. */
    static int[] tabStrip(List<GameLinesParser.Word> rawWords, boolean unused) {
        Row strip = tabStrip(rawWords);
        if (strip == null) return null;
        int left = Integer.MAX_VALUE, right = 0;
        for (GameLinesParser.Word w : strip.words) { left = Math.min(left, w.left); right = Math.max(right, w.right); }
        return new int[] {strip.cy, left, right};
    }

    private static final String[] TAB_WORDS = {"popular", "bet", "builder", "result", "goals", "half", "asian", "asiat", "asial", "lines",
            "corners", "cards", "players", "specials", "player", "team"};

    /** The market tab strip: a row above the first market heading holding at least two known tab labels (it scrolls
     *  horizontally, so "Popular" itself may be off-screen after a swipe). */
    private static Row tabStrip(List<GameLinesParser.Word> rawWords) {
        for (Row row : rows(rawWords)) {
            if (row.cy > 760) break;
            int hits = 0;
            for (GameLinesParser.Word w : row.words) {
                String t = w.text.toLowerCase(Locale.US);
                for (String tab : TAB_WORDS) if (t.startsWith(tab)) { hits++; break; }
            }
            if (hits >= 2 && !row.text().contains("time result") && !row.text().contains("over/under")) return row;
        }
        return null;
    }

    // ------------------------------------------------------------------ sections
    private static void ftr(List<Row> rows, int h, String home, String away, Result r) {
        int end = sectionEnd(rows, h);
        Row prices = null;
        for (int i = h + 1; i < end; i++) {
            List<GameLinesParser.Word> p = priceWords(rows.get(i));
            if (p.size() == 3) { prices = rows.get(i); break; }
        }
        if (prices == null) { r.notes.add("full time result: no row with three prices"); return; }
        List<GameLinesParser.Word> p = priceWords(prices);
        p.sort((a, b) -> Integer.compare(a.cx(), b.cx()));
        // Labels sit between the heading and the price row; each label word belongs to the nearest price column.
        StringBuilder[] labels = {new StringBuilder(), new StringBuilder(), new StringBuilder()};
        for (int i = h + 1; i < end && rows.get(i) != prices; i++) {
            for (GameLinesParser.Word w : rows.get(i).words) {
                int col = nearest(p, w.cx());
                if (col >= 0 && Math.abs(p.get(col).cx() - w.cx()) <= 170) labels[col].append(w.text).append(' ');
            }
        }
        String drawLabel = labels[1].toString().trim().toLowerCase(Locale.US);
        boolean draw = drawLabel.equals("draw") || drawLabel.equals("x") || drawLabel.startsWith("draw ");
        boolean homeOk = home == null || teamMatch(home, labels[0].toString()), awayOk = away == null || teamMatch(away, labels[2].toString());
        if (!draw || !homeOk || !awayOk) {
            r.notes.add("full time result: columns not verified (labels '" + labels[0].toString().trim() + "' | '" + labels[1].toString().trim() + "' | '" + labels[2].toString().trim() + "')");
            return;
        }
        r.cells.add(new Cell("MONEYLINE", "HOME", "NONE", price(p.get(0).text), home != null ? home : labels[0].toString().trim(), bounds(p.get(0))));
        r.cells.add(new Cell("MONEYLINE", "DRAW", "NONE", price(p.get(1).text), "Draw", bounds(p.get(1))));
        r.cells.add(new Cell("MONEYLINE", "AWAY", "NONE", price(p.get(2).text), away != null ? away : labels[2].toString().trim(), bounds(p.get(2))));
    }

    private static void overUnder(List<Row> rows, int h, Result r, String what) {
        int end = sectionEnd(rows, h);
        GameLinesParser.Word over = null, under = null;
        int headerIndex = -1;
        for (int i = h + 1; i < end; i++) {
            for (GameLinesParser.Word w : rows.get(i).words) {
                String t = w.text.toLowerCase(Locale.US);
                if (t.equals("over")) over = w;
                if (t.equals("under")) under = w;
            }
            if (over != null && under != null) { headerIndex = i; break; }
        }
        if (over == null || under == null || over.cx() >= under.cx()) { r.notes.add(what + ": no Over/Under header"); return; }
        for (int i = headerIndex + 1; i < end; i++) {
            Row row = rows.get(i);
            String line = lineToken(row, over.cx() - 60);
            List<GameLinesParser.Word> prices = priceWords(row);
            if (line == null || prices.size() < 2) continue;
            GameLinesParser.Word o = nearestWord(prices, over.cx(), 90), u = nearestWord(prices, under.cx(), 90);
            if (o == null || u == null || o == u) { r.notes.add(what + ": prices not under the Over/Under columns at line " + line); continue; }
            r.cells.add(new Cell("TOTAL", "OVER", line, price(o.text), "Over", bounds(o)));
            r.cells.add(new Cell("TOTAL", "UNDER", line, price(u.text), "Under", bounds(u)));
        }
    }

    private static void asianHandicap(List<Row> rows, int h, String home, String away, Result r) {
        int end = sectionEnd(rows, h);
        // Header row: the two team labels (either order of appearance is handled by their x positions).
        int headerIndex = -1; int homeX = -1, awayX = -1;
        for (int i = h + 1; i < end; i++) {
            Row row = rows.get(i);
            if (!priceWords(row).isEmpty()) break;
            int hx = labelX(row, home), ax = labelX(row, away);
            if (hx >= 0 && ax >= 0 && hx != ax) { headerIndex = i; homeX = hx; awayX = ax; break; }
        }
        if (headerIndex < 0) { r.notes.add("asian handicap: team header not read"); return; }
        if (homeX > awayX) { r.notes.add("asian handicap: away team column left of the home team; not used"); return; }
        int mid = (homeX + awayX) / 2;
        for (int i = headerIndex + 1; i < end; i++) {
            Row row = rows.get(i);
            List<GameLinesParser.Word> prices = priceWords(row);
            if (prices.size() != 2) continue;
            String homeLine = null, awayLine = null;
            for (GameLinesParser.Word p : prices) {
                String line = lineLeftOf(row, p);
                if (line == null) continue;
                if (p.cx() < mid) homeLine = line; else awayLine = line;
            }
            if (homeLine == null || awayLine == null) { r.notes.add("asian handicap: a row without a readable line per team"); continue; }
            GameLinesParser.Word hp = prices.get(0).cx() < mid ? prices.get(0) : prices.get(1), ap = hp == prices.get(0) ? prices.get(1) : prices.get(0);
            if (new BigDecimal(homeLine).add(new BigDecimal(awayLine)).signum() != 0) { r.notes.add("asian handicap: lines are not opposite (" + homeLine + " / " + awayLine + ")"); continue; }
            r.cells.add(new Cell("SPREAD", "HOME", homeLine, price(hp.text), home, bounds(hp)));
            r.cells.add(new Cell("SPREAD", "AWAY", awayLine, price(ap.text), away, bounds(ap)));
        }
    }

    // ------------------------------------------------------------------ helpers
    private static List<Row> rows(List<GameLinesParser.Word> rawWords) {
        List<GameLinesParser.Word> words = new ArrayList<>();
        for (GameLinesParser.Word w : rawWords) if (w != null && !w.text.isEmpty() && w.bottom - w.top >= 8) words.add(w);
        words.sort((a, b) -> Integer.compare(a.cy(), b.cy()));
        List<Row> rows = new ArrayList<>();
        for (GameLinesParser.Word w : words) {
            Row last = rows.isEmpty() ? null : rows.get(rows.size() - 1);
            if (last != null && Math.abs(w.cy() - last.cy) <= 14) last.words.add(w);
            else rows.add(new Row(w.cy()));
            if (last == null || Math.abs(w.cy() - last.cy) > 14) rows.get(rows.size() - 1).words.add(w);
        }
        for (Row row : rows) row.words.sort((a, b) -> Integer.compare(a.left, b.left));
        return rows;
    }

    private static int sectionEnd(List<Row> rows, int h) {
        for (int i = h + 1; i < rows.size(); i++) {
            String t = rows.get(i).text();
            for (String heading : HEADINGS) if (t.contains(heading)) return i;
        }
        return rows.size();
    }

    private static List<GameLinesParser.Word> priceWords(Row row) {
        List<GameLinesParser.Word> out = new ArrayList<>();
        for (GameLinesParser.Word w : row.words) if (PRICE.matcher(w.text).matches() && !w.text.startsWith("0")) out.add(w);
        return out;
    }

    /** Leftmost line token of a row (left of `limitX`), joining "2.5," "3.0" quarter pairs; null if none. */
    private static String lineToken(Row row, int limitX) {
        for (int i = 0; i < row.words.size(); i++) {
            GameLinesParser.Word w = row.words.get(i);
            if (w.cx() >= limitX) break;
            String t = w.text.replace(" ", "");
            if (t.endsWith(",") && i + 1 < row.words.size()) t = t + row.words.get(i + 1).text;
            String line = normaliseLine(t);
            if (line != null) return line;
        }
        return null;
    }

    /** The line token immediately left of a price word (same row, within 140 px), or null. */
    private static String lineLeftOf(Row row, GameLinesParser.Word price) {
        String best = null; int bestGap = Integer.MAX_VALUE;
        for (int i = 0; i < row.words.size(); i++) {
            GameLinesParser.Word w = row.words.get(i);
            if (w == price || w.right > price.left + 4 || PRICE.matcher(w.text).matches()) continue;
            String t = w.text.replace(" ", "");
            if (t.endsWith(",") && i + 1 < row.words.size() && row.words.get(i + 1) != price) t = t + row.words.get(i + 1).text;
            String line = normaliseLine(t);
            int gap = price.left - w.right;
            if (line != null && gap >= -4 && gap < 140 && gap < bestGap) { best = line; bestGap = gap; }
        }
        return best;
    }

    /** "+0.5" -> "+0.5", "0" -> "0.0", "-1" -> "-1.0", "2.5,3.0" -> "2.75", "0.0,-0.5" -> "-0.25"; null if not a line. */
    static String normaliseLine(String raw) {
        if (raw == null) return null;
        String t = raw.trim();
        java.util.regex.Matcher q = QUARTER.matcher(t);
        BigDecimal value = null;
        if (q.matches()) {
            BigDecimal a = new BigDecimal(q.group(1).replace(',', '.')), b = new BigDecimal(q.group(2).replace(',', '.'));
            if (a.subtract(b).abs().compareTo(new BigDecimal("0.5")) == 0) value = a.add(b).divide(new BigDecimal(2));
        }
        if (value == null) {
            String plain = t.replace(',', '.');
            if (!LINE.matcher(plain).matches()) return null;      // "2,5" is an OCR comma decimal; "2.5,3.5" is not a quarter pair
            value = new BigDecimal(plain);
        }
        String sign = t.startsWith("+") && value.signum() > 0 ? "+" : "";
        String text = value.scale() > 1 ? value.setScale(2, RoundingMode.UNNECESSARY).toPlainString() : value.setScale(1, RoundingMode.UNNECESSARY).toPlainString();
        return sign + text;
    }

    private static String price(String raw) { return raw.replace(',', '.'); }

    private static int[] bounds(GameLinesParser.Word w) { return new int[] {w.left - 14, w.top - 12, w.right + 14, w.bottom + 12}; }

    private static int nearest(List<GameLinesParser.Word> columns, int x) {
        int best = -1, gap = Integer.MAX_VALUE;
        for (int i = 0; i < columns.size(); i++) { int d = Math.abs(columns.get(i).cx() - x); if (d < gap) { gap = d; best = i; } }
        return best;
    }

    private static GameLinesParser.Word nearestWord(List<GameLinesParser.Word> words, int x, int limit) {
        GameLinesParser.Word best = null; int gap = Integer.MAX_VALUE;
        for (GameLinesParser.Word w : words) { int d = Math.abs(w.cx() - x); if (d < gap && d <= limit) { gap = d; best = w; } }
        return best;
    }

    /** Accent-insensitive lower-case ASCII ("Enköping" and "Enkoping" read the same; the header parser transliterates too). */
    static String ascii(String s) {
        String n = java.text.Normalizer.normalize(OcrText.normalize(s == null ? "" : s), java.text.Normalizer.Form.NFD).replaceAll("\\p{M}+", "");
        return n.replace('ø', 'o').replace('Ø', 'O').replace('ł', 'l').replace('Ł', 'L').replace('ß', 's').replace('æ', 'a').replace('Æ', 'A')
                .replace('đ', 'd').replace('Đ', 'D').toLowerCase(Locale.US);
    }

    /** Centre x of the team's label words on a row (first-token match, OCR variants of "(W)" tolerated), or -1. */
    private static int labelX(Row row, String team) {
        if (team == null) return -1;
        String first = ascii(team).split("\\s+")[0];
        int left = -1, right = -1;
        for (GameLinesParser.Word w : row.words) {
            if (ascii(w.text).equals(first)) { left = w.left; right = w.right; break; }
        }
        return left < 0 ? -1 : (left + right) / 2;
    }

    private static boolean teamMatch(String team, String label) {
        String a = ascii(team).replaceAll("[^a-z0-9 ]", " ").replaceAll("\\s+", " ").trim();
        String b = ascii(label).replaceAll("[^a-z0-9 ]", " ").replaceAll("\\s+", " ").trim();
        if (a.isEmpty() || b.isEmpty()) return false;
        if (a.equals(b) || a.startsWith(b) || b.startsWith(a)) return true;
        String firstA = a.split("\\s+")[0], firstB = b.split("\\s+")[0];
        return firstA.length() >= 3 && firstA.equals(firstB);
    }
}
