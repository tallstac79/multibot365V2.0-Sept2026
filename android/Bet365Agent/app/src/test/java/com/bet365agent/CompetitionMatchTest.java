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

    @Test public void bodyPrefixAndApprovedMappingsFromCapturedHeaders() {
        // 26-27 Sep 2026: feed "Intercontinental Cup" (World), pages headed "FIBA Intercontinental Cup"
        assertEquals("body_prefixed (fiba)", EventIdentity.competitionMatchKind("Intercontinental Cup", "World", "FIBA Intercontinental Cup 27 Sep 07:30"));
        assertFalse(EventIdentity.competitionMatches("Intercontinental Cup", "World", "Euro Intercontinental Cup 27 Sep 07:30"));
        // 27 Sep 2026 04:11-04:23: feed "KBL Cup" (Korea), three pages headed "Club Friendlies"
        assertTrue(EventIdentity.competitionMatchKind("KBL Cup", "Korea", "Club Friendlies 27 Sep 06:00").startsWith("approved_mapping"));
        assertFalse(EventIdentity.competitionMatches("KBL Cup", "Japan", "Club Friendlies 27 Sep 06:00"));
        assertFalse(EventIdentity.competitionMatches("KBL Cup", "Korea", "Club Friendlies Women 27 Sep 06:00"));
        // feed "B League" (Japan) is the first division; B2/B3 are labelled "B2 League"/"B3 League" by the feed
        assertTrue(EventIdentity.competitionMatches("B League", "Japan", "Japan B League 1 • 25 Sep 10:35"));
        assertTrue(EventIdentity.competitionMatches("B League", "Japan", "Japan B League 127 Sep 07:05"));      // OCR glued the date to the "1"
        assertTrue(EventIdentity.competitionMatches("B League", "Japan", "6 Japan B League 1 - 25 Sep 10:35"));  // stray leading OCR digit
        assertFalse(EventIdentity.competitionMatches("B League", "Japan", "Japan B League 2 25 Sep 10:35"));
        assertFalse(EventIdentity.competitionMatches("B2 League", "Japan", "Japan B League 1 25 Sep 10:35"));
        assertEquals("japan b league 1", EventIdentity.competitionKey("Japan B League 125 Sep 10:45"));
        assertEquals("japan b league 1", EventIdentity.competitionKey("Japan B League 1 25 Sep 10:45"));
        assertEquals("france nationale 1", EventIdentity.competitionKey("France Nationale 1 • 25 Sep 19:00"));
        assertEquals("club friendlies", EventIdentity.competitionKey("Club Friendlies 27 Sep 06:00"));
        // 27 Sep 2026 football: feed "Division 1 Norra" (Sweden), page "Sweden 1.div Norra 27 Sep 12:00" (FC Arlanda v Enköping)
        assertEquals("sweden division 1 norra", EventIdentity.competitionKey("Sweden 1.div Norra 27 Sep 12:00"));
        assertEquals("country_prefixed", EventIdentity.competitionMatchKind("Division 1 Norra", "Sweden", "Sweden 1.div Norra 27 Sep 12:00"));
        assertFalse(EventIdentity.competitionMatches("Division 1 Sodra", "Sweden", "Sweden 1.div Norra 27 Sep 12:00"));
        // operator-approved narrow mappings (27 Sep 2026)
        assertTrue(EventIdentity.competitionMatchKind("ACB", "Spain", "Spain Liga ACB 27 Sep 12:30").startsWith("approved_mapping"));
        assertFalse(EventIdentity.competitionMatches("ACB", "Argentina", "Spain Liga ACB 27 Sep 12:30"));
        assertFalse(EventIdentity.competitionMatches("ACB", "Spain", "Spain Liga Endesa 27 Sep 12:30"));
        assertTrue(EventIdentity.competitionMatchKind("Premier League Women", "Kenya", "Kenya League Women 27 Sep 11:00").startsWith("approved_mapping"));
        assertFalse(EventIdentity.competitionMatches("Premier League Women", "Kenya", "Kenya Premier League 27 Sep 11:00"));
        assertFalse(EventIdentity.competitionMatches("Premier League Women", "Uganda", "Kenya League Women 27 Sep 11:00"));
        assertTrue(EventIdentity.competitionMatchKind("", "Mexico", "Mexico Liga ABE").startsWith("unknown"));
        assertTrue(EventIdentity.competitionMatchKind("Liga ABE", "Mexico", "Mexico LNBP").startsWith("mismatch"));
    }
}
