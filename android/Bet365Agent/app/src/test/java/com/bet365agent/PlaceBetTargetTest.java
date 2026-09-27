package com.bet365agent;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import java.util.Arrays;
import java.util.List;
import org.junit.Test;

/** Place Bet tap target on the real 27 Sep 2026 slips (UD Leiria pre-tap / after, Ossese hold final). */
public class PlaceBetTargetTest {
    private static GameLinesParser.Word w(String t, int l, int top, int r, int b) { return new GameLinesParser.Word(t, l, top, r, b); }

    @Test public void leiriaPretapTargetsThePlaceBetWordsNotTheStakeField() throws Exception {
        List<GameLinesParser.Word> words = StakePadTest.load("placebet_leiria_pretap_20260927.txt");
        int[] box = PlaceBetTarget.locate(words);
        assertNotNull(box);
        int cx = (box[0] + box[2]) / 2;
        // the old target was the merged line x 20-604 (centre x 312, the stake field); the button words are at x 477-604
        assertTrue(cx + " " + Arrays.toString(box), cx >= 477 && cx <= 604);
        assertTrue(box[0] > 106);                       // clear of "Stake" (x 20-69) and "£0.10" (x 20-106)
        assertTrue(box[1] <= 1324 && box[3] >= 1346);
        assertFalse(PlaceBetTarget.keypadOpen(words));
    }

    @Test public void leiriaAfterFrameIsAKeypadNotASubmission() throws Exception {
        List<GameLinesParser.Word> after = StakePadTest.load("placebet_leiria_after_20260927.txt");
        assertTrue(PlaceBetTarget.keypadOpen(after));
        PlacementClassifier.Result r = PlacementClassifier.tapNotAccepted();
        assertEquals("TAP_NOT_ACCEPTED", r.outcome);
        assertTrue(r.definitive);
    }

    @Test public void osseseHoldFinalSlip() throws Exception {
        int[] box = PlaceBetTarget.locate(StakePadTest.load("placebet_ossese_final_20260927.txt"));
        assertNotNull(box);
        int cx = (box[0] + box[2]) / 2;
        assertTrue(Arrays.toString(box), cx >= 477 && cx <= 604);
    }

    @Test public void failsClosedWithoutBothWords() {
        assertNull(PlaceBetTarget.locate(Arrays.asList(w("Stake", 20, 1320, 69, 1335), w("Place", 477, 1324, 550, 1346))));
        assertNull(PlaceBetTarget.locate(Arrays.asList(w("Place", 477, 1324, 550, 1346), w("Bet", 560, 1500, 604, 1520))));   // different rows
        // "Set Stake Place Bet" merged row: still only the button words
        int[] box = PlaceBetTarget.locate(Arrays.asList(w("Set", 20, 1330, 66, 1350), w("Stake", 76, 1330, 156, 1350),
                w("Place", 477, 1330, 550, 1350), w("Bet", 560, 1330, 604, 1350)));
        assertTrue(Arrays.toString(box), box[0] > 156 && box[2] <= 625);
        // the lowest pair wins (a "Place Bet" text higher on the page is never the slip button)
        int[] low = PlaceBetTarget.locate(Arrays.asList(w("Place", 100, 400, 170, 420), w("Bet", 178, 400, 210, 420),
                w("Place", 477, 1330, 550, 1350), w("Bet", 560, 1330, 604, 1350)));
        assertTrue(low[1] > 1300);
    }
}
