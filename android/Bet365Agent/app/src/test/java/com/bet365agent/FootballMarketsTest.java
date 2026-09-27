package com.bet365agent;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import org.junit.Test;

/** Football market parsing on the real OCR of Bet365 football event pages captured 27 Sep 2026 (evidence/football). */
public class FootballMarketsTest {
    private static GameLinesParser.Word w(String t, int l, int top, int r, int b) { return new GameLinesParser.Word(t, l, top, r, b); }

    private static List<String> cells(FootballMarkets.Result r) {
        List<String> out = new ArrayList<>();
        for (FootballMarkets.Cell c : r.cells) out.add(c.market + "/" + c.side + "/" + c.line + "@" + c.price);
        return out;
    }

    @Test public void popularTabFarulConstanta() throws Exception {
        // fb-farul-spread-w-102822/s002_markets.txt: Full Time Result 1.36 | 5.25 | 5.75, Goals Over/Under 2.5 1.36 | 3.00
        List<GameLinesParser.Word> words = StakePadTest.load("football_popular_farul_20260927.txt");
        FootballMarkets.Result r = FootballMarkets.parse(words, "Farul Constanta (W)", "FK Csikszereda Miercurea Ciuc (W)");
        assertTrue(r.notes.toString(), r.fullTimeResult && r.goalsOverUnder);
        assertEquals(List.of("MONEYLINE/HOME/NONE@1.36", "MONEYLINE/DRAW/NONE@5.25", "MONEYLINE/AWAY/NONE@5.75", "TOTAL/OVER/2.5@1.36", "TOTAL/UNDER/2.5@3.00"), cells(r));
        assertEquals("Farul Constanta (W)", r.cells.get(0).name);
        assertEquals("Draw", r.cells.get(1).name);
        assertEquals("Over", r.cells.get(3).name);
        // tap targets are the price boxes, left to right
        assertTrue(r.cells.get(0).bounds[2] < r.cells.get(1).bounds[0] && r.cells.get(1).bounds[2] < r.cells.get(2).bounds[0]);
        // the market tabs: Asian Lines and Goals are on the strip, Popular first
        assertTrue(FootballMarkets.tab(words, "asia").text.startsWith("Asia"));   // strip cut mid-label ("Asiat") in this capture
        assertEquals("Goals", FootballMarkets.tab(words, "goals").text);
        assertEquals(409, FootballMarkets.tab(words, "goals").left);
    }

    @Test public void popularTabSalzburgAndJaps() throws Exception {
        FootballMarkets.Result s = FootballMarkets.parse(StakePadTest.load("football_popular_salzburg_20260927.txt"), "ATSV Salzburg", "Union Henndorf");
        assertEquals(List.of("MONEYLINE/HOME/NONE@3.30", "MONEYLINE/DRAW/NONE@4.75", "MONEYLINE/AWAY/NONE@1.66", "TOTAL/OVER/2.5@1.28", "TOTAL/UNDER/2.5@3.50"), cells(s));
        FootballMarkets.Result j = FootballMarkets.parse(StakePadTest.load("football_popular_japs_20260927.txt"), "JaPS U21", "PPJ U21");
        assertEquals(List.of("MONEYLINE/HOME/NONE@1.80", "MONEYLINE/DRAW/NONE@4.50", "MONEYLINE/AWAY/NONE@3.00", "TOTAL/OVER/2.5@1.16", "TOTAL/UNDER/2.5@4.50"), cells(j));
        FootballMarkets.Result v = FootballMarkets.parse(StakePadTest.load("football_popular_vihiga_20260927.txt"), "Vihiga Queens FC (W)", "Ulinzi Starlets (W)");
        assertEquals(List.of("MONEYLINE/HOME/NONE@3.50", "MONEYLINE/DRAW/NONE@3.40", "MONEYLINE/AWAY/NONE@1.85", "TOTAL/OVER/2.5@2.00", "TOTAL/UNDER/2.5@1.80"), cells(v));
        assertEquals("Asiat", FootballMarkets.tab(StakePadTest.load("football_popular_vihiga_20260927.txt"), "asia").text);   // truncated tab label
    }

    @Test public void fullTimeResultColumnsMustBeLabelled() throws Exception {
        // wrong team names for the page: the columns are not verified and no 1X2 cell is produced (fail closed)
        FootballMarkets.Result r = FootballMarkets.parse(StakePadTest.load("football_popular_farul_20260927.txt"), "Rytas", "Boca Juniors");
        assertTrue(r.notes.toString(), r.notes.get(0).startsWith("full time result: columns not verified"));
        assertEquals(List.of("TOTAL/OVER/2.5@1.36", "TOTAL/UNDER/2.5@3.00"), cells(r));
    }

    /** Asian Lines tab geometry from the screenshot evidence/football/pages/pg-vihiga-103021/p02_asian_lines.png (full resolution). */
    private static List<GameLinesParser.Word> asianLinesVihiga() {
        List<GameLinesParser.Word> words = new ArrayList<>();
        Collections.addAll(words,
                w("Popular", 35, 405, 112, 435), w("Bet", 155, 405, 186, 435), w("Builder", 194, 405, 262, 435), w("Result", 307, 405, 367, 435),
                w("Goals", 409, 405, 464, 435), w("Half", 507, 405, 545, 435), w("Asian", 587, 405, 641, 435),
                w("Asian", 40, 522, 100, 550), w("Handicap", 108, 522, 220, 550),
                w("Vihiga", 84, 596, 150, 620), w("Queens", 158, 596, 232, 620), w("FC", 240, 596, 262, 620), w("(W)", 270, 596, 300, 620),
                w("Ulinzi", 446, 596, 508, 620), w("Starlets", 516, 596, 596, 620), w("(W)", 604, 596, 634, 620),
                w("+0.5", 148, 668, 188, 692), w("1.850", 196, 668, 262, 692), w("-0.5", 506, 668, 546, 692), w("1.950", 554, 668, 620, 692),
                w("Goal", 40, 770, 88, 796), w("Line", 96, 770, 140, 796),
                w("Over", 300, 846, 340, 870), w("Under", 540, 846, 600, 870),
                w("2.5", 88, 916, 120, 940), w("2.025", 284, 916, 346, 940), w("1.775", 544, 916, 602, 940),
                w("1st", 40, 1020, 66, 1044), w("Half", 74, 1020, 118, 1044), w("Asian", 126, 1020, 180, 1044), w("Handicap", 188, 1020, 300, 1044));
        return words;
    }

    @Test public void asianLinesTabHandicapAndGoalLine() {
        FootballMarkets.Result r = FootballMarkets.parse(asianLinesVihiga(), "Vihiga Queens FC (W)", "Ulinzi Starlets (W)");
        assertTrue(r.notes.toString(), r.asianHandicap && r.goalLine && !r.fullTimeResult);
        assertEquals(List.of("SPREAD/HOME/+0.5@1.850", "SPREAD/AWAY/-0.5@1.950", "TOTAL/OVER/2.5@2.025", "TOTAL/UNDER/2.5@1.775"), cells(r));
        assertEquals("Vihiga Queens FC (W)", r.cells.get(0).name);
        assertEquals("Ulinzi Starlets (W)", r.cells.get(1).name);
        // the 1st Half sections are never parsed
        assertEquals(4, r.cells.size());
        // team header reversed on the page: refused
        FootballMarkets.Result rev = FootballMarkets.parse(asianLinesVihiga(), "Ulinzi Starlets (W)", "Vihiga Queens FC (W)");
        assertTrue(rev.notes.toString(), rev.cells.stream().noneMatch(c -> c.market.equals("SPREAD")));
    }

    @Test public void quarterLinesAndSigns() {
        assertEquals("2.75", FootballMarkets.normaliseLine("2.5,3.0"));
        assertEquals("-0.25", FootballMarkets.normaliseLine("0.0,-0.5"));
        assertEquals("+0.25", FootballMarkets.normaliseLine("+0.0,+0.5"));
        assertEquals("0.0", FootballMarkets.normaliseLine("0"));
        assertEquals("-1.0", FootballMarkets.normaliseLine("-1"));
        assertEquals("+0.5", FootballMarkets.normaliseLine("+0.5"));
        assertEquals("2.5", FootballMarkets.normaliseLine("2,5"));
        assertNull(FootballMarkets.normaliseLine("2.5,3.5"));       // not a quarter pair
        assertNull(FootballMarkets.normaliseLine("1.850"));
        // a quarter goal line row on the Goal Line grid
        List<GameLinesParser.Word> words = new ArrayList<>(asianLinesVihiga());
        words.add(w("2.5,", 84, 986, 118, 1010)); words.add(w("3.0", 122, 986, 150, 1010)); words.add(w("1.900", 284, 986, 346, 1010)); words.add(w("1.900", 544, 986, 602, 1010));
        FootballMarkets.Result r = FootballMarkets.parse(words, "Vihiga Queens FC (W)", "Ulinzi Starlets (W)");
        assertTrue(cells(r).toString(), cells(r).contains("TOTAL/OVER/2.75@1.900") && cells(r).contains("TOTAL/UNDER/2.75@1.900"));
    }

    @Test public void accentedColumnLabelsMatchTransliteratedFixtureNames() {
        // Real page 27 Sep 2026 10:32Z (FC Arlanda v Enköping): labels row "FC Arlanda | Draw | Enköping", prices 1.65 3.90 4.10
        List<GameLinesParser.Word> words = new ArrayList<>();
        Collections.addAll(words, w("Popular", 35, 396, 112, 426), w("Bet", 155, 414, 186, 444), w("Builder", 194, 414, 262, 444), w("Result", 307, 414, 367, 444),
                w("Full", 39, 522, 81, 550), w("Time", 90, 522, 153, 550), w("Result", 163, 522, 241, 550),
                w("FC", 60, 594, 86, 616), w("Arlanda", 94, 594, 180, 616), w("Draw", 335, 594, 387, 616), w("Enköping", 540, 594, 640, 616),
                w("1.65", 111, 630, 155, 652), w("3.90", 339, 630, 382, 652), w("4.10", 566, 630, 611, 652), w("Double", 39, 702, 125, 728), w("Chance", 134, 702, 227, 728));
        FootballMarkets.Result r = FootballMarkets.parse(words, "FC Arlanda", "Enkoping");
        assertEquals(List.of("MONEYLINE/HOME/NONE@1.65", "MONEYLINE/DRAW/NONE@3.90", "MONEYLINE/AWAY/NONE@4.10"), cells(r));
        assertEquals("enkoping", FootballMarkets.ascii("Enköping"));
        assertEquals("brondby if", FootballMarkets.ascii("Brøndby IF"));
    }

    @Test public void tabStripSurvivesAHorizontalScroll() {
        // after the strip is swiped left, "Popular" is off-screen; the strip is still recognised by its other labels
        List<GameLinesParser.Word> words = new ArrayList<>();
        Collections.addAll(words, w("Half", 30, 405, 68, 435), w("Asian", 110, 405, 164, 435), w("Lines", 172, 405, 220, 435), w("Corners", 260, 405, 340, 435),
                w("Cards", 380, 405, 436, 435), w("Full", 39, 522, 81, 550), w("Time", 90, 522, 153, 550), w("Result", 163, 522, 241, 550));
        assertNotNull(FootballMarkets.tabStrip(words, true));
        assertEquals(420, FootballMarkets.tabStrip(words, true)[0]);
        assertTrue(FootballMarkets.tab(words, "asia").text.startsWith("Asia"));   // strip cut mid-label ("Asiat") in this capture
        assertNull(FootballMarkets.tab(words, "goals"));
    }

    @Test public void initialPlusClubAffixAbbreviation() {
        // Live 27 Sep 2026 10:40Z: feed "Eskilsminne v AFC Malmo", Bet365 "Eskilsminne IF v Ariana FC Malmo"
        EventIdentity.Side s = EventIdentity.matchSide("AFC Malmo", "Ariana FC Malmo", Collections.emptyMap());
        assertEquals(s.note, EventIdentity.Level.VARIANT, s.level);
        assertEquals("abbreviation", s.kind);
        EventIdentity.Result r = EventIdentity.resolveVerified(new EventIdentity.Event("football", "Eskilsminne", "AFC Malmo", "27 Sep 12:00", "Division 1 Sodra", false),
                new EventIdentity.Event("football", "Eskilsminne IF", "Ariana FC Malmo", "27 Sep 12:00", "Sweden 1.div Sodra 27 Sep 12:00", true), Collections.emptyMap(), false, "Sweden");
        assertEquals(r.reason, EventIdentity.Verdict.HIGH_CONFIDENCE_EVENT_MATCH, r.verdict);
        // the initial must belong to the other name's own token, and the affix must be there
        // without the matching initial or affix it is no abbreviation; a shared "Malmo" core with a word on each side is only
        // event-scoped evidence (shared_core, identity v2), never an alias, and needs a sure opponent under the alert's link
        for (String other : new String[] {"Bogus FC Malmo", "Ariana Malmo"}) {
            EventIdentity.Side x = EventIdentity.matchSide("AFC Malmo", other, Collections.emptyMap());
            assertEquals(other, "shared_core", x.kind);
            assertTrue(!x.aliasSafe && x.score < EventIdentity.DETERMINISTIC);
        }
        assertEquals(EventIdentity.Level.NONE, EventIdentity.matchSide("AFC Malmo", "Ariana FC Lund", Collections.emptyMap()).level);
    }

    @Test public void competitionAgeMarkerIsSuppliedLikeTheWomensMarker() {
        // JaPS U21 v PPJ U21 (Finland U21 League, 27 Sep 2026): the feed names carry no U21, Bet365 appends the competition's own marker
        assertEquals("[u21]", EventIdentity.competitionMarkers("U21 League").toString());
        assertEquals("[]", EventIdentity.competitionMarkers("Premier League Women").toString());
        EventIdentity.Side side = EventIdentity.matchSide("JaPS", "JaPS U21", Collections.emptyMap(), false, EventIdentity.competitionMarkers("U21 League"));
        assertEquals(EventIdentity.Level.VARIANT, side.level);
        assertTrue(side.markerFromCompetition);
        EventIdentity.Result r = EventIdentity.resolveVerified(new EventIdentity.Event("football", "JaPS", "PPJ", "27 Sep 11:00", "U21 League", false),
                new EventIdentity.Event("football", "JaPS U21", "PPJ U21", "27 Sep 11:00", "Finland U21 League• 27 Sep 11:00", true), Collections.emptyMap(), false, "Finland");
        assertEquals(r.reason, EventIdentity.Verdict.HIGH_CONFIDENCE_EVENT_MATCH, r.verdict);
        // a different age group, or a marker the competition does not carry, is still a protected conflict
        assertEquals(EventIdentity.Level.NONE, EventIdentity.matchSide("JaPS", "JaPS U19", Collections.emptyMap(), false, EventIdentity.competitionMarkers("U21 League")).level);
        assertEquals(EventIdentity.Level.NONE, EventIdentity.matchSide("JaPS", "JaPS U21", Collections.emptyMap(), false, EventIdentity.competitionMarkers("Veikkausliiga")).level);
        assertEquals(EventIdentity.Level.NONE, EventIdentity.matchSide("JaPS", "JaPS (W)", Collections.emptyMap(), false, EventIdentity.competitionMarkers("U21 League")).level);
    }
}
