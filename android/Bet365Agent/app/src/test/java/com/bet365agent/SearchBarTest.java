package com.bet365agent;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import org.junit.Test;

/** Real frames from the live Kyoto Hannaryz v Shiga Lake Stars failure (2026-09-24). */
public class SearchBarTest {
    private static GameLinesParser.Word w(String t, int l, int top, int r, int b) { return new GameLinesParser.Word(t, l, top, r, b); }

    @Test public void filledBarFromTheLiveFailureIsFoundWithItsClearIcon() throws Exception {
        SearchBar.Bar bar = SearchBar.locate(StakePadTest.load("search_kyoto_filled_20260924.txt"));
        assertNotNull(bar);
        assertEquals("Kyoto Hannaryz Shiga Lake Stars", bar.text);
        assertFalse(bar.empty);
        assertNotNull("the X the old line-level match missed", bar.clear);
        assertEquals(567, bar.clear[0]);
        assertTrue(bar.field[0] >= 70 && bar.field[2] < 567);
    }

    @Test public void cursorFrameToo() throws Exception {
        SearchBar.Bar bar = SearchBar.locate(StakePadTest.load("search_kyoto_filled_cursor_20260924.txt"));
        assertFalse(bar.empty);
        assertNotNull(bar.clear);
    }

    @Test public void emptyBarShowsOnlyThePlaceholder() throws Exception {
        SearchBar.Bar bar = SearchBar.locate(StakePadTest.load("search_empty_20260924.txt"));
        assertNotNull(bar);
        assertTrue(bar.text, bar.empty);
        assertNull(bar.clear);
    }

    /** Real frame, Milestone B 2026-09-25 (on-8f79281a, Norrkoping v Umea): the empty bar's voice icon OCRs as "HO". */
    @Test public void emptyBarWithVoiceIconReadAsHoIsStillEmpty() throws Exception {
        SearchBar.Bar bar = SearchBar.locate(StakePadTest.load("search_empty_voice_icon_20260925.txt"));
        assertNotNull(bar);
        assertEquals(1, bar.candidates);
        assertEquals("Search bet365...", bar.text);
        assertTrue(bar.empty);
        assertNull(bar.clear);
    }

    @Test public void typedQueryReachingTheIconZoneIsStillNotEmpty() {
        List<GameLinesParser.Word> words = new ArrayList<>(Arrays.asList(
                w("Q", 68, 177, 75, 203), w("Hapoel", 87, 177, 170, 203), w("Jerusalem", 178, 177, 300, 203),
                w("Bnei", 308, 177, 360, 203), w("Herzliya", 368, 177, 470, 203), w("Utd", 478, 177, 545, 203),
                w("X", 567, 178, 590, 202), w("Close", 632, 183, 682, 198)));
        SearchBar.Bar bar = SearchBar.locate(words);
        assertNotNull(bar);
        assertFalse(bar.empty);
        assertEquals("Hapoel Jerusalem Bnei Herzliya Utd", bar.text);
        assertNotNull(bar.clear);
    }

    @Test public void closedSearchOnSportsHomeIsNotAnOpenBar() throws Exception {
        assertNull(SearchBar.locate(StakePadTest.load("search_home_closed_20260924.txt")));
    }

    @Test public void twoBarLikeRowsAreAmbiguousNeverUsed() {
        List<GameLinesParser.Word> words = new ArrayList<>(Arrays.asList(
                w("Q", 38, 175, 70, 208), w("Search", 87, 181, 163, 200), w("Close", 632, 183, 682, 198),
                w("Q", 38, 275, 70, 308), w("Close", 632, 283, 682, 298)));
        SearchBar.Bar bar = SearchBar.locate(words);
        assertEquals(2, bar.candidates);
        assertNull(bar.field);
    }
}
