package com.bet365agent;

import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Direct event-link navigation helpers (pure Java; JVM tests: EventPageTest).
 *
 * The OddsNotifier alert carries the Bet365 event link (e.g. #/AC/B18/C21168177/D19/E26747385/F19/I0/).
 * Opening it replaces Home -> Search -> results -> fixture (about a minute). The page is then verified
 * strictly: sport from the link (B18 basketball, B1 football), both teams from the header (explicit
 * aliases only), and the kick-off shown in the header (UK time) against the alert's UTC time.
 */
final class EventPage {
    private static final Pattern URL = Pattern.compile("^https://www\\.bet365\\.com/#/AC/B(\\d{1,3})(/[A-Z]\\d{1,12}){2,8}/?$");
    private static final Pattern VS = Pattern.compile("(?i)^(.+?)\\s+(?:vs|v)\\s+(.+)$");
    /** "25 Sep 10:35"; tolerates one OCR digit glued in front of a two-digit day ("Japan B League 127 Sep 07:05" is the
     *  league's "1" joined to "27 Sep" - seen 40 times in the 25-27 Sep captures) without ever splitting a real day. */
    private static final Pattern KICKOFF = Pattern.compile("(?i)(?<!\\d)(?:\\d(?=\\d{2}\\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)))?(\\d{1,2})\\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\\s*(\\d{1,2}):(\\d{2})\\b");
    static final ZoneId UK = ZoneId.of("Europe/London");
    private static final String[] MONTHS = {"Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"};

    private EventPage() {}

    /**
     * Bet365's closed-event page: "Sorry, this page is no longer available. Betting has closed or has been
     * suspended." (real: Araraquara v Mogi Das Cruzes, 2026-09-24). No bet is possible on that event, so the
     * run stops at once (SUSPENDED) instead of spending minutes on a search that cannot succeed.
     */
    static boolean closed(List<String> lines) {
        String t = " " + OcrText.normalize(String.join(" ", lines)).toLowerCase(Locale.US).replaceAll("\s+", " ") + " ";
        return t.contains("no longer available") || t.contains("betting has closed")
                || (t.contains("betting") && t.contains("has been suspended"));
    }

    /** Generic tokens that never identify a club on their own. */
    private static final java.util.Set<String> GENERIC = java.util.Set.of("basket", "basketball", "club", "team", "sport",
            "sports", "united", "city", "town", "real", "athletic", "atletico", "academy", "college", "university", "women",
            "ladies", "men", "reserves", "youth", "junior", "juniors", "senior", "seniors");

    /**
     * Do two team names look like variants of the same name (bookmaker vs feed spelling)? True when they share a
     * significant token (4+ letters, not generic) or their letters agree for >= 70% (Soproni KC / Sopron KC).
     * Used only to LABEL a refusal (ALIAS_REQUIRED vs WRONG_EVENT); it never verifies an event by itself.
     */
    static boolean namingVariant(String a, String b) {
        if (a == null || b == null) return false;
        String na = OcrText.normalize(a).toLowerCase(Locale.US), nb = OcrText.normalize(b).toLowerCase(Locale.US);
        java.util.Set<String> ta = new java.util.HashSet<>(), tb = new java.util.HashSet<>();
        for (String t : na.split("[^a-z0-9]+")) if (t.length() >= 4 && !GENERIC.contains(t)) ta.add(t);
        for (String t : nb.split("[^a-z0-9]+")) if (t.length() >= 4 && !GENERIC.contains(t)) tb.add(t);
        for (String t : ta) if (tb.contains(t)) return true;
        // Letter overlap over the NON-generic tokens only ("Basket Club A" / "Basket Club B" must not pass on
        // the shared generic words).
        String la = lettersWithoutGeneric(na), lb = lettersWithoutGeneric(nb);
        if (la.length() < 4 || lb.length() < 4) return false;
        int common = lcs(la, lb);
        return common * 100 >= Math.max(la.length(), lb.length()) * 70;
    }

    private static String lettersWithoutGeneric(String normalisedLower) {
        StringBuilder b = new StringBuilder();
        for (String t : normalisedLower.split("[^a-z0-9]+")) if (!t.isEmpty() && !GENERIC.contains(t)) b.append(t);
        return b.toString();
    }

    private static int lcs(String a, String b) {
        int[][] d = new int[a.length() + 1][b.length() + 1];
        for (int i = 1; i <= a.length(); i++)
            for (int j = 1; j <= b.length(); j++)
                d[i][j] = a.charAt(i - 1) == b.charAt(j - 1) ? d[i - 1][j - 1] + 1 : Math.max(d[i - 1][j], d[i][j - 1]);
        return d[a.length()][b.length()];
    }

    static boolean validUrl(String url) { return url != null && URL.matcher(url.trim()).matches(); }

    /** Sport from the link's B code: 18 basketball, 1 football; null if unknown. */
    static String sportOf(String url) {
        Matcher m = URL.matcher(url == null ? "" : url.trim());
        if (!m.matches()) return null;
        switch (m.group(1)) {
            case "18": return "basketball";
            case "1": return "football";
            default: return null;
        }
    }

    /** {home, away} from the header ("Kyoto Hannaryz vs Shiga Lakes" or "Hapoel Tel Aviv VS Bayern Munich"). */
    static String[] teams(List<String> headerLines) {
        for (int index = 0; index < headerLines.size(); index++) {
            String raw = headerLines.get(index);
            // A team title too long for one line wraps onto the next header line ("... vs Katarzynki II" / "Torun (W)",
            // "... vs Leonas de Ponce" / "(W)"): join a short continuation that is neither a kick-off, a tab strip nor a fixture.
            if (index + 1 < headerLines.size() && raw.length() >= 30 && VS.matcher(OcrText.normalize(raw)).matches()) {
                String next = headerLines.get(index + 1).trim();
                if (continuation(next)) raw = raw + " " + next;
            }
            String t = headerText(raw);
            Matcher m = VS.matcher(t);
            if (!m.matches()) continue;
            String home = tidy(m.group(1)), away = tidy(m.group(2));
            if (home.length() >= 2 && away.length() >= 2) return new String[] {home, away};
        }
        return null;
    }

    /** One header line as the resolver reads it: unread squad numerals as a placeholder, letters transliterated, only
     *  name characters kept. Shared by every header parse (plain, hint-aware, numeral reread). */
    private static String headerText(String raw) {
        // OCR glyph runs containing '|' inside a name ("KS Basket 25 I| Bydgoszcz", "||") are an unread squad numeral:
        // kept as an explicit placeholder so the resolver asks for a reread instead of silently dropping it.
        raw = raw.replaceAll("(?<=^|\\s)[|Il1!]*\\|[|Il1!]*(?=\\s|$)", EventIdentity.UNREAD_TIER);
        // Accented letters are transliterated, not dropped: "FC Arlanda v Enköping" read as "Enk ping" (27 Sep 2026,
        // live football proof) can never match the feed's "Enkopings"; "Enkoping" can. The ligatures take their
        // two-letter spelling (28 Sep 2026: page "Rælingen" became "Ralingen" and never equalled the feed's "Raelingen").
        String ascii = java.text.Normalizer.normalize(OcrText.normalize(raw), java.text.Normalizer.Form.NFD).replaceAll("\\p{M}+", "")
                .replace('ø', 'o').replace('Ø', 'O').replace('ł', 'l').replace('Ł', 'L').replace("ß", "ss").replace("æ", "ae").replace("Æ", "Ae")
                .replace("œ", "oe").replace("Œ", "Oe").replace('đ', 'd').replace('Đ', 'D');
        return ascii.replaceAll("[^A-Za-z0-9/ .'&()-]", " ").replaceAll("\\s+", " ").trim();
    }

    /**
     * teams() with the alert's own names as the only evidence for two OCR defects of the header line (28 Sep 2026, Codex
     * daily audit):
     *  - a separator glued to the home name ("Georgiav Ukraine v", "Belgiumv France"): no " v " exists, so teams() is null;
     *    the line is split at the one word ending in a glued 'v' ONLY when the text before it is exactly the alert's home
     *    name or its supplied bookmaker alias. The resolver then still has to accept both teams.
     *  - the header's dropdown chevron glued to the away name ("Eng Tat Hornets Vs SG Basketballv"): the trailing 'v' is
     *    dropped ONLY when the result is exactly the alert's away name or its alias ("SG Basketball"), so the held name the
     *    slip is later checked against is the clean one.
     * Any other shape is left as teams() reads it.
     */
    static String[] teams(List<String> headerLines, java.util.Collection<String> homeHints, java.util.Collection<String> awayHints) {
        String[] plain = teams(headerLines);
        if (plain != null) return new String[] {unglue(plain[0], homeHints), unglue(plain[1], awayHints)};
        if (homeHints == null || homeHints.isEmpty()) return null;
        for (String raw : headerLines) {
            String[] w = tidy(headerText(raw)).split(" ");
            int at = -1, count = 0;
            for (int k = 0; k < w.length - 1; k++)
                if (w[k].length() >= 3 && w[k].endsWith("v") && Character.isLetter(w[k].charAt(w[k].length() - 2))) { at = k; count++; }
            if (count != 1) continue;
            StringBuilder home = new StringBuilder();
            for (int k = 0; k <= at; k++) home.append(k == 0 ? "" : " ").append(k == at ? w[k].substring(0, w[k].length() - 1) : w[k]);
            StringBuilder away = new StringBuilder();
            for (int k = at + 1; k < w.length; k++) away.append(k == at + 1 ? "" : " ").append(w[k]);
            String h = home.toString(), a = tidy(away.toString());
            if (a.length() >= 2 && hinted(h, homeHints)) return new String[] {h, unglue(a, awayHints)};
        }
        return null;
    }

    private static String unglue(String name, java.util.Collection<String> hints) {
        if (name == null || !name.endsWith("v") || name.length() < 4 || !Character.isLetter(name.charAt(name.length() - 2))) return name;
        String cut = name.substring(0, name.length() - 1);
        return hinted(name, hints) ? name : hinted(cut, hints) ? cut : name;
    }

    private static boolean hinted(String name, java.util.Collection<String> hints) {
        if (hints == null) return false;
        String n = EventIdentity.normalise(name);
        for (String hint : hints) if (hint != null && !hint.isEmpty() && !n.isEmpty() && n.equals(EventIdentity.normalise(hint))) return true;
        return false;
    }

    /** The alert's own names for one side: the feed name and the bookmaker alias the instruction supplies for it. */
    static java.util.List<String> hints(String feedName, java.util.Map<String, String> aliases) {
        java.util.List<String> out = new java.util.ArrayList<>();
        if (feedName != null && !feedName.isEmpty()) out.add(feedName);
        String alias = aliases == null || feedName == null ? null : aliases.get(EventIdentity.plain(feedName));
        if (alias != null && !alias.isEmpty()) out.add(alias);
        return out;
    }

    private static final Pattern STROKES = Pattern.compile("^[IiLl1|!]{1,3}$");

    /**
     * Identity v2 reread of an unread squad numeral: the first read's teams with each UNREADTIER / lone "I" replaced by the
     * numeral an independent enhanced read shows at the same place (same neighbouring words), counted in vertical strokes
     * ("ll", "Il", "II", "||" = II; three = III; one = I). Everything else keeps the first read (the enhanced pass garbles
     * other text: "12230" for 12:30 on the real Bydgoszcz frames). Null when the reread does not show the numeral at that
     * place: the recheck then stays unresolved. Pure; the live adapter and EventIdentityV2AdversarialTest call it.
     */
    static String[] patchNumeral(List<String> firstHeader, List<String> rereadHeader) {
        String[] first = teams(firstHeader), again = teams(rereadHeader);
        if (first == null || again == null) return null;
        String[] out = first.clone();
        boolean patched = false;
        for (int side = 0; side < 2; side++) {
            String[] f = first[side].split("\s+");
            java.util.List<String> r = java.util.Arrays.asList(again[side].split("\s+"));
            for (int k = 0; k < f.length; k++) {
                // placeholders: the unread-glyph token, a lone "I", or a stroke run with an OCR glyph in it ("Il"; a clean II/III is read)
                if (!f[k].equals(EventIdentity.UNREAD_TIER) && !f[k].equals("I")
                        && !(k > 0 && f[k].length() >= 2 && STROKES.matcher(f[k]).matches() && f[k].matches(".*[Ll1|!].*")))
                    continue;
                String prev = k > 0 ? f[k - 1] : null, next = k + 1 < f.length ? f[k + 1] : null;
                String numeral = null;
                for (int j = 0; j < r.size(); j++) {
                    if (!STROKES.matcher(r.get(j)).matches()) continue;
                    boolean before = prev == null ? j == 0 : j > 0 && r.get(j - 1).equalsIgnoreCase(prev);
                    boolean after = next == null ? j == r.size() - 1 : j + 1 < r.size() && r.get(j + 1).equalsIgnoreCase(next);
                    if (before && after) { numeral = "III".substring(0, r.get(j).length()); break; }
                }
                if (numeral == null) return null;
                f[k] = numeral; patched = true;
            }
            out[side] = String.join(" ", f);
        }
        return patched ? out : null;
    }

    private static boolean continuation(String next) {
        if (next.isEmpty() || next.length() > 24 || next.split("\\s+").length > 3) return false;
        if (VS.matcher(next).matches() || KICKOFF.matcher(next).find()) return false;
        String low = next.toLowerCase(Locale.US);
        for (String w : new String[] {"popular", "bet builder", "game lines", "result", "goals", "quarter", "half", "team", "asian", "corners"})
            if (low.contains(w)) return false;
        return next.matches("[A-Za-z0-9() .'&/-]+");
    }

    private static String tidy(String s) {
        // Trailing header chevron OCR'd as ">" or a lone "v".
        return s.replaceAll("\\s*[>]+$", "").replaceAll("\\s+[vV]$", "").replaceAll("^[^A-Za-z0-9]+|[^A-Za-z0-9)]+$", "").trim();
    }

    /** One direct-link identity decision: the header lines of the captured page, the teams and kick-off read from them and
     *  the resolver's verdict. The live adapter and the stored-capture replay (EventIdentityV2ReplayTest) both call this. */
    static final class Direct {
        final List<String> header; final String[] teams; final String shown; final EventIdentity.Result result;
        Direct(List<String> header, String[] teams, String shown, EventIdentity.Result result) {
            this.header = header; this.teams = teams; this.shown = shown; this.result = result;
        }
        String competitionLine() { return header.isEmpty() ? null : header.get(0); }
    }

    /** teams == null / result == null when the header has no readable "A v B" line. wantUk: the alert kick-off in UK display. */
    static Direct decide(List<String> header, String sport, String feedHome, String feedAway, String wantUk, String feedCompetition,
                         String country, boolean anchored, java.util.Map<String, String> aliases, boolean womensCompetition) {
        return decide(header, teams(header, hints(feedHome, aliases), hints(feedAway, aliases)), sport, feedHome, feedAway, wantUk,
                feedCompetition, country, anchored, aliases, womensCompetition);
    }

    static Direct decide(List<String> header, String[] teams, String sport, String feedHome, String feedAway, String wantUk, String feedCompetition,
                         String country, boolean anchored, java.util.Map<String, String> aliases, boolean womensCompetition) {
        String shown = kickoffText(header);
        if (teams == null) return new Direct(header, null, shown, null);
        EventIdentity.Result r = EventIdentity.resolveVerified(
                new EventIdentity.Event(sport, feedHome, feedAway, wantUk, feedCompetition, false),
                new EventIdentity.Event(sport, teams[0], teams[1], shown, header.isEmpty() ? null : header.get(0), anchored),
                aliases, womensCompetition, country);
        return new Direct(header, teams, shown, r);
    }

    /** "25 Sep 10:35" style kick-off text in the header, or null (live events show a clock instead). */
    static String kickoffText(List<String> headerLines) {
        for (String line : headerLines) {
            Matcher m = KICKOFF.matcher(line);
            while (m.find()) {
                int day = Integer.parseInt(m.group(1)), hour = Integer.parseInt(m.group(3)), minute = Integer.parseInt(m.group(4));
                if (day >= 1 && day <= 31 && hour <= 23 && minute <= 59) return day + " " + cap(m.group(2)) + " " + pad(m.group(3)) + ":" + m.group(4);
            }
        }
        return null;
    }

    /** The alert's UTC kick-off ("2026-09-25T09:35") as Bet365 shows it in UK time ("25 Sep 10:35"). */
    static String ukDisplay(String kickoffUtc) {
        LocalDateTime uk = LocalDateTime.parse(kickoffUtc).atOffset(ZoneOffset.UTC).atZoneSameInstant(UK).toLocalDateTime();
        // Fixed three-letter months as Bet365 shows them (locale data varies: "Sept" on some JDKs).
        return uk.getDayOfMonth() + " " + MONTHS[uk.getMonthValue() - 1] + " " + uk.format(DateTimeFormatter.ofPattern("HH:mm"));
    }

    private static String cap(String s) { return s.substring(0, 1).toUpperCase(Locale.US) + s.substring(1).toLowerCase(Locale.US); }
    private static String pad(String h) { return h.length() == 1 ? "0" + h : h; }
}
