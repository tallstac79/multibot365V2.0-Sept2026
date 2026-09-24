package com.bet365agent;

/** Read-only reconciliation: open live home, confirm the session, read My Bets (OPEN or SETTLED). */
final class MyBetsWorkflow {
    private final VisualSession session;
    private final Bet365LiveAdapter adapter;
    private final String view;
    MyBetsWorkflow(VisualSession session, Bet365LiveAdapter adapter, String view) {
        this.session = session; this.adapter = adapter; this.view = view;
    }
    void start() {
        session.checkpoint("OPEN_HOME");
        adapter.open_home()
            .thenCompose(v -> { session.checkpoint("ENSURE_SESSION"); return adapter.ensure_session(); })
            .thenCompose(v -> adapter.read_my_bets(view))
            .whenComplete((myBets, error) -> {
                if (error == null) {
                    session.put("my_bets", myBets);
                    session.put("verification_detail", "My Bets " + view + " read: " + myBets.optJSONArray("lines").length()
                            + " lines over " + myBets.optJSONArray("frames").length() + " frames; no bet controls touched");
                    session.finish("PASS", "MY_BETS");
                } else {
                    Throwable cause = error; while (cause.getCause() != null) cause = cause.getCause();
                    String status = cause instanceof SiteAdapter.Failure ? ((SiteAdapter.Failure) cause).stage : "INTERNAL_ERROR";
                    session.finish(status, cause.getMessage() == null ? cause.getClass().getSimpleName() : cause.getMessage());
                }
            });
    }
}
