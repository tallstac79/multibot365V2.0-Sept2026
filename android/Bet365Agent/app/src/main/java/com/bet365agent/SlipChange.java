package com.bet365agent;

import java.util.List;

/**
 * Bet365's changed-price slip state, decided from one fresh frame (pure; SlipChangeTest).
 *
 * When the price moves while a bet sits on the slip, Bet365 shows "The price of your selection changed" and replaces
 * the stake area's "To Return" with "Accept Change" (stake empty) or "Accept Change and Place Bet" (stake entered), so
 * the ordinary stake check can never pass. Real case 28 Sep 2026 (Sawmer v Nongkseh SS & CC, on-eb956945): alert AWAY
 * -2.75 @1.90 (floor 1.81, allowance 0.25); the slip showed AWAY -3.0 @1.900 - inside both - and the run ended
 * PRICE_CHANGED without ever judging those terms.
 *
 * Decision on the frame with the stake cleared: ACCEPT only when the standalone "Accept Change" button is shown (never
 * the combined "Accept Change and Place Bet"), the slip holds both approved teams and the full-game market
 * (HeldSlipIdentity), its selection row reads (HeldSlipQuote) and the fresh line/price pass the instruction's own
 * tolerances (FootballLineCheck.freshTerms). Anything else is REFUSE with the real reason. The caller taps that button
 * once, then re-verifies the slip at the decided terms and repeats the normal stake check.
 */
final class SlipChange {
    private SlipChange() {}

    static final class Decision {
        final String action, stage, detail, line, price;   // action: NONE | ACCEPT | REFUSE
        final int[] acceptBounds;
        Decision(String action, String stage, String detail, String line, String price, int[] acceptBounds) {
            this.action = action; this.stage = stage; this.detail = detail; this.line = line; this.price = price; this.acceptBounds = acceptBounds;
        }
        static Decision refuse(String stage, String detail) { return new Decision("REFUSE", stage, detail, null, null, null); }
    }

    static Decision decide(List<GameLinesParser.Word> rawWords, String home, String away, String name, String market, String side,
                           String requestedLine, String allowance, String minimum) {
        List<GameLinesParser.Word> lines = EventHeader.lineWords(rawWords);
        // The button from its own words: "Accept" then "Change(s)" on the same row; combined when "and" follows it (the
        // "Accept Change and / Place Bet" button). OCR can group the empty stake field "£0.00" into the same line, so the
        // tap target is the two words' own box, never the grouped line's.
        GameLinesParser.Word standalone = null;
        boolean banner = false, combined = false;
        for (GameLinesParser.Word a : rawWords) {
            if (!a.text.equalsIgnoreCase("Accept")) continue;
            GameLinesParser.Word change = null, and = null;
            for (GameLinesParser.Word w : rawWords) {
                boolean sameRow = Math.abs(w.top - a.top) <= 12 && w.left > a.left;
                if (sameRow && w.left - a.right <= 40 && w.text.matches("(?i)changes?")) change = w;
            }
            if (change == null) continue;
            banner = true;
            for (GameLinesParser.Word w : rawWords)
                if (Math.abs(w.top - change.top) <= 12 && w.left > change.left && w.left - change.right <= 40 && w.text.equalsIgnoreCase("and")) and = w;
            if (and != null) { combined = true; continue; }
            standalone = new GameLinesParser.Word("Accept Change", a.left, Math.min(a.top, change.top), change.right, Math.max(a.bottom, change.bottom));
        }
        if (!banner) return new Decision("NONE", null, "no changed-price state on the slip", null, null, null);
        if (standalone == null)
            return Decision.refuse("PRICE_CHANGED", combined ? "Only the combined 'Accept Change and Place Bet' is shown: never tapped"
                    : "Changed-price state without a standalone 'Accept Change'");
        int top = standalone.top;
        if (!HeldSlipIdentity.matches(lines, home, away, market, top, "football"))
            return Decision.refuse("WRONG_EVENT", "Changed-price slip does not show both approved teams and the full-game market");
        HeldSlipQuote quote = HeldSlipQuote.read(lines, name, market, top, "football");
        if (quote == null) return Decision.refuse("PRICE_CHANGED", "Changed-price slip: selection line and price unreadable");
        String line = "MONEYLINE".equals(market) || "1X2".equals(market) ? "" : quote.line;
        String[] refusal = FootballLineCheck.freshTerms("1X2".equals(market) ? "MONEYLINE" : market, side, requestedLine, line, quote.price, allowance, minimum);
        if (refusal != null) return Decision.refuse(refusal[0], "Changed price on the slip: " + refusal[1]);
        return new Decision("ACCEPT", null, "Changed price inside the tolerances: " + side + " " + line + " @ " + quote.price, line, quote.price,
                new int[] {standalone.left, standalone.top, standalone.right, standalone.bottom});
    }
}
