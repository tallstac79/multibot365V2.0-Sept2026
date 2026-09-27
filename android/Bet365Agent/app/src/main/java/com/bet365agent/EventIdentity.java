package com.bet365agent;

import java.text.Normalizer;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Event identity resolver (Milestone B; event-level evidence since 0.9.25). Identifies EVENTS, not strings.
 *
 * Team names are compared in layers, strongest first:
 *   EXACT      the same after Unicode NFKC (ligatures), case and whitespace normalisation
 *   CANONICAL  the same sorted tokens after diacritics, punctuation, slash/hyphen separators and safe club
 *              affixes (FC, BC, KC, AC ...) are removed ("Besancon AC" / "Besancon")
 *   ALIAS      equal through the explicit alias registry (TeamAliases) or aliases supplied with the instruction
 *   VARIANT    deterministic token evidence (compareTokens): every distinctive token of the shorter name is
 *              explained by the longer one (same token, plural, "Sky Gunners"/"Skygunners" split, initials or
 *              an abbreviation), or the whole single-token names agree letter for letter >= 0.80. ONE signal:
 *              a variant is never enough on its own.
 *   WEAK       partial resemblance (a shared nickname next to an unexplained token: "Samsung Thunders" /
 *              "Seoul Thunders"; a prefix: "Lyon" / "LYONSO"). Never accepted; keeps the event AMBIGUOUS
 *              (alias review) instead of calling it a different event.
 * Protected markers (women, reserves, U21 ..., II/B, academy, youth) must agree on both sides or the team
 * is a MISMATCH whatever the letters say. Two different club-family prefixes (Real / Atletico, Hapoel /
 * Maccabi, United / City) are two different clubs.
 *
 * Event verdicts: EXACT, CANONICAL_MATCH, ALIAS_MATCH (both teams at that level or better),
 * HIGH_CONFIDENCE_EVENT_MATCH (the page was opened from the alert's own Bet365 event link, the kick-off agrees
 * (exact or within KICKOFF_TOLERANCE_MINUTES), HOME/AWAY orientation agrees, no protected-marker conflict, and
 * either one team is ALIAS-or-better with the other a strong VARIANT, or BOTH teams carry deterministic
 * token-level evidence - "Atletico Boca Juniors v Tigers" against "Boca Juniors v RSSB Tigers"), AMBIGUOUS
 * (compatible names without that corroboration, WEAK evidence, or an undecidable orientation) and MISMATCH
 * (sport, kick-off, markers, family prefix, wrong opponent, reversed home/away). resolveVerified adds the
 * production gate: known agreeing kick-off AND a deterministic competition match. Every result carries an
 * evidence log (event anchor, sport, competition, kick-off, both similarities, markers, orientation, policy).
 * Nothing here creates aliases: a nickname contained in a longer bookmaker name ("Tigers" in "RSSB Tigers")
 * is event-scoped evidence and is never proposed as an alias candidate.
 * Pure Java: JVM tests EventIdentityTest / EventEvidenceTest / EventIdentityCorpusTest.
 */
final class EventIdentity {
    enum Level { NONE, WEAK, VARIANT, ALIAS, CANONICAL, EXACT }
    enum Verdict { EXACT, CANONICAL_MATCH, ALIAS_MATCH, HIGH_CONFIDENCE_EVENT_MATCH, AMBIGUOUS, MISMATCH }

    static final double STRONG = 0.70, DETERMINISTIC = 0.85;
    /** Scheduled starts this close (minutes, UK display time) are the same kick-off. */
    static final int KICKOFF_TOLERANCE_MINUTES = 5;

    /** Safe club affix tokens: removable without changing which club is meant. */
    private static final Set<String> AFFIX = new HashSet<>(Arrays.asList("fc", "bc", "bk", "kk", "cf", "cd", "sc", "ac", "kc",
            "ks", "sk", "fk", "nk", "hc", "cb", "ec", "sv", "as", "kd", "hjk", "club", "cs", "ss"));
    /** Descriptor words that carry no identity: ignored on either side. */
    private static final Set<String> GENERIC = new HashSet<>(Arrays.asList("basket", "basketball", "club", "team", "sport",
            "sports", "college", "university", "de", "du", "da", "do", "dos", "das", "la", "le", "les", "el", "los", "las", "the",
            "of", "and", "y", "e", "san", "santa", "santo"));
    /** Club-family / civic prefixes shared by many clubs: no credit on their own; ignorable when only one side has
     *  one ("Atletico Boca Juniors" / "Boca Juniors"); two DIFFERENT ones are two different clubs. */
    private static final Set<String> FAMILY = new HashSet<>(Arrays.asList("real", "atletico", "atletic", "athletic", "sporting",
            "deportivo", "hapoel", "maccabi", "elitzur", "ironi", "bnei", "dinamo", "dynamo", "spartak", "lokomotiv", "olimpia",
            "olimpija", "union", "racing", "nacional", "independiente", "estudiantes", "universitario", "universidad", "united",
            "city", "town"));
    /** Protected markers: these distinguish teams and must agree on both sides. */
    private static final Pattern WOMEN = Pattern.compile("^(w|women|womens|ladies|female|femenino|feminin|feminino|damen|dames|fem)$");
    private static final Pattern AGE = Pattern.compile("^(u1[5-9]|u2[0-3]|u-1[5-9]|u-2[0-3])$");
    private static final Pattern RESERVE = Pattern.compile("^(ii|iii|b|reserve|reserves|res|academy|youth|junior|juniors|jr|colts|development|dev|amateur|amateurs)$");
    /** Token-level evidence kinds: deterministic enough to carry an event match when both teams have one. */
    private static final Set<String> TOKEN_KINDS = new HashSet<>(Arrays.asList("tokens_equal", "token_containment", "token_split",
            "abbreviation", "women_marker_from_competition"));

    static final class Side {
        final String feed, bookmaker; final Level level; final double score; final boolean markersAgree; final String note;
        /** How the names relate: exact | canonical | registry_alias | instruction_alias | tokens_equal | token_containment |
         *  token_split | abbreviation | letters | prefix | partial | family_conflict | markers_conflict | none. */
        final String kind;
        /** The bookmaker's women's marker was supplied by the competition (feed name had none): never above VARIANT. */
        final boolean markerFromCompetition;
        /** False when the bookmaker name carries distinctive tokens the feed name lacks ("Tigers" in "RSSB Tigers"):
         *  event-scoped evidence only, never an alias candidate. */
        final boolean aliasSafe;
        Side(String feed, String bookmaker, Level level, double score, boolean markersAgree, String note) {
            this(feed, bookmaker, level, score, markersAgree, note, kindFor(level), false, true);
        }
        Side(String feed, String bookmaker, Level level, double score, boolean markersAgree, String note, String kind,
             boolean markerFromCompetition, boolean aliasSafe) {
            this.feed = feed; this.bookmaker = bookmaker; this.level = level; this.score = score; this.markersAgree = markersAgree;
            this.note = note; this.kind = kind; this.markerFromCompetition = markerFromCompetition; this.aliasSafe = aliasSafe;
        }
        private static String kindFor(Level l) { return l == Level.EXACT ? "exact" : l == Level.CANONICAL ? "canonical" : l == Level.ALIAS ? "alias" : "none"; }
        boolean atLeast(Level l) { return level.ordinal() >= l.ordinal(); }
        boolean tokenEvidence() { return level == Level.VARIANT && TOKEN_KINDS.contains(kind) && score >= DETERMINISTIC; }
        Map<String, Object> log() {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("feed", feed); m.put("bookmaker", bookmaker); m.put("level", level.name()); m.put("kind", kind);
            m.put("score", Math.round(score * 100) / 100.0); m.put("note", note);
            return m;
        }
    }

    /** One side's view of an event. kickoffUk: as Bet365 shows it ("25 Sep 10:35"); the feed's UTC time is
     *  converted by the caller. anchored: the page was opened from the alert's own Bet365 event link. */
    static final class Event {
        final String sport, home, away, kickoffUk, competition; final boolean anchored;
        Event(String sport, String home, String away, String kickoffUk, String competition, boolean anchored) {
            this.sport = sport; this.home = home; this.away = away; this.kickoffUk = kickoffUk; this.competition = competition; this.anchored = anchored;
        }
    }

    static final class Result {
        final Verdict verdict; final String reason; final Side home, away; final boolean kickoffAgrees, kickoffKnown, reversed;
        final Map<String, String> aliasCandidates;   // feed name -> bookmaker name for alias-safe VARIANT sides
        final String candidateConfidence;            // deterministic | high | review | null
        /** Evidence log: event_id_match, event_anchor, sport_match, competition_match, kickoff_match, home_similarity,
         *  away_similarity, protected_markers, orientation, competing_event, policy. */
        final Map<String, Object> evidence;
        Result(Verdict verdict, String reason, Side home, Side away, boolean kickoffKnown, boolean kickoffAgrees, boolean reversed,
               Map<String, String> aliasCandidates, String candidateConfidence, Map<String, Object> evidence) {
            this.verdict = verdict; this.reason = reason; this.home = home; this.away = away; this.kickoffKnown = kickoffKnown;
            this.kickoffAgrees = kickoffAgrees; this.reversed = reversed; this.aliasCandidates = aliasCandidates;
            this.candidateConfidence = candidateConfidence; this.evidence = evidence;
            evidence.put("verdict", verdict.name());
        }
        boolean accepted() {
            return verdict == Verdict.EXACT || verdict == Verdict.CANONICAL_MATCH || verdict == Verdict.ALIAS_MATCH
                    || verdict == Verdict.HIGH_CONFIDENCE_EVENT_MATCH;
        }
    }

    private EventIdentity() {}

    // ------------------------------------------------------------------ text normalisation (B2)
    /** NFKC (ligatures), lower case, whitespace collapsed; punctuation kept (alias registry keys use it). */
    static String plain(String s) {
        if (s == null) return "";
        return Normalizer.normalize(s, Normalizer.Form.NFKC).toLowerCase(Locale.US).trim().replaceAll("\\s+", " ");
    }

    /** plain + diacritics stripped + every non-alphanumeric run (punctuation, slash, hyphen) as one space. */
    static String normalise(String s) {
        String t = Normalizer.normalize(plain(s), Normalizer.Form.NFD).replaceAll("\\p{M}+", "");
        return t.replaceAll("[^a-z0-9]+", " ").trim().replaceAll("\\bu ([12][0-9])\\b", "u$1");
    }

    private static boolean markerToken(String t) {
        return WOMEN.matcher(t).matches() || AGE.matcher(t).matches() || RESERVE.matcher(t).matches();
    }

    static Set<String> markers(String normalised) {
        Set<String> out = new TreeSet<>();
        for (String t : normalised.split(" ")) {
            if (t.isEmpty()) continue;
            if (WOMEN.matcher(t).matches()) out.add("women");
            else if (AGE.matcher(t).matches()) out.add(t.replace("-", ""));
            else if (RESERVE.matcher(t).matches()) out.add(t.matches("res|reserves") ? "reserve" :
                    t.matches("jr|juniors") ? "junior" : t.equals("dev") ? "development" :
                    t.equals("amateurs") ? "amateur" : t);
        }
        return out;
    }

    /** Sorted tokens without safe affixes (and without the marker tokens, which are compared separately). */
    static String canonicalTokens(String normalised) {
        List<String> keep = new ArrayList<>();
        for (String t : normalised.split(" ")) {
            if (t.isEmpty() || AFFIX.contains(t) || markerToken(t)) continue;
            keep.add(t);
        }
        Collections.sort(keep);
        return String.join(" ", keep);
    }

    // ------------------------------------------------------------------ token evidence
    /** Deterministic token-level comparison of two normalised names. */
    static final class TokenEvidence {
        final String kind; final double score; final Level level; final String note;
        final List<String> shared, unexplained, extra;
        /** The longer name (the one with tokens to spare) is the second argument (the bookmaker's). */
        final boolean extraOnSecond;
        TokenEvidence(String kind, double score, Level level, String note, List<String> shared, List<String> unexplained,
                      List<String> extra, boolean extraOnSecond) {
            this.kind = kind; this.score = score; this.level = level; this.note = note; this.shared = shared;
            this.unexplained = unexplained; this.extra = extra; this.extraOnSecond = extraOnSecond;
        }
    }

    /** Tokens that can identify the club: affixes and protected-marker tokens removed, order kept. */
    private static List<String> identityTokens(String normalised) {
        List<String> out = new ArrayList<>();
        for (String t : normalised.split(" ")) if (!t.isEmpty() && !AFFIX.contains(t) && !markerToken(t)) out.add(t);
        return out;
    }

    private static List<String> distinctive(List<String> tokens) {
        List<String> out = new ArrayList<>();
        for (String t : tokens) if (!GENERIC.contains(t) && !FAMILY.contains(t)) out.add(t);
        return out;
    }

    private static Set<String> family(List<String> tokens) {
        Set<String> out = new TreeSet<>();
        for (String t : tokens) if (FAMILY.contains(t)) out.add(t);
        return out;
    }

    private static boolean plural(String a, String b) {
        String s = a.length() < b.length() ? a : b, l = a.length() < b.length() ? b : a;
        return s.length() >= 4 && l.equals(s + "s");
    }

    /** t is an abbreviation of u (or u of t): the shorter is a same-initial subsequence of the longer, >= 3 letters and at
     *  least 3 letters shorter ("jlm" / "jerusalem"), and not a plain prefix (a prefix is a stem or a weak prefix, below).
     *  A one-letter drop ("besancn" / "besancon") is a typo, judged by letters(), not an abbreviation. */
    private static boolean abbreviation(String t, String u) {
        String s = t.length() <= u.length() ? t : u, l = t.length() <= u.length() ? u : t;
        if (s.length() < 3 || l.length() - s.length() < 3 || s.charAt(0) != l.charAt(0) || !s.matches("[a-z]+") || l.startsWith(s)) return false;
        int j = 0;
        for (int i = 0; i < l.length() && j < s.length(); i++) if (l.charAt(i) == s.charAt(j)) j++;
        return j == s.length();
    }

    /** Inflected stem: one is a prefix of the other and nearly all of it ("sopron" / "soproni" 0.86). Returns the ratio or 0. */
    private static double stem(String t, String u) {
        String s = t.length() <= u.length() ? t : u, l = t.length() <= u.length() ? u : t;
        if (s.length() < 4 || s.equals(l) || !l.startsWith(s)) return 0;
        double ratio = (double) s.length() / l.length();
        return ratio >= DETERMINISTIC ? ratio : 0;
    }

    /** One is a prefix of the other: >= 4 letters shared, at most 3 left over ("lyon" / "lyonso"). Weak evidence. */
    private static boolean prefix(String t, String u) {
        String s = t.length() <= u.length() ? t : u, l = t.length() <= u.length() ? u : t;
        return s.length() >= 4 && l.length() - s.length() <= 3 && l.startsWith(s) && !s.equals(l);
    }

    private static double letters(String t, String u) {
        if (t.length() < 5 || u.length() < 5) return 0;
        return (double) lcs(t, u) / Math.max(t.length(), u.length());
    }

    /** t == the concatenation of 2..3 consecutive unused tokens of l starting anywhere; returns the run or null. */
    private static int[] concatRun(List<String> l, boolean[] used, String t) {
        for (int start = 0; start < l.size(); start++) {
            StringBuilder sb = new StringBuilder();
            for (int end = start; end < l.size() && end < start + 3; end++) {
                if (used[end]) break;
                sb.append(l.get(end));
                if (sb.length() > t.length()) break;
                if (end > start && sb.toString().equals(t)) return new int[] {start, end};
            }
        }
        return null;
    }

    /** t (2..4 letters) == the initials of 2..4 consecutive unused tokens of l; returns the run or null. */
    private static int[] initialsRun(List<String> l, boolean[] used, String t) {
        if (t.length() < 2 || t.length() > 4 || !t.matches("[a-z]+")) return null;
        for (int start = 0; start + t.length() <= l.size(); start++) {
            boolean ok = true;
            for (int k = 0; k < t.length(); k++) {
                int idx = start + k;
                if (used[idx] || l.get(idx).isEmpty() || l.get(idx).charAt(0) != t.charAt(k)) { ok = false; break; }
            }
            if (ok) return new int[] {start, start + t.length() - 1};
        }
        return null;
    }

    /**
     * Token evidence between the feed name (first) and the bookmaker name (second), both normalised. The side with fewer
     * distinctive tokens must be fully explained by the other; tokens left over on the longer side are "extra"
     * (containment). Any unexplained distinctive token on the shorter side is a conflict.
     */
    static TokenEvidence compareTokens(String normFeed, String normBook) {
        List<String> a = identityTokens(normFeed), b = identityTokens(normBook);
        List<String> da = distinctive(a), db = distinctive(b);
        Set<String> fa = family(a), fb = family(b);
        List<String> none = Collections.emptyList();
        if (da.isEmpty() || db.isEmpty()) {
            if (!fa.isEmpty() && fa.equals(fb) && da.isEmpty() && db.isEmpty())
                return new TokenEvidence("tokens_equal", 0.75, Level.VARIANT, "only family words, equal " + fa, new ArrayList<>(fa), none, none, false);
            return new TokenEvidence("none", 0, Level.NONE, "no distinctive tokens to compare", none, none, none, false);
        }
        boolean familyConflict = !fa.isEmpty() && !fb.isEmpty() && !fa.containsAll(fb) && !fb.containsAll(fa);
        boolean feedIsShort = da.size() <= db.size();
        List<String> s = feedIsShort ? a : b, l = feedIsShort ? b : a;
        Set<String> ds = new HashSet<>(feedIsShort ? da : db), dl = new HashSet<>(feedIsShort ? db : da);
        boolean[] usedS = new boolean[s.size()], usedL = new boolean[l.size()];
        List<String> shared = new ArrayList<>(), unexplained = new ArrayList<>();
        int full = 0, abbrev = 0, sharedLetters = 0; boolean split = false, fuzzyPrefix = false, stemmed = false, lettered = false; double fuzzy = 1;
        for (int i = 0; i < s.size(); i++) {
            String t = s.get(i);
            if (usedS[i] || !ds.contains(t)) continue;
            usedS[i] = true;
            int j = -1;
            for (int k = 0; k < l.size() && j < 0; k++) if (!usedL[k] && (l.get(k).equals(t) || plural(t, l.get(k)))) j = k;
            if (j >= 0) { usedL[j] = true; full++; shared.add(t); sharedLetters += t.length(); continue; }
            int[] run = concatRun(l, usedL, t);
            if (run != null) { for (int k = run[0]; k <= run[1]; k++) usedL[k] = true; full++; split = true; shared.add(t); sharedLetters += t.length(); continue; }
            // reverse split: one token of l is this token joined with the following tokens of s ("Val de Seine" -> "Valdeseine")
            StringBuilder sb = new StringBuilder(t); int endS = -1, jl = -1;
            for (int n = i + 1; n < s.size() && n < i + 3 && jl < 0; n++) {
                if (usedS[n]) break;
                sb.append(s.get(n));
                for (int k = 0; k < l.size() && jl < 0; k++) if (!usedL[k] && l.get(k).equals(sb.toString())) { jl = k; endS = n; }
            }
            if (jl >= 0) { usedL[jl] = true; for (int n = i + 1; n <= endS; n++) usedS[n] = true; full++; split = true; shared.add(l.get(jl)); sharedLetters += l.get(jl).length(); continue; }
            int[] ini = initialsRun(l, usedL, t);
            if (ini != null) { for (int k = ini[0]; k <= ini[1]; k++) usedL[k] = true; abbrev++; shared.add(t); continue; }
            j = -1;
            for (int k = 0; k < l.size() && j < 0; k++) if (!usedL[k] && dl.contains(l.get(k)) && abbreviation(t, l.get(k))) j = k;
            if (j >= 0) { usedL[j] = true; abbrev++; shared.add(t); continue; }
            j = -1; double best = 0;
            for (int k = 0; k < l.size(); k++) if (!usedL[k] && dl.contains(l.get(k))) { double r = stem(t, l.get(k)); if (r > best) { best = r; j = k; } }
            if (j >= 0) { usedL[j] = true; fuzzy = Math.min(fuzzy, best); stemmed = true; shared.add(t); continue; }
            j = -1; best = 0;
            for (int k = 0; k < l.size(); k++) if (!usedL[k] && dl.contains(l.get(k))) { double r = letters(t, l.get(k)); if (r >= 0.80 && r > best) { best = r; j = k; } }
            if (j >= 0) { usedL[j] = true; fuzzy = Math.min(fuzzy, best); lettered = true; shared.add(t); continue; }
            j = -1;
            for (int k = 0; k < l.size() && j < 0; k++) if (!usedL[k] && dl.contains(l.get(k)) && prefix(t, l.get(k))) j = k;
            if (j >= 0) { usedL[j] = true; fuzzyPrefix = true; fuzzy = Math.min(fuzzy, 0.67); shared.add(t); continue; }
            unexplained.add(t);
        }
        List<String> extra = new ArrayList<>();
        for (int k = 0; k < l.size(); k++) if (!usedL[k] && dl.contains(l.get(k))) extra.add(l.get(k));
        boolean extraOnSecond = feedIsShort && !extra.isEmpty();
        int explained = full + abbrev + (fuzzy < 1 ? 1 : 0);
        if (familyConflict) {
            Set<String> fx = new TreeSet<>(fa); fx.removeAll(fb); Set<String> fy = new TreeSet<>(fb); fy.removeAll(fa);
            return new TokenEvidence("family_conflict", 0, Level.NONE, "different club prefixes " + fx + " vs " + fy, shared, unexplained, extra, extraOnSecond);
        }
        if (!unexplained.isEmpty()) {
            if (full >= 1 && ds.size() >= 2)
                return new TokenEvidence("partial", Math.min(0.5, (double) full / ds.size()), Level.WEAK,
                        "shared " + shared + " but " + unexplained + " has no counterpart", shared, unexplained, extra, extraOnSecond);
            return new TokenEvidence("none", 0, Level.NONE, "no shared distinctive token (" + unexplained + " unexplained)", shared, unexplained, extra, extraOnSecond);
        }
        if (fuzzyPrefix)
            return new TokenEvidence("prefix", 0.67, Level.WEAK, "prefix only " + shared, shared, unexplained, extra, extraOnSecond);
        if (fuzzy < 1) {
            if (!extra.isEmpty() || explained > 1)
                return new TokenEvidence("partial", 0.5, Level.WEAK, "letters agree only for part of the name " + shared + "; extra " + extra, shared, unexplained, extra, extraOnSecond);
            String fk = stemmed && !lettered ? "stem" : "letters";
            return new TokenEvidence(fk, fuzzy, fuzzy >= STRONG ? Level.VARIANT : Level.WEAK,
                    String.format(Locale.US, "%s agree %.2f", fk.equals("stem") ? "stems" : "letters", fuzzy), shared, unexplained, extra, extraOnSecond);
        }
        if (abbrev > 0)
            return new TokenEvidence("abbreviation", 0.85, Level.VARIANT, "abbreviated tokens " + shared + (extra.isEmpty() ? "" : "; extra " + extra),
                    shared, unexplained, extra, extraOnSecond);
        double score = sharedLetters >= 4 ? 1.0 : 0.75;
        String kind = split ? "token_split" : (extra.isEmpty() && fa.equals(fb) ? "tokens_equal" : "token_containment");
        String note = extra.isEmpty() ? "distinctive tokens equal " + shared : "distinctive tokens " + shared + " contained; extra " + extra;
        if (!fa.equals(fb)) note += "; club prefix only on one side " + (fa.isEmpty() ? fb : fa);
        return new TokenEvidence(kind, score, Level.VARIANT, note, shared, unexplained, extra, extraOnSecond);
    }

    /** Controlled similarity in [0,1] (token evidence score); kept for callers of the previous API. */
    static double variantScore(String normA, String normB) { return compareTokens(normA, normB).score; }

    private static int lcs(String a, String b) {
        int[][] d = new int[a.length() + 1][b.length() + 1];
        for (int i = 1; i <= a.length(); i++)
            for (int j = 1; j <= b.length(); j++)
                d[i][j] = a.charAt(i - 1) == b.charAt(j - 1) ? d[i - 1][j - 1] + 1 : Math.max(d[i - 1][j], d[i][j - 1]);
        return d[a.length()][b.length()];
    }

    // ------------------------------------------------------------------ team level (B2, B3, B5)
    static Side matchSide(String feed, String bookmaker, Map<String, String> extraAliases) {
        return matchSide(feed, bookmaker, extraAliases, false);
    }

    /**
     * womensCompetition: the backend established the competition as women's. Then, and only then, a bookmaker
     * name carrying exactly the women's marker the feed name lacks is compared without it, capped at VARIANT
     * (the event still needs corroboration in resolve()). Any other marker difference is a MISMATCH.
     */
    static Side matchSide(String feed, String bookmaker, Map<String, String> extraAliases, boolean womensCompetition) {
        String nf = normalise(feed), nb = normalise(bookmaker);
        if (nf.isEmpty() || nb.isEmpty()) return new Side(feed, bookmaker, Level.NONE, 0, true, "empty name");
        Set<String> mf = markers(nf), mb = markers(nb);
        if (!mf.equals(mb)) {
            Set<String> mbLessWomen = new TreeSet<>(mb);
            boolean onlyWomenOnBookmaker = mbLessWomen.remove("women") && !mf.contains("women") && mbLessWomen.equals(mf);
            if (!(womensCompetition && onlyWomenOnBookmaker))
                return new Side(feed, bookmaker, Level.NONE, 0, false, "protected markers differ " + mf + " vs " + mb, "markers_conflict", false, true);
            String cf = canonicalTokens(nf), cb = canonicalTokens(nb);
            TokenEvidence te = compareTokens(nf, nb);
            double score = !cf.isEmpty() && cf.equals(cb) ? 1.0 : te.score;
            if (score < STRONG) return new Side(feed, bookmaker, Level.NONE, score, true, String.format(Locale.US, "different name %.2f (women's marker from competition)", score), "none", true, true);
            return new Side(feed, bookmaker, Level.VARIANT, score, true, String.format(Locale.US, "women's marker supplied by the competition; names agree %.2f", score),
                    "women_marker_from_competition", true, !te.extraOnSecond);
        }
        if (nf.equals(nb)) return new Side(feed, bookmaker, Level.EXACT, 1, true, "exact");
        String cf = canonicalTokens(nf), cb = canonicalTokens(nb);
        if (!cf.isEmpty() && cf.equals(cb)) return new Side(feed, bookmaker, Level.CANONICAL, 1, true, "canonical tokens equal");
        // Explicit aliases: registry (exact full-name keys) and instruction-supplied (feed -> bookmaker).
        String registryFeed = canonicalTokens(normalise(TeamAliases.canonical(plain(feed))));
        String registryBook = canonicalTokens(normalise(TeamAliases.canonical(plain(bookmaker))));
        if (!registryFeed.isEmpty() && registryFeed.equals(registryBook))
            return new Side(feed, bookmaker, Level.ALIAS, 1, true, "registry alias", "registry_alias", false, true);
        if (extraAliases != null) {
            String mapped = extraAliases.get(plain(feed));
            if (mapped != null && canonicalTokens(normalise(mapped)).equals(cb))
                return new Side(feed, bookmaker, Level.ALIAS, 1, true, "instruction alias", "instruction_alias", false, true);
        }
        TokenEvidence te = compareTokens(nf, nb);
        String note = te.level == Level.VARIANT ? String.format(Locale.US, "naming variant %.2f: %s", te.score, te.note)
                : te.level == Level.WEAK ? String.format(Locale.US, "weak resemblance %.2f: %s", te.score, te.note)
                : String.format(Locale.US, "different name %.2f: %s", te.score, te.note);
        return new Side(feed, bookmaker, te.level, te.score, true, note, te.kind, false, !te.extraOnSecond);
    }

    // ------------------------------------------------------------------ kick-off (UK display text)
    private static final Pattern UK_KICKOFF = Pattern.compile("^(\\d{1,2}) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (\\d{1,2}):(\\d{2})$", Pattern.CASE_INSENSITIVE);
    private static final int[] DAY_OF_YEAR = {0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334};
    private static final List<String> MONTHS = Arrays.asList("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec");

    /** Minutes into a nominal year for "27 Sep 07:30", or null when the text is not in Bet365's display form. */
    static Integer kickoffMinutes(String uk) {
        if (uk == null) return null;
        Matcher m = UK_KICKOFF.matcher(uk.trim());
        if (!m.matches()) return null;
        int day = Integer.parseInt(m.group(1)), month = MONTHS.indexOf(m.group(2).toLowerCase(Locale.US));
        if (day < 1 || day > 31 || month < 0) return null;
        return ((DAY_OF_YEAR[month] + day) * 24 + Integer.parseInt(m.group(3))) * 60 + Integer.parseInt(m.group(4));
    }

    /** exact | within_tolerance (+n min) | mismatch (n min) | unknown */
    static String kickoffMatch(String feedUk, String pageUk) {
        if (feedUk == null || pageUk == null) return "unknown";
        if (feedUk.trim().equalsIgnoreCase(pageUk.trim())) return "exact";
        Integer f = kickoffMinutes(feedUk), p = kickoffMinutes(pageUk);
        if (f == null || p == null) return "mismatch (texts differ: '" + feedUk + "' vs '" + pageUk + "')";
        int delta = p - f;
        if (Math.abs(delta) <= KICKOFF_TOLERANCE_MINUTES) return String.format(Locale.US, "within_tolerance (%+d min)", delta);
        return String.format(Locale.US, "mismatch (%+d min)", delta);
    }

    // ------------------------------------------------------------------ event level (B4, B8)
    private static final String MONTH_RE = "(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)";

    static String competitionKey(String value) {
        if (value == null) return "";
        // A stray leading OCR digit ("6 Japan B League 1 - 25 Sep 10:35"); competition names never start with a bare digit.
        String v = value.trim().replaceFirst("^\\d\\s+", "");
        String withoutDate = v.replaceAll("(?i)\\s+\\d{1,2}\\s+" + MONTH_RE + "[a-z]*.*$", "");
        if (withoutDate.equals(v))
            // Date glued to the league digit by OCR ("Japan B League 125 Sep 10:45"): keep the digit, drop the date.
            withoutDate = v.replaceAll("(?i)(?<=\\d)\\d{2}\\s+" + MONTH_RE + "[a-z]*.*$", "");
        String key = normalise(withoutDate);
        // Observed provider label (Seoul/Wonju) includes the global region; bookmaker omits it.
        return key.equals("world club friendlies") ? "club friendlies" : key;
    }

    /** Approved feed-label -> bookmaker-header mappings, keyed "country|feed competition" (normalised). Each entry is
     *  backed by an event page header captured on the phone; nothing here is inferred from similarity. */
    static final Map<String, String> COMPETITION_ALIASES = new HashMap<>();
    static {
        // 2026-09-26: Kotwica Kolobrzeg v Polonia Warszawa and Spojnia Stargard v Polonia Bytom, header "Poland 1st Division"
        COMPETITION_ALIASES.put("poland|1 liga", "poland 1st division");
        // 2026-09-27 04:11-04:23: Samsung/Seoul Thunders v Anyang and Suwon Sonicboom v Goyang Sky Gunners (feed "KBL Cup",
        // Korea), three event pages headed "Club Friendlies 27 Sep 06:00"
        COMPETITION_ALIASES.put("korea|kbl cup", "club friendlies");
        // The feed labels the top Japanese division "B League" (B2/B3 are labelled "B2 League"/"B3 League"); Bet365 heads
        // it "Japan B League 1" (Kyoto v Shiga 25 Sep, Saga v Hiroshima 25 Sep, Utsunomiya v Yokohama 27 Sep)
        COMPETITION_ALIASES.put("japan|b league", "japan b league 1");
    }
    /** Governing bodies Bet365 prefixes to a competition the feed names without one ("FIBA Intercontinental Cup"). */
    private static final List<String> BODY_PREFIXES = Arrays.asList("fiba", "fifa", "uefa", "concacaf", "conmebol", "afc", "caf");

    /** equal | country_prefixed | body_prefixed (x) | approved_mapping (key) | unknown | mismatch (feed vs page) */
    static String competitionMatchKind(String feedCompetition, String country, String pageCompetition) {
        String fc = competitionKey(feedCompetition), pc = competitionKey(pageCompetition), ck = normalise(country);
        if (fc.isEmpty() || pc.isEmpty()) return "unknown (feed '" + fc + "', page '" + pc + "')";
        if (fc.equals(pc)) return "equal";
        if (!ck.isEmpty() && pc.equals(ck + " " + fc)) return "country_prefixed";
        for (String body : BODY_PREFIXES) if (pc.equals(body + " " + fc)) return "body_prefixed (" + body + ")";
        String approved = ck.isEmpty() ? null : COMPETITION_ALIASES.get(ck + "|" + fc);
        if (approved != null && approved.equals(pc)) return "approved_mapping (" + ck + "|" + fc + " -> " + pc + ")";
        return "mismatch (feed '" + fc + "' vs page '" + pc + "')";
    }

    /** Deterministic competition match: equal keys; the bookmaker's country- or body-prefixed form of the feed label
     *  ("Mexico Liga ABE", "FIBA Intercontinental Cup"); or an approved mapping scoped by country. Anything else is a mismatch. */
    static boolean competitionMatches(String feedCompetition, String country, String pageCompetition) {
        String kind = competitionMatchKind(feedCompetition, country, pageCompetition);
        return !kind.startsWith("mismatch") && !kind.startsWith("unknown");
    }

    /** Production gate: naming similarity alone never establishes event identity. */
    static Result resolveVerified(Event feed, Event page, Map<String,String> aliases, boolean women) {
        return resolveVerified(feed, page, aliases, women, null);
    }

    static Result resolveVerified(Event feed, Event page, Map<String,String> aliases, boolean women, String country) {
        Result r = resolve(feed, page, aliases, women);
        String competition = competitionMatchKind(feed.competition, country, page.competition);
        r.evidence.put("competition_match", competition);
        if (!r.accepted()) return r;
        boolean competitionOk = !competition.startsWith("mismatch") && !competition.startsWith("unknown");
        if (!r.kickoffKnown || !r.kickoffAgrees || !competitionOk) {
            List<String> missing = new ArrayList<>();
            if (!r.kickoffKnown) missing.add("kick-off unknown");
            else if (!r.kickoffAgrees) missing.add("kick-off differs");
            if (!competitionOk) missing.add("competition " + competition);
            r.evidence.put("policy", "verified_gate_failed");
            return new Result(Verdict.AMBIGUOUS, "Known matching kick-off and competition required (" + String.join("; ", missing) + ")", r.home, r.away,
                    r.kickoffKnown, r.kickoffAgrees, false, Collections.emptyMap(), null, r.evidence);
        }
        return r;
    }

    static Result resolve(Event feed, Event page, Map<String, String> extraAliases) {
        return resolve(feed, page, extraAliases, false);
    }

    private static String fmt(double v) { return String.format(Locale.US, "%.2f", v); }

    static Result resolve(Event feed, Event page, Map<String, String> extraAliases, boolean womensCompetition) {
        Map<String, Object> ev = new LinkedHashMap<>();
        ev.put("event_id_match", page.anchored);
        ev.put("event_anchor", page.anchored ? "page opened from the alert's own Bet365 event link" : "none (search result or unanchored page)");
        boolean sportKnown = feed.sport != null && page.sport != null;
        boolean sportOk = !sportKnown || feed.sport.equalsIgnoreCase(page.sport);
        ev.put("sport_match", sportKnown ? (sportOk ? "equal" : "mismatch (" + feed.sport + " vs " + page.sport + ")") : "unknown");
        String ko = kickoffMatch(feed.kickoffUk, page.kickoffUk);
        boolean koKnown = feed.kickoffUk != null && page.kickoffUk != null;
        boolean koAgrees = koKnown && (ko.equals("exact") || ko.startsWith("within_tolerance"));
        ev.put("kickoff_match", ko);
        ev.put("competition_match", "not checked (resolve)");
        ev.put("competing_event", page.anchored ? "none: a single event page reached through the alert's own link" : "not excluded: no event anchor");
        Map<String, String> none = Collections.emptyMap();
        if (!sportOk) {
            ev.put("policy", "sport");
            return new Result(Verdict.MISMATCH, "sport differs: " + feed.sport + " vs " + page.sport, null, null, koKnown, koAgrees, false, none, null, ev);
        }
        Side h = matchSide(feed.home, page.home, extraAliases, womensCompetition), a = matchSide(feed.away, page.away, extraAliases, womensCompetition);
        ev.put("home_similarity", h.log());
        ev.put("away_similarity", a.log());
        ev.put("protected_markers", h.markersAgree && a.markersAgree ? "agree" : "conflict: " + (!h.markersAgree ? h.note : a.note));
        // Orientation: a reversed pairing is never accepted (a HOME/AWAY selection would land on the other team), and a
        // pairing that also reads plausibly the other way round is undecidable.
        boolean straight = h.atLeast(Level.VARIANT) && a.atLeast(Level.VARIANT);
        Side hs = matchSide(feed.home, page.away, extraAliases, womensCompetition), as = matchSide(feed.away, page.home, extraAliases, womensCompetition);
        boolean crossed = hs.atLeast(Level.VARIANT) && as.atLeast(Level.VARIANT);
        if (!straight && crossed) {
            ev.put("orientation", "reversed");
            ev.put("crossed_similarity", hs.kind + " " + fmt(hs.score) + " / " + as.kind + " " + fmt(as.score));
            ev.put("policy", "orientation");
            return new Result(Verdict.MISMATCH, "teams reversed (home/away): '" + feed.home + " v " + feed.away + "' is listed as '"
                    + page.home + " v " + page.away + "'", h, a, koKnown, koAgrees, true, none, null, ev);
        }
        if (!h.markersAgree || !a.markersAgree) {
            Side bad = !h.markersAgree ? h : a;
            ev.put("orientation", "not established");
            ev.put("policy", "protected_markers");
            return new Result(Verdict.MISMATCH, "'" + bad.feed + "' vs '" + bad.bookmaker + "': " + bad.note, h, a, koKnown, koAgrees, false, none, null, ev);
        }
        if (straight && crossed) {
            ev.put("orientation", "ambiguous (both pairings read plausibly)");
            ev.put("policy", "orientation");
            return new Result(Verdict.AMBIGUOUS, "home/away orientation undecidable: the names also pair the other way round", h, a, koKnown, koAgrees, false, none, "review", ev);
        }
        ev.put("orientation", straight ? "agree" : "not established");
        if (koKnown && !koAgrees) {
            ev.put("policy", "kickoff");
            return new Result(Verdict.MISMATCH, "kick-off differs: alert " + feed.kickoffUk + " vs page " + page.kickoffUk + " (UK, " + ko + ")", h, a, koKnown, false, false, none, null, ev);
        }
        Level lo = h.level.ordinal() <= a.level.ordinal() ? h.level : a.level;
        Level hi = h.level.ordinal() >= a.level.ordinal() ? h.level : a.level;
        if (lo == Level.EXACT) { ev.put("policy", "both_exact"); return new Result(Verdict.EXACT, "both teams exact", h, a, koKnown, koAgrees, false, none, null, ev); }
        if (lo == Level.CANONICAL) { ev.put("policy", "both_canonical"); return new Result(Verdict.CANONICAL_MATCH, "both teams canonical", h, a, koKnown, koAgrees, false, none, null, ev); }
        if (lo == Level.ALIAS) { ev.put("policy", "both_alias"); return new Result(Verdict.ALIAS_MATCH, "both teams via aliases", h, a, koKnown, koAgrees, false, none, null, ev); }
        String anchorText = "event link + kick-off " + page.kickoffUk + (ko.equals("exact") ? "" : " (" + ko + ")");
        if (lo == Level.VARIANT && hi.ordinal() >= Level.ALIAS.ordinal()) {
            Side v = h.level == Level.VARIANT ? h : a;
            Map<String, String> cand = new LinkedHashMap<>();
            if (v.aliasSafe) cand.put(v.feed, v.bookmaker);
            if (page.anchored && koAgrees) {
                String conf = v.score >= DETERMINISTIC ? "deterministic" : "high";
                ev.put("policy", "one_sure_team_plus_variant");
                return new Result(Verdict.HIGH_CONFIDENCE_EVENT_MATCH, anchorText + " + '" + (v == h ? a.feed : h.feed) + "' " + (v == h ? a.kind : h.kind)
                        + "; '" + v.feed + "' is a naming variant of '" + v.bookmaker + "' (" + v.kind + " " + fmt(v.score) + ")", h, a, koKnown, koAgrees, false, cand, conf, ev);
            }
            ev.put("policy", "variant_without_anchor");
            return new Result(Verdict.AMBIGUOUS, "'" + v.feed + "' only resembles '" + v.bookmaker + "' (" + v.kind + " " + fmt(v.score)
                    + ") and there is no event anchor with an agreeing kick-off", h, a, koKnown, koAgrees, false, cand, "review", ev);
        }
        if (lo == Level.VARIANT) {
            // Both names are variants of the page's. Deterministic token-level evidence on BOTH sides, the alert's own event
            // link and an agreeing kick-off identify the event without either team being exact.
            Map<String, String> cand = new LinkedHashMap<>();
            if (h.aliasSafe) cand.put(h.feed, h.bookmaker);
            if (a.aliasSafe) cand.put(a.feed, a.bookmaker);
            if (h.tokenEvidence() && a.tokenEvidence() && page.anchored && koAgrees) {
                ev.put("policy", "event_evidence_both_variants");
                String women = h.markerFromCompetition || a.markerFromCompetition ? " + women's competition supplies Bet365's (W)" : "";
                return new Result(Verdict.HIGH_CONFIDENCE_EVENT_MATCH, anchorText + women + " + both names compatible: '" + h.feed + "' ~ '" + h.bookmaker
                        + "' (" + h.kind + " " + fmt(h.score) + "); '" + a.feed + "' ~ '" + a.bookmaker + "' (" + a.kind + " " + fmt(a.score) + ")",
                        h, a, koKnown, koAgrees, false, cand, "deterministic", ev);
            }
            List<String> why = new ArrayList<>();
            if (!page.anchored) why.add("no event anchor");
            else if (!koAgrees) why.add(koKnown ? "kick-off differs" : "kick-off unknown");
            if (!h.tokenEvidence()) why.add("'" + h.feed + "' vs '" + h.bookmaker + "' rests on " + h.kind + " " + fmt(h.score) + " only");
            if (!a.tokenEvidence()) why.add("'" + a.feed + "' vs '" + a.bookmaker + "' rests on " + a.kind + " " + fmt(a.score) + " only");
            ev.put("policy", "both_variants_without_deterministic_evidence");
            return new Result(Verdict.AMBIGUOUS, "both names only resemble the page's names and the event evidence is not deterministic: "
                    + String.join("; ", why), h, a, koKnown, koAgrees, false, cand, "review", ev);
        }
        if (lo == Level.WEAK) {
            Side w = h.level == Level.WEAK ? h : a;
            ev.put("policy", "weak_resemblance");
            return new Result(Verdict.AMBIGUOUS, "'" + w.feed + "' only partly resembles '" + w.bookmaker + "' (" + w.note + "); not a different event, not proven the same",
                    h, a, koKnown, koAgrees, false, none, "review", ev);
        }
        Side bad = h.level == Level.NONE ? h : a;
        ev.put("policy", "different_team");
        return new Result(Verdict.MISMATCH, "'" + bad.feed + "' is not '" + bad.bookmaker + "' (" + bad.note + ")", h, a, koKnown, koAgrees, false, none, null, ev);
    }

    static Map<String, String> aliasesFromJson(String json) {
        Map<String, String> out = new HashMap<>();
        if (json == null || json.trim().isEmpty()) return out;
        try {
            org.json.JSONObject o = new org.json.JSONObject(json);
            for (java.util.Iterator<String> it = o.keys(); it.hasNext(); ) { String k = it.next(); out.put(plain(k), o.getString(k)); }
        } catch (Exception ignored) {}
        return out;
    }
}
