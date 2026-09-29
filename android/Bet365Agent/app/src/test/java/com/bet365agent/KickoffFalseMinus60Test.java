package com.bet365agent;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.junit.Test;

/**
 * False -60 minute kick-off mismatch class (28 Sep 2026 BST).
 *
 * Captured from pipeline.sqlite3 / speed-gap analysis:
 * - Zetech (#1): kickoff_utc 2026-09-28T12:00, alert UK "28 Sep 13:00", page "28 Sep 12:00"
 *   at 11:57 and 11:59 BST (on-d3678571, on-81633228). Same event at 12:29 read "28 Sep 13:00"
 *   and placed (on-b14751ca, receipt "Kenya League Women 28 Sep 13:00").
 * - Fomento Los Hornos: kickoff_utc 2026-09-28T20:00, alert UK "28 Sep 21:00", page "28 Sep 20:00"
 *   at 19:54 and 19:59 BST (on-0904d518, on-b807a521).
 *
 * Common signature: page wall-clock equals the UTC form of the alert instant; alert path correctly
 * converts to Europe/London (BST = UTC+1). Before the fix kickoffMatch returned mismatch (-60 min)
 * and identity refused WRONG_EVENT on the alert's own event link.
 */
public class KickoffFalseMinus60Test {

    @Test public void capturedStringsAreExactlySixtyMinutesApartDuringBst() {
        // Raw minute delta that the old matcher treated as a hard mismatch.
        assertEquals(-60, EventIdentity.kickoffMinutes("28 Sep 12:00") - EventIdentity.kickoffMinutes("28 Sep 13:00"));
        assertEquals(-60, EventIdentity.kickoffMinutes("28 Sep 20:00") - EventIdentity.kickoffMinutes("28 Sep 21:00"));
        assertEquals("28 Sep 13:00", EventPage.ukDisplay("2026-09-28T12:00"));
        assertEquals("28 Sep 12:00", EventPage.utcDisplay("2026-09-28T12:00"));
        assertEquals("28 Sep 21:00", EventPage.ukDisplay("2026-09-28T20:00"));
        assertEquals("28 Sep 20:00", EventPage.utcDisplay("2026-09-28T20:00"));
    }

    @Test public void zetechAndFomentoKickoffsAgreeAfterFix() {
        String zetech = EventIdentity.kickoffMatch("28 Sep 13:00", "28 Sep 12:00");
        assertTrue("Zetech should be same-instant, was: " + zetech, zetech.startsWith("same_instant_utc_display"));
        assertTrue(zetech.contains("-60"));

        String fomento = EventIdentity.kickoffMatch("28 Sep 21:00", "28 Sep 20:00");
        assertTrue("Fomento should be same-instant, was: " + fomento, fomento.startsWith("same_instant_utc_display"));
        assertTrue(fomento.contains("-60"));
    }

    @Test public void normalKickoffsUnchanged() {
        assertEquals("exact", EventIdentity.kickoffMatch("28 Sep 13:00", "28 Sep 13:00"));
        assertEquals("within_tolerance (+3 min)", EventIdentity.kickoffMatch("28 Sep 13:00", "28 Sep 13:03"));
        // Real two-hour difference stays a mismatch (not the UTC-display class).
        assertEquals("mismatch (-120 min)", EventIdentity.kickoffMatch("28 Sep 13:00", "28 Sep 11:00"));
        // Page ahead by 60 (alert behind) is NOT the UTC-display class ? stays a mismatch.
        assertEquals("mismatch (+60 min)", EventIdentity.kickoffMatch("28 Sep 12:00", "28 Sep 13:00"));
        // Winter (GMT=UTC): a genuine 60 min difference must not be waved through.
        assertEquals("mismatch (-60 min)", EventIdentity.kickoffMatch("5 Dec 13:00", "5 Dec 12:00"));
    }

    @Test public void zetechDirectLinkIdentityAcceptsAfterFix() {
        // Replays the identity decision that refused at 11:57 BST: teams matched, event link anchored,
        // only kick-off looked -60. After the fix it must accept (women marker from competition).
        Map<String, String> aliases = Collections.emptyMap();
        List<String> header = Arrays.asList(
                "Kenya League Women 28 Sep 12:00",
                "Zetech Sparks FC (W) v Kenya Police Bullets (W)");
        EventPage.Direct d = EventPage.decide(header, "football", "Zetech Sparks FC", "Kenya Police Bullets",
                EventPage.ukDisplay("2026-09-28T12:00"), "Premier League Women", "Kenya", true, aliases, true);
        assertEquals("28 Sep 12:00", d.shown);
        assertTrue(d.result.kickoffAgrees);
        assertTrue(d.result.kickoffKnown);
        assertTrue("Zetech identity must accept after kick-off class fix, was " + d.result.verdict + ": " + d.result.reason,
                d.result.accepted());
        assertTrue(String.valueOf(d.result.evidence.get("kickoff_match")).startsWith("same_instant"));
    }

    @Test public void fomentoKickoffNoLongerRefusesOnMinusSixty() {
        // Fomento page OCR read "Formento"; that name weakness is separate. This test locks the kick-off
        // class: the -60 min UTC-display reading must agree so policy is not "kickoff".
        Map<String, String> aliases = new HashMap<>();
        List<String> header = Arrays.asList(
                "Argentina Torneo Regional Amateur 28 Sep 20:00",
                "Formento Los Hornos v Napoli Argentino");
        EventPage.Direct d = EventPage.decide(header, "football", "Fomento Los Hornos", "Napoli Argentino",
                EventPage.ukDisplay("2026-09-28T20:00"), "Torneo Regional Federal Amateur", "Argentina", true, aliases, false);
        assertEquals("28 Sep 20:00", d.shown);
        assertTrue("Fomento kick-off must agree after class fix", d.result.kickoffAgrees);
        assertFalse("kickoff".equals(d.result.evidence.get("policy")));
        assertTrue(String.valueOf(d.result.evidence.get("kickoff_match")).startsWith("same_instant"));
        // Must not be the old WRONG_EVENT kick-off refusal.
        assertFalse(d.result.reason != null && d.result.reason.startsWith("kick-off differs"));
    }

    @Test public void laterExactUkReadStillMatches() {
        // Zetech at 12:29 BST: page correctly showed UK 13:00 (receipt OCR). Exact path unchanged.
        assertEquals("exact", EventIdentity.kickoffMatch("28 Sep 13:00", "28 Sep 13:00"));
        List<String> header = Arrays.asList(
                "Kenya League Women 28 Sep 13:00",
                "Zetech Sparks FC (W) v Kenya Police Bullets (W)");
        EventPage.Direct d = EventPage.decide(header, "football", "Zetech Sparks FC", "Kenya Police Bullets",
                EventPage.ukDisplay("2026-09-28T12:00"), "Premier League Women", "Kenya", true, Collections.emptyMap(), true);
        assertEquals("exact", d.result.evidence.get("kickoff_match"));
        assertTrue(d.result.accepted());
    }

    @Test public void searchPathWithMinusSixtyMustRefuseEvenWithExactTeams() {
        // Search / unanchored must NOT treat same_instant_utc_display as a general 60-minute tolerance.
        // Exact team names + -60 BST on a Search candidate must still refuse (WRONG_EVENT / kick-off differs).
        java.util.List<String> header = java.util.Arrays.asList(
                "Kenya League Women 28 Sep 12:00",
                "Zetech Sparks FC (W) v Kenya Police Bullets (W)");
        EventPage.Direct search = EventPage.decide(header, "football", "Zetech Sparks FC", "Kenya Police Bullets",
                EventPage.ukDisplay("2026-09-28T12:00"), "Premier League Women", "Kenya", false, java.util.Collections.emptyMap(), true);
        assertTrue(String.valueOf(search.result.evidence.get("kickoff_match")).startsWith("same_instant"));
        assertFalse("Search path must not agree on same_instant without event_id_match", search.result.kickoffAgrees);
        assertFalse("Search path with -60 must refuse", search.result.accepted());
        assertNotNull(search.result.evidence.get("same_instant_gate"));
        assertTrue(search.result.reason != null && search.result.reason.startsWith("kick-off differs"));
    }

    @Test public void weakUnanchoredMinusSixtyMustRefuse() {
        // Weak identity (naming variants) + unanchored + -60: still refuse; same_instant is not a Search tolerance.
        java.util.List<String> header = java.util.Arrays.asList(
                "Argentina Torneo Regional Amateur 28 Sep 20:00",
                "Formento Los Hornos v Napoli Argentino");
        EventPage.Direct weak = EventPage.decide(header, "football", "Fomento Los Hornos", "Napoli Argentino",
                EventPage.ukDisplay("2026-09-28T20:00"), "Torneo Regional Federal Amateur", "Argentina", false, java.util.Collections.emptyMap(), false);
        assertTrue(String.valueOf(weak.result.evidence.get("kickoff_match")).startsWith("same_instant"));
        assertFalse(weak.result.kickoffAgrees);
        assertFalse(weak.result.accepted());
    }

    @Test public void anchoredZetechAndFomentoStillAcceptSameInstant() {
        // Direct-link anchor + teams/date + no protected conflict: same_instant may ACCEPT (the 1f36d20 class).
        java.util.List<String> zHeader = java.util.Arrays.asList(
                "Kenya League Women 28 Sep 12:00",
                "Zetech Sparks FC (W) v Kenya Police Bullets (W)");
        EventPage.Direct z = EventPage.decide(zHeader, "football", "Zetech Sparks FC", "Kenya Police Bullets",
                EventPage.ukDisplay("2026-09-28T12:00"), "Premier League Women", "Kenya", true, java.util.Collections.emptyMap(), true);
        assertTrue(z.result.accepted());
        assertTrue(z.result.kickoffAgrees);
        assertEquals(Boolean.TRUE, z.result.evidence.get("event_id_match"));

        java.util.Map<String, String> aliases = new java.util.HashMap<>();
        java.util.List<String> fHeader = java.util.Arrays.asList(
                "Argentina Torneo Regional Amateur 28 Sep 20:00",
                "Formento Los Hornos v Napoli Argentino");
        EventPage.Direct f = EventPage.decide(fHeader, "football", "Fomento Los Hornos", "Napoli Argentino",
                EventPage.ukDisplay("2026-09-28T20:00"), "Torneo Regional Federal Amateur", "Argentina", true, aliases, false);
        assertTrue(f.result.kickoffAgrees);
        assertTrue(String.valueOf(f.result.evidence.get("kickoff_match")).startsWith("same_instant"));
        assertFalse(f.result.reason != null && f.result.reason.startsWith("kick-off differs"));
    }
}
