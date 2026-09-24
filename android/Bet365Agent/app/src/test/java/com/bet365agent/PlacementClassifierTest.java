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

    /** OCR lines of the real receipt (shadow capture receipt-20260924-102616, frame s011). */
    @Test public void realReceiptFromShadowCapture() {
        PlacementClassifier.Result r = classify(false,
                "10227 B”? 0 (m5). 100%.", "ED 23 bet365.com/#/AC/Bl + E]", "Bet Placed", "m Share x",
                "Bet Ref BT496441 1231 W", "A; Live Alena Reuse Selecllons", "Hapoel Tel Aviv -8.0 1.83",
                "Point Spread", "Hapoel Tel Aviv vs Bayern Munich", "Stake To Return", "£O.1 0 £0.1 8",
                "g Q «o» (5’ BE", "Home All Sports ln-Play My Bets Casino");
        assertEquals("PLACED", r.outcome);
        assertTrue(r.definitive);
        assertEquals("BT4964411231W", r.betReference);
        assertEquals("0.10", r.stake);
        assertEquals("0.18", r.potentialReturn);
    }

    /** First supervised live placement (on-ca8c7974): "Stake" OCR'd as "Sta ke"; return must be 0.18, not the stake. */
    @Test public void liveReceiptWithSplitStakeHeader() {
        PlacementClassifier.Result r = classify(false, "2057 \u00ae 0 e.\u00bb 5).: 100%.", "ED 23 bet365.com/#/AC/Bi + E2]",
                "Bet Placed", "m Share x", "Bet Ref HT5515901931W", ";; Live Aieris Reuse Selections", "Val de Seine +3.5 1.83",
                "Point Spread", "Besancon AC vs Val de Seine", "Sta ke To Return", "\u00a3O.1 0 \u00a30.1 8",
                "g Q \u00abo\u00bb @9 BEE", "Hume All Sparts ln-Play My Bets Casino", "III C) <");
        assertEquals("PLACED", r.outcome);
        assertEquals("HT5515901931W", r.betReference);
        assertEquals("0.10", r.stake);
        assertEquals("0.18", r.potentialReturn);
    }

    @Test public void realBetslipBeforeTapIsPending() {
        PlacementClassifier.Result r = classify(true, "ED Ea bet365.com/#/AC/BW + E]", ">< Hapoel Tel Aviv -8.0 1.83",
                "Point Spread", "Hapoel Te‘ Aviv vs Bayern Munich", "3““ Place Bet", "£0.10 To Return £018",
                "WWW Silver £1,419‘46", "@ £050", "+£1 +£5 +£20", "Remember Stake Done");
        assertEquals("PENDING", r.outcome);
        assertFalse(r.definitive);
    }

    @Test public void receiptCloseIsTheXAfterShareNeverReuse() {
        assertEquals(2, PlacementClassifier.receiptCloseWord(Arrays.asList("m", "Share", "x")));
        assertEquals(-1, PlacementClassifier.receiptCloseWord(Arrays.asList("Live", "Alerts", "Reuse", "Selections")));
        assertEquals(-1, PlacementClassifier.receiptCloseWord(Arrays.asList("x", "Share")));
    }

    @Test public void removeSelectionIconOnlyOnTheSelectionLine() {
        assertEquals(0, PlacementClassifier.removeSelectionWord(
                Arrays.asList("><", "Hapoel", "Tel", "Aviv", "-8.0", "1.83"), "Hapoel Tel Aviv"));
        assertEquals(-1, PlacementClassifier.removeSelectionWord(
                Arrays.asList("><", "Bayern", "Munich", "+8.0"), "Hapoel Tel Aviv"));
        assertEquals(-1, PlacementClassifier.removeSelectionWord(
                Arrays.asList("3““", "Place", "Bet"), "Hapoel Tel Aviv"));
    }

    @Test public void genericResetRemovesOnlyASelectionLine() {
        assertEquals(0, PlacementClassifier.removeAnySelectionWord(Arrays.asList("><", "Bayern", "Munich", "+8.0", "1.83")));
        assertEquals(-1, PlacementClassifier.removeAnySelectionWord(Arrays.asList("m", "Share", "x")));
        assertEquals(-1, PlacementClassifier.removeAnySelectionWord(Arrays.asList("x", "Reuse", "Selections")));
        assertEquals(-1, PlacementClassifier.removeAnySelectionWord(Arrays.asList("><", "Place", "Bet")));
    }

    @Test public void collapsedSlipSelectionFoundByIndentWhenIconUnread() {
        // Real collapsed slip: "Bayern Munich +8.0" at left 59, "Point Spread" below, X not OCR'd.
        assertTrue(PlacementClassifier.selectionLineByIndent("Bayern Munich +8.0", 59, "Point Spread", "Bayern Munich"));
        assertTrue(PlacementClassifier.selectionLineByIndent("Bayern Munich +8.0", 59, "Point Spread", null));
        assertFalse(PlacementClassifier.selectionLineByIndent("Bayern Munich", 39, "Points", null));        // grid row
        assertFalse(PlacementClassifier.selectionLineByIndent("Hapoel Tel Aviv vs Bayern", 59, "Stake", null));
        assertFalse(PlacementClassifier.selectionLineByIndent("Bayern Munich +8.0", 59, "Point Spread", "Hapoel Tel Aviv"));
    }

    @Test public void betslipMustShowTheExactLine() {
        java.util.List<String> spread = Arrays.asList("Bayern Munich +8.0", "Point Spread", "Hapoel Tel Aviv vs Bayern Munich");
        assertTrue(PlacementClassifier.slipShowsLine(spread, "SPREAD", "AWAY", "Bayern Munich", "+8.0"));
        assertTrue(PlacementClassifier.slipShowsLine(spread, "SPREAD", "AWAY", "Bayern Munich", "8.0"));
        assertFalse(PlacementClassifier.slipShowsLine(spread, "SPREAD", "AWAY", "Bayern Munich", "-8.0"));
        assertFalse(PlacementClassifier.slipShowsLine(spread, "SPREAD", "AWAY", "Bayern Munich", "+18.0"));
        assertFalse(PlacementClassifier.slipShowsLine(spread, "SPREAD", "HOME", "Hapoel Tel Aviv", "-8.0"));
        java.util.List<String> under = Arrays.asList("Under 173.5", "Game Totals");
        assertTrue(PlacementClassifier.slipShowsLine(under, "TOTAL", "UNDER", "Under", "173.5"));
        assertFalse(PlacementClassifier.slipShowsLine(under, "TOTAL", "OVER", "Over", "173.5"));
        assertFalse(PlacementClassifier.slipShowsLine(under, "TOTAL", "UNDER", "Under", "172.5"));
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
