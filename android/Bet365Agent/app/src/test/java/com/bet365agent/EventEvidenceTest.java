package com.bet365agent;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

import java.util.Collections;
import java.util.Map;
import org.junit.Test;

/**
 * Event-level evidence matching (0.9.25). The failure that motivated it: OddsNotifier "Atletico Boca Juniors v Tigers"
 * against the Bet365 event page "Boca Juniors v RSSB Tigers" (FIBA Intercontinental Cup, 27 Sep 07:30, alert's own
 * event link; live instructions on-e3d73d9b / on-7035a28f were ALIAS_REQUIRED on 0.9.24).
 */
public class EventEvidenceTest {
    private static final Map<String, String> NO_ALIASES = Collections.emptyMap();

    private static EventIdentity.Event feed(String home, String away, String ko, String competition) {
        return new EventIdentity.Event("basketball", home, away, ko, competition, false);
    }
    private static EventIdentity.Event page(String home, String away, String ko, String header, boolean anchored) {
        return new EventIdentity.Event("basketball", home, away, ko, header, anchored);
    }
    private static EventIdentity.Result boca(String feedHome, String feedAway, String feedKo, String feedComp, String country,
                                             String pageHome, String pageAway, String pageKo, String header, boolean anchored) {
        return EventIdentity.resolveVerified(feed(feedHome, feedAway, feedKo, feedComp), page(pageHome, pageAway, pageKo, header, anchored),
                NO_ALIASES, false, country);
    }
    private static EventIdentity.Result bocaTigers() {
        return boca("Atletico Boca Juniors", "Tigers", "27 Sep 07:30", "Intercontinental Cup", "World",
                "Boca Juniors", "RSSB Tigers", "27 Sep 07:30", "FIBA Intercontinental Cup 27 Sep 07:30", true);
    }

    @Test public void bocaTigersResolvesOnEventEvidence() {
        EventIdentity.Result r = bocaTigers();
        assertEquals(r.reason, EventIdentity.Verdict.HIGH_CONFIDENCE_EVENT_MATCH, r.verdict);
        assertTrue(r.accepted());
        assertEquals("token_containment", r.home.kind);      // Atletico (club prefix) + Boca Juniors  ->  Boca Juniors
        assertEquals("token_containment", r.away.kind);      // Tigers  within  RSSB Tigers
        assertEquals(1.0, r.home.score, 0.001);
        assertEquals(1.0, r.away.score, 0.001);
        assertEquals("event_evidence_both_variants", r.evidence.get("policy"));
    }

    @Test public void bocaTigersCreatesNoAlias() {
        EventIdentity.Result r = bocaTigers();
        // "Tigers" is a nickname contained in the bookmaker's longer name: event-scoped evidence, never an alias candidate.
        assertFalse(r.away.aliasSafe);
        assertFalse(r.aliasCandidates.containsKey("Tigers"));
        // the specific-to-shorter direction ("Atletico Boca Juniors" -> "Boca Juniors") may be proposed for the scoped registry
        assertEquals("Boca Juniors", r.aliasCandidates.get("Atletico Boca Juniors"));
        // the phone's registry is untouched and the team-level match is a VARIANT, not an alias
        assertEquals("tigers", TeamAliases.canonical("Tigers"));
        assertEquals("rssb tigers", TeamAliases.canonical("RSSB Tigers"));
        EventIdentity.Side side = EventIdentity.matchSide("Tigers", "RSSB Tigers", NO_ALIASES);
        assertEquals(EventIdentity.Level.VARIANT, side.level);
        assertFalse(side.atLeast(EventIdentity.Level.ALIAS));
        // the same names without the event anchor (Search route) are AMBIGUOUS: the anchor decides, not the nickname
        EventIdentity.Result unanchored = boca("Atletico Boca Juniors", "Tigers", "27 Sep 07:30", "Intercontinental Cup", "World",
                "Boca Juniors", "RSSB Tigers", "27 Sep 07:30", "FIBA Intercontinental Cup 27 Sep 07:30", false);
        assertEquals(EventIdentity.Verdict.AMBIGUOUS, unanchored.verdict);
        assertFalse(unanchored.accepted());
        // the alert names another competition than the page: the competition gate holds the event back
        assertEquals(EventIdentity.Verdict.AMBIGUOUS, boca("Atletico Boca Juniors", "Tigers", "27 Sep 07:30", "Liga Nacional", "Argentina",
                "Boca Juniors", "RSSB Tigers", "27 Sep 07:30", "FIBA Intercontinental Cup 27 Sep 07:30", true).verdict);
    }

    @Test public void evidenceLogNamesEveryAnchor() {
        EventIdentity.Result boca = bocaTigers();
        Map<String, Object> ev = boca.evidence;
        System.out.println("BOCA_TIGERS_VERDICT " + boca.verdict + " | " + boca.reason);
        System.out.println("BOCA_TIGERS_EVIDENCE " + ev);
        System.out.println("BOCA_TIGERS_ALIAS_CANDIDATES " + boca.aliasCandidates + " confidence=" + boca.candidateConfidence);
        assertEquals(Boolean.TRUE, ev.get("event_id_match"));
        assertEquals("equal", ev.get("sport_match"));
        assertEquals("body_prefixed (fiba)", ev.get("competition_match"));
        assertEquals("exact", ev.get("kickoff_match"));
        assertEquals("agree", ev.get("protected_markers"));
        assertEquals("agree", ev.get("orientation"));
        assertTrue(String.valueOf(ev.get("competing_event")).startsWith("none"));
        @SuppressWarnings("unchecked") Map<String, Object> home = (Map<String, Object>) ev.get("home_similarity");
        @SuppressWarnings("unchecked") Map<String, Object> away = (Map<String, Object>) ev.get("away_similarity");
        assertEquals("VARIANT", home.get("level"));
        assertEquals("token_containment", away.get("kind"));
        assertNotNull(away.get("note"));
        assertEquals("HIGH_CONFIDENCE_EVENT_MATCH", ev.get("verdict"));
    }

    @Test public void kickoffToleranceIsSmallAndExplicit() {
        assertEquals("exact", EventIdentity.kickoffMatch("27 Sep 07:30", "27 Sep 07:30"));
        assertEquals("within_tolerance (+3 min)", EventIdentity.kickoffMatch("27 Sep 07:30", "27 Sep 07:33"));
        assertEquals("within_tolerance (-5 min)", EventIdentity.kickoffMatch("27 Sep 07:30", "27 Sep 07:25"));
        assertTrue(EventIdentity.kickoffMatch("27 Sep 07:30", "27 Sep 07:36").startsWith("mismatch"));
        assertTrue(EventIdentity.kickoffMatch("27 Sep 07:30", "27 Sep 08:30").startsWith("mismatch"));
        assertTrue(EventIdentity.kickoffMatch("27 Sep 07:30", "28 Sep 07:30").startsWith("mismatch"));
        assertTrue(EventIdentity.kickoffMatch("30 Sep 23:58", "1 Oct 00:02").startsWith("within_tolerance"));
        assertEquals("unknown", EventIdentity.kickoffMatch(null, "27 Sep 07:30"));
        EventIdentity.Result r = boca("Atletico Boca Juniors", "Tigers", "27 Sep 07:30", "Intercontinental Cup", "World",
                "Boca Juniors", "RSSB Tigers", "27 Sep 07:33", "FIBA Intercontinental Cup 27 Sep 07:33", true);
        assertEquals(EventIdentity.Verdict.HIGH_CONFIDENCE_EVENT_MATCH, r.verdict);
        assertEquals("within_tolerance (+3 min)", r.evidence.get("kickoff_match"));
    }

    @Test public void constructedLookalikesAreNotAccepted() {
        // kick-off one hour / one day off on the same names: a different event
        assertEquals(EventIdentity.Verdict.MISMATCH, boca("Atletico Boca Juniors", "Tigers", "27 Sep 07:30", "Intercontinental Cup", "World",
                "Boca Juniors", "RSSB Tigers", "27 Sep 08:30", "FIBA Intercontinental Cup 27 Sep 08:30", true).verdict);
        assertEquals(EventIdentity.Verdict.MISMATCH, boca("Atletico Boca Juniors", "Tigers", "27 Sep 07:30", "Intercontinental Cup", "World",
                "Boca Juniors", "RSSB Tigers", "28 Sep 07:30", "FIBA Intercontinental Cup 28 Sep 07:30", true).verdict);
        // protected markers on the lookalike page
        assertEquals(EventIdentity.Verdict.MISMATCH, boca("Atletico Boca Juniors", "Tigers", "27 Sep 07:30", "Intercontinental Cup", "World",
                "Boca Juniors", "RSSB Tigers (W)", "27 Sep 07:30", "FIBA Intercontinental Cup 27 Sep 07:30", true).verdict);
        assertEquals(EventIdentity.Verdict.MISMATCH, boca("Atletico Boca Juniors", "Tigers", "27 Sep 07:30", "Intercontinental Cup", "World",
                "Boca Juniors", "RSSB Tigers U19", "27 Sep 07:30", "FIBA Intercontinental Cup 27 Sep 07:30", true).verdict);
        assertEquals(EventIdentity.Verdict.MISMATCH, boca("Atletico Boca Juniors", "Tigers", "27 Sep 07:30", "Intercontinental Cup", "World",
                "Boca Juniors II", "RSSB Tigers", "27 Sep 07:30", "FIBA Intercontinental Cup 27 Sep 07:30", true).verdict);
        // reversed pairing
        EventIdentity.Result rev = boca("Tigers", "Atletico Boca Juniors", "27 Sep 07:30", "Intercontinental Cup", "World",
                "Boca Juniors", "RSSB Tigers", "27 Sep 07:30", "FIBA Intercontinental Cup 27 Sep 07:30", true);
        assertEquals(EventIdentity.Verdict.MISMATCH, rev.verdict);
        assertTrue(rev.reversed);
        assertEquals("reversed", rev.evidence.get("orientation"));
        // a page whose names are letter-similar but not token-compatible on both sides ("Tigres" is not "Tigers" by tokens)
        EventIdentity.Result tigres = boca("Atletico Boca Juniors", "Tigers", "27 Sep 07:30", "Intercontinental Cup", "World",
                "Boca Juniors", "Tigres", "27 Sep 07:30", "FIBA Intercontinental Cup 27 Sep 07:30", true);
        assertEquals(EventIdentity.Verdict.AMBIGUOUS, tigres.verdict);
        assertEquals("letters", tigres.away.kind);
        // a partial name with a stranger's extra token: Leicester Tigers is not RSSB Tigers
        assertEquals(EventIdentity.Verdict.AMBIGUOUS, boca("Atletico Boca Juniors", "Leicester Tigers", "27 Sep 07:30", "Intercontinental Cup", "World",
                "Boca Juniors", "RSSB Tigers", "27 Sep 07:30", "FIBA Intercontinental Cup 27 Sep 07:30", true).verdict);
        // a different opponent altogether
        assertEquals(EventIdentity.Verdict.MISMATCH, boca("Atletico Boca Juniors", "Tigers", "27 Sep 07:30", "Intercontinental Cup", "World",
                "Boca Juniors", "Rytas", "27 Sep 07:30", "FIBA Intercontinental Cup 27 Sep 07:30", true).verdict);
    }

    @Test public void differentClubPrefixesAreDifferentClubs() {
        assertEquals(EventIdentity.Verdict.MISMATCH, boca("Real Madrid", "Barcelona", "27 Sep 19:00", "Liga ACB", "Spain",
                "Atletico Madrid", "Barcelona", "27 Sep 19:00", "Spain Liga ACB 27 Sep 19:00", true).verdict);
        assertEquals(EventIdentity.Verdict.MISMATCH, boca("Hapoel Tel Aviv", "Bayern Munich", "27 Sep 19:00", "Euroleague", "Europe",
                "Maccabi Tel Aviv", "Bayern Munich", "27 Sep 19:00", "Euroleague 27 Sep 19:00", true).verdict);
        assertEquals(EventIdentity.Verdict.MISMATCH, boca("Manchester United", "Arsenal", "27 Sep 19:00", "Premier League", "England",
                "Manchester City", "Arsenal", "27 Sep 19:00", "England Premier League 27 Sep 19:00", true).verdict);
        assertEquals("family_conflict", EventIdentity.matchSide("Hapoel Tel Aviv", "Maccabi Tel Aviv", NO_ALIASES).kind);
        // a prefix present on one side only is not a conflict (Atletico Boca Juniors / Boca Juniors)
        assertEquals(EventIdentity.Level.VARIANT, EventIdentity.matchSide("Atletico Boca Juniors", "Boca Juniors", NO_ALIASES).level);
        // the family prefix alone never carries a match: Hapoel Jerusalem is not Hapoel Tel Aviv, Hapoel TA is not Hapoel Holon
        assertEquals(EventIdentity.Level.NONE, EventIdentity.matchSide("Hapoel Jerusalem", "Hapoel Tel Aviv", NO_ALIASES).level);
        assertEquals(EventIdentity.Level.NONE, EventIdentity.matchSide("Hapoel TA", "Hapoel Holon", NO_ALIASES).level);
        assertEquals("abbreviation", EventIdentity.matchSide("Hapoel TA", "Hapoel Tel Aviv", NO_ALIASES).kind);
    }

    @Test public void partialResemblanceStaysAmbiguousNeverAccepted() {
        // Samsung Thunders / Seoul Thunders: shared nickname, unexplained sponsor vs city token -> WEAK
        EventIdentity.Side s = EventIdentity.matchSide("Samsung Thunders", "Seoul Thunders", NO_ALIASES);
        assertEquals(EventIdentity.Level.WEAK, s.level);
        assertEquals("partial", s.kind);
        EventIdentity.Result korea = boca("Samsung Thunders", "Anyang Jungkwanjang Red Boosters", "27 Sep 06:00", "KBL Cup", "Korea",
                "Seoul Thunders", "Anyang Red Boosters", "27 Sep 06:00", "Club Friendlies 27 Sep 06:00", true);
        assertEquals(EventIdentity.Verdict.AMBIGUOUS, korea.verdict);
        assertFalse(korea.accepted());
        assertEquals("weak_resemblance", korea.evidence.get("policy"));
        // Lyon / LYONSO: a prefix only -> WEAK -> AMBIGUOUS (alias review), not a wrong event
        EventIdentity.Side lyon = EventIdentity.matchSide("Lyon", "LYONSO", NO_ALIASES);
        assertEquals(EventIdentity.Level.WEAK, lyon.level);
        assertEquals("prefix", lyon.kind);
        assertEquals(EventIdentity.Verdict.AMBIGUOUS, boca("Orchies", "Lyon", "25 Sep 19:00", "Nationale 1", "France",
                "Orchies", "LYONSO", "25 Sep 19:00", "France Nationale 1 25 Sep 19:00", true).verdict);
        // no shared distinctive token at all is still a MISMATCH
        assertEquals(EventIdentity.Level.NONE, EventIdentity.matchSide("Basket Club Nantes", "Basket Club Besancon", NO_ALIASES).level);
    }

    @Test public void koreanAndLithuanianPairsResolveWithTheirCompetitionMappings() {
        EventIdentity.Result suwon = boca("Suwon KT Sonicboom", "Goyang Skygunners", "27 Sep 06:00", "KBL Cup", "Korea",
                "Suwon Sonicboom", "Goyang Sky Gunners", "27 Sep 06:00", "Club Friendlies 27 Sep 06:00", true);
        assertEquals(suwon.reason, EventIdentity.Verdict.HIGH_CONFIDENCE_EVENT_MATCH, suwon.verdict);
        assertEquals("token_containment", suwon.home.kind);
        assertEquals("token_split", suwon.away.kind);
        assertTrue(String.valueOf(suwon.evidence.get("competition_match")).startsWith("approved_mapping"));
        // the mapping is scoped to Korea
        assertEquals(EventIdentity.Verdict.AMBIGUOUS, boca("Suwon KT Sonicboom", "Goyang Skygunners", "27 Sep 06:00", "KBL Cup", "Japan",
                "Suwon Sonicboom", "Goyang Sky Gunners", "27 Sep 06:00", "Club Friendlies 27 Sep 06:00", true).verdict);
        EventIdentity.Result rytas = boca("Rytas Vilnius", "Atletico Boca Juniors", "26 Sep 12:30", "Intercontinental Cup", "World",
                "Rytas", "Boca Juniors", "26 Sep 12:30", "FIBA Intercontinental Cup 26 Sep 12:30", true);
        assertEquals(rytas.reason, EventIdentity.Verdict.HIGH_CONFIDENCE_EVENT_MATCH, rytas.verdict);
        assertEquals("Rytas", rytas.aliasCandidates.get("Rytas Vilnius"));            // specific -> shorter: alias-safe
        // Utsunomiya v Yokohama: exact names; the page kick-off is now read from "Japan B League 127 Sep 07:05"
        EventIdentity.Result brex = boca("Utsunomiya Brex", "Yokohama B-Corsairs", "27 Sep 07:05", "B League", "Japan",
                "Utsunomiya Brex", "Yokohama B-Corsairs", EventPage.kickoffText(Collections.singletonList("Japan B League 127 Sep 07:05")),
                "Japan B League 127 Sep 07:05", true);
        assertEquals(brex.reason, EventIdentity.Verdict.EXACT, brex.verdict);
    }

    @Test public void orientationMustBeDecidable() {
        // straight and crossed pairings both plausible (a contrived same-nickname pairing): undecidable -> AMBIGUOUS
        EventIdentity.Result r = EventIdentity.resolve(feed("Tigers", "Tigers Basket", "27 Sep 07:30", null),
                page("RSSB Tigers", "Tigers", "27 Sep 07:30", null, true), NO_ALIASES);
        assertEquals(EventIdentity.Verdict.AMBIGUOUS, r.verdict);
        assertTrue(String.valueOf(r.evidence.get("orientation")).startsWith("ambiguous"));
        // crossed-only plausibility at VARIANT level is reported as reversed
        EventIdentity.Result rev = EventIdentity.resolve(feed("Rytas", "Shanghai Sharks", "26 Sep 12:30", null),
                page("Shanghai Sharks", "Rytas Vilnius", "26 Sep 12:30", null, true), NO_ALIASES);
        assertEquals(EventIdentity.Verdict.MISMATCH, rev.verdict);
        assertTrue(rev.reversed);
    }

    @Test public void tokenEvidenceKinds() {
        assertEquals("token_containment", EventIdentity.matchSide("Rytas Vilnius", "Rytas", NO_ALIASES).kind);
        assertEquals("token_containment", EventIdentity.matchSide("Pays Salonais Basket 13", "Pays Salonais Basket", NO_ALIASES).kind);
        assertEquals("token_containment", EventIdentity.matchSide("ASC Denain", "Denain", NO_ALIASES).kind);
        assertEquals("token_split", EventIdentity.matchSide("Goyang Skygunners", "Goyang Sky Gunners", NO_ALIASES).kind);
        assertEquals("token_split", EventIdentity.matchSide("Val de Seine", "Valdeseine", NO_ALIASES).kind);
        assertEquals("stem", EventIdentity.matchSide("Soproni", "Sopron", NO_ALIASES).kind);          // inflected stem 0.86
        assertEquals("abbreviation", EventIdentity.matchSide("Hapoel JLM", "Hapoel Jerusalem", NO_ALIASES).kind);
        assertEquals("letters", EventIdentity.matchSide("Besancn", "Besancon", NO_ALIASES).kind);
        assertEquals("prefix", EventIdentity.matchSide("Lyon", "LYONSO", NO_ALIASES).kind);
        assertEquals("partial", EventIdentity.matchSide("Bayern Munich", "Bayern 1 2", NO_ALIASES).kind);
        assertEquals("none", EventIdentity.matchSide("Kyoto Hannaryz", "Shiga Lakes", NO_ALIASES).kind);
        // letters agreement is trusted for whole single-token names only, never for a partial name
        assertEquals(EventIdentity.Level.WEAK, EventIdentity.matchSide("Tigers", "Tigres UANL", NO_ALIASES).level);
        // alias safety: extra distinctive tokens on the bookmaker side block a candidate
        assertFalse(EventIdentity.matchSide("Tigers", "RSSB Tigers", NO_ALIASES).aliasSafe);
        assertTrue(EventIdentity.matchSide("Rytas Vilnius", "Rytas", NO_ALIASES).aliasSafe);
        assertTrue(EventIdentity.matchSide("Goyang Skygunners", "Goyang Sky Gunners", NO_ALIASES).aliasSafe);
    }
}
