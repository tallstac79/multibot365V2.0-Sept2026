package com.bet365agent;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import java.util.Arrays;
import java.util.List;
import org.junit.Test;

/** Post-tap outcome classification. Screens are OCR-style line lists; calibrated further from shadow capture. */
public class PlacementClassifierTest {
    private static PlacementClassifier.Result classify(boolean placeVisible, String... lines) {
        return PlacementClassifier.classify(Arrays.asList(lines), placeVisible);
    }

    @Test public void receiptIsPlacedWithReferenceStakeAndReturn() {
        PlacementClassifier.Result r = classify(false, "Bet Placed", "Rytas Vilnius -18.5", "Stake £0.10",
                "To Return £0.18", "Bet Ref JL1234567890", "Done");
        assertEquals("PLACED", r.outcome);
        assertTrue(r.definitive);
        assertEquals("JL1234567890", r.betReference);
        assertEquals("0.10", r.stake);
        assertEquals("0.18", r.potentialReturn);
    }

    @Test public void oddsChangePromptIsReportedNeverAccepted() {
        PlacementClassifier.Result r = classify(false, "The odds have changed", "1.83 → 1.72", "Accept Changes");
        assertEquals("PRICE_CHANGED", r.outcome);
        assertTrue(r.detail.contains("NOT accepted"));
        assertFalse(PlacementClassifier.safeResetControl("Accept Changes"));
        assertFalse(PlacementClassifier.safeResetControl("Accept & Place Bet"));
    }

    @Test public void lineChangeBeatsGenericOddsWording() {
        assertEquals("LINE_CHANGED", classify(false, "Line has changed", "Accept Changes").outcome);
    }

    @Test public void refusalsAreDefinitive() {
        assertEquals("STAKE_LIMITED", classify(false, "Max Stake £0.05", "Your stake exceeds the maximum").outcome);
        assertEquals("INSUFFICIENT_FUNDS", classify(false, "Insufficient funds", "Deposit").outcome);
        assertEquals("SUSPENDED", classify(true, "Selection Suspended", "Place Bet").outcome);
        assertEquals("REJECTED", classify(false, "Your bet could not be placed").outcome);
        assertEquals("SESSION_EXPIRED", classify(false, "Log In", "Username", "Password").outcome);
    }

    @Test public void headerDepositButtonIsNotInsufficientFunds() {
        PlacementClassifier.Result r = classify(true, "Deposit", "£0.00", "Place Bet £0.10");
        assertEquals("PENDING", r.outcome);
        assertFalse(r.definitive);
    }

    @Test public void nothingRecognisableIsNotDefinitive() {
        PlacementClassifier.Result r = classify(false, "Sports", "In-Play");
        assertEquals("UNKNOWN", r.outcome);
        assertFalse(r.definitive);
        assertNull(r.betReference);
    }

    @Test public void resetOnlyTapsSafeControls() {
        for (String ok : Arrays.asList("Done", "Continue", "Close", "Remove All", "Clear All")) {
            assertTrue(ok, PlacementClassifier.safeResetControl(ok));
        }
        for (String bad : Arrays.asList("Place Bet", "Place Bet £0.10", "Accept", "Confirm", "Bet Now", "Set Stake")) {
            assertFalse(bad, PlacementClassifier.safeResetControl(bad));
        }
    }

    @Test public void multiplesAreDetected() {
        List<String> slip = Arrays.asList("2 Selections", "Doubles", "Place Bet");
        assertTrue(PlacementClassifier.multipleSelections(slip));
        assertFalse(PlacementClassifier.multipleSelections(Arrays.asList("Single", "Rytas Vilnius -18.5", "Place Bet")));
    }
}
