package com.bet365agent;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.util.Arrays;
import org.junit.Test;

public class OcrTextTest {
    @Test public void ligaturesBecomePlainLetters() {
        assertEquals("Hiroshima Dragonflies", OcrText.normalize("Hiroshima Dragonﬂies"));
        assertEquals("fi", OcrText.normalize("ﬁ"));
    }

    @Test public void placeholderHintToleratesTheEllipsisOnly() {
        assertTrue(OcrText.placeholderMatches("bet365...", "bet365..."));
        assertTrue(OcrText.placeholderMatches("bet365.", "bet365..."));      // real frame: caret over the dots
        assertTrue(OcrText.placeholderMatches("bet365…", "bet365..."));
        assertFalse(OcrText.placeholderMatches("bet365", "bet365..."));      // the bare logo word is not the field
        assertFalse(OcrText.placeholderMatches("bet365.com/#/AX/", "bet365..."));
        assertFalse(OcrText.placeholderMatches("Search", "bet365..."));
        assertFalse(OcrText.placeholderMatches("Searc", "Search"));          // hints without an ellipsis stay exact
    }

    @Test public void realSagaHeaderVerifiesAfterNormalisation() {
        String header = OcrText.normalize("Saga Ballooners vs Hiroshima Dragonﬂies");
        assertArrayEquals(new String[] {"Saga Ballooners", "Hiroshima Dragonflies"}, EventPage.teams(Arrays.asList(header)));
        assertTrue(Bet365LiveAdapter.identityForTest("Hiroshima Dragonﬂies", "Hiroshima Dragonflies"));
    }
}
