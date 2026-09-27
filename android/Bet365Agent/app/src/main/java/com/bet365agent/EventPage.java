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
        for (String raw : headerLines) {
            String t = OcrText.normalize(raw).replaceAll("[^A-Za-z0-9/ .'&()-]", " ").replaceAll("\\s+", " ").trim();
            Matcher m = VS.matcher(t);
            if (!m.matches()) continue;
            String home = tidy(m.group(1)), away = tidy(m.group(2));
            if (home.length() >= 2 && away.length() >= 2) return new String[] {home, away};
        }
        return null;
    }

    private static String tidy(String s) {
        // Trailing header chevron OCR'd as ">" or a lone "v".
        return s.replaceAll("\\s*[>]+$", "").replaceAll("\\s+[vV]$", "").replaceAll("^[^A-Za-z0-9]+|[^A-Za-z0-9)]+$", "").trim();
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
