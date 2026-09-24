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
import java.util.regex.Pattern;

/**
 * Event identity resolver (Milestone B). Identifies EVENTS, not strings: sport, both teams, their pairing
 * and the kick-off, using the alert's own Bet365 event link as the anchor when it resolved.
 *
 * Team names are compared in layers, strongest first:
 *   EXACT      the same after Unicode NFKC (ligatures), case and whitespace normalisation
 *   CANONICAL  the same sorted tokens after diacritics, punctuation, slash/hyphen separators and safe club
 *              affixes (FC, BC, KC, AC ...) are removed ("Besancon AC" / "Besancon")
 *   ALIAS      equal through the explicit alias registry (TeamAliases) or aliases supplied with the instruction
 *   VARIANT    a controlled fuzzy score >= 0.70 (shared significant token, or letters of the non-generic
 *              tokens agree; "Soproni KC" / "Sopron KC") - ONE signal, never enough on its own
 * Protected markers (women, reserves, U21 ..., II/B, academy, youth) must agree on both sides or the team
 * is a MISMATCH whatever the letters say.
 *
 * Event verdicts: EXACT, CANONICAL_MATCH, ALIAS_MATCH (both teams at that level or better),
 * HIGH_CONFIDENCE_EVENT_MATCH (page opened from the alert's own link, kick-off agrees, one team ALIAS or
 * better, the other a strong VARIANT with agreeing markers -> accepted, and the variant becomes an alias
 * candidate), AMBIGUOUS (a variant without that corroboration, or both teams only variants) and
 * MISMATCH (sport, kick-off, markers, wrong opponent, reversed home/away). Anything but the first four
 * fails closed with an explicit reason. Pure Java: JVM tests EventIdentityTest / EventIdentityCorpusTest.
 */
final class EventIdentity {
    enum Level { NONE, VARIANT, ALIAS, CANONICAL, EXACT }
    enum Verdict { EXACT, CANONICAL_MATCH, ALIAS_MATCH, HIGH_CONFIDENCE_EVENT_MATCH, AMBIGUOUS, MISMATCH }

    static final double STRONG = 0.70, DETERMINISTIC = 0.85;

    /** Safe club affix tokens: removable without changing which club is meant. */
    private static final Set<String> AFFIX = new HashSet<>(Arrays.asList("fc", "bc", "bk", "kk", "cf", "cd", "sc", "ac", "kc",
            "ks", "sk", "fk", "nk", "hc", "cb", "ec", "sv", "as", "kd", "hjk", "club", "cs", "ss"));
    /** Tokens too generic to identify a club on their own (fuzzy scoring ignores them). */
    private static final Set<String> GENERIC = new HashSet<>(Arrays.asList("basket", "basketball", "club", "team", "sport",
            "sports", "united", "city", "town", "real", "athletic", "atletico", "academy", "college", "university", "de", "du",
            "la", "le", "les", "el", "los", "the", "of"));
    /** Protected markers: these distinguish teams and must agree on both sides. */
    private static final Pattern WOMEN = Pattern.compile("^(w|women|womens|ladies|female|femenino|feminin|feminino|damen|dames|fem)$");
    private static final Pattern AGE = Pattern.compile("^(u1[5-9]|u2[0-3]|u-1[5-9]|u-2[0-3])$");
    private static final Pattern RESERVE = Pattern.compile("^(ii|iii|b|reserve|reserves|res|academy|youth|junior|juniors|jr|colts|development|dev|amateur|amateurs)$");

    static final class Side {
        final String feed, bookmaker; final Level level; final double score; final boolean markersAgree; final String note;
        Side(String feed, String bookmaker, Level level, double score, boolean markersAgree, String note) {
            this.feed = feed; this.bookmaker = bookmaker; this.level = level; this.score = score; this.markersAgree = markersAgree; this.note = note;
        }
        boolean atLeast(Level l) { return level.ordinal() >= l.ordinal(); }
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
        final Map<String, String> aliasCandidates;   // feed name -> bookmaker name for VARIANT sides
        final String candidateConfidence;            // deterministic | high | review | null
        Result(Verdict verdict, String reason, Side home, Side away, boolean kickoffKnown, boolean kickoffAgrees, boolean reversed,
               Map<String, String> aliasCandidates, String candidateConfidence) {
            this.verdict = verdict; this.reason = reason; this.home = home; this.away = away; this.kickoffKnown = kickoffKnown;
            this.kickoffAgrees = kickoffAgrees; this.reversed = reversed; this.aliasCandidates = aliasCandidates; this.candidateConfidence = candidateConfidence;
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
        return t.replaceAll("[^a-z0-9]+", " ").trim();
    }

    static Set<String> markers(String normalised) {
        Set<String> out = new TreeSet<>();
        for (String t : normalised.split(" ")) {
            if (t.isEmpty()) continue;
            if (WOMEN.matcher(t).matches()) out.add("women");
            else if (AGE.matcher(t).matches()) out.add(t.replace("-", ""));
            else if (RESERVE.matcher(t).matches()) out.add("reserve");
        }
        return out;
    }

    /** Sorted tokens without safe affixes (and without the marker tokens, which are compared separately). */
    static String canonicalTokens(String normalised) {
        List<String> keep = new ArrayList<>();
        for (String t : normalised.split(" ")) {
            if (t.isEmpty() || AFFIX.contains(t)) continue;
            if (WOMEN.matcher(t).matches() || AGE.matcher(t).matches() || RESERVE.matcher(t).matches()) continue;
            keep.add(t);
        }
        Collections.sort(keep);
        return String.join(" ", keep);
    }

    private static List<String> significant(String normalised) {
        List<String> out = new ArrayList<>();
        for (String t : normalised.split(" ")) if (t.length() >= 3 && !AFFIX.contains(t) && !GENERIC.contains(t)) out.add(t);
        return out;
    }

    /** Controlled fuzzy score in [0,1]: shared significant token, or letter agreement of the non-generic tokens. */
    static double variantScore(String normA, String normB) {
        List<String> ta = significant(normA), tb = significant(normB);
        if (ta.isEmpty() || tb.isEmpty()) return 0;
        Set<String> sa = new HashSet<>(ta), sb = new HashSet<>(tb);
        double shared = 0;
        for (String t : sa) if (sb.contains(t) && t.length() >= 4) shared = 1;   // one shared distinguishing word
        String la = String.join("", ta), lb = String.join("", tb);
        double letters = la.length() < 4 || lb.length() < 4 ? 0 : (double) lcs(la, lb) / Math.max(la.length(), lb.length());
        return Math.max(shared, letters);
    }

    private static int lcs(String a, String b) {
        int[][] d = new int[a.length() + 1][b.length() + 1];
        for (int i = 1; i <= a.length(); i++)
            for (int j = 1; j <= b.length(); j++)
                d[i][j] = a.charAt(i - 1) == b.charAt(j - 1) ? d[i - 1][j - 1] + 1 : Math.max(d[i - 1][j], d[i][j - 1]);
        return d[a.length()][b.length()];
    }

    // ------------------------------------------------------------------ team level (B2, B3, B5)
    static Side matchSide(String feed, String bookmaker, Map<String, String> extraAliases) {
        String nf = normalise(feed), nb = normalise(bookmaker);
        if (nf.isEmpty() || nb.isEmpty()) return new Side(feed, bookmaker, Level.NONE, 0, true, "empty name");
        Set<String> mf = markers(nf), mb = markers(nb);
        if (!mf.equals(mb)) return new Side(feed, bookmaker, Level.NONE, 0, false, "protected markers differ " + mf + " vs " + mb);
        if (nf.equals(nb)) return new Side(feed, bookmaker, Level.EXACT, 1, true, "exact");
        String cf = canonicalTokens(nf), cb = canonicalTokens(nb);
        if (!cf.isEmpty() && cf.equals(cb)) return new Side(feed, bookmaker, Level.CANONICAL, 1, true, "canonical tokens equal");
        // Explicit aliases: registry (exact full-name keys) and instruction-supplied (feed -> bookmaker).
        String registryFeed = canonicalTokens(normalise(TeamAliases.canonical(plain(feed))));
        String registryBook = canonicalTokens(normalise(TeamAliases.canonical(plain(bookmaker))));
        if (!registryFeed.isEmpty() && registryFeed.equals(registryBook)) return new Side(feed, bookmaker, Level.ALIAS, 1, true, "registry alias");
        if (extraAliases != null) {
            String mapped = extraAliases.get(plain(feed));
            if (mapped != null && canonicalTokens(normalise(mapped)).equals(cb)) return new Side(feed, bookmaker, Level.ALIAS, 1, true, "instruction alias");
        }
        double score = variantScore(nf, nb);
        if (score >= STRONG) return new Side(feed, bookmaker, Level.VARIANT, score, true, String.format(Locale.US, "naming variant %.2f", score));
        return new Side(feed, bookmaker, Level.NONE, score, true, String.format(Locale.US, "different name %.2f", score));
    }

    // ------------------------------------------------------------------ event level (B4, B8)
    static Result resolve(Event feed, Event page, Map<String, String> extraAliases) {
        boolean koKnown = feed.kickoffUk != null && page.kickoffUk != null;
        boolean koAgrees = koKnown && feed.kickoffUk.equals(page.kickoffUk);
        if (feed.sport != null && page.sport != null && !feed.sport.equalsIgnoreCase(page.sport))
            return new Result(Verdict.MISMATCH, "sport differs: " + feed.sport + " vs " + page.sport, null, null, koKnown, koAgrees, false, Collections.emptyMap(), null);
        Side h = matchSide(feed.home, page.home, extraAliases), a = matchSide(feed.away, page.away, extraAliases);
        Map<String, String> none = Collections.emptyMap();
        if (!h.markersAgree || !a.markersAgree) {
            Side bad = !h.markersAgree ? h : a;
            return new Result(Verdict.MISMATCH, "'" + bad.feed + "' vs '" + bad.bookmaker + "': " + bad.note, h, a, koKnown, koAgrees, false, none, null);
        }
        // Reversed pairing is never accepted: a HOME/AWAY selection would land on the other team.
        if (h.level == Level.NONE && a.level == Level.NONE) {
            Side hs = matchSide(feed.home, page.away, extraAliases), as = matchSide(feed.away, page.home, extraAliases);
            if (hs.atLeast(Level.ALIAS) && as.atLeast(Level.ALIAS))
                return new Result(Verdict.MISMATCH, "teams reversed (home/away): '" + feed.home + " v " + feed.away + "' is listed as '"
                        + page.home + " v " + page.away + "'", h, a, koKnown, koAgrees, true, none, null);
        }
        if (koKnown && !koAgrees)
            return new Result(Verdict.MISMATCH, "kick-off differs: alert " + feed.kickoffUk + " vs page " + page.kickoffUk + " (UK)", h, a, koKnown, false, false, none, null);
        Level lo = h.level.ordinal() <= a.level.ordinal() ? h.level : a.level;
        Level hi = h.level.ordinal() >= a.level.ordinal() ? h.level : a.level;
        if (lo == Level.EXACT) return new Result(Verdict.EXACT, "both teams exact", h, a, koKnown, koAgrees, false, none, null);
        if (lo == Level.CANONICAL) return new Result(Verdict.CANONICAL_MATCH, "both teams canonical", h, a, koKnown, koAgrees, false, none, null);
        if (lo == Level.ALIAS) return new Result(Verdict.ALIAS_MATCH, "both teams via aliases", h, a, koKnown, koAgrees, false, none, null);
        if (lo == Level.VARIANT && hi.ordinal() >= Level.ALIAS.ordinal()) {
            Side v = h.level == Level.VARIANT ? h : a;
            Map<String, String> cand = new LinkedHashMap<>();
            cand.put(v.feed, v.bookmaker);
            if (page.anchored && koAgrees) {
                String conf = v.score >= DETERMINISTIC ? "deterministic" : "high";
                return new Result(Verdict.HIGH_CONFIDENCE_EVENT_MATCH, "event link + kick-off " + page.kickoffUk + " + '"
                        + (v == h ? a.feed : h.feed) + "' exact; '" + v.feed + "' is a naming variant of '" + v.bookmaker + "' ("
                        + String.format(Locale.US, "%.2f", v.score) + ")", h, a, koKnown, koAgrees, false, cand, conf);
            }
            return new Result(Verdict.AMBIGUOUS, "'" + v.feed + "' only resembles '" + v.bookmaker + "' (" + String.format(Locale.US, "%.2f", v.score)
                    + ") and there is no event anchor with an agreeing kick-off", h, a, koKnown, koAgrees, false, cand, "review");
        }
        if (lo == Level.VARIANT)
            return new Result(Verdict.AMBIGUOUS, "both teams only resemble the page's names; no exact team to anchor on", h, a, koKnown, koAgrees, false, none, "review");
        Side bad = h.level == Level.NONE ? h : a;
        return new Result(Verdict.MISMATCH, "'" + bad.feed + "' is not '" + bad.bookmaker + "' (" + bad.note + ")", h, a, koKnown, koAgrees, false, none, null);
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
