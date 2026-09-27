package com.bet365agent;

/**
 * PLACE_HELD: the approved bet is already on the slip (left there by the hold run). No navigation,
 * no search, no rebuilding: one fast pre-tap check of the current slip, then ONE Place Bet tap
 * (execution_mode dispatch), or the check only (prepare, for regression proofs). If the slip changed
 * or disappeared the run fails closed; it never rebuilds the bet after approval.
 */
final class PlaceHeldWorkflow {
    private final VisualSession session;
    private final Bet365LiveAdapter adapter;
    PlaceHeldWorkflow(VisualSession session, Bet365LiveAdapter adapter) { this.session = session; this.adapter = adapter; }

    void start(String market, String side, String line, String name, String price, String minimumPrice, String stake, String mode) {
        final boolean dispatch = "dispatch".equals(mode);
        session.put("t_start_ms", System.currentTimeMillis());
        adapter.place_held("1X2".equals(market) ? "MONEYLINE" : market, side, line, name, price, minimumPrice, stake, dispatch).whenComplete((v, error) -> {
            if (error == null) {
                if (dispatch) {
                    org.json.JSONObject placement = session.record.optJSONObject("placement");
                    String outcome = placement == null ? "PLACEMENT_UNKNOWN" : placement.optString("outcome", "PLACEMENT_UNKNOWN");
                    session.put("verification_detail", "PLACE_HELD: pre-tap check passed; outcome=" + outcome);
                    if ("PLACED".equals(outcome)) session.finish("PASS", "PLACED");
                    else session.finish(outcome, placement == null ? "No placement record after tap" : placement.optString("detail", outcome));
                } else {
                    session.put("verification_detail", "PLACE_HELD prepare: held slip verified and Place Bet located; NOT tapped");
                    session.finish("PASS", "PRETAP_READY");
                }
                return;
            }
            if (dispatch && !session.record.has("placement"))
                session.put("placement", CoordinatorAgent.object("tapped", false, "outcome", "NOT_TAPPED", "detail", "Held slip failed the pre-tap check"));
            Throwable cause = error; while (cause.getCause() != null) cause = cause.getCause();
            String status = cause instanceof SiteAdapter.Failure ? ((SiteAdapter.Failure) cause).stage : "INTERNAL_ERROR";
            session.finish(status, cause.getMessage() == null ? cause.getClass().getSimpleName() : cause.getMessage());
        });
    }
}
