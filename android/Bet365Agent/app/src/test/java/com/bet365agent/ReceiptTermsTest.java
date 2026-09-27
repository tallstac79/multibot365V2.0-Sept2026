package com.bet365agent;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertNull;

import java.util.Arrays;
import java.util.List;
import org.junit.Test;

/** Real receipt lines, 27 Sep 2026. */
public class ReceiptTermsTest {
    @Test public void footballQuarterLineReceipt() {
        // CT4705359181W, Sao Paulo Crystal v Auto Esporte (the first automatic football bet)
        List<String> receipt = Arrays.asList("Bet Ref CT4705359181W", "Auto Esporte 0.0,-0.5 1.900", "Asian Handicap",
                "Sao Paulo Crystal V Auto Esporte", "£0.10 £0.19");
        assertArrayEquals(new String[] {"-0.25", "1.900"}, ReceiptTerms.parse(receipt, "Auto Esporte"));
    }

    @Test public void basketballReceiptsUnchanged() {
        assertArrayEquals(new String[] {"+5.5", "1.83"}, ReceiptTerms.parse(Arrays.asList("Bet Ref AT3003000811 W", "KB Prishtina +5.5 1.83"), "KB Prishtina"));
        assertArrayEquals(new String[] {"166.5", "1.83"}, ReceiptTerms.parse(Arrays.asList("Bet Ref ST2998906111W", "Under 166.5 1.83"), "Under"));
    }

    @Test public void nothingGuessed() {
        assertNull(ReceiptTerms.parse(Arrays.asList("Auto Esporte 0.0,-1.0 1.900"), "Auto Esporte"));   // not a quarter pair
        assertNull(ReceiptTerms.parse(Arrays.asList("Sao Paulo Crystal 0.0,+0.5 1.950"), "Auto Esporte"));
        assertNull(ReceiptTerms.parse(Arrays.asList("Auto Esporte 1.900"), "Auto Esporte"));
    }
}
