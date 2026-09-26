package com.bet365agent;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.util.Collections;
import org.junit.Test;

/** Competition headers captured on the phone 26 Sep 2026 (evidence/timezone-probe/run-1790441189). */
public class CompetitionMatchTest {
    @Test public void bookmakerPrefixesTheFeedLabelWithTheCountry() {
        assertTrue(EventIdentity.competitionMatches("Liga ABE", "Mexico", "Mexico Liga ABE 26 Sep 21:30"));      // UP Mexico v UMAD
        assertTrue(EventIdentity.competitionMatches("BNXT Super Cup", "Belgium", "BNXT Super Cup 26 Sep 19:30")); // Landstede v Antwerp
        assertTrue(EventIdentity.competitionMatches("Copa Espana", "Spain", "Copa Espana 26 Sep 18:00"));
    }

    @Test public void approvedMappingIsScopedByCountryAndExact() {
        assertTrue(EventIdentity.competitionMatches("1. Liga", "Poland", "Poland 1st Division 26 Sep 19:00"));      // Kotwica, Spojnia
        assertFalse(EventIdentity.competitionMatches("1. Liga", "Poland", "Poland 2nd Division 26 Sep 19:00"));
        assertFalse(EventIdentity.competitionMatches("1. Liga", "Czech Republic", "Poland 1st Division 26 Sep 19:00"));
        assertFalse(EventIdentity.competitionMatches("1. Liga", null, "Poland 1st Division 26 Sep 19:00"));
    }

    @Test public void differentCompetitionsNeverMatch() {
        assertFalse(EventIdentity.competitionMatches("Liga ABE", "Mexico", "Spain Liga ABE 26 Sep 21:30"));
        assertFalse(EventIdentity.competitionMatches("Liga ABE", "Mexico", "Mexico LNBP 26 Sep 21:30"));
        assertFalse(EventIdentity.competitionMatches("", "Mexico", "Mexico Liga ABE"));
        assertFalse(EventIdentity.competitionMatches("Liga ABE", "Mexico", ""));
    }

    @Test public void verifiedResolutionUsesTheCountryAwareMatch() {
        EventIdentity.Event feed = new EventIdentity.Event("basketball", "UP Mexico", "UMAD", "26 Sep 21:30", "Liga ABE", false);
        EventIdentity.Event page = new EventIdentity.Event("basketball", "UP Mexico", "UMAD", "26 Sep 21:30", "Mexico Liga ABE 26 Sep 21:30", true);
        assertEquals(EventIdentity.Verdict.AMBIGUOUS, EventIdentity.resolveVerified(feed, page, Collections.emptyMap(), false).verdict);
        assertEquals(EventIdentity.Verdict.EXACT, EventIdentity.resolveVerified(feed, page, Collections.emptyMap(), false, "Mexico").verdict);
        assertEquals(EventIdentity.Verdict.AMBIGUOUS, EventIdentity.resolveVerified(feed, page, Collections.emptyMap(), false, "Spain").verdict);
    }
}
