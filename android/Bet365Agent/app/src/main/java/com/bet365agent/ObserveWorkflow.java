package com.bet365agent;

import android.os.SystemClock;
import org.json.JSONArray;

/**
 * Shadow capture: screenshot + OCR every 2.5 s while the operator uses the phone by hand.
 * Never taps, types, scrolls or navigates. Used to collect real receipt / error / My Bets
 * screens for calibrating the placement classifier and bet matching.
 */
final class ObserveWorkflow {
    private static final long INTERVAL_MS = 2500L;
    private static final int MAX_FRAMES = 200;
    private static final int MAX_LINES = 80;
    private final VisualSession session;
    private final long until;
    ObserveWorkflow(VisualSession session, long budgetMs) {
        this.session = session;
        this.until = SystemClock.elapsedRealtime() + Math.max(5_000L, budgetMs - 8_000L);
    }
    void start() { frame(0, new JSONArray()); }
    private void frame(int n, JSONArray frames) {
        if (SystemClock.elapsedRealtime() >= until || n >= MAX_FRAMES) { done(n, frames, "OBSERVED"); return; }
        session.checkpoint("OBSERVE");
        session.capture("observe").whenComplete((screen, error) -> {
            if (error != null) { done(n, frames, "OBSERVED_PARTIAL"); return; }
            JSONArray lines = new JSONArray();
            for (VisualScreen.Line line : screen.lines) {
                if (lines.length() >= MAX_LINES) break;
                lines.put(CoordinatorAgent.object("text", line.text, "top", line.bounds.top, "left", line.bounds.left));
            }
            frames.put(CoordinatorAgent.object("frame", n, "image", session.lastImage(), "at_ms", System.currentTimeMillis(), "lines", lines));
            session.delay(INTERVAL_MS).whenComplete((v, e) -> { if (e == null) frame(n + 1, frames); else done(n + 1, frames, "OBSERVED_PARTIAL"); });
        });
    }
    private void done(int count, JSONArray frames, String detail) {
        session.put("observe", CoordinatorAgent.object("count", count, "frames", frames));
        session.put("verification_detail", "Observed " + count + " frames; no taps, typing or navigation");
        session.finish("PASS", detail);
    }
}
