"""Patch MultiBot365 agent+pipeline for stage timeouts, progress heartbeats, session keepalive (0.6.28-stage)."""
from pathlib import Path
import re

ROOT = Path('.')

def write(rel, text):
    p = ROOT / rel
    p.write_text(text, encoding='utf-8', newline='\n')
    print('WROTE', rel, 'bytes', len(text.encode()))

def patch_file(rel, replacements):
    p = ROOT / rel
    text = p.read_text(encoding='utf-8')
    for i, (old, new) in enumerate(replacements):
        if old not in text:
            raise SystemExit(f'MISSING pattern {i} in {rel}:\n{old[:120]!r}')
        text = text.replace(old, new, 1)
    p.write_text(text, encoding='utf-8', newline='\n' if '\r' not in p.read_bytes().decode('utf-8', 'ignore')[:200] else None)
    # normalize to utf-8 with original newlines style
    print('PATCHED', rel)

# ---------- VisualSession.java ----------
vs = (ROOT / 'android/Bet365Agent/app/src/main/java/com/bet365agent/VisualSession.java').read_text(encoding='utf-8')

old_fields = '''    private boolean done;
    private int sequence;
    VisualSession(AccessibilityService service,VisualControlRunner runner,String id,String adapter) {
        this.service=service;this.runner=runner;this.id=id;
        record=CoordinatorAgent.object("run_id",id,"adapter",adapter,"status","RUNNING","phase","STARTED","started_at_ms",System.currentTimeMillis(),"events",events,"screenshots",images,"gesture_attempts",0);
        checkpoint("STARTED");
        runner.setTerminalObserver((run,status,detail)->terminated(status,detail));
    }'''

new_fields = '''    private boolean done;
    private int sequence;
    private ProgressListener progressListener;
    private String activeStage = "STARTED";
    private long stageStartedElapsed = 0;
    private final JSONArray stageTimings = new JSONArray();
    interface ProgressListener { void onProgress(String stage, long elapsedMs, JSONObject timing); }
    void setProgressListener(ProgressListener listener) { this.progressListener = listener; }
    VisualSession(AccessibilityService service,VisualControlRunner runner,String id,String adapter) {
        this.service=service;this.runner=runner;this.id=id;
        record=CoordinatorAgent.object("run_id",id,"adapter",adapter,"status","RUNNING","phase","STARTED","started_at_ms",System.currentTimeMillis(),"events",events,"screenshots",images,"gesture_attempts",0,"stage_timings",stageTimings);
        stageStartedElapsed = SystemClock.elapsedRealtime();
        checkpoint("STARTED");
        runner.setTerminalObserver((run,status,detail)->terminated(status,detail));
    }'''

if old_fields not in vs:
    raise SystemExit('VisualSession fields block not found')
vs = vs.replace(old_fields, new_fields, 1)

old_cp = '''    void checkpoint(String phase) {
        put("phase",phase);events.put(CoordinatorAgent.object("phase",phase,"elapsed_ms",SystemClock.elapsedRealtime()-started));persist(file(service,id),record);
    }'''

new_cp = '''    void checkpoint(String phase) {
        long nowElapsed = SystemClock.elapsedRealtime();
        long elapsed = nowElapsed - started;
        // Close prior stage timing when moving to a new named workflow stage.
        if (phase != null && !phase.equals(activeStage) && isWorkflowStage(phase)) {
            closeStage(nowElapsed, "ok");
            activeStage = phase;
            stageStartedElapsed = nowElapsed;
            JSONObject startEv = CoordinatorAgent.object(
                "stage", phase,
                "start_elapsed_ms", elapsed,
                "start_ts_ms", System.currentTimeMillis(),
                "end_elapsed_ms", JSONObject.NULL,
                "end_ts_ms", JSONObject.NULL,
                "duration_ms", JSONObject.NULL,
                "status", "running",
                "retries", 0);
            stageTimings.put(startEv);
            put("current_stage", phase);
            put("stage_timings", stageTimings);
        }
        put("phase",phase);
        events.put(CoordinatorAgent.object("phase",phase,"elapsed_ms",elapsed,"wall_ts_ms",System.currentTimeMillis()));
        persist(file(service,id),record);
        if (progressListener != null && isWorkflowStage(phase)) {
            JSONObject snap = stageTimings.length() == 0 ? null : stageTimings.optJSONObject(stageTimings.length()-1);
            progressListener.onProgress(phase, elapsed, snap);
        } else if (progressListener != null) {
            progressListener.onProgress(phase, elapsed, null);
        }
    }
    private static boolean isWorkflowStage(String phase) {
        if (phase == null) return false;
        return java.util.Set.of(
            "STARTED","SESSION_CHECK","SPORTS_HOME","SPORTS_CONTEXT","OPEN_SEARCH","FOCUS",
            "ENTER_QUERY","QUERY_VERIFY","RESULTS_WAIT","FIXTURE_VERIFY","MARKET_NAV",
            "OPEN_HOME","ENSURE_SESSION","DISCOVER_FIXTURE","SELECT_FIXTURE","VERIFY_EVENT",
            "DISCOVER_MARKETS","READ_SELECTION","READ_LINE","READ_PRICE","OPEN_SELECTION",
            "ENTER_STAKE","VERIFY_FINAL_STATE","PREPARE_COMPLETE_EXECUTION","PLACE_BET"
        ).contains(phase);
    }
    private void closeStage(long nowElapsed, String status) {
        if (stageTimings.length() == 0) return;
        JSONObject last = stageTimings.optJSONObject(stageTimings.length()-1);
        if (last == null || !last.isNull("end_elapsed_ms")) return;
        try {
            long startEl = last.optLong("start_elapsed_ms", stageStartedElapsed - started);
            last.put("end_elapsed_ms", nowElapsed - started);
            last.put("end_ts_ms", System.currentTimeMillis());
            last.put("duration_ms", Math.max(0, (nowElapsed - started) - startEl));
            last.put("status", status);
        } catch (JSONException e) { throw new IllegalStateException(e); }
    }
    void bumpStageRetry(String stage) {
        if (stageTimings.length() == 0) return;
        JSONObject last = stageTimings.optJSONObject(stageTimings.length()-1);
        if (last == null) return;
        if (!stage.equals(last.optString("stage"))) return;
        try { last.put("retries", last.optInt("retries", 0) + 1); } catch (JSONException e) { throw new IllegalStateException(e); }
        persist(file(service,id),record);
    }'''

if old_cp not in vs:
    raise SystemExit('checkpoint block not found')
vs = vs.replace(old_cp, new_cp, 1)

# Ensure finish closes last stage
old_finish_put = 'put("status",status.equals("INTERRUPTED")?"INTERNAL_ERROR":status);put("detail",detail);put("duration_ms",SystemClock.elapsedRealtime()-started'
if old_finish_put not in vs:
    # find finish method
    m = re.search(r'void finish\(String status,String detail\)', vs)
    print('finish search', bool(m))
    idx = vs.find('put("status",status.equals("INTERRUPTED")')
    print('idx', idx, vs[idx:idx+200] if idx>=0 else 'NONE')
    raise SystemExit('finish put not found')

vs = vs.replace(
    'put("status",status.equals("INTERRUPTED")?"INTERNAL_ERROR":status);put("detail",detail);put("duration_ms",SystemClock.elapsedRealtime()-started',
    'closeStage(SystemClock.elapsedRealtime(), status.equals("PASS")?"ok":"fail");put("stage_timings",stageTimings);put("status",status.equals("INTERRUPTED")?"INTERNAL_ERROR":status);put("detail",detail);put("duration_ms",SystemClock.elapsedRealtime()-started',
    1)

(ROOT / 'android/Bet365Agent/app/src/main/java/com/bet365agent/VisualSession.java').write_text(vs, encoding='utf-8')
print('OK VisualSession')
