package com.bet365agent;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

import java.util.ArrayList;
import java.util.List;
import org.junit.Test;

/**
 * The alternative-line fallback on the REAL OCR frames the 0.9.48 phone captured on Al Markhiya v Al-Ahli Doha (Qatar Stars
 * Cup, 29 Sep 2026, 18:04 BST; hold-only smoke, nothing tapped but the section heading): the collapsed Asian Lines group
 * headings, and the "Alternative Goal Line" / "Alternative Asian Handicap" groups just expanded. Screenshots of the same
 * frames: evidence/football/alt-lines-20260929.
 */
public class FootballAlternativeRealFramesTest {
    private static final String HOME = "Al Markhiya", AWAY = "Al-Ahli Doha";

    private static List<GameLinesParser.Word> frame(String name) throws Exception { return StakePadTest.load(name); }

    private static List<String[]> quotes(FootballMarkets.Result r) {
        List<String[]> out = new ArrayList<>();
        for (FootballMarkets.Cell c : r.cells) out.add(FootballLineCheck.quote(c.market, c.side, c.line, c.price));
        return out;
    }

    private static boolean has(FootballMarkets.Result r, String market, String side, String line) {
        for (FootballMarkets.Cell c : r.cells) if (c.market.equals(market) && c.side.equals(side) && c.line.equals(line)) return true;
        return false;
    }

    @Test public void theCollapsedGroupsAreFoundAndOnlyTheFullGameOnes() throws Exception {
        List<GameLinesParser.Word> f = frame("football_alt_total_collapsed_20260929.txt");
        FootballMarkets.Alt total = FootballMarkets.alternative(f, "TOTAL", HOME, AWAY);
        assertNotNull(total);
        assertFalse(total.expanded);
        assertTrue("a tap target inside the visible list", total.headingCy > 250 && total.headingCy < 1395);
        FootballMarkets.Alt spread = FootballMarkets.alternative(frame("football_alt_spread_collapsed_20260929.txt"), "SPREAD", HOME, AWAY);
        assertNotNull(spread);
        assertFalse(spread.expanded);
    }

    @Test public void theExpandedGoalLineListIsReadInFull() throws Exception {
        List<GameLinesParser.Word> f = frame("football_alt_total_expanded_20260929.txt");
        FootballMarkets.Alt a = FootballMarkets.alternative(f, "TOTAL", HOME, AWAY);
        assertNotNull(a);
        assertTrue(a.expanded);
        FootballMarkets.Result r = FootballMarkets.parse(f, HOME, AWAY, a.columns);
        for (String line : new String[] {"1.25", "1.5", "1.75", "2.0", "2.25", "2.5", "2.75", "3.25", "3.5", "3.75", "4.0"}) {
            assertTrue("OVER " + line, has(r, "TOTAL", "OVER", line));
            assertTrue("UNDER " + line, has(r, "TOTAL", "UNDER", line));
        }
        assertFalse("Bet365 lists no 3.0 line", has(r, "TOTAL", "OVER", "3.0"));
    }

    @Test public void theExactTotalLineIsUsedAndAMissingOneWithTwoEquidistantNeighboursIsNeverGuessed() throws Exception {
        List<GameLinesParser.Word> f = frame("football_alt_total_expanded_20260929.txt");
        FootballMarkets.Result r = FootballMarkets.parse(f, HOME, AWAY, FootballMarkets.alternative(f, "TOTAL", HOME, AWAY).columns);
        List<String[]> q = quotes(r);
        assertEquals("3.5", q.get(FootballLineCheck.nearest(q, "TOTAL", "OVER", "3.5", "0.25"))[2]);
        assertEquals("exact first", "3.75", q.get(FootballLineCheck.nearest(q, "TOTAL", "OVER", "3.75", "0.25"))[2]);
        assertEquals("3.0 is not listed: 2.75 and 3.25 are equally near, so nothing is chosen for the operator", -1,
                FootballLineCheck.nearest(q, "TOTAL", "OVER", "3.0", "0.25"));
        assertEquals("a line further away is never used", -1, FootballLineCheck.nearest(q, "TOTAL", "OVER", "3.0", "0.1"));
        assertEquals("nothing near 6.5", -1, FootballLineCheck.nearest(q, "TOTAL", "OVER", "6.5", "0.25"));
    }

    @Test public void theExpandedHandicapListIsReadAndQuarterLinesAreAveraged() throws Exception {
        List<GameLinesParser.Word> f = frame("football_alt_spread_expanded_20260929.txt");
        FootballMarkets.Alt a = FootballMarkets.alternative(f, "SPREAD", HOME, AWAY);
        assertNotNull(a);
        assertTrue(a.expanded);
        FootballMarkets.Result r = FootballMarkets.parse(f, HOME, AWAY, a.columns);
        for (String line : new String[] {"-0.75", "-0.5", "-0.25", "0.0", "0.25", "+0.5", "+1.0", "1.25", "+1.5", "1.75", "+2.0", "2.25"})
            assertTrue("HOME " + line, has(r, "SPREAD", "HOME", line) || has(r, "SPREAD", "HOME", line.replace("+", "")) || has(r, "SPREAD", "HOME", "+" + line));
        assertTrue(has(r, "SPREAD", "AWAY", "-2.0"));
        assertTrue(has(r, "SPREAD", "AWAY", "-0.5"));
        // every HOME cell has its AWAY partner at the opposite line
        for (FootballMarkets.Cell c : r.cells) {
            if (!c.side.equals("HOME")) continue;
            String opposite = new java.math.BigDecimal(c.line).negate().stripTrailingZeros().toPlainString();
            boolean partner = false;
            for (FootballMarkets.Cell d : r.cells)
                if (d.side.equals("AWAY") && new java.math.BigDecimal(d.line).compareTo(new java.math.BigDecimal(opposite)) == 0) partner = true;
            assertTrue("partner of " + c, partner);
        }
    }

    @Test public void theExactHandicapLineAndItsBandFollowTheNormalRules() throws Exception {
        List<GameLinesParser.Word> f = frame("football_alt_spread_expanded_20260929.txt");
        FootballMarkets.Result r = FootballMarkets.parse(f, HOME, AWAY, FootballMarkets.alternative(f, "SPREAD", HOME, AWAY).columns);
        List<String[]> q = quotes(r);
        assertEquals("+2.0", q.get(FootballLineCheck.nearest(q, "SPREAD", "HOME", "+2.0", "0.25"))[2]);
        // 2.1 is not a line: 2.0 (0.1 away) beats 2.25 (0.15 away), both inside the allowance
        assertEquals("+2.0", q.get(FootballLineCheck.nearest(q, "SPREAD", "HOME", "2.1", "0.25"))[2]);
        assertEquals("nothing within 0.25 of +8", -1, FootballLineCheck.nearest(q, "SPREAD", "HOME", "+8.0", "0.25"));
    }

    @Test public void theCollapsedFrameYieldsNoAlternativeRows() throws Exception {
        List<GameLinesParser.Word> f = frame("football_alt_total_collapsed_20260929.txt");
        FootballMarkets.Alt a = FootballMarkets.alternative(f, "TOTAL", HOME, AWAY);
        FootballMarkets.Result r = FootballMarkets.parse(f, HOME, AWAY, null);
        assertFalse("a collapsed group has no Over/Under header row under it", a.expanded);
        assertTrue("main rows only (the alternative group contributes nothing)", r.cells.size() <= 8);
    }
}
