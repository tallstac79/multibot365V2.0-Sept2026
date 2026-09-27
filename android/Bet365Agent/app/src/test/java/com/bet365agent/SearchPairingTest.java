package com.bet365agent;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotEquals;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

/** Search fallback, real results 27 Sep 2026: heading "Vellaznimi vs KB Prishtina >" + the event row = one event. */
public class SearchPairingTest {
    @Test public void headingChevronIsTheSameEvent() {
        assertEquals(SearchPairing.key("Vellaznimi", "KB Prishtina)"), SearchPairing.key("Vellaznimi", "KB Prishtina"));
        assertEquals(SearchPairing.key("Vellaznimi", "KB Prishtina >"), SearchPairing.key("Vellaznimi", "KB Prishtina"));
        assertTrue(SearchPairing.cleaner("Vellaznimi", "KB Prishtina", "Vellaznimi", "KB Prishtina)"));
        assertFalse(SearchPairing.cleaner("Vellaznimi", "KB Prishtina)", "Vellaznimi", "KB Prishtina"));
    }

    @Test public void differentEventsStayDistinct() {
        assertNotEquals(SearchPairing.key("Skovbakken (W)", "Horsholm 79ers (W)"), SearchPairing.key("Skovbakken", "Horsholm 79ers"));
        assertNotEquals(SearchPairing.key("Legia Warsaw", "Zielona Gora"), SearchPairing.key("Legia Warsaw II", "Zielona Gora"));
        assertNotEquals(SearchPairing.key("Vellaznimi", "KB Prishtina"), SearchPairing.key("KB Prishtina", "Vellaznimi"));
        assertFalse(SearchPairing.cleaner("Skovbakken (W)", "Horsholm 79ers (W)", "Skovbakken", "Horsholm 79ers"));
    }
}
