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

/**
 * Live regression, 28 Sep 2026 07:05-07:15Z, Wenzhou Yincai U20 v Qingdao Red Lions U20 (China U20 League):
 * on-cebe474a Over 4.25 (min 1.84) and on-44457a9c / on-11883180 / on-eae84dcd Over 4.5 (min 1.77), allowance 0.25.
 * The Popular tab showed only the main "Goals Over/Under 2.5 - Over 1.20 / Under 4.33"; the one-sided line rule counted
 * Over 2.5 as an improvement, discovery stopped there and 1.20 was judged against the 4.25/4.5 minimum (BELOW_MINIMUM).
 * Football AH and Totals now use a +/- allowance band around the alert line; basketball is unchanged.
 */
public class FootballLineBandTest {
    static final String HOME = "Wenzhou Yincai U20", AWAY = "Qingdao Red Lions U20";

    static List<String[]> popular() throws Exception {
        List<String[]> out = new ArrayList<>();
        for (FootballMarkets.Cell c : FootballMarkets.parse(StakePadTest.load("football_wenzhou_popular_20260928.txt"), HOME, AWAY).cells)
            out.add(FootballLineCheck.quote(c.market, c.side, c.line, c.price));
        return out;
    }

    @Test public void thePopularTabShowsOnlyTheMainLine() throws Exception {
        List<String[]> q = popular();
        boolean over25 = false;
        for (String[] x : q) if (x[0].equals("TOTAL") && x[1].equals("OVER") && x[2].equals("2.5") && x[3].equals("1.20")) over25 = true;
        assertTrue(over25);
    }

    @Test public void over25IsNeverTheQuoteForAnOver425OrOver45Alert() throws Exception {
        List<String[]> q = popular();
        for (String requested : new String[] {"4.25", "4.5"}) {
            assertEquals(requested, -1, FootballLineCheck.nearest(q, "TOTAL", "OVER", requested, "0.25"));
            assertFalse(FootballLineCheck.withinAllowance("TOTAL", "OVER", requested, "2.5", "0.25"));
            String refusal = FootballLineCheck.lineRefusal(q, "TOTAL", "OVER", requested, "0.25");
            assertNotNull(refusal);                                   // the genuine reason: no line near the alert line
            assertTrue(refusal, refusal.contains("2.5 @ 1.20"));
            assertEquals("LINE_CHANGED", FootballLineCheck.freshTerms("TOTAL", "OVER", requested, "2.5", "1.20", "0.25", "1.77")[0]);
        }
    }

    @Test public void theBandIsTwoSidedForFootballTotalsAndHandicaps() {
        for (String live : new String[] {"4.25", "4.5", "4.75"}) assertTrue(live, ExecutionTolerance.footballLine("TOTAL", "OVER", "4.5", live, "0.25"));
        for (String live : new String[] {"4.0", "5.0", "2.5", "6.5"}) assertFalse(live, ExecutionTolerance.footballLine("TOTAL", "OVER", "4.5", live, "0.25"));
        assertTrue(ExecutionTolerance.footballLine("TOTALS", "UNDER", "2.5", "2.75", "0.25"));
        assertFalse(ExecutionTolerance.footballLine("TOTALS", "UNDER", "2.5", "4.5", "0.25"));      // "better" for Under, still another line
        assertTrue(ExecutionTolerance.footballLine("SPREAD", "AWAY", "-2", "-2.25", "0.25"));
        assertTrue(ExecutionTolerance.footballLine("SPREAD", "AWAY", "-2", "-1.75", "0.25"));
        assertFalse(ExecutionTolerance.footballLine("SPREAD", "AWAY", "-2", "0.5", "0.25"));        // far "improvement"
        assertFalse(ExecutionTolerance.footballLine("SPREAD", "AWAY", "-2", "-2.5", "0.25"));
        assertFalse(ExecutionTolerance.footballLine("MONEYLINE", "HOME", "", "", "0.25"));
        assertFalse(ExecutionTolerance.footballLine("TOTAL", "OVER", "4.5", "4.5", "-1"));
    }

    @Test public void basketballKeepsItsOneSidedRule() {
        assertTrue(ExecutionTolerance.line("TOTAL", "OVER", "190.5", "180.5", "1"));                // improvement unchanged
        assertFalse(ExecutionTolerance.line("TOTAL", "OVER", "190.5", "192.5", "1"));
        assertTrue(ExecutionTolerance.lineForSport("basketball", "TOTAL", "OVER", "190.5", "180.5", "1"));
        assertFalse(ExecutionTolerance.lineForSport("football", "TOTAL", "OVER", "4.5", "2.5", "0.25"));
    }

    @Test public void exactLineFirstThenNearestInsideTheBand() {
        List<String[]> lines = Arrays.asList(FootballLineCheck.quote("TOTAL", "OVER", "4.0", "1.70"), FootballLineCheck.quote("TOTAL", "OVER", "4.5", "1.95"),
                FootballLineCheck.quote("TOTAL", "OVER", "4.25", "1.85"), FootballLineCheck.quote("TOTAL", "UNDER", "4.25", "1.95"));
        assertEquals(2, FootballLineCheck.nearest(lines, "TOTAL", "OVER", "4.25", "0.25"));          // exact
        assertEquals(1, FootballLineCheck.nearest(lines, "TOTAL", "OVER", "4.75", "0.25"));          // nearest (4.5)
        assertEquals(-1, FootballLineCheck.nearest(lines, "TOTAL", "OVER", "5.25", "0.25"));         // none within 0.25
        List<String[]> tie = Arrays.asList(FootballLineCheck.quote("TOTAL", "OVER", "4.25", "1.90"), FootballLineCheck.quote("TOTAL", "OVER", "4.75", "2.10"));
        assertEquals(-1, FootballLineCheck.nearest(tie, "TOTAL", "OVER", "4.5", "0.25"));            // equally near: no implicit choice
        List<String[]> same = Arrays.asList(FootballLineCheck.quote("TOTAL", "OVER", "4.75", "1.90"), FootballLineCheck.quote("TOTAL", "OVER", "4.75", "1.90"));
        assertEquals(0, FootballLineCheck.nearest(same, "TOTAL", "OVER", "4.5", "0.25"));            // the same line read twice is no tie
        List<String[]> ml = Arrays.<String[]>asList(FootballLineCheck.quote("MONEYLINE", "AWAY", "", "2.50"));
        assertEquals(0, FootballLineCheck.nearest(ml, "MONEYLINE", "AWAY", "NONE", "0.25"));
    }

    @Test public void theReReadNeverSubstitutesAFarLine() {
        List<String[]> moved = Arrays.asList(FootballLineCheck.quote("TOTAL", "OVER", "2.5", "1.20"), FootballLineCheck.quote("TOTAL", "OVER", "4.75", "2.05"));
        assertEquals(1, FootballLineCheck.pick(moved, "TOTAL", "OVER", "4.5", "4.5", "0.25"));      // 4.5 gone: nearest in band
        List<String[]> gone = Arrays.<String[]>asList(FootballLineCheck.quote("TOTAL", "OVER", "2.5", "1.20"));
        assertEquals(-1, FootballLineCheck.pick(gone, "TOTAL", "OVER", "4.5", "4.5", "0.25"));
        assertNull(FootballLineCheck.freshTerms("TOTAL", "OVER", "4.5", "4.75", "1.90", "0.25", "1.77"));
        assertEquals("LINE_CHANGED", FootballLineCheck.freshTerms("SPREAD", "AWAY", "-2", "0.5", "1.90", "0.25", "1.86")[0]);
    }
}
