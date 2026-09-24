package com.bet365agent;

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

    @Test public void aWrongStakeCannotPassBothReadings() {
        // Stake really £10.10 but OCR drops the £: stake digits look right, the return (18.48) does not.
        List<GameLinesParser.Word> words = Arrays.asList(w("10.10", 20, 686, 102, 718),
                w("Place", 478, 658, 550, 680), w("Bet", 560, 659, 604, 680),
                w("To", 438, 696, 459, 711), w("Return", 467, 696, 526, 711), w("£18.48", 534, 696, 610, 715));
        assertFalse(StakePad.check(words, "0.10", "1.83").ok);
    }
}
