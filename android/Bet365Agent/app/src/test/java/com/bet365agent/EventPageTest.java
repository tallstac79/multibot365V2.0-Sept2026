package com.bet365agent;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import java.util.Arrays;
import org.junit.Test;

/** Real event pages and alert links (2026-09-24). */
public class EventPageTest {
    @Test public void alertLinksAreValidatedAndCarryTheSport() {
        String besancon = "https://www.bet365.com/#/AC/B18/C21168177/D19/E26747385/F19/I0/";
        assertTrue(EventPage.validUrl(besancon));
        assertEquals("basketball", EventPage.sportOf(besancon));
        assertEquals("football", EventPage.sportOf("https://www.bet365.com/#/AC/B1/C1/D8/E191/F3/"));
        assertFalse(EventPage.validUrl("https://evil.example/#/AC/B18/C1/D1/"));
        assertFalse(EventPage.validUrl("https://www.bet365.com/#/AX/K9"));
        assertFalse(EventPage.validUrl("https://www.bet365.com/#/AC/B18/C21168177/D19/E26747385/F19/I0/?x=javascript:"));
    }

    @Test public void headerTeamsFromBothLayouts() {
        assertArrayEquals(new String[] {"Kyoto Hannaryz", "Shiga Lakes"},
                EventPage.teams(Arrays.asList("Japan B League 1 * 25 Sep 10:35", "Kyoto Hannaryz vs Shiga Lakes v")));
        assertArrayEquals(new String[] {"Besancon AC", "Val de Seine"},
                EventPage.teams(Arrays.asList("France Nationale 1 • 25 Sep 19:00", "Besancon AC vs Val de Seine")));
        // Euroleague layout OCR: "Hapoel ‘ \ Tel Aviv VS Bayern Munich".
        assertArrayEquals(new String[] {"Hapoel Tel Aviv", "Bayern Munich"},
                EventPage.teams(Arrays.asList("Euroleague", "Hapoel ‘ \\ Tel Aviv VS Bayern Munich")));
        assertNull(EventPage.teams(Arrays.asList("Game Lines", "Spread Total Money Li...")));
    }

    @Test public void scrolledHeaderStillGivesTeamsAndKickoff() {
        // Real run (2026-09-25 01:02): the page rendered with bet365's top bar scrolled off; the header lines the
        // adapter now passes start right below Chrome's URL bar, with the logo/balance line skipped.
        java.util.List<String> header = Arrays.asList("France Nationale 1 • 25 Sep 19:00", "Berck/Rang du Fliers vs Pays Salonais Basket", "13", "Popular Bet Builder", "Game Lines");
        assertArrayEquals(new String[] {"Berck/Rang du Fliers", "Pays Salonais Basket"}, EventPage.teams(header));
        assertEquals("25 Sep 19:00", EventPage.kickoffText(header));
        // normal layout with the logo/balance line present would still read the same
        assertEquals("25 Sep 19:00", EventPage.kickoffText(Arrays.asList("bet365 £3.50 (+)", "France Nationale 1 • 25 Sep 19:00", "Besancon AC vs Val de Seine")));
    }

    @Test public void closedEventPageIsRecognised() throws Exception {
        java.util.List<String> words = new java.util.ArrayList<>();
        for (GameLinesParser.Word w : StakePadTest.load("event_closed_araraquara_20260924.txt")) words.add(w.text);
        assertTrue(EventPage.closed(words));
        assertFalse(EventPage.closed(Arrays.asList("Japan B League 1 * 25 Sep 10:35", "Kyoto Hannaryz vs Shiga Lakes",
                "Game Lines", "Spread Total Money Li...")));
        assertFalse(EventPage.closed(Arrays.asList("Hapoel Tel Aviv -8.0", "Selection Suspended")));   // not the page message
    }

    @Test public void namingVariantsAreLabelledButWrongOpponentsAreNot() {
        assertTrue(EventPage.namingVariant("Sopron KC", "Soproni KC"));
        assertTrue(EventPage.namingVariant("DEAC Debreceni", "Debreceni EAC"));
        assertTrue(EventPage.namingVariant("Shiga Lakes", "Shiga Lake Stars"));
        assertTrue(EventPage.namingVariant("Berck/Rang du Fliers", "Berck Fliers Range"));
        assertTrue(EventPage.namingVariant("Val de Seine", "Valdeseine"));
        assertTrue(EventPage.namingVariant("Hiroshima Dragon\uFB02ies", "Hiroshima Dragonflies"));
        assertFalse(EventPage.namingVariant("Shiga Lakes", "Bayern Munich"));
        assertFalse(EventPage.namingVariant("Pays Salonais Basket 13", "Mogi Das Cruzes"));
        assertFalse(EventPage.namingVariant("Basket Club A", "Basket Club B"));      // generic tokens do not count
    }

    @Test public void kickoffIsComparedInUkTime() {
        assertEquals("25 Sep 10:35", EventPage.kickoffText(Arrays.asList("Japan B League 1 * 25 Sep 10:35")));
        assertEquals("25 Sep 10:35", EventPage.ukDisplay("2026-09-25T09:35"));     // BST = UTC+1
        assertEquals("25 Sep 19:00", EventPage.ukDisplay("2026-09-25T18:00"));
        assertEquals("5 Dec 18:00", EventPage.ukDisplay("2026-12-05T18:00"));      // GMT = UTC in winter
        assertNull(EventPage.kickoffText(Arrays.asList("Q3 04:12", "Kyoto Hannaryz vs Shiga Lakes")));
    }
}
