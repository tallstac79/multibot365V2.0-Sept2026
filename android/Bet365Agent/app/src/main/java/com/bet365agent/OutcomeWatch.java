package com.bet365agent;

/**
 * How the phone watches for Bet365's answer after the single Place Bet tap (pure Java; OutcomeWatchTest).
 *
 * Before 29 Sep 2026 the watch was five frames separated by fixed waits of 1.5, 1.5, 2, 3 and 4 s, the first one 2 s
 * after the tap: every placed bet took a near-constant 5.3 s from tap to receipt (min 5.08 s, max 5.66 s over 35 bets),
 * a number set by those waits and not by Bet365. The watch now looks from 0.15 s after the tap's own settle and again
 * after a short pause, for at least as long as before, judging every frame with the same PlacementClassifier.
 *
 * Receipt proof is unchanged in strength: a PLACED frame must carry the bet reference and the receipt's stake and
 * return. A frame read the instant the banner draws can lack them, so the watch looks again (the banner stays until
 * closed) before finalising - an early detection is never a weaker confirmation than a late one was.
 */
final class OutcomeWatch {
    private OutcomeWatch() {}

    /** Total time after the tap to keep watching before the outcome is reported PLACEMENT_UNKNOWN (was 12 s of waits + frames). */
    static final long BUDGET_MS = 16_000;
    /** Extra looks at a PLACED frame that lacks reference or terms. */
    static final int RECEIPT_EXTRA_LOOKS = 3;
    /** Pause before the first frame after the tap's own settle. */
    static final long FIRST_LOOK_MS = 150;

    /** Pause between frames, by time since the tap: dense while a receipt is expected, sparse if Bet365 is slow. */
    static long gapMs(long sinceTapMs) {
        return sinceTapMs < 6_000 ? 120 : sinceTapMs < 10_000 ? 400 : 1_000;
    }

    /** The frame is a definitive PLACED but does not yet prove the bet (reference, stake or return unread). */
    static boolean thinReceipt(PlacementClassifier.Result r) {
        return r.definitive && "PLACED".equals(r.outcome) && (r.betReference == null || r.stake == null || r.potentialReturn == null);
    }

    /** Keep watching: no definitive outcome yet and the budget is not spent, or a thin receipt with looks left. */
    static boolean lookAgain(PlacementClassifier.Result r, long sinceTapMs, int extraLooksUsed) {
        if (!r.definitive) return sinceTapMs < BUDGET_MS;
        return thinReceipt(r) && extraLooksUsed < RECEIPT_EXTRA_LOOKS;
    }
}
