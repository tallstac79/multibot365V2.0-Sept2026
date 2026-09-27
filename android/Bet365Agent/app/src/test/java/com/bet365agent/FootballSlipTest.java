package com.bet365agent;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.util.Arrays;
import org.junit.Test;

/** Betslip line readback for football lines: whole/half goals as before, quarter goals in both Bet365 spellings. */
public class FootballSlipTest {
    @Test public void basketballHalfLinesUnchanged() {
        assertTrue(PlacementClassifier.slipShowsLine(Arrays.asList("Bayern Munich +8.0", "1.83"), "SPREAD", "AWAY", "Bayern Munich", "+8.0"));
        assertTrue(PlacementClassifier.slipShowsLine(Arrays.asList("Under 173.5", "1.83"), "TOTAL", "UNDER", "Under", "173.5"));
        assertFalse(PlacementClassifier.slipShowsLine(Arrays.asList("Bayern Munich +7.0"), "SPREAD", "AWAY", "Bayern Munich", "+8.0"));
        assertTrue(PlacementClassifier.slipShowsLine(Arrays.asList("Kyoto Hannaryz 1.47"), "MONEYLINE", "HOME", "Kyoto Hannaryz", "NONE"));
    }

    @Test public void footballWholeHalfAndQuarterGoalLines() {
        // Asian handicap, whole goal, both spellings of the requested "-1"
        assertTrue(PlacementClassifier.slipShowsLine(Arrays.asList("Farul Constanta (W) -1.0", "Asian Handicap", "1.85"), "SPREAD", "HOME", "Farul Constanta (W)", "-1"));
        assertTrue(PlacementClassifier.slipShowsLine(Arrays.asList("Farul Constanta (W) -1.0"), "SPREAD", "HOME", "Farul Constanta (W)", "-1.0"));
        // quarter handicap as a decimal or as Bet365's split pair; never a different quarter
        assertTrue(PlacementClassifier.slipShowsLine(Arrays.asList("Halcones Negros -1.75"), "SPREAD", "HOME", "Halcones Negros", "-1.75"));
        assertTrue(PlacementClassifier.slipShowsLine(Arrays.asList("Halcones Negros -1.5,-2.0"), "SPREAD", "HOME", "Halcones Negros", "-1.75"));
        assertTrue(PlacementClassifier.slipShowsLine(Arrays.asList("Halcones Negros -1.5, -2.0"), "SPREAD", "HOME", "Halcones Negros", "-1.75"));
        assertTrue(PlacementClassifier.slipShowsLine(Arrays.asList("Ulinzi Starlets (W) 0.0,-0.5"), "SPREAD", "AWAY", "Ulinzi Starlets (W)", "-0.25"));
        assertTrue(PlacementClassifier.slipShowsLine(Arrays.asList("Vihiga Queens FC (W) +0.0,+0.5"), "SPREAD", "HOME", "Vihiga Queens FC (W)", "+0.25"));
        assertFalse(PlacementClassifier.slipShowsLine(Arrays.asList("Halcones Negros -1.25"), "SPREAD", "HOME", "Halcones Negros", "-1.75"));
        assertFalse(PlacementClassifier.slipShowsLine(Arrays.asList("Halcones Negros -1.0,-1.5"), "SPREAD", "HOME", "Halcones Negros", "-1.75"));
        // goals: half, whole and quarter totals
        assertTrue(PlacementClassifier.slipShowsLine(Arrays.asList("Over 2.5", "Goals Over/Under"), "TOTAL", "OVER", "Over", "2.5"));
        assertTrue(PlacementClassifier.slipShowsLine(Arrays.asList("Under 3.0"), "TOTAL", "UNDER", "Under", "3"));
        assertTrue(PlacementClassifier.slipShowsLine(Arrays.asList("Over 2.75"), "TOTAL", "OVER", "Over", "2.75"));
        assertTrue(PlacementClassifier.slipShowsLine(Arrays.asList("Over 2.5,3.0"), "TOTAL", "OVER", "Over", "2.75"));
        assertFalse(PlacementClassifier.slipShowsLine(Arrays.asList("Over 2.5"), "TOTAL", "OVER", "Over", "2.75"));
        assertFalse(PlacementClassifier.slipShowsLine(Arrays.asList("Under 2.75"), "TOTAL", "OVER", "Over", "2.75"));
    }
}
