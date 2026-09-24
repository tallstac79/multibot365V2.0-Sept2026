package com.bet365agent;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.junit.Test;

/** Real OCR words of the Hapoel Tel Aviv v Bayern Munich event page (READY proof run, 2026-09-24). */
public class GameLinesParserTest {
    private static final Pattern WORD = Pattern.compile("^(.*) \\[(\\d+),(\\d+)\\]\\[(\\d+),(\\d+)\\]$");

    private static List<GameLinesParser.Word> real() throws Exception { return load("gamelines_hapoel_bayern_20260924.txt"); }

    private static List<GameLinesParser.Word> load(String name) throws Exception {
        List<GameLinesParser.Word> out = new ArrayList<>();
        try (BufferedReader in = new BufferedReader(new InputStreamReader(
                GameLinesParserTest.class.getResourceAsStream("/" + name), StandardCharsets.UTF_8))) {
            for (String line; (line = in.readLine()) != null; ) {
                Matcher m = WORD.matcher(line);
                if (m.matches()) out.add(new GameLinesParser.Word(m.group(1), Integer.parseInt(m.group(2)), Integer.parseInt(m.group(3)),
                        Integer.parseInt(m.group(4)), Integer.parseInt(m.group(5))));
            }
        }
        return out;
    }

    private static String cells(GameLinesParser.Result r) {
        List<String> s = new ArrayList<>();
        for (GameLinesParser.Cell c : r.cells) s.add(c.toString());
        return String.join(" ", s);
    }

    @Test public void realGridReadsEveryCellDespiteOcrNoise() throws Exception {
        GameLinesParser.Result r = GameLinesParser.parse(real(), "Hapoel Tel Aviv", "Bayern Munich");
        assertTrue(r.notes.toString(), r.grid);
        // "8.0" (sign lost) takes the minus from the away row's "+8.0"; "0 173.5" is Over; "1." ".23" is 1.23.
        assertEquals("SPREAD/HOME/-8.0@1.83 SPREAD/AWAY/+8.0@1.83 TOTAL/OVER/173.5@1.83 TOTAL/UNDER/173.5@1.83 "
                + "MONEYLINE/HOME/NONE@1.23 MONEYLINE/AWAY/NONE@3.75", cells(r));
        GameLinesParser.Cell awaySpread = r.cells.get(1);
        assertEquals("Bayern Munich", awaySpread.name);
        // Tap target is the away spread cell (line + price), inside the Spread column.
        assertTrue(awaySpread.bounds[0] >= 290 && awaySpread.bounds[2] <= 360 && awaySpread.bounds[1] >= 870 && awaySpread.bounds[3] <= 940);
    }

    @Test public void sameGridWithDotsLostAsGaps() throws Exception {
        // Another frame of the same page: "8 0", "1 83", "1" ".83", "173 5", "3" "75".
        GameLinesParser.Result r = GameLinesParser.parse(load("gamelines_totals_fail_20260924.txt"), "Hapoel Tel Aviv", "Bayern Munich");
        assertEquals(r.notes.toString(), "SPREAD/HOME/-8.0@1.83 SPREAD/AWAY/+8.0@1.83 TOTAL/OVER/173.5@1.83 TOTAL/UNDER/173.5@1.83 "
                + "MONEYLINE/HOME/NONE@1.23 MONEYLINE/AWAY/NONE@3.75", cells(r));
    }

    @Test public void undottedNumbersAreNeverGuessed() {
        assertEquals(null, GameLinesParser.price("375"));
        assertEquals("3.75", GameLinesParser.price("3 75"));
        assertEquals("1.23", GameLinesParser.price("1. .23"));
    }

    @Test public void consensusOutvotesAMisreadDigitAndDropsTies() throws Exception {
        List<GameLinesParser.Cell> good = GameLinesParser.parse(real(), "Hapoel Tel Aviv", "Bayern Munich").cells;
        List<GameLinesParser.Cell> misread = new ArrayList<>();
        for (GameLinesParser.Cell c : good) misread.add(c.market.equals("TOTAL") && c.side.equals("UNDER")
                ? new GameLinesParser.Cell(c.market, c.side, c.line, "1.82", c.name, c.bounds) : c);
        // Garbled frame (real): team label unread -> no cells at all.
        List<GameLinesParser.Cell> garbled = GameLinesParser.parse(load("gamelines_totals_fail2_20260924.txt"), "Hapoel Tel Aviv", "Bayern Munich").cells;
        assertTrue(garbled.isEmpty());
        List<List<GameLinesParser.Cell>> reads = new ArrayList<>();
        reads.add(good); reads.add(misread); reads.add(garbled); reads.add(good);
        String agreed = cellsOf(GameLinesParser.consensus(reads));
        assertTrue(agreed, agreed.contains("TOTAL/UNDER/173.5@1.83"));
        // One good + one misread only: a tie is not agreement, so that cell is left out.
        List<List<GameLinesParser.Cell>> tie = new ArrayList<>();
        tie.add(good); tie.add(misread);
        String tied = cellsOf(GameLinesParser.consensus(tie));
        assertTrue(tied, !tied.contains("TOTAL/UNDER") && tied.contains("TOTAL/OVER/173.5@1.83"));
    }

    private static String cellsOf(List<GameLinesParser.Cell> cells) {
        List<String> s = new ArrayList<>();
        for (GameLinesParser.Cell c : cells) s.add(c.toString());
        return String.join(" ", s);
    }

    @Test public void secondFixtureWithFragmentedLabelsAndMisreadMinus() throws Exception {
        // Crvena Zvezda v Zalgiris: labels OCR'd in pieces; "-2.5" read as "12.5" opposite "+2.5".
        GameLinesParser.Result r = GameLinesParser.parse(load("gamelines_zvezda_zalgiris_20260924.txt"), "Crvena Zvezda", "Zalgiris");
        assertTrue(r.notes.toString(), r.grid);
        String got = cells(r);
        assertTrue(got, got.contains("SPREAD/HOME/-2.5@1.86") && got.contains("SPREAD/AWAY/+2.5@1.79"));
        assertTrue(got, got.contains("TOTAL/OVER/168.5@1.83") && got.contains("TOTAL/UNDER/168.5@1.83"));
        assertTrue(got, got.contains("MONEYLINE/HOME/NONE@1.68") && got.contains("MONEYLINE/AWAY/NONE@2.05"));
    }

    @Test public void fuzzyLabelsNeedTheTeamsLettersInOrder() {
        assertTrue(GameLinesParser.fuzzyTeam("Cr )rvena Z» ZveZ( zdz la", "Crvena Zvezda"));
        assertTrue(GameLinesParser.fuzzyTeam("Zalg )iris", "Zalgiris"));
        assertTrue(!GameLinesParser.fuzzyTeam("Zalg )iris", "Crvena Zvezda"));
        assertTrue(!GameLinesParser.fuzzyTeam("Jordan Nwora", "Crvena Zvezda"));
        assertEquals("-2.5", GameLinesParser.repairMinus("12.5", "+2.5"));
        assertEquals("12.5", GameLinesParser.repairMinus("12.5", "+12.0"));
        assertEquals("12.5", GameLinesParser.repairMinus("12.5", "-2.5"));
    }

    @Test public void wrongTeamsFindNoGrid() throws Exception {
        GameLinesParser.Result r = GameLinesParser.parse(real(), "Real Madrid", "Bayern Munich");
        assertTrue(r.cells.isEmpty());
    }

    @Test public void spreadWithNoReadableSignIsLeftOut() throws Exception {
        List<GameLinesParser.Word> words = new ArrayList<>();
        for (GameLinesParser.Word w : real()) words.add(w.text.equals("+8.0")
                ? new GameLinesParser.Word("8.0", w.left, w.top, w.right, w.bottom) : w);
        GameLinesParser.Result r = GameLinesParser.parse(words, "Hapoel Tel Aviv", "Bayern Munich");
        assertTrue(!cells(r).contains("SPREAD"));
        assertTrue(r.notes.toString().contains("spread signs unreadable"));
        assertTrue(cells(r).contains("TOTAL/OVER/173.5@1.83"));
    }
}
