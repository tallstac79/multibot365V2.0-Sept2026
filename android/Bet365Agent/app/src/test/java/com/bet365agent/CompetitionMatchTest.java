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

    @Test public void bookmakerRegionalGroupSuffixIsAccepted() {
        // 27 Sep 2026 10:49Z: feed "Division 2" (Sweden), page "Sweden 2.div Norrland 27 Sep 12:00" (Lucksta IF v Taftea IK)
        assertEquals("country_prefixed_group (norrland)", EventIdentity.competitionMatchKind("Division 2", "Sweden", "Sweden 2.div Norrland 27 Sep 12:00"));
        assertEquals("country_prefixed_group (norra svealand)", EventIdentity.competitionMatchKind("Division 2", "Sweden", "Sweden 2.div Norra Svealand 27 Sep 12:00"));
        // a protected marker, a number or a third word is a different competition, not a group
        assertFalse(EventIdentity.competitionMatches("Division 2", "Sweden", "Sweden 2.div Women 27 Sep 12:00"));
        assertFalse(EventIdentity.competitionMatches("Division 2", "Sweden", "Sweden 2.div U21 27 Sep 12:00"));
        assertFalse(EventIdentity.competitionMatches("Division 2", "Sweden", "Sweden 2.div 3 27 Sep 12:00"));
        assertFalse(EventIdentity.competitionMatches("Division 2", "Sweden", "Sweden 2.div Norra Svealand Cup 27 Sep 12:00"));
        assertFalse(EventIdentity.competitionMatches("Division 2", "Norway", "Sweden 2.div Norrland 27 Sep 12:00"));
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
        // anchored page (the alert's own event link): without an alert country the prefix cannot conflict -> structural match
        assertEquals(EventIdentity.Verdict.EXACT, EventIdentity.resolveVerified(feed, page, Collections.emptyMap(), false).verdict);
        EventIdentity.Event unanchored = new EventIdentity.Event("basketball", "UP Mexico", "UMAD", "26 Sep 21:30", "Mexico Liga ABE 26 Sep 21:30", false);
        assertEquals(EventIdentity.Verdict.AMBIGUOUS, EventIdentity.resolveVerified(feed, unanchored, Collections.emptyMap(), false).verdict);
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
        // real header 27 Sep 2026 (EGS Gafsa v AS Kasserine): separator read glued, "League 2\u202227 Sep 15:00"
        assertEquals("tunisia league 2", EventIdentity.competitionKey("Tunisia League 2\u202227 Sep 15:00"));
        assertEquals("country_prefixed", EventIdentity.competitionMatchKind("League 2", "Tunisia", "Tunisia League 2\u202227 Sep 15:00"));
        assertTrue(EventIdentity.competitionMatchKind("League 1", "Tunisia", "Tunisia League 2\u202227 Sep 15:00").startsWith("mismatch"));
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

    /** 2026-09-29 inventory: SAFE verified equivalences seeded into COMPETITION_ALIASES (Spain ACB already present). */
    @Test public void inventorySafeCompetitionMappings20260929() {
        // Adriatic: operator scope international| (alerts often omit ISO country)
        assertTrue(EventIdentity.competitionMatchKind("Adriatic League Women", "International", "Adriatic WABA Women 27 Sep 15:00").startsWith("approved_mapping"));
        assertFalse(EventIdentity.competitionMatches("Adriatic League Women", "Poland", "Adriatic WABA Women 27 Sep 15:00"));
        assertTrue(EventIdentity.competitionMatchKind("Liga 1 Women", "Poland", "Poland 1 Liga Women 27 Sep 12:00").startsWith("approved_mapping")
                || EventIdentity.competitionMatchKind("Liga 1 Women", "Poland", "Poland 1 Liga Women 27 Sep 12:00").equals("same_words_reordered"));
        assertTrue(EventIdentity.competitionMatches("Liga 1 Women", "Poland", "Poland 1 Liga Women 27 Sep 12:00"));
        assertTrue(EventIdentity.competitionMatchKind("Super League Women", "Turkey", "Turkiye TKBSL Women 27 Sep 12:00").startsWith("approved_mapping"));
        assertTrue(EventIdentity.competitionMatches("Division 1 Women", "Belgium", "Belgium Div 1 Women 27 Sep 14:00"));
        assertTrue(EventIdentity.competitionMatchKind("NPFL", "Nigeria", "Nigeria Premier League 27 Sep 16:00").startsWith("approved_mapping"));
        assertTrue(EventIdentity.competitionMatchKind("SB League", "Switzerland", "Switzerland LNA 27 Sep 15:00").startsWith("approved_mapping"));
        assertTrue(EventIdentity.competitionMatchKind("ACB", "Spain", "Spain Liga ACB 27 Sep 12:30").startsWith("approved_mapping")); // already present
        assertTrue(EventIdentity.competitionMatchKind("Nacional Championship Women", "Portugal", "Portugal Campeonato Nacional Women 27 Sep 17:00").startsWith("approved_mapping"));
        assertTrue(EventIdentity.competitionMatchKind("NB 2 Women", "Hungary", "Hungary NBII Women 27 Sep 16:30").startsWith("approved_mapping"));
        assertTrue(EventIdentity.competitionMatchKind("Paraense 3", "Brazil", "Brazil Campeonato Paraense A3 27 Sep 23:00").startsWith("approved_mapping"));
        assertTrue(EventIdentity.competitionMatchKind("Super League", "Turkey", "Turkiye BSL 27 Sep 16:00").startsWith("approved_mapping"));
        // country / gender / tier scoping still closed
        assertFalse(EventIdentity.competitionMatches("Super League Women", "Greece", "Turkiye TKBSL Women 27 Sep 12:00"));
        assertFalse(EventIdentity.competitionMatches("Super League", "Turkey", "Turkiye TKBSL Women 27 Sep 12:00")); // men vs women page
        assertFalse(EventIdentity.competitionMatches("NPFL", "Nigeria", "Nigeria Premier League Women 27 Sep 16:00"));
        assertFalse(EventIdentity.competitionMatches("SB League", "Switzerland", "Switzerland LNB 27 Sep 15:00"));
        assertFalse(EventIdentity.competitionMatches("Paraense 3", "Brazil", "Brazil Campeonato Paraense A2 27 Sep 23:00"));
    }

    /**
     * Historical ALIAS_REQUIRED competition-mismatch instructions from the 2026-09-29 SAFE set (33 occurrences
     * across 11 pairs / 11 event IDs). Anchored direct-link pages with known kick-off must pass the competition gate;
     * must_remain_conflicting and needs_manual_review must not gain approved mappings.
     */
    @Test public void inventorySafeHistoricalInstructionsPassCompetitionGate() {
        Object[][] safe = new Object[][] {
            // sport, home, away, kickoff, feedCompetition, pageCompetition, country, occurrences
            {"basketball", "ZKK Buducnost", "Sibenik", "27 Sep 15:00", "Adriatic League Women", "Adriatic WABA Women 27 Sep 15:00", "International", 8},
            {"basketball", "LKS Lodz", "Sparta Ziebice", "27 Sep 12:00", "Liga 1 Women", "Poland 1 Liga Women 27 Sep 12:00", "Poland", 7},
            {"basketball", "Botas SK", "CBK Mersin Yenisehir Bld", "27 Sep 12:00", "Super League Women", "Turkiye TKBSL Women 27 Sep 12:00", "Turkey", 6},
            {"basketball", "Phantoms Boom", "Liege Panthers", "27 Sep 14:00", "Division 1 Women", "Belgium Div 1 Women 27 Sep 14:00", "Belgium", 3},
            {"football", "Ikorodu City", "Enugu Rangers International", "27 Sep 16:00", "NPFL", "Nigeria Premier League 27 Sep 16:00", "Nigeria", 2},
            {"basketball", "Fribourg Olympic", "Union Neuchatel Basket", "27 Sep 15:00", "SB League", "Switzerland LNA 27 Sep 15:00", "Switzerland", 2},
            {"basketball", "CB San Pablo Burgos", "Baskonia Vitoria Gasteiz", "27 Sep 11:30", "ACB", "Spain Liga ACB 27 Sep 11:30", "Spain", 1},
            {"football", "Torreense", "Maritimo", "27 Sep 17:00", "Nacional Championship Women", "Portugal Campeonato Nacional Women 27 Sep 17:00", "Portugal", 1},
            {"football", "Budaorsi", "Godolloi SK", "27 Sep 16:30", "NB 2 Women", "Hungary NBII Women 27 Sep 16:30", "Hungary", 1},
            {"football", "Tesla", "Pedreira EC", "27 Sep 23:00", "Paraense 3", "Brazil Campeonato Paraense A3 27 Sep 23:00", "Brazil", 1},
            {"basketball", "Bahcesehir Koleji", "Fenerbahce", "27 Sep 16:00", "Super League", "Turkiye BSL 27 Sep 16:00", "Turkey", 1},
        };
        int covered = 0;
        for (Object[] row : safe) {
            EventIdentity.Event feed = new EventIdentity.Event((String) row[0], (String) row[1], (String) row[2], (String) row[3], (String) row[4], false);
            EventIdentity.Event page = new EventIdentity.Event((String) row[0], (String) row[1], (String) row[2], (String) row[3], (String) row[5], true);
            EventIdentity.Result r = EventIdentity.resolveVerified(feed, page, Collections.emptyMap(), false, (String) row[6]);
            assertTrue(row[4] + " -> " + row[5] + " : " + r.reason + " evidence=" + r.evidence, r.accepted());
            String kind = String.valueOf(r.evidence.get("competition_match"));
            assertFalse("must not be mismatch: " + kind, kind.startsWith("mismatch"));
            covered += (Integer) row[7];
        }
        assertEquals("33 historical SAFE instruction occurrences", 33, covered);

        // Empty-country Adriatic (as on live alerts): anchored + structural_compatible still passes; no code-path widen.
        EventIdentity.Event af = new EventIdentity.Event("basketball", "ZKK Buducnost", "Sibenik", "27 Sep 15:00", "Adriatic League Women", false);
        EventIdentity.Event ap = new EventIdentity.Event("basketball", "ZKK Buducnost", "Sibenik", "27 Sep 15:00", "Adriatic WABA Women 27 Sep 15:00", true);
        EventIdentity.Result ar = EventIdentity.resolveVerified(af, ap, Collections.emptyMap(), false, null);
        assertTrue(ar.reason, ar.accepted());
    }

    @Test public void inventoryConflictingAndReviewDoNotGainApprovedMappings() {
        // must_remain_conflicting — naming gate stays mismatch; structural gate stays closed
        assertTrue(EventIdentity.competitionMatchKind("Professional Development League U21", "England", "England Development League 2").startsWith("mismatch"));
        assertFalse(EventIdentity.competitionMatches("Professional Development League U21", "England", "England Development League 2"));
        assertTrue(EventIdentity.competitionMatchKind("Friendlies Women", "International", "Women s International Match").startsWith("mismatch"));
        assertTrue(EventIdentity.competitionMatchKind("Friendlies U19", "International", "U19 International").startsWith("mismatch"));
        assertTrue(EventIdentity.competitionMatchKind("Nations League A", "CONCACAF", "CONCACAF Nations League").startsWith("mismatch"));
        EventIdentity.Event f = new EventIdentity.Event("football", "Swansea City", "Queens Park Rangers", "28 Sep 19:00", "Professional Development League U21", false);
        EventIdentity.Event p = new EventIdentity.Event("football", "Swansea City", "Queens Park Rangers", "28 Sep 19:00", "England Development League 2", true);
        EventIdentity.Result bad = EventIdentity.resolveVerified(f, p, Collections.emptyMap(), false, "England");
        assertFalse(bad.accepted());
        assertTrue(String.valueOf(bad.evidence.get("competition_match")), String.valueOf(bad.evidence.get("competition_match")).contains("structural conflict"));

        // Friendlies / Nations League / U19: must NOT gain approved COMPETITION_ALIASES entries (naming gate stays mismatch).
        // Structural friendly-vs-competitive may still use genericOnly exceptions for bare international labels —
        // that path is unchanged here; we only assert aliases were not seeded.
        assertFalse(EventIdentity.COMPETITION_ALIASES.containsKey("international|friendlies women"));
        assertFalse(EventIdentity.COMPETITION_ALIASES.containsKey("international|friendlies u19"));
        assertFalse(EventIdentity.COMPETITION_ALIASES.containsKey("concacaf|nations league a"));
        assertFalse(EventIdentity.COMPETITION_ALIASES.containsKey("england|professional development league u21"));
        assertFalse(EventIdentity.COMPETITION_ALIASES.containsKey("spain|tercera division"));
        assertFalse(EventIdentity.COMPETITION_ALIASES.containsKey("spain|segunda federacion"));
        assertFalse(EventIdentity.COMPETITION_ALIASES.containsKey("bosnia and herzegovina|1st league"));

        // needs_manual_review — do NOT seed whole-competition aliases for group-specific / residue keys
        assertTrue(EventIdentity.competitionMatchKind("Tercera Division", "Spain", "Spain Tercera Group 18").startsWith("mismatch"));
        assertFalse(EventIdentity.competitionMatchKind("Tercera Division", "Spain", "Spain Tercera Group 18").startsWith("approved_mapping"));
        assertTrue(EventIdentity.competitionMatchKind("Segunda Federacion", "Spain", "Spain Segunda Division RFEF Group1").startsWith("mismatch"));
        assertFalse(EventIdentity.competitionMatchKind("Segunda Federacion", "Spain", "Spain Segunda Division RFEF Group1").startsWith("approved_mapping"));
        // Bosnia date-glue residue: after competitionKey strip it becomes country_prefixed, not an alias seed
        assertFalse(EventIdentity.competitionMatchKind("1st League", "Bosnia and Herzegovina", "Bosnia & Herzegovina 1st League27 Sep 15:00").startsWith("approved_mapping"));
    }
}
