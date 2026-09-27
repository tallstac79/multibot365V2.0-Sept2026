package com.bet365agent;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import java.util.List;
import org.junit.Test;

/**
 * PLACE_HELD pre-tap on REAL football slips (27 Sep 2026): Villan Pojat v HauPa 1X2 (HauPa 2.50) and Asian Handicap
 * (HauPa 0.0,+0.5 @ 1.850), EGS Gafsa v AS Kasserine Goal Line (Over 2.0,2.5 @ 1.900, with the page's own "Goal Line"
 * heading just above the slip). Before 0.9.32 every football pre-tap failed closed: basketball-only slip labels, no split
 * lines, two-decimal prices only, and 1X2 vs the held MONEYLINE was "Held market changed".
 */
public class FootballPretapTest {
    private static int placeTop(List<GameLinesParser.Word> lines) {
        int top = -1;
        for (GameLinesParser.Word l : lines) if (l.text.contains("Place Bet")) top = l.top;
        return top;
    }

    private static List<GameLinesParser.Word> slip(String name) throws Exception {
        return EventHeader.lineWords(StakePadTest.load(name));
    }

    @Test public void fullTimeResultSlip() throws Exception {
        List<GameLinesParser.Word> lines = slip("footslip_1x2_villan_20260927.txt");
        int top = placeTop(lines);
        assertTrue(HeldSlipIdentity.matches(lines, "Villan Pojat", "HauPa", "MONEYLINE", top, "football"));
        HeldSlipQuote q = HeldSlipQuote.read(lines, "HauPa", "MONEYLINE", top, "football");
        assertNotNull(q);
        assertEquals("", q.line);
        assertEquals("2.50", q.price);
        assertFalse(HeldSlipIdentity.matches(lines, "Villan Pojat", "HauPa", "MONEYLINE", top, "basketball"));   // no "Money Line" label
        assertFalse(HeldSlipIdentity.matches(lines, "Villan Pojat", "HJK", "MONEYLINE", top, "football"));        // another away team
    }

    @Test public void asianHandicapSplitLine() throws Exception {
        List<GameLinesParser.Word> lines = slip("footslip_ah_villan_20260927.txt");
        int top = placeTop(lines);
        assertTrue(HeldSlipIdentity.matches(lines, "Villan Pojat", "HauPa", "SPREAD", top, "football"));
        HeldSlipQuote q = HeldSlipQuote.read(lines, "HauPa", "SPREAD", top, "football");
        assertNotNull(q);
        assertEquals("0.25", q.line);
        assertEquals("1.850", q.price);
        // alert AWAY +0.5, live +0.25: 0.25-goal deterioration inside the approved cap; +0.75 would be 0.5 (refused)
        assertTrue(ExecutionTolerance.line("SPREAD", "AWAY", "0.5", q.line, "0.25"));
        assertFalse(ExecutionTolerance.line("SPREAD", "AWAY", "0.75", q.line, "0.25"));
    }

    @Test public void goalLineWithPageHeadingAboveTheSlip() throws Exception {
        List<GameLinesParser.Word> lines = slip("footslip_totals_gafsa_20260927.txt");
        int top = placeTop(lines);
        assertTrue(HeldSlipIdentity.matches(lines, "EGS Gafsa", "AS Kasserine", "TOTALS", top, "football"));
        HeldSlipQuote q = HeldSlipQuote.read(lines, "Over", "TOTALS", top, "football");
        assertNotNull(q);
        assertEquals("2.25", q.line);
        assertEquals("1.900", q.price);
        assertTrue(ExecutionTolerance.line("TOTALS", "OVER", "2", q.line, "0.25"));
        assertFalse(ExecutionTolerance.line("TOTALS", "OVER", "1.75", q.line, "0.25"));
    }

    @Test public void basketballSlipUnchanged() throws Exception {
        List<GameLinesParser.Word> lines = slip("placebet_pantery_pretap_20260927.txt");
        int top = placeTop(lines);
        assertTrue(HeldSlipIdentity.matches(lines, "Pantery Lancut (W)", "MUKS Poznan (W)", "SPREAD", top));
        HeldSlipQuote q = HeldSlipQuote.read(lines, "Pantery Lancut (W)", "SPREAD", top);
        assertNotNull(q);
        assertEquals("-8.5", q.line);
        assertEquals("1.83", q.price);
    }

    @Test public void quarterAndMarketNames() {
        assertEquals("0.25", HeldSlipQuote.quarter("0.0,+0.5"));
        assertEquals("-0.25", HeldSlipQuote.quarter("0.0,-0.5"));
        assertEquals("-1.75", HeldSlipQuote.quarter("-1.5, -2.0"));
        assertEquals("2.75", HeldSlipQuote.quarter("2.5,3.0"));
        assertNull(HeldSlipQuote.quarter("2.0,3.0"));
        assertEquals("MONEYLINE", HeldInstruction.wireMarket("1X2"));
        assertEquals("MONEYLINE", HeldInstruction.wireMarket("MONEYLINE"));
        assertEquals("TOTAL", HeldInstruction.wireMarket("TOTALS"));
        assertEquals("SPREAD", HeldInstruction.wireMarket("SPREAD"));
    }
}
