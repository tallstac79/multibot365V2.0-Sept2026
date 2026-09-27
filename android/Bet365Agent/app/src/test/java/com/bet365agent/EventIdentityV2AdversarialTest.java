package com.bet365agent;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import org.junit.Test;

/**
 * Codex identity-v2 adversarial corpus (evidence/identity-v2/adversarial-inputs.json: 2 positive controls, 19 negatives built
 * from the real Boca/Tigers observation) through the PRODUCTION decision (EventPage.decide on header lines). Name, marker,
 * kick-off, orientation and competition negatives are decided by the resolver; the URL/search/period/quote negatives are
 * decided by the production guards that own them, each asserted here or named where the phone has no such input.
 */
public class EventIdentityV2AdversarialTest {
    private static final String KO = "27 Sep 07:30", COMP = "Intercontinental Cup", HEADER = "FIBA Intercontinental Cup 27 Sep 07:30";

    private static EventPage.Direct decide(String feedHome, String feedAway, String pageTitle, String header, String feedComp, boolean anchored) {
        List<String> lines = Arrays.asList(header, pageTitle, "Popular Bet Builder Game Team Quarter Half");
        return EventPage.decide(lines, "basketball", feedHome, feedAway, KO, feedComp, "World", anchored, Collections.emptyMap(), false);
    }
    private static EventIdentity.Verdict v(String feedHome, String feedAway, String pageTitle) {
        return decide(feedHome, feedAway, pageTitle, HEADER, COMP, true).result.verdict;
    }

    @Test public void positiveControls() {
        assertEquals(EventIdentity.Verdict.EXACT, v("Boca Juniors", "RSSB Tigers", "Boca Juniors vs RSSB Tigers"));
        assertEquals(EventIdentity.Verdict.HIGH_CONFIDENCE_EVENT_MATCH, v("Atletico Boca Juniors", "Tigers", "Boca Juniors vs RSSB Tigers"));
    }

    @Test public void resolverNegativesNeverAccept() {
        // wrong kick-off (a day later)
        EventPage.Direct d = decide("Atletico Boca Juniors", "Tigers", "Boca Juniors vs RSSB Tigers", "FIBA Intercontinental Cup 28 Sep 07:30", COMP, true);
        assertEquals(EventIdentity.Verdict.MISMATCH, d.result.verdict);
        // wrong opponent
        assertFalse(decide("Atletico Boca Juniors", "Tigers", "Boca Juniors vs Real Madrid", HEADER, COMP, true).result.accepted());
        // reversed fixture
        EventPage.Direct rev = decide("Atletico Boca Juniors", "Tigers", "RSSB Tigers vs Boca Juniors", HEADER, COMP, true);
        assertEquals(EventIdentity.Verdict.MISMATCH, rev.result.verdict);
        assertTrue(rev.result.reversed);
        // explicit men versus women (feed says Men; the page says Women)
        assertFalse(v("Boca Juniors Men", "Tigers", "Boca Juniors Women vs RSSB Tigers").ordinal() <= EventIdentity.Verdict.HIGH_CONFIDENCE_EVENT_MATCH.ordinal());
        assertFalse(decide("Boca Juniors Men", "Tigers", "Boca Juniors Women vs RSSB Tigers", HEADER, COMP, true).result.accepted());
        // U19 versus U21
        assertEquals(EventIdentity.Verdict.MISMATCH, v("Boca Juniors U19", "Tigers", "Boca Juniors U21 vs RSSB Tigers"));
        // independently read first versus second squad
        assertFalse(decide("Boca Juniors I", "Tigers", "Boca Juniors II vs RSSB Tigers", HEADER, COMP, true).result.accepted());
        // OCR first versus second squad uncertain: the page's lone "I" against the feed's II is a reread, never an accept
        assertEquals(EventIdentity.Verdict.NEEDS_RECHECK, v("Boca Juniors II", "Tigers", "Boca Juniors I vs RSSB Tigers"));
        assertEquals(EventIdentity.Verdict.NEEDS_RECHECK, v("Boca Juniors II", "Tigers", "Boca Juniors I| vs RSSB Tigers"));
        assertEquals(EventIdentity.Verdict.NEEDS_RECHECK, v("Boca Juniors", "Tigers", "Boca Juniors || vs RSSB Tigers"));
        // first team versus reserves
        assertEquals(EventIdentity.Verdict.MISMATCH, v("Boca Juniors", "Tigers", "Boca Juniors reserves vs RSSB Tigers"));
        // same generic nickname, different club
        assertFalse(decide("Atletico Boca Juniors", "Tokyo Tigers", "Boca Juniors vs RSSB Tigers", HEADER, COMP, true).result.accepted());
        // same names, different numbered division
        assertFalse(decide("Atletico Boca Juniors", "Tigers", "Boca Juniors vs RSSB Tigers", "Division 2 27 Sep 07:30", "Division 1", true).result.accepted());
        // a search candidate (no direct-link anchor)
        assertFalse(decide("Atletico Boca Juniors", "Tigers", "Boca Juniors vs RSSB Tigers", HEADER, COMP, false).result.accepted());
    }

    @Test public void structuralNegativesAreOwnedByTheirProductionGuards() {
        // generic home URL: the phone never opens it as an event link (open_event_direct -> EventPage.validUrl)
        assertFalse(EventPage.validUrl("https://www.bet365.com/"));
        assertTrue(EventPage.validUrl("https://www.bet365.com/#/AC/B18/C21172577/D19/E26832491/F19/I0/"));
        // search redirect page: no "A v B" event header -> no teams -> no identity (the direct route fails closed / searches)
        EventPage.Direct search = EventPage.decide(Arrays.asList("Search", "Boca Juniors", "RSSB Tigers Basketball"), "basketball",
                "Atletico Boca Juniors", "Tigers", KO, COMP, "World", true, Collections.emptyMap(), false);
        assertNull(search.result);
        // wrong period: the adapter requires the FULL_GAME context before identity (verifyDirectEvent) and the grid parser reads
        // only the full-game rows; quote/line/price differences are judged by the alert-to-live execution terms after identity
        // (ExecutionTolerance, requireExecutionTerms), not by the identity verdict. Destination event-ID read-back and a
        // competing-event count are not observable on the phone (documented data needs, same as the offline V2 report).
        assertTrue(ExecutionTolerance.line("TOTAL", "UNDER", "184.5", "184.5", "1.0"));
        assertFalse(ExecutionTolerance.line("TOTAL", "UNDER", "184.5", "180.5", "1.0"));   // "unexplained snapshot conflict" line 184.5 -> 180.5
    }

    @Test public void wrappedHeaderAndUnreadNumeral() {
        // Real Bydgoszcz header (on-75688678, 27 Sep 2026): title wrapped, numeral read as "I|"
        List<String> header = Arrays.asList("Poland 1 Liga Women 27 Sep 12:30", "KS Basket 25 I| Bydgoszcz (W) vs Katarzynki II", "Torun (W)",
                "Popular Bet Builder Game Team Quarter");
        String[] teams = EventPage.teams(header);
        assertEquals("KS Basket 25 UNREADTIER Bydgoszcz (W)", teams[0]);
        assertEquals("Katarzynki II Torun (W)", teams[1]);
        EventPage.Direct first = EventPage.decide(header, "basketball", "KS Basket 25 II Bydgoszcz", "Energa Torun II", "27 Sep 12:30",
                "Liga 1 Women", "Poland", true, Collections.emptyMap(), true);
        assertEquals(first.result.reason, EventIdentity.Verdict.NEEDS_RECHECK, first.result.verdict);
        assertFalse(first.result.accepted());
        // an independent reread that shows II: accepted as a naming variant (competition supplies (W); Torun shared core)
        List<String> reread = Arrays.asList("Poland 1 Liga Women 27 Sep 12:30", "KS Basket 25 II Bydgoszcz (W) vs Katarzynki II", "Torun (W)");
        EventPage.Direct second = EventPage.decide(reread, "basketball", "KS Basket 25 II Bydgoszcz", "Energa Torun II", "27 Sep 12:30",
                "Liga 1 Women", "Poland", true, Collections.emptyMap(), true);
        assertEquals(second.result.reason, EventIdentity.Verdict.HIGH_CONFIDENCE_EVENT_MATCH, second.result.verdict);
        assertTrue(second.result.aliasCandidates.isEmpty() || !second.result.aliasCandidates.containsKey("Energa Torun II"));
        // a reread that shows a first team (no numeral) is not accepted
        List<String> first2 = Arrays.asList("Poland 1 Liga Women 27 Sep 12:30", "KS Basket 25 Bydgoszcz (W) vs Katarzynki II", "Torun (W)");
        assertFalse(EventPage.decide(first2, "basketball", "KS Basket 25 II Bydgoszcz", "Energa Torun II", "27 Sep 12:30",
                "Liga 1 Women", "Poland", true, Collections.emptyMap(), true).result.accepted());
        // the continuation join never swallows a tab strip or a second fixture
        assertEquals("Leonas de Ponce (W)", EventPage.teams(Arrays.asList("Explosivas de Moca (W) vs Leonas de Ponce", "(W)"))[1]);
        assertEquals("Leonas de Ponce", EventPage.teams(Arrays.asList("Explosivas de Moca (W) vs Leonas de Ponce", "Popular Bet Builder"))[1]);
        assertEquals("Val de Seine", EventPage.teams(Arrays.asList("Besancon AC vs Val de Seine", "Game Lines"))[1]);
    }

    @Test public void sharedCoreNeedsASureOpponentAndIsNeverANickname() {
        EventIdentity.Side castello = EventIdentity.matchSide("AB Castello", "Amics Castello", Collections.emptyMap());
        assertEquals("shared_core", castello.kind);
        assertFalse(castello.aliasSafe);
        assertEquals(EventIdentity.Level.WEAK, EventIdentity.matchSide("Samsung Thunders", "Seoul Thunders", Collections.emptyMap()).level);
        assertEquals(EventIdentity.Level.WEAK, EventIdentity.matchSide("Tokyo Tigers", "RSSB Tigers", Collections.emptyMap()).level);
        assertEquals(EventIdentity.Level.WEAK, EventIdentity.matchSide("Bayern Munich", "Bayern 1 2", Collections.emptyMap()).level);
        // both sides only shared cores: not enough
        assertFalse(v("AB Castello", "CB Benicarlo Spur", "Amics Castello vs Club Benicarlo Aeroport").ordinal() <= EventIdentity.Verdict.HIGH_CONFIDENCE_EVENT_MATCH.ordinal()
                && decide("AB Castello", "CB Benicarlo Spur", "Amics Castello vs Club Benicarlo Aeroport", HEADER, COMP, true).result.accepted());
    }
}
