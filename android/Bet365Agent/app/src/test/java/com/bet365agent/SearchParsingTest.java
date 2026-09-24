package com.bet365agent;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

/** Search-result team names from real OCR (READY proof 2026-09-24, Hapoel Tel Aviv vs Bayern Munich). */
public class SearchParsingTest {
    @Test public void eventLinkChevronIsNotPartOfTheName() {
        assertEquals("Bayern Munich", Bet365LiveAdapter.cleanTeam("Bayern Munich >"));
    }

    @Test public void mergedColumnHeadersAreStripped() {
        assertEquals("Bayern", Bet365LiveAdapter.cleanTeam("Bayern 1 2"));
        assertEquals("Wales", Bet365LiveAdapter.cleanTeam("Wales 1 X 2"));
        assertEquals("Hapoel Tel Aviv 2", Bet365LiveAdapter.cleanTeam("Hapoel Tel Aviv 2")); // a lone digit may be the name
    }

    @Test public void onlyNameLikeLinesContinueAWrappedName() {
        assertTrue(Bet365LiveAdapter.continuationWord("Munich"));
        assertFalse(Bet365LiveAdapter.continuationWord("Thu 24 Sep 17:00"));
        assertFalse(Bet365LiveAdapter.continuationWord("Thu"));
        assertFalse(Bet365LiveAdapter.continuationWord("-8.0 1.83 +8.0 1.83"));
        assertFalse(Bet365LiveAdapter.continuationWord("Casino"));
    }
}
