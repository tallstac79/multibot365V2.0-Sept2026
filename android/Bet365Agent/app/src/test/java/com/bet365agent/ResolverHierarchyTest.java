package com.bet365agent;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import org.junit.Test;

/**
 * The evidence hierarchy of the direct-event decision (29 Sep 2026, the SSC-R Stags / Fiji (W) / Mohun Bagan class), through
 * the production entry EventPage.decide. Real live headers; no fixture-specific alias anywhere.
 *
 *  - an anchored link with an EXACT kick-off and a confirmed opponent is not vetoed by ONE team that only partly resembles
 *    (a bookmaker abbreviation) or by cosmetic competition wording ("Women's International Match");
 *  - everything that separates events still refuses: another opponent, another kick-off, protected markers, cup vs league;
 *  - SEARCH is never an anchor: it may identify an event only from the ONE matching fixture row with the kick-off exact, a
 *    sure opponent, a deterministic variant and a deterministic competition match.
 */
public class ResolverHierarchyTest {
    private static EventPage.Direct decide(List<String> header, String sport, String home, String away, String koUtc, String comp,
                                           String country, boolean anchored, boolean searchUnique, boolean women) {
        return EventPage.decide(header, EventPage.teams(header), sport, home, away, EventPage.ukDisplay(koUtc), comp, country, anchored,
                searchUnique, Collections.emptyMap(), women);
    }

    private static List<String> ssc(String kickoff, String away) {
        return Arrays.asList("Philippines NCAA • 29 Sep " + kickoff, "SSC-R Stags vs " + away);
    }

    private static EventPage.Direct sscCase(String kickoff, String away, boolean anchored) {
        return decide(ssc(kickoff, away), "basketball", "San Sebastian Golden Stags", "EAC Generals", "2026-09-29T07:00", "NCAA", "Philippines",
                anchored, false, false);
    }

    // ------------------------------------------------------------------ SSC-R Stags
    @Test public void anAbbreviatedTeamNextToAConfirmedOpponentOnTheOwnLinkIsAccepted() {
        EventPage.Direct d = sscCase("08:00", "EAC Generals", true);
        assertTrue(d.result.reason, d.result.accepted());
        assertEquals("anchored_confirmed_opponent_plus_shared_word", d.result.evidence.get("policy"));
        assertTrue("no alias is proposed for it", d.result.aliasCandidates.isEmpty());
    }

    @Test public void theSameNamesWithoutTheOwnLinkAreStillUnproven() {
        assertFalse(sscCase("08:00", "EAC Generals", false).result.accepted());
        assertEquals("weak_resemblance", sscCase("08:00", "EAC Generals", false).result.evidence.get("policy"));
    }

    @Test public void aDifferentOpponentIsStillTheWrongEvent() {
        EventPage.Direct d = sscCase("08:00", "Letran Knights", true);
        assertFalse(d.result.accepted());
        assertEquals(EventIdentity.Verdict.MISMATCH, d.result.verdict);
    }

    @Test public void aDifferentKickoffIsStillTheWrongEvent() {
        EventPage.Direct d = sscCase("10:00", "EAC Generals", true);
        assertFalse(d.result.accepted());
        assertEquals("kickoff", d.result.evidence.get("policy"));
    }

    @Test public void aKickoffOnlyWithinToleranceIsNotEnoughForAPartialName() {
        EventPage.Direct d = sscCase("08:03", "EAC Generals", true);   // 3 min: inside the kick-off tolerance, not exact
        assertFalse(d.result.reason, d.result.accepted());
    }

    @Test public void aPartialNameWithNoSharedWordIsNotAccepted() {
        EventPage.Direct d = decide(Arrays.asList("Philippines NCAA • 29 Sep 08:00", "Mapua Cardinals vs EAC Generals"), "basketball",
                "San Sebastian Golden Stags", "EAC Generals", "2026-09-29T07:00", "NCAA", "Philippines", true, false, false);
        assertFalse(d.result.accepted());
    }

    @Test public void aProtectedMarkerOnThePartialTeamStillRefuses() {
        EventPage.Direct d = decide(Arrays.asList("Philippines NCAA • 29 Sep 08:00", "SSC-R Stags U19 vs EAC Generals"), "basketball",
                "San Sebastian Golden Stags", "EAC Generals", "2026-09-29T07:00", "NCAA", "Philippines", true, false, false);
        assertFalse(d.result.accepted());
        assertEquals(EventIdentity.Verdict.MISMATCH, d.result.verdict);
    }

    @Test public void theOpponentOnTheWrongSideIsStillRefused() {
        EventPage.Direct d = decide(Arrays.asList("Philippines NCAA • 29 Sep 08:00", "EAC Generals vs SSC-R Stags"), "basketball",
                "San Sebastian Golden Stags", "EAC Generals", "2026-09-29T07:00", "NCAA", "Philippines", true, false, false);
        assertFalse(d.result.accepted());
    }

    @Test public void aCompetitionInAnotherCountryStillRefuses() {
        EventPage.Direct d = decide(ssc("08:00", "EAC Generals"), "basketball", "San Sebastian Golden Stags", "EAC Generals", "2026-09-29T07:00",
                "NCAA", "Japan", true, false, false);
        assertFalse(d.result.accepted());
    }

    // ------------------------------------------------------------------ Fiji (W): cosmetic competition wording
    private static EventPage.Direct fiji(String competitionLine, String teamsLine, String feedCompetition) {
        return decide(Arrays.asList(competitionLine + " 29 Sep 08:00", teamsLine), "football", "Fiji", "New Caledonia", "2026-09-29T07:00",
                feedCompetition, "International", true, false, true);
    }

    @Test public void aFriendlyLabelledInternationalMatchIsNotACompetitionConflict() {
        EventPage.Direct d = fiji("Women's International Match", "Fiji (W) v New Caledonia (W)", "Friendlies Women");
        assertTrue(d.result.reason, d.result.accepted());
        assertEquals("structural_compatible", d.result.evidence.get("competition_match").toString().split(" ")[0]);
    }

    @Test public void aCupOrTierCompetitionStillConflictsWithAFriendly() {
        assertFalse(fiji("Women's International Cup", "Fiji (W) v New Caledonia (W)", "Friendlies Women").result.accepted());
        assertFalse(fiji("Women's International League Two", "Fiji (W) v New Caledonia (W)", "Friendlies Women").result.accepted());
    }

    @Test public void theAgeGroupAndGenderStillRefuse() {
        assertFalse(fiji("U19 International Match", "Fiji U19 v New Caledonia U19", "Friendlies Women").result.accepted());
        assertFalse(fiji("International Match", "Fiji v New Caledonia", "Friendlies Women").result.accepted());   // page not women's
    }

    // ------------------------------------------------------------------ Search: weaker tier, stronger corroboration
    private static EventPage.Direct bagan(String kickoffLine, boolean unique, boolean anchored, String competition) {
        return decide(Arrays.asList(kickoffLine, "Mohun Bagan SG v Northeast United"), "football", "Mohun Bagan", "NorthEast United",
                "2026-09-29T09:00", competition, "India", anchored, unique, false);
    }

    @Test public void aUniqueSearchRowWithAnExactKickoffAndAVariantIsAccepted() {
        EventPage.Direct d = bagan("India IFA Shield 29 Sep 10:00", true, false, "IFA Shield");
        assertTrue(d.result.reason, d.result.accepted());
        assertEquals("search_unique_one_sure_team_plus_variant", d.result.evidence.get("policy"));
        assertEquals("event_id_match must stay false for Search", false, d.result.evidence.get("event_id_match"));
    }

    @Test public void searchIsNotTheDirectLinkAnchor() {
        assertFalse(bagan("India IFA Shield 29 Sep 10:00", false, false, "IFA Shield").result.accepted());   // no unique row: as before
        assertEquals("variant_without_anchor", bagan("India IFA Shield 29 Sep 10:00", false, false, "IFA Shield").result.evidence.get("policy"));
        // the same names on the own link are accepted by the anchored rule (unchanged)
        assertTrue(bagan("India IFA Shield 29 Sep 10:00", false, true, "IFA Shield").result.accepted());
    }

    @Test public void searchNeedsAnExactKickoffNotJustOneInsideTheTolerance() {
        assertFalse(bagan("India IFA Shield 29 Sep 10:03", true, false, "IFA Shield").result.accepted());
    }

    @Test public void searchNeedsADeterministicCompetitionMatch() {
        assertFalse(bagan("India IFA Shield 29 Sep 10:00", true, false, "Super Cup").result.accepted());
        assertFalse(bagan("India Super League 29 Sep 10:00", true, false, "IFA Shield").result.accepted());
    }

    @Test public void searchDoesNotAcceptTwoVariantsOrAPartialName() {
        EventPage.Direct both = decide(Arrays.asList("India IFA Shield 29 Sep 10:00", "Mohun Bagan SG v Northeast United FC Reserves"), "football",
                "Mohun Bagan", "NorthEast United", "2026-09-29T09:00", "IFA Shield", "India", false, true, false);
        assertFalse(both.result.accepted());
        assertFalse(decide(ssc("08:00", "EAC Generals"), "basketball", "San Sebastian Golden Stags", "EAC Generals", "2026-09-29T07:00", "NCAA",
                "Philippines", false, true, false).result.accepted());   // the weak-name tier is for the own link only
    }

    // ------------------------------------------------------------------ header reading on the Search route
    @Test public void aGluedUppercaseSeparatorIsReadOnlyWhenTheTextBeforeItIsAHintedName() {
        List<String> header = Arrays.asList("India IFA Shield 29 Sep 10:00", "Mohun Bagan SGV Northeast United v");
        assertNull(EventPage.teams(header, Arrays.asList("Mohun Bagan"), Arrays.asList("NorthEast United")));
        assertArrayEquals(new String[] {"Mohun Bagan SG", "Northeast United"},
                EventPage.teams(header, Arrays.asList("Mohun Bagan", "Mohun Bagan SG"), Arrays.asList("NorthEast United")));
        assertNull("an unrelated hint does not split it", EventPage.teams(header, Arrays.asList("Kerala Blasters"), Arrays.asList("NorthEast United")));
    }
}
