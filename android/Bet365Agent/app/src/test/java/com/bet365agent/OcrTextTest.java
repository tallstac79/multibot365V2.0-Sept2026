package com.bet365agent;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import java.util.Arrays;
import org.junit.Test;

public class OcrTextTest {
    @Test public void ligaturesBecomePlainLetters() {
        assertEquals("Hiroshima Dragonflies", OcrText.normalize("Hiroshima Dragonﬂies"));
        assertEquals("fi", OcrText.normalize("ﬁ"));
    }

    @Test public void realSagaHeaderVerifiesAfterNormalisation() {
        String header = OcrText.normalize("Saga Ballooners vs Hiroshima Dragonﬂies");
        assertArrayEquals(new String[] {"Saga Ballooners", "Hiroshima Dragonflies"}, EventPage.teams(Arrays.asList(header)));
        assertTrue(Bet365LiveAdapter.identityForTest("Hiroshima Dragonﬂies", "Hiroshima Dragonflies"));
    }
}
