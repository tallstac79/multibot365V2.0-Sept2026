package com.bet365agent;

/** Non-betting workflow: open live home, restore session if needed, then stop. */
final class SessionCheckWorkflow {
    private final VisualSession session;
    private final SiteAdapter adapter;
    SessionCheckWorkflow(VisualSession session, SiteAdapter adapter) { this.session=session; this.adapter=adapter; }
    void start() {
        session.checkpoint("OPEN_HOME");
        adapter.open_home()
            .thenCompose(v -> { session.checkpoint("ENSURE_SESSION"); return adapter.ensure_session(); })
            .whenComplete((v,error) -> {
                if(error==null) {
                    session.put("session", "AUTHENTICATED");
                    session.put("verification_detail", "Session authenticated independently; no betting instruction executed");
                    session.finish("PASS", "SESSION_AUTHENTICATED");
                } else {
                    Throwable cause=error; while(cause.getCause()!=null) cause=cause.getCause();
                    String status=cause instanceof SiteAdapter.Failure ? ((SiteAdapter.Failure)cause).stage : "INTERNAL_ERROR";
                    session.finish(status, cause.getMessage()==null ? cause.getClass().getSimpleName() : cause.getMessage());
                }
            });
    }
}
