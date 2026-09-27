package com.bet365agent;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Pure classification of what Bet365 shows after a Place Bet tap, from OCR line text only.
 * No Android types, so it is covered by plain JVM unit tests (PlacementClassifierTest).
 *
 * Outcomes: PLACED, SESSION_EXPIRED, PRICE_CHANGED, LINE_CHANGED, STAKE_LIMITED,
 * INSUFFICIENT_FUNDS, SUSPENDED, REJECTED (all definitive), or PENDING / UNKNOWN (keep
 * watching; after the last frame the caller reports PLACEMENT_UNKNOWN). The classifier never
 * suggests tapping anything: an odds-change "Accept" prompt is reported, never accepted.
 */
final class PlacementClassifier {
    static final class Result {
        final String outcome, detail, betReference, stake, potentialReturn;
        final boolean definitive;
        Result(String outcome, String detail, boolean definitive, String betReference, String stake, String potentialReturn) {
            this.outcome = outcome; this.detail = detail; this.definitive = definitive;
            this.betReference = betReference; this.stake = stake; this.potentialReturn = potentialReturn;
        }
    }

    // Real receipt (2026-09-24): "Bet Ref BT4964411281W" OCR'd as "Bet Ref BT496441 1231 W", so the
    // reference may be split by spaces; the pieces are joined. OCR digits are not trusted exactly:
    // My Bets reconciliation identifies the bet by fixture, selection and stake, not by reference.
    private static final Pattern REFERENCE = Pattern.compile("(?i)\\bbet\\s*ref(?:erence)?\\.?\\s*:?\\s*([A-Z0-9]{2,20}(?:\\s(?:[A-Z0-9]*\\d[A-Z0-9]*|[A-Z]\\b)){0,3})");
    private static final Pattern MONEY_OCR = Pattern.compile("£\\s*([0-9Oo][0-9Oo.,\\s]{0,9})");
    private static final Pattern AMOUNT = Pattern.compile("£(\\d+(?:[.,]\\d{1,2})?)");
    private static final Pattern STAKE = Pattern.compile("(?i)\\bstake\\b[^0-9]{0,6}(\\d+(?:[.,]\\d{1,2})?)");
    private static final Pattern RETURNS = Pattern.compile("(?i)\\b(?:to\\s+return|returns?|potential\\s+returns?)\\b[^0-9]{0,6}(\\d+(?:[.,]\\d{1,2})?)");

    private PlacementClassifier() {}

    static Result classify(List<String> lines, boolean placeBetStillVisible) {
        String blob = blob(lines);
        if (receiptVisible(lines)) {
            List<String> fixed = new ArrayList<>();
            if (lines != null) for (String line : lines) fixed.add(moneyFix(line));
            String[] amounts = stakeAndReturn(fixed);
            String stake = amounts[0] != null ? amounts[0] : group(STAKE, joined(fixed));
            String ret = amounts[1] != null ? amounts[1] : group(RETURNS, joined(fixed));
            return new Result("PLACED", "Bet365 receipt visible", true, reference(lines), money(stake), money(ret));
        }
        if (has(blob, "password") && has(blob, "log in", "login")) {
            return definitive("SESSION_EXPIRED", "Login wall after Place Bet");
        }
        // current Bet365 wording (27 Sep 2026): "The line and price of your selection changed" / "The price of your
        // selection changed" with the button relabelled "Accept Change and Place Bet". Nothing is placed until accepted.
        if (has(blob, "line has changed", "line changed", "handicap has changed", "handicap changed", "points changed",
                "line and price of your selection", "line of your selection changed")) {
            return definitive("LINE_CHANGED", "Bet365 reports the line changed; changes NOT accepted");
        }
        if (has(blob, "odds have changed", "odds changed", "price has changed", "price changed", "accept odds",
                "accept changes", "accept price", "accept new odds", "price of your selection changed",
                "odds of your selection changed", "accept change")) {
            return definitive("PRICE_CHANGED", "Bet365 reports the odds changed; changes NOT accepted");
        }
        if (has(blob, "max stake", "maximum stake", "stake limit", "exceeds the maximum", "stake is too high",
                "stake offered", "offered stake")) {
            return definitive("STAKE_LIMITED", "Bet365 limited the stake");
        }
        if (has(blob, "insufficient", "not enough funds", "please deposit", "deposit funds", "add funds", "top up")
                || (has(blob, "balance") && has(blob, "not enough", "too low", "unable"))) {
            return definitive("INSUFFICIENT_FUNDS", "Bet365 reports insufficient funds");
        }
        if (has(blob, "suspended", "no longer available", "selection unavailable", "market unavailable")) {
            return definitive("SUSPENDED", "Selection or market suspended/unavailable");
        }
        if (has(blob, "not accepted", "bet rejected", "has been rejected", "unable to place", "could not be placed",
                "cannot be placed")) {
            return definitive("REJECTED", "Bet365 refused the bet");
        }
        if (placeBetStillVisible) return new Result("PENDING", "Place Bet still visible; no outcome yet", false, null, null, null);
        return new Result("UNKNOWN", "No recognisable outcome on screen", false, null, null, null);
    }

    /** The Place Bet gesture opened the stake keypad instead (it landed on the stake field): the UI did not accept a
     *  submission. Definitive for the device; the backend still confirms absence in My Bets. */
    static Result tapNotAccepted() {
        return new Result("TAP_NOT_ACCEPTED", "Place Bet gesture opened the stake keypad; no submission accepted by the UI", true, null, null, null);
    }

    /** Receipt markers. Real receipt: green banner "Bet Placed" + "Bet Ref ...", then the selection and a
     *  "Stake  To Return" row. The banner stays on screen until its close (X) is tapped. */
    static boolean receiptVisible(List<String> lines) {
        return has(blob(lines), "bet placed", "bets placed", "your bet has been placed", "bet ref", "bet reference",
                "receipt", "bet confirmed");
    }

    /** "Stake  To Return" header with the two amounts on the next line ("£O.1 0 £0.1 8" after OCR). */
    static String[] stakeAndReturn(List<String> fixedLines) {
        for (int i = 0; i < fixedLines.size(); i++) {
            String t = fixedLines.get(i).toLowerCase(Locale.US);
            // OCR splits words: real receipt HT5515901931W read the header as "Sta ke To Return".
            String compact = t.replace(" ", "");
            if (!(compact.contains("stake") && compact.contains("return"))) continue;
            List<String> found = new ArrayList<>();
            Matcher m = AMOUNT.matcher(t);
            while (m.find()) found.add(m.group(1));
            if (found.size() < 2 && i + 1 < fixedLines.size()) {
                m = AMOUNT.matcher(fixedLines.get(i + 1));
                while (m.find()) found.add(m.group(1));
            }
            if (found.size() >= 2) return new String[] {found.get(0), found.get(1)};
        }
        return new String[] {null, null};
    }

    /** "£O.1 0" -> "£0.10": OCR letter O and stray spaces inside amounts. */
    static String moneyFix(String text) {
        Matcher m = MONEY_OCR.matcher(text == null ? "" : text);
        StringBuffer out = new StringBuffer();
        while (m.find()) {
            String amount = m.group(1).replace(" ", "").replace('O', '0').replace('o', '0');
            m.appendReplacement(out, Matcher.quoteReplacement("£" + amount + " "));
        }
        m.appendTail(out);
        return out.toString();
    }

    static String reference(List<String> lines) {
        for (String line : lines == null ? new ArrayList<String>() : lines) {
            Matcher m = REFERENCE.matcher(line);
            if (m.find()) {
                String ref = m.group(1).replace(" ", "").toUpperCase(Locale.US);
                if (ref.length() >= 6 && ref.matches(".*\\d.*")) return ref;
            }
        }
        return null;
    }

    /** OCR of a close/remove icon: the receipt banner "X" reads as "x"; the betslip selection "X" as "><". */
    static boolean closeGlyph(String word) {
        String w = word == null ? "" : word.trim();
        return w.equals("x") || w.equals("X") || w.equals("×") || w.equals("><") || w.equals(")<") || w.equals("><.");
    }

    /** Index of the receipt close icon on the banner line ("Share" then the X), or -1.
     *  Never "Share" and never "Reuse Selections" (that would put the bet back on the slip). */
    static int receiptCloseWord(List<String> words) {
        int share = -1;
        for (int i = 0; i < words.size(); i++) if (words.get(i).trim().equalsIgnoreCase("share")) share = i;
        if (share < 0) return -1;
        for (int i = share + 1; i < words.size(); i++) if (closeGlyph(words.get(i))) return i;
        return -1;
    }

    /** Index of the remove-selection icon at the start of a betslip selection line ("><  Hapoel Tel Aviv -8.0 1.83"),
     *  only when the rest of the line names the selection. -1 otherwise. */
    static int removeSelectionWord(List<String> words, String selectionName) {
        if (words.size() < 2 || !closeGlyph(words.get(0)) || selectionName == null || selectionName.trim().isEmpty()) return -1;
        String rest = String.join(" ", words.subList(1, words.size())).toLowerCase(Locale.US);
        String first = selectionName.trim().toLowerCase(Locale.US).split("\\s+")[0];
        return rest.contains(first) ? 0 : -1;
    }

    /** Remove icon at the start of ANY betslip selection line ("><  Bayern Munich +8.0 1.83"): used by the
     *  generic reset, which does not know the selection. Needs either two named words after the icon, or one
     *  named word plus a line/price number: real slip row "X Szekszard (W) +3.5" (2026-09-25, single-word women's
     *  team) was not recognised and the held selection stayed on the slip. */
    static int removeAnySelectionWord(List<String> words) {
        if (words.size() < 3 || !closeGlyph(words.get(0))) return -1;
        int named = 0, numeric = 0;
        for (String w : words.subList(1, words.size())) {
            if (w.matches(".*[A-Za-z]{2,}.*")) named++;
            else if (w.matches("[+-]?[0-9]+(\\.[0-9]+)?")) numeric++;
        }
        String rest = String.join(" ", words.subList(1, words.size())).toLowerCase(Locale.US);
        if (rest.contains("share") || rest.contains("reuse") || rest.contains("place")) return -1;
        return named >= 2 || (named >= 1 && numeric >= 1) ? 0 : -1;
    }

    /** Betslip selection line whose remove icon OCR missed (real collapsed slip): the name line is indented
     *  by the icon (left edge ~59 px) and the line below names the market ("Point Spread"). With a known
     *  selection name the line must contain it; otherwise it must look like a selection (letters). */
    static boolean selectionLineByIndent(String line, int left, String nextLine, String selectionName) {
        if (left < 45 || left > 85 || line == null || nextLine == null) return false;
        String t = line.toLowerCase(Locale.US), next = nextLine.toLowerCase(Locale.US);
        if (t.contains("place") || t.contains("share") || t.contains("reuse") || t.contains("stake")) return false;
        boolean market = next.contains("spread") || next.contains("total") || next.contains("money line")
                || next.contains("moneyline") || next.contains("result") || next.contains("winner") || next.contains("handicap");
        if (!market) return false;
        if (selectionName != null && !selectionName.trim().isEmpty())
            return t.contains(selectionName.trim().toLowerCase(Locale.US).split("\s+")[0]);
        return t.matches(".*[a-z]{2,}.*");
    }

    /** The betslip re-shows the selection in large text ("Bayern Munich +8.0", "Under 173.5"): an independent
     *  read of the line. SPREAD: team word + the exact signed line; TOTAL: Over/Under + the line. */
    static boolean slipShowsLine(List<String> lines, String market, String side, String name, String line) {
        if (lines == null || line == null) return false;
        if (!"SPREAD".equals(market) && !"TOTAL".equals(market)) return true;
        java.math.BigDecimal want;
        try { want = new java.math.BigDecimal(line); } catch (Exception e) { return false; }
        // Basketball lines are x.0 / x.5. Football Asian lines also come in quarters (-1.75, +0.25), which Bet365 shows either
        // as "1.75" or split as "1.5,2.0"; both spellings are accepted for the exact requested value only.
        for (String pattern : linePatterns(want, "SPREAD".equals(market))) {
            for (String raw : lines) {
                String t = " " + raw.toLowerCase(Locale.US).replace(',', '.') + " ";
                if ("TOTAL".equals(market)) {
                    String word = "OVER".equals(side) ? "over" : "under";
                    if (t.contains(" " + word + " ") && t.matches(".*(?<![\\d.])" + pattern + "(?![\\d]).*")) return true;
                } else {
                    String team = name == null ? "" : name.trim().toLowerCase(Locale.US).split("\\s+")[0];
                    if (!team.isEmpty() && t.contains(team) && t.matches(".*(?<![\\d.+-])" + pattern + "(?![\\d]).*")) return true;
                }
            }
        }
        return false;
    }

    /** Regex alternatives for a line as the slip may print it (commas already turned into dots by the caller). */
    static List<String> linePatterns(java.math.BigDecimal want, boolean signed) {
        List<String> out = new ArrayList<>();
        java.math.BigDecimal magnitude = want.abs().stripTrailingZeros();
        int scale = Math.max(1, magnitude.scale());
        String plain = magnitude.setScale(scale, java.math.RoundingMode.UNNECESSARY).toPlainString();
        String sign = !signed ? "" : want.signum() > 0 ? "+" : want.signum() < 0 ? "-" : "";
        out.add(java.util.regex.Pattern.quote(sign + plain));
        if (scale == 2) {
            // quarter line: the two half lines it is made of ("1.75" = "1.5,2.0"; "0.25" = "0.0,0.5"), in Bet365's order
            java.math.BigDecimal lo = magnitude.subtract(new java.math.BigDecimal("0.25")).setScale(1, java.math.RoundingMode.UNNECESSARY);
            java.math.BigDecimal hi = magnitude.add(new java.math.BigDecimal("0.25")).setScale(1, java.math.RoundingMode.UNNECESSARY);
            String a = lo.toPlainString(), b = hi.toPlainString();
            String sa = sign.isEmpty() ? "" : (lo.signum() == 0 ? "[+-]?" : java.util.regex.Pattern.quote(sign));
            String sb = sign.isEmpty() ? "" : java.util.regex.Pattern.quote(sign);
            out.add(sa + java.util.regex.Pattern.quote(a) + "[.\\s]\\s*" + sb + java.util.regex.Pattern.quote(b));
        }
        return out;
    }

    /** True if a line is a control the reset may tap: never anything that could place or accept a bet. */
    static boolean safeResetControl(String text) {
        String t = text.trim().toLowerCase(Locale.US);
        if (t.contains("place") || t.contains("accept") || t.contains("confirm") || t.contains("bet now")) return false;
        return t.equals("done") || t.equals("continue") || t.equals("close") || t.equals("remove all")
                || t.equals("clear all") || t.equals("remove") || t.equals("clear");
    }

    /** Betslip shows more than one selection: placing would create a multiple. */
    static boolean multipleSelections(List<String> lines) {
        // A football event page shows its "Double Chance" market behind the slip (FC Munsingen v SV Muttenz, 27 Sep 2026):
        // that heading is a market name, not a multiple. Only the bet-type words on the slip itself count.
        String blob = blob(lines).replace("double chance", " ");
        return has(blob, "double", "treble", "multiples", "accumulator", "trixie", "yankee", "patent", "lucky 15",
                "2 selections", "3 selections", "4 selections", "5 selections");
    }

    static List<String> receiptLines(List<String> lines) {
        List<String> out = new ArrayList<>();
        for (String line : lines) if (out.size() < 40 && !line.trim().isEmpty()) out.add(line.trim());
        return out;
    }

    private static Result definitive(String outcome, String detail) {
        return new Result(outcome, detail, true, null, null, null);
    }

    private static String blob(List<String> lines) {
        return " " + joined(lines).toLowerCase(Locale.US).replaceAll("\\s+", " ") + " ";
    }

    private static String joined(List<String> lines) {
        return lines == null ? "" : String.join(" | ", lines);
    }

    private static boolean has(String blob, String... phrases) {
        for (String p : phrases) if (blob.contains(p)) return true;
        return false;
    }

    private static String group(Pattern pattern, String text) {
        Matcher m = pattern.matcher(text);
        return m.find() ? m.group(1) : null;
    }

    private static String money(String value) {
        if (value == null) return null;
        String v = value.replace(',', '.');
        if (!v.contains(".")) v = v + ".00";
        else if (v.substring(v.indexOf('.') + 1).length() == 1) v = v + "0";
        return v;
    }
}
