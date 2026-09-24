package com.bet365agent;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.util.Arrays;
import java.util.List;
import org.junit.Test;

/**
 * Milestone C9: OCR failure modes seen on real frames (either engine) must be recovered by an exact rule or
 * fail closed. Every case here is engine-agnostic: it is what the parsers do with a bad read.
 */
public class OcrFailureModesTest {
    private static GameLinesParser.Word w(String text, int l, int t, int r, int b) { return new GameLinesParser.Word(text, l, t, r, b); }

    @Test public void slipLineReadAsThreeFifteenIsRefusedButTheRealLinePasses() {
        // Real Besancon slip (legacy engine): "Val de Seine +3.5" OCR'd as "Val de Seine +315" -> LINE_CHANGED (re-read), never accepted.
        assertFalse(PlacementClassifier.slipShowsLine(Arrays.asList("Val de Seine +315", "Point Spread"), "SPREAD", "AWAY", "Val de Seine", "+3.5"));
        assertTrue(PlacementClassifier.slipShowsLine(Arrays.asList("Val de Seine +3.5", "Point Spread"), "SPREAD", "AWAY", "Val de Seine", "+3.5"));
        // merged slip line (name, line and price on one OCR line) still carries the exact signed line
        assertTrue(PlacementClassifier.slipShowsLine(Arrays.asList("Val de Seine +3.5 1.83"), "SPREAD", "AWAY", "Val de Seine", "+3.5"));
    }

    @Test public void droppedOrWrongSignIsRefused() {
        assertFalse("sign dropped", PlacementClassifier.slipShowsLine(Arrays.asList("Val de Seine 3.5"), "SPREAD", "AWAY", "Val de Seine", "+3.5"));
        assertFalse("sign flipped", PlacementClassifier.slipShowsLine(Arrays.asList("Val de Seine -3.5"), "SPREAD", "AWAY", "Val de Seine", "+3.5"));
        assertFalse("wrong line", PlacementClassifier.slipShowsLine(Arrays.asList("Val de Seine +1.5"), "SPREAD", "AWAY", "Val de Seine", "+3.5"));
        assertFalse("other team", PlacementClassifier.slipShowsLine(Arrays.asList("Besancon AC +3.5"), "SPREAD", "AWAY", "Val de Seine", "+3.5"));
    }

    @Test public void totalsNeedTheSideAndTheDecimal() {
        assertTrue(PlacementClassifier.slipShowsLine(Arrays.asList("Under 173.5"), "TOTAL", "UNDER", "", "173.5"));
        assertFalse("over/under swapped", PlacementClassifier.slipShowsLine(Arrays.asList("Over 173.5"), "TOTAL", "UNDER", "", "173.5"));
        assertFalse("decimal dropped", PlacementClassifier.slipShowsLine(Arrays.asList("Under 1735"), "TOTAL", "UNDER", "", "173.5"));
        assertFalse("merged digits", PlacementClassifier.slipShowsLine(Arrays.asList("Under 1173.5"), "TOTAL", "UNDER", "", "173.5"));
    }

    @Test public void poundMisreadIsToleratedOnceButAWrongReturnNever() {
        // "£" read as "E" on both amounts: one stray leading character, digits exact -> accepted.
        List<GameLinesParser.Word> words = Arrays.asList(w("E0.10", 20, 686, 102, 718),
                w("Place", 478, 658, 550, 680), w("Bet", 560, 659, 604, 680),
                w("To", 438, 696, 459, 711), w("Return", 467, 696, 526, 711), w("E0.18", 534, 696, 590, 715));
        assertTrue(StakePad.check(words, "0.10", "1.83").ok);
        // the same frame with To Return £0.19 (price moved) or the stake £0.11 fails on the arithmetic
        List<GameLinesParser.Word> moved = Arrays.asList(words.get(0), words.get(1), words.get(2), words.get(3), words.get(4), w("E0.19", 534, 696, 590, 715));
        assertFalse(StakePad.check(moved, "0.10", "1.83").ok);
        List<GameLinesParser.Word> wrongStake = Arrays.asList(w("E0.11", 20, 686, 102, 718), words.get(1), words.get(2), words.get(3), words.get(4), words.get(5));
        assertFalse(StakePad.check(wrongStake, "0.10", "1.83").ok);
    }

    @Test public void droppedDecimalIsToleratedOnlyWhenEveryDigitIsExact() {
        // £1.83 read as "£183": Bet365 always shows two decimals, so the digit sequence is still exactly stake x price.
        List<GameLinesParser.Word> words = Arrays.asList(w("£1.00", 20, 686, 102, 718),
                w("Place", 478, 658, 550, 680), w("Bet", 560, 659, 604, 680),
                w("To", 438, 696, 459, 711), w("Return", 467, 696, 526, 711), w("£183", 534, 696, 590, 715));
        assertTrue(StakePad.check(words, "1.00", "1.83").ok);
        // a different amount can never pass on digits: £18.30 / £1.88 / £183.00
        for (String bad : new String[]{"£18.30", "£1.88", "£183.00", "£1.8"}) {
            List<GameLinesParser.Word> other = Arrays.asList(words.get(0), words.get(1), words.get(2), words.get(3), words.get(4), w(bad, 534, 696, 590, 715));
            assertFalse(bad, StakePad.check(other, "1.00", "1.83").ok);
        }
        // and the "decimal read as 1" repair is never applied above £1 (ambiguous with £11.83)
        assertEquals("1183", StakePad.dotReadAsOne("1183", "183", "183"));
    }

    @Test public void placeBetSpinnerAndNoiseAreNeverAReceipt() {
        // Real frame right after the tap: slip still shown, Place Bet button replaced by a spinner, no receipt yet.
        PlacementClassifier.Result r = PlacementClassifier.classify(Arrays.asList("bet365 £3.79", "Besancon AC vs Val de Seine",
                "Val de Seine +1.5", "Point Spread", "Stake", "£0.10", "Home All Sports In-Play My Bets Casino"), false);
        assertFalse(r.definitive);
        assertFalse("PLACED".equals(r.outcome));
        PlacementClassifier.Result noise = PlacementClassifier.classify(Arrays.asList("11:07 B>-:- 100%", "m 2; bet365.com/#/AC/B1 + [Q", "\\L ?\\ | +?1 +?5 +?20"), true);
        assertFalse(noise.definitive);
    }

    @Test public void truncatedGridNamesStillReadByPositionAndAreFlagged() throws Exception {
        // Bet365 truncates long names in the grid ("B erc k/R ang (:1 LI Fl"): rows are taken by position AND flagged.
        List<GameLinesParser.Word> words = Arrays.asList(
                w("Spread", 286, 743, 356, 760), w("Total", 452, 743, 496, 760),
                w("Berck/Ra", 38, 812, 160, 832), w("-3.5", 304, 795, 340, 812), w("O", 447, 795, 461, 812), w("156.5", 466, 795, 512, 812),
                w("1.83", 304, 828, 340, 845), w("1.83", 457, 828, 492, 845),
                w("Pays Sal", 38, 897, 160, 917), w("+3.5", 304, 880, 340, 897), w("U", 447, 880, 461, 897), w("156.5", 466, 880, 512, 897),
                w("1.83", 304, 913, 340, 930), w("1.83", 457, 913, 492, 930));
        GameLinesParser.Result g = GameLinesParser.parse(words, "Berck/Rang du Fliers", "Pays Salonais Basket 13");
        assertTrue(g.grid);
        assertTrue(g.cells.toString(), g.cells.toString().contains("SPREAD/AWAY/+3.5@1.83"));
        assertTrue(g.cells.toString(), g.cells.toString().contains("TOTAL/UNDER/156.5@1.83"));
    }
}
