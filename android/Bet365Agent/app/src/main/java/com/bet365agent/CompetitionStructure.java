package com.bet365agent;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Structural competition identity (pure Java; CompetitionStructureTest, CompetitionReplayTest).
 *
 * OddsNotifier and Bet365 name the same competition differently: country prefixes ("Liga 1 Women" / "Poland 1 Liga
 * Women"), bookmaker groups ("Tercera Division" / "Spain Tercera Group 18"), roman tiers ("NB 2 Women" / "Hungary NBII
 * Women", "4th Liga" / "Poland IV Liga"), federation terminology ("Segunda Federacion" / "Spain Segunda Division RFEF
 * Group1") and brand names with no shared text at all ("Super League Women" / "Turkiye TKBSL Women", "NPFL" / "Nigeria
 * Premier League", "SB League" / "Switzerland LNA"). Literal matching can never cover the last kind, and one alias per
 * league does not scale.
 *
 * When the page was opened from the alert's OWN Bet365 event link and teams, sport and kick-off already agree, the
 * competition text is corroboration, not identity: it must not CONFLICT. Each name is reduced to the facts that separate
 * genuinely different competitions -
 *   gender (women's markers in several languages), age/reserve level (U19, youth, junior, primavera, reserves...),
 *   tier numbers (digits, roman numerals, ordinal words; an unnumbered name is the top tier), tier letters (Serie A/B),
 *   cup / friendly / federation (RFEF) qualifiers, and an explicitly different country -
 * and any difference in those facts fails closed. Group/pool designators ("Group 18", "Group C"), country prefixes and
 * cosmetic words (league, liga, division, ...) are not identity and are ignored.
 */
final class CompetitionStructure {
    private CompetitionStructure() {}

    static final class Facts {
        boolean women, cup, friendly, federation;
        final Set<String> level = new TreeSet<>(), letters = new TreeSet<>();
        final Set<Integer> tiers = new TreeSet<>();
        String country;          // a known country named by the text itself (normalised), or null
        final List<String> core = new ArrayList<>();
        String describe() {
            return "women=" + women + " level=" + level + " tier=" + (tiers.isEmpty() ? "top" : tiers.toString()) + " letters=" + letters
                    + " cup=" + cup + " friendly=" + friendly + " federation=" + federation + (country == null ? "" : " country=" + country);
        }
    }

    private static final Set<String> WOMEN = new HashSet<>(Arrays.asList("w", "women", "womens", "woman", "ladies", "female", "femenino",
            "femenina", "feminine", "feminin", "feminino", "feminina", "femminile", "frauen", "damen", "dames", "damas", "kvinder", "kvinner",
            "kvinnor", "naiset", "kadinlar", "zeny", "kobiet", "wnba", "wnbl", "wbbl", "wcba", "wkbl", "lfb", "waba"));
    private static final String[] WOMEN_PREFIX = {"kvinde", "kvinne", "frauen", "damall", "dameliga"};
    private static final Pattern AGE = Pattern.compile("^u(1[4-9]|2[0-3])$");
    private static final Set<String> LEVEL = new HashSet<>(Arrays.asList("youth", "junior", "juniors", "juvenil", "juvenile", "primavera",
            "reserve", "reserves", "academy", "development", "espoirs", "jeunes"));
    private static final Set<String> CUP = new HashSet<>(Arrays.asList("cup", "pokal", "copa", "coppa", "coupe", "kupa", "kup", "beker",
            "puchar", "taca", "supercup", "supercopa", "trophy", "shield"));
    private static final Set<String> FRIENDLY = new HashSet<>(Arrays.asList("friendly", "friendlies", "amistoso", "amistosos", "friendlys"));
    private static final Set<String> FEDERATION = new HashSet<>(Arrays.asList("rfef", "federacion", "federation", "federacao"));
    private static final Map<String, Integer> ORDINAL = new HashMap<>();
    static {
        for (String w : new String[] {"1st", "first", "primera", "primeira", "prima", "erste", "premiere"}) ORDINAL.put(w, 1);
        for (String w : new String[] {"2nd", "second", "segunda", "seconda", "zweite", "deuxieme", "druga"}) ORDINAL.put(w, 2);
        for (String w : new String[] {"3rd", "third", "tercera", "terceira", "terza", "dritte", "troisieme", "treca"}) ORDINAL.put(w, 3);
        for (String w : new String[] {"4th", "fourth", "cuarta", "quarta", "vierte", "quatrieme"}) ORDINAL.put(w, 4);
        for (String w : new String[] {"5th", "fifth", "quinta", "funfte", "cinquieme"}) ORDINAL.put(w, 5);
        ORDINAL.put("i", 1); ORDINAL.put("ii", 2); ORDINAL.put("iii", 3); ORDINAL.put("iv", 4);
    }
    /** Countries (normalised) and the spellings either side uses for them. */
    private static final Map<String, String> COUNTRY = new HashMap<>();
    static {
        String[] groups = {
            "turkey|turkiye", "czech republic|czechia|czech", "bosnia and herzegovina|bosnia herzegovina|bosnia", "korea|south korea|korea republic",
            "usa|united states|united states of america", "uae|united arab emirates", "north macedonia|macedonia", "netherlands|holland",
            "ivory coast|cote d ivoire", "england", "scotland", "wales", "northern ireland", "ireland|republic of ireland", "spain", "portugal",
            "france", "germany", "italy", "belgium", "switzerland", "austria", "poland", "hungary", "slovakia", "slovenia", "croatia", "serbia",
            "montenegro", "albania", "kosovo", "greece", "cyprus", "bulgaria", "romania", "moldova", "ukraine", "belarus", "russia", "lithuania",
            "latvia", "estonia", "finland", "sweden", "norway", "denmark", "iceland", "israel", "georgia", "armenia", "azerbaijan", "kazakhstan",
            "japan", "china", "taiwan|chinese taipei", "philippines", "indonesia", "australia", "new zealand", "argentina", "brazil", "chile",
            "uruguay", "paraguay", "bolivia", "peru", "ecuador", "colombia", "venezuela", "mexico", "canada", "puerto rico", "dominican republic",
            "egypt", "morocco", "tunisia", "algeria", "nigeria", "ghana", "south africa", "kenya", "iraq", "iran", "saudi arabia", "qatar",
            "kuwait", "bahrain", "jordan", "lebanon", "india", "vietnam", "thailand", "malaysia", "singapore"};
        for (String g : groups) { String[] names = g.split("\\|"); for (String n : names) COUNTRY.put(n, names[0]); }
    }

    static String country(String name) {
        return name == null ? null : COUNTRY.get(EventIdentity.normalise(name.replace("&", " and ")));
    }

    /** Structural facts of one competition name (header text or feed label). */
    static Facts facts(String competition) {
        Facts f = new Facts();
        String key = EventIdentity.competitionKey(competition);
        if (key.isEmpty()) return f;
        // glued forms: "nbii" -> "nb ii", "group1" -> "group 1", "u-19"/"u 19" -> "u19"
        key = key.replaceAll("\\b([a-z]{2,3}?)(iii|ii|iv)\\b", "$1 $2")
                 .replaceAll("\\b(group|grupo|groupe|gruppe|girone|grupa|pool)(\\d{1,2})\\b", "$1 $2")
                 .replaceAll("\\bu (1[4-9]|2[0-3])\\b", "u$1");
        // group / pool designators are the bookmaker's split of one competition, never its identity
        key = key.replaceAll("\\b(group|grupo|groupe|gruppe|girone|grupa|pool|gr)\\s+([a-z]|\\d{1,2})\\b", " ").replaceAll("\\s+", " ").trim();
        List<String> tokens = new ArrayList<>(Arrays.asList(key.split(" ")));
        // a leading country name (one to four words) is the bookmaker's prefix
        for (int n = Math.min(4, tokens.size() - 1); n >= 1; n--) {
            String head = String.join(" ", tokens.subList(0, n));
            if (COUNTRY.containsKey(head)) { f.country = COUNTRY.get(head); tokens = new ArrayList<>(tokens.subList(n, tokens.size())); break; }
        }
        for (String t : tokens) {
            if (t.isEmpty()) continue;
            if (WOMEN.contains(t) || startsWithAny(t, WOMEN_PREFIX)) { f.women = true; continue; }
            if (AGE.matcher(t).matches() || LEVEL.contains(t)) { f.level.add(t.startsWith("u") && AGE.matcher(t).matches() ? t : t.replaceAll("s$", "")); continue; }
            if (CUP.contains(t) || t.endsWith("pokal") || t.endsWith("cup")) f.cup = true;
            if (FRIENDLY.contains(t) || t.startsWith("friendl")) { f.friendly = true; continue; }
            if (FEDERATION.contains(t)) { f.federation = true; continue; }
            if (t.matches("[1-9]")) { f.tiers.add(Integer.parseInt(t)); continue; }
            if (ORDINAL.containsKey(t)) { f.tiers.add(ORDINAL.get(t)); continue; }
            Matcher glued = Pattern.compile("^([a-z]{1,3})([1-9])$").matcher(t);   // "b2", "nb1"
            if (glued.matches() && !t.startsWith("u")) {
                f.tiers.add(Integer.parseInt(glued.group(2)));
                if (glued.group(1).matches("[a-e]")) f.letters.add(glued.group(1)); else f.core.add(glued.group(1));
                continue;
            }
            if (t.matches("[a-e]")) { f.letters.add(t); continue; }
            f.core.add(t);
        }
        if (f.tiers.equals(Collections.singleton(1))) f.tiers.clear();   // "1st" / "I" / "1" = the top tier, same as unnumbered
        return f;
    }

    /** Null when the two names can denote the same competition; otherwise the structural conflict (fails closed). */
    static String conflict(String feedCompetition, String alertCountry, String pageCompetition) {
        if (EventIdentity.competitionKey(feedCompetition).isEmpty() || EventIdentity.competitionKey(pageCompetition).isEmpty())
            return "competition unknown on one side";
        Facts feed = facts(feedCompetition), page = facts(pageCompetition);
        List<String> out = new ArrayList<>();
        if (feed.women != page.women) out.add("gender (women's " + (feed.women ? "feed only" : "page only") + ")");
        if (!feed.level.equals(page.level)) out.add("age/reserve level " + feed.level + " vs " + page.level);
        if (!feed.tiers.equals(page.tiers)) out.add("tier " + tier(feed) + " vs " + tier(page));
        if (!feed.letters.equals(page.letters)) out.add("tier letter " + feed.letters + " vs " + page.letters);
        if (feed.cup != page.cup) out.add("cup vs league");
        if (feed.friendly != page.friendly) out.add("friendly vs competitive");
        if (feed.federation != page.federation) out.add("federation (RFEF) qualifier on one side only");
        String expected = country(alertCountry);
        for (Facts x : Arrays.asList(feed, page))
            if (x.country != null && expected != null && !x.country.equals(expected)) out.add("country " + x.country + " vs alert " + expected);
        if (feed.country != null && page.country != null && !feed.country.equals(page.country)) out.add("country " + feed.country + " vs " + page.country);
        return out.isEmpty() ? null : String.join("; ", out);
    }

    static String describe(String feedCompetition, String pageCompetition) {
        return "feed {" + facts(feedCompetition).describe() + "} page {" + facts(pageCompetition).describe() + "}";
    }

    private static String tier(Facts f) { return f.tiers.isEmpty() ? "top" : f.tiers.toString(); }

    private static boolean startsWithAny(String t, String[] prefixes) {
        for (String p : prefixes) if (t.startsWith(p)) return true;
        return false;
    }
}
