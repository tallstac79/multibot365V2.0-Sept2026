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
 * The alternative-line FALLBACK reader (FootballMarkets.alternative / parse with columns), on layouts measured on the real
 * phone (Al Markhiya v Al-Ahli Doha, Qatar Stars Cup, 29 Sep 2026; screenshots in evidence/football/alt-lines-20260929): the
 * Asian Lines tab shows the main "Asian Handicap" and "Goal Line" expanded and every alternative group collapsed; expanding
 * "Alternative Asian Handicap" / "Alternative Goal Line" lists the lines as consecutive rows in the same columns as the main
 * row, and a scrolled frame shows those rows without their header. Coordinates are those of the 720 px wide screenshots.
 */
public class FootballAlternativeLinesTest {
    private static final String HOME = "Al Markhiya", AWAY = "Al-Ahli Doha";

    /** A word of `text` whose left edge is `left` on the row centred at `cy`. */
    private static GameLinesParser.Word w(String text, int left, int cy) {
        return new GameLinesParser.Word(text, left, cy - 11, left + text.length() * 13, cy + 11);
    }

    private static void add(List<GameLinesParser.Word> out, int cy, Object... leftAndText) {
        for (int i = 0; i < leftAndText.length; i += 2) out.add(w((String) leftAndText[i + 1], (Integer) leftAndText[i], cy));
    }

    private static void teamsHeader(List<GameLinesParser.Word> f, int cy) { add(f, cy, 130, "Al", 153, "Markhiya", 468, "Al-Ahli", 545, "Doha"); }

    private static void handicapRow(List<GameLinesParser.Word> f, int cy, String homeLine, String homePrice, String awayLine, String awayPrice) {
        String[] h = homeLine.split(" "), a = awayLine.split(" ");
        int x = 190 - 52 * h.length;
        for (String t : h) { f.add(w(t, x, cy)); x += 52; }
        f.add(w(homePrice, 202, cy));
        x = 530 - 52 * a.length;
        for (String t : a) { f.add(w(t, x, cy)); x += 52; }
        f.add(w(awayPrice, 544, cy));
    }

    /** Asian Lines tab, the alternative Asian Handicap group just expanded (real screenshot e5). */
    private static List<GameLinesParser.Word> expandedFrame() {
        List<GameLinesParser.Word> f = new ArrayList<>();
        add(f, 423, 36, "Popular", 154, "Bet", 190, "Builder", 305, "Result", 409, "Corners", 503, "Asian", 550, "Lines");
        add(f, 535, 38, "Asian", 110, "Handicap");
        teamsHeader(f, 610);
        handicapRow(f, 682, "+1.0", "1.875", "-1.0", "1.925");
        add(f, 783, 38, "Goal", 90, "Line");
        add(f, 858, 294, "Over", 543, "Under");
        add(f, 929, 65, "2.5,", 110, "3.0", 288, "1.825", 543, "1.975");
        add(f, 1030, 38, "Alternative", 220, "Asian", 275, "Handicap");
        teamsHeader(f, 1105);
        handicapRow(f, 1176, "-0.5, -1.0", "6.250", "+0.5, +1.0", "1.120");
        handicapRow(f, 1261, "-0.5", "4.650", "+0.5", "1.180");
        handicapRow(f, 1345, "0.0, -0.5", "4.250", "0.0, +0.5", "1.210");
        return f;
    }

    private static List<GameLinesParser.Word> collapsedFrame() {
        List<GameLinesParser.Word> f = new ArrayList<>();
        add(f, 535, 38, "Asian", 110, "Handicap");
        teamsHeader(f, 610);
        handicapRow(f, 682, "+1.0", "1.875", "-1.0", "1.925");
        add(f, 783, 38, "Goal", 90, "Line");
        add(f, 858, 294, "Over", 543, "Under");
        add(f, 929, 65, "2.5,", 110, "3.0", 288, "1.825", 543, "1.975");
        add(f, 1030, 38, "Alternative", 220, "Asian", 275, "Handicap");
        add(f, 1137, 38, "Alternative", 220, "Goal", 275, "Line");
        add(f, 1244, 38, "1st", 90, "Half", 150, "Asian", 210, "Handicap");
        return f;
    }

    /** The scrolled frame (real screenshot e6): rows only, no header, the group's next heading not yet reached. */
    private static List<GameLinesParser.Word> scrolledFrame(boolean endsAtHeading) {
        List<GameLinesParser.Word> f = new ArrayList<>();
        add(f, 190, 18, "bet365");
        handicapRow(f, 280, "-0.5, -1.0", "6.250", "+0.5, +1.0", "1.120");
        handicapRow(f, 365, "-0.5", "4.650", "+0.5", "1.180");
        handicapRow(f, 449, "0.0, -0.5", "4.250", "0.0, +0.5", "1.210");
        handicapRow(f, 533, "0.0", "3.800", "0.0", "1.250");
        handicapRow(f, 618, "0.0, +0.5", "2.850", "0.0, -0.5", "1.400");
        if (endsAtHeading) {
            add(f, 760, 38, "Alternative", 220, "Goal", 275, "Line");
            handicapRow(f, 900, "+9.0", "1.010", "-9.0", "9.990");   // below the next heading: never read
        } else {
            handicapRow(f, 702, "+0.5", "2.350", "-0.5", "1.575");
        }
        add(f, 1480, 51, "Home", 190, "All", 250, "Sports");
        return f;
    }

    private static boolean has(FootballMarkets.Result r, String market, String side, String line, String price) {
        for (FootballMarkets.Cell c : r.cells) if (c.market.equals(market) && c.side.equals(side) && c.line.equals(line) && c.price.equals(price)) return true;
        return false;
    }

    // ------------------------------------------------------------------ finding and recognising the section
    @Test public void aCollapsedAlternativeSectionIsFoundWithItsHeadingToTap() {
        FootballMarkets.Alt a = FootballMarkets.alternative(collapsedFrame(), "SPREAD", HOME, AWAY);
        assertNotNull(a);
        assertFalse(a.expanded);
        assertEquals(1030, a.headingCy);
        assertTrue(a.headingBox[1] < 1030 && a.headingBox[3] > 1030 && a.headingBox[0] < 300 && a.headingBox[2] > 300);
        FootballMarkets.Alt g = FootballMarkets.alternative(collapsedFrame(), "TOTAL", HOME, AWAY);
        assertNotNull(g);
        assertEquals(1137, g.headingCy);
    }

    @Test public void anExpandedSectionGivesItsColumns() {
        FootballMarkets.Alt a = FootballMarkets.alternative(expandedFrame(), "SPREAD", HOME, AWAY);
        assertNotNull(a);
        assertTrue(a.expanded);
        assertTrue("home column left of the away column", a.columns.mid > 250 && a.columns.mid < 400);
        assertNull("the goal-line group's heading is not on this frame", FootballMarkets.alternative(expandedFrame(), "TOTAL", HOME, AWAY));
    }

    @Test public void firstHalfAndOtherAlternativeGroupsAreNeverTheSection() {
        List<GameLinesParser.Word> f = new ArrayList<>();
        add(f, 700, 38, "Alternative", 220, "1st", 265, "Half", 320, "Asian", 380, "Handicap");
        add(f, 800, 38, "Asian", 100, "Total", 160, "Corners");
        add(f, 900, 38, "Alternative", 220, "Corner", 300, "Line");
        assertNull(FootballMarkets.alternative(f, "SPREAD", HOME, AWAY));
        assertNull(FootballMarkets.alternative(f, "TOTAL", HOME, AWAY));
    }

    // ------------------------------------------------------------------ reading rows
    @Test public void theExpandedFrameYieldsTheMainRowAndTheAlternativeRows() {
        FootballMarkets.AltColumns cols = FootballMarkets.alternative(expandedFrame(), "SPREAD", HOME, AWAY).columns;
        FootballMarkets.Result r = FootballMarkets.parse(expandedFrame(), HOME, AWAY, cols);
        assertTrue(has(r, "SPREAD", "HOME", "+1.0", "1.875"));
        assertTrue(has(r, "SPREAD", "AWAY", "-1.0", "1.925"));
        assertTrue(has(r, "SPREAD", "HOME", "-0.75", "6.250"));
        assertTrue(has(r, "SPREAD", "AWAY", "+0.75", "1.120"));
        assertTrue(has(r, "SPREAD", "HOME", "-0.5", "4.650"));
        assertTrue(has(r, "SPREAD", "HOME", "-0.25", "4.250"));
        assertFalse("the goal line rows are not handicap rows", has(r, "SPREAD", "HOME", "2.75", "1.825"));
    }

    @Test public void aScrolledFrameIsReadWithTheSavedColumnsOnly() {
        FootballMarkets.AltColumns cols = FootballMarkets.alternative(expandedFrame(), "SPREAD", HOME, AWAY).columns;
        FootballMarkets.Result r = FootballMarkets.parse(scrolledFrame(false), HOME, AWAY, cols);
        assertTrue(has(r, "SPREAD", "HOME", "-0.75", "6.250"));
        assertTrue(has(r, "SPREAD", "AWAY", "+0.75", "1.120"));
        assertTrue(has(r, "SPREAD", "HOME", "0.0", "3.800"));
        assertTrue(has(r, "SPREAD", "HOME", "0.25", "2.850"));
        assertTrue(has(r, "SPREAD", "HOME", "+0.5", "2.350"));
        assertFalse(r.altEnd);
        assertEquals("a HOME price is left of the mid column", "HOME", r.cells.get(0).side);
    }

    @Test public void withoutTheSavedColumnsNothingIsReadFromAHeaderlessFrame() {
        assertTrue("every normal run: no alternative reading", FootballMarkets.parse(scrolledFrame(false), HOME, AWAY, null).cells.isEmpty());
        assertTrue(FootballMarkets.parse(scrolledFrame(false), HOME, AWAY).cells.isEmpty());
    }

    @Test public void theNextHeadingEndsTheListAndRowsBelowItAreNotRead() {
        FootballMarkets.AltColumns cols = FootballMarkets.alternative(expandedFrame(), "SPREAD", HOME, AWAY).columns;
        FootballMarkets.Result r = FootballMarkets.parse(scrolledFrame(true), HOME, AWAY, cols);
        assertTrue(r.altEnd);
        assertTrue(has(r, "SPREAD", "HOME", "0.25", "2.850"));
        assertFalse("below the next group's heading", has(r, "SPREAD", "HOME", "+9.0", "1.010"));
    }

    @Test public void theGoalLineAlternativeIsReadTheSameWay() {
        List<GameLinesParser.Word> header = new ArrayList<>();
        add(header, 1137, 38, "Alternative", 220, "Goal", 275, "Line");
        add(header, 1212, 294, "Over", 543, "Under");
        add(header, 1290, 65, "1.5,", 110, "2.0", 288, "1.400", 543, "2.700");
        FootballMarkets.Alt a = FootballMarkets.alternative(header, "TOTAL", HOME, AWAY);
        assertNotNull(a);
        assertTrue(a.expanded);
        assertTrue(a.columns.overX > 300 && a.columns.overX < 340 && a.columns.underX > 560 && a.columns.underX < 600);
        List<GameLinesParser.Word> scrolled = new ArrayList<>();
        add(scrolled, 300, 65, "2.0", 288, "1.520", 543, "2.400");
        add(scrolled, 385, 65, "2.0,", 110, "2.5", 288, "1.600", 543, "2.250");
        add(scrolled, 470, 65, "2.5", 288, "1.660", 543, "2.150");
        add(scrolled, 555, 65, "2.5,", 110, "3.0", 288, "1.825", 543, "1.975");
        FootballMarkets.Result r = FootballMarkets.parse(scrolled, HOME, AWAY, a.columns);
        assertTrue(has(r, "TOTAL", "OVER", "2.0", "1.520"));
        assertTrue(has(r, "TOTAL", "UNDER", "2.25", "2.250"));
        assertTrue(has(r, "TOTAL", "OVER", "2.75", "1.825"));
        assertTrue(has(r, "TOTAL", "UNDER", "2.5", "2.150"));
    }

    @Test public void twoFramesAreOneListOnlyWhenTheyShareARow() {
        FootballMarkets.AltColumns cols = FootballMarkets.alternative(expandedFrame(), "SPREAD", HOME, AWAY).columns;
        FootballMarkets.Result a = FootballMarkets.parse(expandedFrame(), HOME, AWAY, cols), b = FootballMarkets.parse(scrolledFrame(false), HOME, AWAY, cols);
        assertTrue(shareARow(a, b));
        List<GameLinesParser.Word> other = new ArrayList<>();
        handicapRow(other, 300, "-3.0", "9.000", "+3.0", "1.020");
        assertFalse(shareARow(a, FootballMarkets.parse(other, HOME, AWAY, cols)));
    }

    private static boolean shareARow(FootballMarkets.Result a, FootballMarkets.Result b) {
        for (FootballMarkets.Cell x : a.cells)
            for (FootballMarkets.Cell y : b.cells)
                if (x.market.equals(y.market) && x.side.equals(y.side) && x.line.equals(y.line) && x.price.equals(y.price)) return true;
        return false;
    }

    // ------------------------------------------------------------------ the selection rules stay the normal ones
    @Test public void theExactLineIsPickedBeforeANeighbourAndNothingFurtherAwayIsEver() {
        FootballMarkets.AltColumns cols = FootballMarkets.alternative(expandedFrame(), "SPREAD", HOME, AWAY).columns;
        FootballMarkets.Result r = FootballMarkets.parse(scrolledFrame(false), HOME, AWAY, cols);
        List<String[]> quotes = new ArrayList<>();
        for (FootballMarkets.Cell c : r.cells) quotes.add(FootballLineCheck.quote(c.market, c.side, c.line, c.price));
        int exact = FootballLineCheck.nearest(quotes, "SPREAD", "HOME", "0.0", "0.25");
        assertEquals("0.0", quotes.get(exact)[2]);
        int band = FootballLineCheck.nearest(quotes, "SPREAD", "HOME", "-0.25", "0.25");
        assertEquals("-0.25", quotes.get(band)[2]);
        // requested +1.0: the list read here ends at +0.5 (0.5 away): outside the +/-0.25 allowance, never substituted
        assertEquals(-1, FootballLineCheck.nearest(quotes, "SPREAD", "HOME", "+1.0", "0.25"));
    }
}
