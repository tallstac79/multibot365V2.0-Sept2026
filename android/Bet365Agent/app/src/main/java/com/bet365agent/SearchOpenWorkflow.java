package com.bet365agent;

/** Non-betting Search harness: home → session → open Search UI (+ optional query) → reset. */
final class SearchOpenWorkflow {
    private final VisualSession session;
    private final SiteAdapter adapter;
    private final String query;
    SearchOpenWorkflow(VisualSession session, SiteAdapter adapter, String query) {
        this.session = session;
        this.adapter = adapter;
        this.query = query == null ? "" : query.trim();
    }
    void start() {
        session.checkpoint("OPEN_HOME");
        adapter.open_home()
            .thenCompose(v -> { session.checkpoint("ENSURE_SESSION"); return adapter.ensure_session(); })
            .thenCompose(v -> { session.checkpoint("OPEN_SEARCH"); return adapter.open_search(); })
            .thenCompose(v -> {
                if (query.isEmpty()) return java.util.concurrent.CompletableFuture.completedFuture(null);
                session.checkpoint("ENTER_QUERY");
                return adapter.enter_query(query);
            })
            .thenCompose(v -> {
                session.checkpoint("RESET_SEARCH");
                if (adapter instanceof Bet365LiveAdapter) {
                    return ((Bet365LiveAdapter) adapter).reset_search_ui()
                        .thenCompose(x -> adapter.open_home());
                }
                return adapter.open_home();
            })
            .whenComplete((v, error) -> {
                if (error == null) {
                    session.put("search_ui_open", true);
                    if (!query.isEmpty()) session.put("search_query", query);
                    session.put("verification_detail", query.isEmpty()
                        ? "OPEN_SEARCH: Search UI positively recognized; reset afterward"
                        : ("OPEN_SEARCH: query '" + query + "' entered and results verified; reset afterward"));
                    session.finish("PASS", query.isEmpty() ? "OPEN_SEARCH" : "OPEN_SEARCH_QUERY");
                } else {
                    Throwable cause = error;
                    while (cause.getCause() != null) cause = cause.getCause();
                    String status = cause instanceof SiteAdapter.Failure ? ((SiteAdapter.Failure) cause).stage : "INTERNAL_ERROR";
                    session.finish(status, cause.getMessage() == null ? cause.getClass().getSimpleName() : cause.getMessage());
                }
            });
    }
}
