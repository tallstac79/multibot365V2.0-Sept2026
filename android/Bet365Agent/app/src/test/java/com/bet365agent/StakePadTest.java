package com.bet365agent;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.junit.Test;

/** Real betslip keypad frames from the READY proof that typed £8,718 (2026-09-24). */
public class StakePadTest {
    private static final Pattern WORD = Pattern.compile("^(.*) \\[(\\d+),(\\d+)\\]\\[(\\d+),(\\d+)\\]$");

    static List<GameLinesParser.Word> load(String name) throws Exception {
        List<GameLinesParser.Word> out = new ArrayList<>();
        try (BufferedReader in = new BufferedReader(new InputStreamReader(
                StakePadTest.class.getResourceAsStream("/" + name), StandardCharsets.UTF_8))) {
            for (String line; (line = in.readLine()) != null; ) {
                Matcher m = WORD.matcher(line);
                if (m.matches()) out.add(new GameLinesParser.Word(m.group(1), Integer.parseInt(m.group(2)),
                        Integer.parseInt(m.group(3)), Integer.parseInt(m.group(4)), Integer.parseInt(m.group(5))));
            }
        }
        return out;
    }

    private static void near(int[] p, int x, int y) {
        assertTrue(Arrays.toString(p), Math.abs(p[0] - x) <= 3 && Math.abs(p[1] - y) <= 3);
    }

    private static GameLinesParser.Word w(String text, int l, int t, int r, int b) { return new GameLinesParser.Word(text, l, t, r, b); }

    @Test public void keypadFromRealDigitWords() throws Exception {
        Map<Character, int[]> keys = StakePad.keypad(load("keypad_empty_20260924.txt"), 850);
        assertNotNull(keys);
        near(keys.get('1'), 119, 997);
        near(keys.get('0'), 360, 1250);
        // '.' has no OCR text: column of 1/4/7, row of 0. The old guess tapped "7" here.
        near(keys.get('.'), 119, 1250);
        assertTrue(Math.abs(keys.get(StakePad.BACKSPACE)[0] - 600) < 10);
    }

    @Test public void missingThirdColumnIsInferredFromSpacing() throws Exception {
        Map<Character, int[]> keys = StakePad.keypad(load("keypad_typed_8718_20260924.txt"), 850);
        assertNotNull(keys);
        assertTrue(Math.abs(keys.get('9')[0] - 600) < 10);
        assertTrue(Math.abs(keys.get('9')[1] - 1165) < 10);
    }

    @Test public void noKeypadNoGuess() {
        assertNull(StakePad.keypad(Arrays.asList(w("1", 112, 983, 124, 1012), w("Done", 514, 1342, 567, 1359)), 850));
    }

    @Test public void theRealWrongStakeIsRejected() throws Exception {
        StakePad.Check c = StakePad.check(load("keypad_typed_8718_20260924.txt"), "0.10", "1.83");
        assertFalse(c.detail, c.ok);
    }

    @Test public void correctStakeAndReturnAreAccepted() {
        List<GameLinesParser.Word> words = Arrays.asList(w("Stake", 20, 654, 70, 669), w("£0.10", 20, 686, 102, 718),
                w("Place", 478, 658, 550, 680), w("Bet", 560, 659, 604, 680),
                w("To", 438, 696, 459, 711), w("Return", 467, 696, 526, 711), w("£018", 534, 696, 590, 715));
        StakePad.Check c = StakePad.check(words, "0.10", "1.83");
        assertTrue(c.detail, c.ok);
        // £ misread as "1" in edit mode is tolerated once...
        List<GameLinesParser.Word> misread = new ArrayList<>(words);
        misread.set(1, w("10.10", 20, 686, 102, 718));
        assertTrue(StakePad.check(misread, "0.10", "1.83").ok);
    }

    @Test public void stakeReturnUsesFreshToleratedPriceInsteadOfOriginalQuote() {
        List<GameLinesParser.Word> words = Arrays.asList(w("Stake",20,654,70,669), w("£1.00",20,686,102,718),
                w("Place",478,658,550,680), w("Bet",560,659,604,680),
                w("To",438,696,459,711), w("Return",467,696,526,711), w("£1.75",534,696,590,715));
        HeldSlipQuote quote = HeldSlipQuote.read(Arrays.asList(w("Under 165.0 1.75",80,520,600,540),
                w("Game Totals",80,560,600,580)),"Under","TOTAL",658);
        assertNotNull(quote);
        assertTrue(ExecutionTolerance.price(quote.price,"1.75"));
        assertTrue(StakePad.check(words,"1.00",quote.price).ok);
        assertFalse(StakePad.check(words,"1.00","1.83").ok);
        assertFalse(StakePad.check(words,"2.00",quote.price).ok);
    }

    @Test public void realTypedStakeBeforeDone() throws Exception {
        // Edit mode: "£0.10|" OCR'd with a stray leading digit; To Return £0.18.
        StakePad.Check c = StakePad.check(load("keypad_typed_010_20260924.txt"), "0.10", "1.83");
        assertTrue(c.detail, c.ok);
    }

    @Test public void realCollapsedSlipAfterDoneUsesTheExactReturn() throws Exception {
        // OCR dropped "Stake £0.10" entirely and read "Return" as "Re'urn"; "£0.18" is exact.
        List<GameLinesParser.Word> words = load("betslip_after_done_20260924.txt");
        StakePad.Check c = StakePad.check(words, "0.10", "1.83");
        assertTrue(c.detail, c.ok);
        assertFalse(StakePad.check(words, "0.11", "1.83").ok);
        assertFalse(StakePad.check(words, "0.09", "1.83").ok);
        assertFalse(StakePad.check(words, "1.00", "1.83").ok);
        assertFalse("price too low for return-only", StakePad.check(words, "0.10", "1.05").ok);
    }

    @Test public void decimalPointReadAsOneOnlyUnderOnePound() {
        assertTrue(StakePad.dotReadAsOne("0118", "018", "018").equals("018"));     // £0.18 read as £0118
        assertTrue(StakePad.dotReadAsOne("1183", "183", "183").equals("1183"));    // £1.83 vs £11.83: ambiguous, no fix
        assertTrue(StakePad.dotReadAsOne("0128", "018", "018").equals("0128"));    // not the decimal position
        List<GameLinesParser.Word> words = Arrays.asList(w("Place", 478, 1324, 550, 1346), w("Bet", 560, 1325, 604, 1346),
                w("To", 464, 1362, 485, 1377), w("Return", 493, 1362, 552, 1377), w("£0118", 560, 1362, 611, 1377));
        assertTrue(StakePad.check(words, "0.10", "1.83").ok);
        assertFalse(StakePad.check(words, "0.11", "1.83").ok);
    }

    @Test public void stakeFieldStateFromRealFrames() throws Exception {
        assertTrue(StakePad.fieldState(load("keypad_empty_20260924.txt")).equals("EMPTY"));        // £0.00 selected: no To Return
        assertTrue(StakePad.fieldState(load("keypad_typed_8718_20260924.txt")).equals("FILLED"));  // £8,718 typed: To Return shown
        assertTrue(StakePad.fieldState(load("keypad_typed_010_20260924.txt")).equals("FILLED"));   // £0.10 typed
        assertTrue(StakePad.fieldState(Arrays.asList(w("Done", 514, 1342, 567, 1359))).equals("UNKNOWN"));
    }

    @Test public void aWrongStakeCannotPassBothReadings() {
        // Stake really £10.10 but OCR drops the £: stake digits look right, the return (18.48) does not.
        List<GameLinesParser.Word> words = Arrays.asList(w("10.10", 20, 686, 102, 718),
                w("Place", 478, 658, 550, 680), w("Bet", 560, 659, 604, 680),
                w("To", 438, 696, 459, 711), w("Return", 467, 696, 526, 711), w("£18.48", 534, 696, 610, 715));
        assertFalse(StakePad.check(words, "0.10", "1.83").ok);
    }

    // ---- a stake already in the field (Remember Stake) is kept only on a stricter read than a typed one
    private static List<GameLinesParser.Word> slip(String stakeText, String returnText) {
        List<GameLinesParser.Word> l = new ArrayList<>(Arrays.asList(w("Stake", 20, 654, 70, 669),
                w("Place", 478, 658, 550, 680), w("Bet", 560, 659, 604, 680), w("To", 438, 696, 459, 711), w("Return", 467, 696, 526, 711)));
        if (stakeText != null) l.add(w(stakeText, 20, 686, 102, 718));
        if (returnText != null) l.add(w(returnText, 534, 696, 590, 715));
        return l;
    }

    @Test public void aRememberedStakeThatReadsExactlyIsAccepted() {
        assertTrue(StakePad.checkPrefilled(slip("£0.10", "£0.18"), "0.10", "1.83").ok);
        assertTrue("one misread pound sign is tolerated on the stake box only", StakePad.checkPrefilled(slip("10.10", "£0.18"), "0.10", "1.83").ok);
    }

    @Test public void aRememberedStakeNeedsTheStakeBoxRead() {
        assertFalse("return alone is never enough for a stake nobody typed", StakePad.checkPrefilled(slip(null, "£0.18"), "0.10", "1.83").ok);
        assertTrue("the same frame is fine for a stake that was typed", StakePad.check(slip(null, "£0.18"), "0.10", "1.83").ok);
    }

    @Test public void aRememberedStakeNeedsTheExactReturn() {
        assertFalse("stray glyph on the return", StakePad.checkPrefilled(slip("£0.10", "£10.18"), "0.10", "1.83").ok);
        assertFalse("wrong remembered stake 0.20", StakePad.checkPrefilled(slip("£0.20", "£0.36"), "0.10", "1.83").ok);
        assertFalse("wrong remembered stake 1.00", StakePad.checkPrefilled(slip("£1.00", "£1.83"), "0.10", "1.83").ok);
        assertFalse("wrong remembered stake 10.10 with the pound sign dropped", StakePad.checkPrefilled(slip("10.10", "£18.48"), "0.10", "1.83").ok);
        assertFalse("no To Return", StakePad.checkPrefilled(slip("£0.10", null), "0.10", "1.83").ok);
    }

    @Test public void aRememberedStakeIsJudgedAtTheFreshPrice() {
        assertFalse("price moved 1.83 -> 2.10 under the remembered stake", StakePad.checkPrefilled(slip("£0.10", "£0.18"), "0.10", "2.10").ok);
    }

    @Test public void theRealRememberedStakeSlipIsKeptOnlyWhenStakeAndReturnAgreeExactly() throws Exception {
        // 29 Sep 2026 21:41 (Real Espana Reserves v Motagua Reserves, 1X2 HOME 2.45): Bet365 "Remember Stake" shows the slip as
        // "Stake £0.10 | Place Bet, To Return £0.24" with no "Set Stake" control. 0.10 x 2.45 = 0.245 -> 0.24.
        List<GameLinesParser.Word> words = load("slip_remembered_stake_20260929.txt");
        assertTrue(StakePad.checkPrefilled(words, "0.10", "2.45").detail, StakePad.checkPrefilled(words, "0.10", "2.45").ok);
        assertFalse("another stake", StakePad.checkPrefilled(words, "0.20", "2.45").ok);
        assertFalse("another stake", StakePad.checkPrefilled(words, "1.00", "2.45").ok);
        assertFalse("the price moved under the remembered stake", StakePad.checkPrefilled(words, "0.10", "2.60").ok);
        assertEquals("FILLED", StakePad.fieldState(words));
    }
}
