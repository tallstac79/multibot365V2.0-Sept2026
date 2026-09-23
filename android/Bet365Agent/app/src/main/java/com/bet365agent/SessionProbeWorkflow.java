package com.bet365agent;

/** Non-betting screen-only session classifier; never types or taps. */
final class SessionProbeWorkflow {
    private final VisualSession session;
    SessionProbeWorkflow(VisualSession session) { this.session=session; }
    void start() {
        session.checkpoint("CLASSIFY_SESSION");
        session.capture("session_probe").whenComplete((screen,error) -> {
            if(error==null) {
                String state=Bet365LiveAdapter.classifySessionState(screen);
                session.put("session", state);
                session.put("verification_detail", "On-screen session classified without input or betting instruction");
                session.finish("PASS", "SESSION_" + state);
            } else {
                Throwable cause=error; while(cause.getCause()!=null) cause=cause.getCause();
                session.finish("INTERNAL_ERROR", cause.getMessage()==null ? cause.getClass().getSimpleName() : cause.getMessage());
            }
        });
    }
}
