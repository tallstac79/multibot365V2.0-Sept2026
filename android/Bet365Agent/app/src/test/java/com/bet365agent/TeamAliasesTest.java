package com.bet365agent;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

/** Explicit team aliases (live Kyoto Hannaryz v Shiga Lake Stars, 2026-09-24). */
public class TeamAliasesTest {
    @Test public void feedNameMatchesBet365Name() {
        assertEquals("shiga lakes", TeamAliases.canonical("shiga lake stars"));
        assertTrue(Bet365LiveAdapter.identityForTest("Shiga Lakes", "Shiga Lake Stars"));
        assertTrue(Bet365LiveAdapter.identityForTest("Shiga Lakes", "SHIGA  Lake Stars"));
        assertTrue(Bet365LiveAdapter.identityForTest("Kyoto Hannaryz", "Kyoto Hannaryz"));
    }

    @Test public void aliasIsExactAndTeamSpecific() {
        assertEquals("lake stars", TeamAliases.canonical("lake stars"));               // no partial-name aliasing
        assertEquals("shiga lake stars b", TeamAliases.canonical("shiga lake stars b"));
        assertFalse(Bet365LiveAdapter.identityForTest("Kyoto Hannaryz", "Shiga Lake Stars"));
        assertFalse(Bet365LiveAdapter.identityForTest("Shiga Lakes", "Kyoto Hannaryz"));
        assertFalse(Bet365LiveAdapter.identityForTest("Osaka Evessa", "Shiga Lake Stars"));
        assertFalse(Bet365LiveAdapter.identityForTest("Bayern Munich", "Shiga Lake Stars"));
    }
}
