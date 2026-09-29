package com.bet365agent;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import java.util.List;
import org.junit.Test;

/**
 * Mauritania U23 1X2 stake hang, 28 Sep 2026 (on-a63fdd616d188e00afe19d87).
 *
 * First quote 4.50 at 17:31:15.57 BST (identical to BetSwifty). ENTER_STAKE took 15.2 s then
 * STAKE_REJECTED. Stored frames show the stake box already read as 0.10 on both typed captures;
 * To Return was 0.41 (= 0.10 x 4.10) while openedPrice stayed 4.50; no Accept Change banner.
 * The old path cleared+retyped anyway. Class fix: detect silent price move when stake digits
 * already match, fail PRICE_CHANGED immediately, and keep stake_check readings on the result.
 */
public class MauritaniaStake20260928Test {

    @Test public void typedFrameStakeDigitsMatchButReturnImplies410() throws Exception {
        List<GameLinesParser.Word> words = StakePadTest.load("footslip_mauritania_stake_typed_20260928.txt");
        assertEquals("EMPTY was only the pre-type state", "FILLED", StakePad.fieldState(words));
        StakePad.Check againstOpened = StakePad.check(words, "0.10", "4.50");
        assertFalse(againstOpened.detail, againstOpened.ok);
        assertTrue(againstOpened.detail, StakePad.stakeDigitsMatch(againstOpened, "0.10"));
        assertEquals("010", againstOpened.stakeDigits);
        assertEquals("041", againstOpened.returnDigits);
        assertEquals("4.10", StakePad.silentMovedPrice(againstOpened, "0.10", "4.50"));
        // Against the implied slip price the same frame would verify.
        assertTrue(StakePad.check(words, "0.10", "4.10").ok);
    }

    @Test public void secondTypedCaptureSameSilentMove() throws Exception {
        List<GameLinesParser.Word> words = StakePadTest.load("footslip_mauritania_stake_typed2_20260928.txt");
        StakePad.Check c = StakePad.check(words, "0.10", "4.50");
        assertFalse(c.ok);
        assertTrue(StakePad.stakeDigitsMatch(c, "0.10"));
        assertEquals("4.10", StakePad.silentMovedPrice(c, "0.10", "4.50"));
    }

    @Test public void retypedFrameStillSilentMoveNotStakeTypo() throws Exception {
        List<GameLinesParser.Word> words = StakePadTest.load("footslip_mauritania_stake_retyped_20260928.txt");
        StakePad.Check c = StakePad.check(words, "0.10", "4.50");
        assertFalse(c.ok);
        assertTrue(StakePad.stakeDigitsMatch(c, "0.10"));
        assertEquals("4.10", StakePad.silentMovedPrice(c, "0.10", "4.50"));
        assertNull("no Accept Change words on the retyped frame", acceptChange(words));
    }

    @Test public void emptyStakeUiBeforeTyping() throws Exception {
        List<GameLinesParser.Word> words = StakePadTest.load("footslip_mauritania_stake_ui_20260928.txt");
        assertEquals("EMPTY", StakePad.fieldState(words));
        assertNotNull(StakePad.keypad(words, 850));
    }

    @Test public void clearedFrameEmptyAfterBackspaces() throws Exception {
        assertEquals("EMPTY", StakePad.fieldState(StakePadTest.load("footslip_mauritania_stake_cleared_20260928.txt")));
    }

    @Test public void silentMovedPriceNullWhenStakeItselfWrong() {
        // Stake OCR 10.10 with return 0.41 must not be called a silent price move.
        // Note: agrees() tolerates one leading stray digit, so "1010" agrees with "010"; silentMovedPrice
        // requires exact stake digits and must still return null here.
        List<GameLinesParser.Word> words = java.util.Arrays.asList(
                w("Stake", 20, 654, 70, 669), w("£10.10", 20, 683, 106, 711),
                w("Place", 477, 658, 550, 680), w("Bet", 560, 658, 604, 680),
                w("To", 464, 696, 486, 711), w("Return", 493, 696, 552, 711), w("£0.41", 560, 696, 609, 711));
        StakePad.Check c = StakePad.check(words, "0.10", "4.50");
        assertFalse(c.ok);
        assertEquals("1010", c.stakeDigits);
        assertNull(StakePad.silentMovedPrice(c, "0.10", "4.50"));
    }

    @Test public void silentMovedPriceNullWhenReturnMatchesOpened() {
        List<GameLinesParser.Word> words = java.util.Arrays.asList(
                w("Stake", 20, 654, 70, 669), w("£0.10", 20, 683, 106, 711),
                w("Place", 477, 658, 550, 680), w("Bet", 560, 658, 604, 680),
                w("To", 464, 696, 486, 711), w("Return", 493, 696, 552, 711), w("£0.45", 560, 696, 609, 711));
        StakePad.Check c = StakePad.check(words, "0.10", "4.50");
        assertTrue(c.detail, c.ok);
        assertNull(StakePad.silentMovedPrice(c, "0.10", "4.50"));
    }

    private static GameLinesParser.Word w(String t, int l, int top, int r, int b) {
        return new GameLinesParser.Word(t, l, top, r, b);
    }

    private static String acceptChange(List<GameLinesParser.Word> words) {
        for (GameLinesParser.Word a : words) {
            if (!a.text.equalsIgnoreCase("Accept")) continue;
            for (GameLinesParser.Word w : words)
                if (Math.abs(w.top - a.top) <= 12 && w.left > a.left && w.text.matches("(?i)changes?")) return "Accept Change";
        }
        return null;
    }
}
