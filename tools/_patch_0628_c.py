"""Patch CoordinatorAgent: progress, keepalive, stage inactivity + absolute timeout."""
from pathlib import Path

p = Path('android/Bet365Agent/app/src/main/java/com/bet365agent/CoordinatorAgent.java')
text = p.read_text(encoding='utf-8')

# Add progress/timeout fields after sessionRefresh
old = '''    private final Runnable sessionRefresh = this::refreshSession;

    CoordinatorAgent(AccessibilityService service, VisualControlRunner runner) {'''

new = '''    private final Runnable sessionRefresh = this::refreshSession;
    /** Absolute backstop comes from instruction.timeout_ms; inactivity fails closed sooner. */
    private static final long STAGE_INACTIVITY_MS = 45_000L;
    private static final long PROGRESS_TICK_MS = 2_000L;
    private volatile String progressInstructionId;
    private volatile String progressStage = "IDLE";
    private volatile long progressElapsedMs;
    private volatile long lastProgressAtElapsed;
    private volatile long lastProgressWallMs;
    private org.json.JSONArray progressStages = new org.json.JSONArray();
    private Runnable deadlineWatch;

    CoordinatorAgent(AccessibilityService service, VisualControlRunner runner) {'''

if old not in text:
    raise SystemExit('fields insert point missing')
text = text.replace(old, new, 1)

# Replace execute()'s hard deadline block
old_exec = '''    private void execute(CoordinatorInstruction instruction) {
        JSONObject row = store.get(instruction.id);
        if (closed || row == null || !row.isNull("result")) return;
        long remaining = remaining(row, instruction.timeout);
        if (remaining < 100) { complete(row, "TIMEOUT", "Deadline expired before dispatch"); return; }
        main.postDelayed(() -> {
            JSONObject current = store.get(instruction.id);
            if (current != null && current.isNull("result")) {
                runner.finish(instruction.runId, "TIMEOUT", "Coordinator hard deadline expired");
                complete(current, "TIMEOUT", "Coordinator hard deadline expired");
            }
        }, remaining);
        try {
            PowerManager power = (PowerManager) service.getSystemService(android.content.Context.POWER_SERVICE);
            KeyguardManager keyguard = (KeyguardManager) service.getSystemService(android.content.Context.KEYGUARD_SERVICE);
            // Best-effort screen wake (no ADB): ACQUIRE_CAUSES_WAKEUP. Unlock still required if keyguard is secure.
            try {
                if (power != null && !power.isInteractive()) {
                    @SuppressWarnings("deprecation")
                    PowerManager.WakeLock wake = power.newWakeLock(
                        PowerManager.SCREEN_BRIGHT_WAKE_LOCK | PowerManager.ACQUIRE_CAUSES_WAKEUP | PowerManager.ON_AFTER_RELEASE,
                        "bet365agent:instruction");
                    wake.acquire(4000L);
                    try { Thread.sleep(250); } catch (InterruptedException ignored) {}
                    if (wake.isHeld()) wake.release();
                }
            } catch (Exception ignored) {}
            if (power == null || !power.isInteractive()) { complete(row, "FOCUS_FAILED", "Phone must be awake and unlocked"); return; }
            store.executing(instruction.id);
            if(instruction.action.equals("ADAPTER_WORKFLOW") || instruction.action.equals("SESSION_CHECK") || instruction.action.equals("SESSION_PROBE") || instruction.action.equals("OPEN_SEARCH")) {
                if(!runner.startExternal(instruction.runId,remaining(row,instruction.timeout))) {complete(row,"INTERNAL_ERROR","Runner rejected workflow");return;}
                VisualSession session=new VisualSession(service,runner,instruction.runId,instruction.adapter);
                if(instruction.action.equals("SESSION_PROBE")) { new SessionProbeWorkflow(session).start(); return; }
                SiteAdapter adapter=SiteAdapters.create(instruction.adapter,session,endpoint(),instruction.scenario,instruction.id,instruction.sport,instruction.stake);
                if(instruction.action.equals("SESSION_CHECK")) new SessionCheckWorkflow(session,adapter).start();
                else if(instruction.action.equals("OPEN_SEARCH")) new SearchOpenWorkflow(session,adapter,instruction.text).start();
                else new AdapterWorkflow(session,adapter).start(instruction.text,instruction.market,instruction.side,instruction.line,instruction.minimumPrice,instruction.stake,instruction.executionMode,instruction.confirmationStatus);
                return;
            }'''

new_exec = '''    private void execute(CoordinatorInstruction instruction) {
        JSONObject row = store.get(instruction.id);
        if (closed || row == null || !row.isNull("result")) return;
        long remaining = remaining(row, instruction.timeout);
        if (remaining < 100) { complete(row, "TIMEOUT", "Deadline expired before dispatch"); return; }
        armDeadlineWatch(instruction);
        try {
            PowerManager power = (PowerManager) service.getSystemService(android.content.Context.POWER_SERVICE);
            KeyguardManager keyguard = (KeyguardManager) service.getSystemService(android.content.Context.KEYGUARD_SERVICE);
            // Best-effort screen wake (no ADB): ACQUIRE_CAUSES_WAKEUP. Unlock still required if keyguard is secure.
            try {
                if (power != null && !power.isInteractive()) {
                    @SuppressWarnings("deprecation")
                    PowerManager.WakeLock wake = power.newWakeLock(
                        PowerManager.SCREEN_BRIGHT_WAKE_LOCK | PowerManager.ACQUIRE_CAUSES_WAKEUP | PowerManager.ON_AFTER_RELEASE,
                        "bet365agent:instruction");
                    wake.acquire(4000L);
                    try { Thread.sleep(250); } catch (InterruptedException ignored) {}
                    if (wake.isHeld()) wake.release();
                }
            } catch (Exception ignored) {}
            if (power == null || !power.isInteractive()) { complete(row, "FOCUS_FAILED", "Phone must be awake and unlocked"); return; }
            // Phase C: refresh session observation immediately before starting a device job.
            preJobSessionRefresh();
            store.executing(instruction.id);
            if(instruction.action.equals("ADAPTER_WORKFLOW") || instruction.action.equals("SESSION_CHECK") || instruction.action.equals("SESSION_PROBE") || instruction.action.equals("OPEN_SEARCH")) {
                if(!runner.startExternal(instruction.runId,remaining(row,instruction.timeout))) {complete(row,"INTERNAL_ERROR","Runner rejected workflow");return;}
                VisualSession session=new VisualSession(service,runner,instruction.runId,instruction.adapter);
                session.setProgressListener(this::onWorkflowProgress);
                noteProgress(instruction.id, "STARTED", 0, null);
                if(instruction.action.equals("SESSION_PROBE")) { new SessionProbeWorkflow(session).start(); return; }
                SiteAdapter adapter=SiteAdapters.create(instruction.adapter,session,endpoint(),instruction.scenario,instruction.id,instruction.sport,instruction.stake);
                if(instruction.action.equals("SESSION_CHECK")) new SessionCheckWorkflow(session,adapter).start();
                else if(instruction.action.equals("OPEN_SEARCH")) new SearchOpenWorkflow(session,adapter,instruction.text).start();
                else new AdapterWorkflow(session,adapter).start(instruction.text,instruction.market,instruction.side,instruction.line,instruction.minimumPrice,instruction.stake,instruction.executionMode,instruction.confirmationStatus);
                return;
            }'''

if old_exec not in text:
    raise SystemExit('execute block not found')
text = text.replace(old_exec, new_exec, 1)

# Insert helper methods before remaining()
old_rem = '''    private long remaining(JSONObject row, int timeout) { return timeout - (SystemClock.elapsedRealtime() - row.optLong("received_elapsed")); }'''

helpers = '''    private void armDeadlineWatch(CoordinatorInstruction instruction) {
        if (deadlineWatch != null) main.removeCallbacks(deadlineWatch);
        lastProgressAtElapsed = SystemClock.elapsedRealtime();
        lastProgressWallMs = System.currentTimeMillis();
        progressInstructionId = instruction.id;
        progressStage = "STARTED";
        progressElapsedMs = 0;
        progressStages = new JSONArray();
        deadlineWatch = new Runnable() {
            @Override public void run() {
                if (closed) return;
                JSONObject current = store.get(instruction.id);
                if (current == null || !current.isNull("result")) return;
                long absLeft = remaining(current, instruction.timeout);
                if (absLeft < 100) {
                    runner.finish(instruction.runId, "TIMEOUT", "Absolute deadline expired");
                    complete(current, "TIMEOUT", "Absolute deadline expired after " + instruction.timeout + "ms");
                    return;
                }
                long idle = SystemClock.elapsedRealtime() - lastProgressAtElapsed;
                if (idle > STAGE_INACTIVITY_MS) {
                    String detail = "Stage inactivity timeout: " + progressStage + " idle " + idle + "ms (limit " + STAGE_INACTIVITY_MS + "ms)";
                    runner.finish(instruction.runId, "TIMEOUT", detail);
                    complete(current, "TIMEOUT", detail);
                    return;
                }
                main.postDelayed(this, PROGRESS_TICK_MS);
            }
        };
        main.postDelayed(deadlineWatch, PROGRESS_TICK_MS);
    }

    private void onWorkflowProgress(String stage, long elapsedMs, JSONObject timing) {
        noteProgress(progressInstructionId, stage, elapsedMs, timing);
        // When ENSURE_SESSION / SESSION_CHECK reports AUTHENTICATED via record, noteSession is called from complete path;
        // also treat workflow progress as keepalive for an already AUTHENTICATED session.
        synchronized (sessionLock) {
            if ("AUTHENTICATED".equals(sessionState)) {
                sessionObservedAtMs = System.currentTimeMillis();
                sessionDetail = "job-active progress keepalive @" + stage;
            }
        }
    }

    private synchronized void noteProgress(String instructionId, String stage, long elapsedMs, JSONObject timing) {
        if (instructionId == null) return;
        progressInstructionId = instructionId;
        if (stage != null && !stage.isEmpty()) progressStage = stage;
        progressElapsedMs = elapsedMs;
        lastProgressAtElapsed = SystemClock.elapsedRealtime();
        lastProgressWallMs = System.currentTimeMillis();
        try {
            JSONObject ev = object(
                "stage", progressStage,
                "elapsed_ms", elapsedMs,
                "at_ms", lastProgressWallMs);
            if (timing != null) ev.put("timing", timing);
            progressStages.put(ev);
            // Cap memory
            if (progressStages.length() > 80) {
                JSONArray trimmed = new JSONArray();
                for (int i = progressStages.length() - 60; i < progressStages.length(); i++) trimmed.put(progressStages.get(i));
                progressStages = trimmed;
            }
        } catch (Exception ignored) {}
        Log.i("AgentCoordinator", "PROGRESS id=" + instructionId + " stage=" + progressStage + " elapsed_ms=" + elapsedMs);
    }

    private void preJobSessionRefresh() {
        synchronized (sessionLock) {
            if ("AUTHENTICATED".equals(sessionState)) {
                sessionObservedAtMs = System.currentTimeMillis();
                sessionDetail = "pre-job session refresh (held AUTHENTICATED; on-screen ENSURE_SESSION follows)";
            } else {
                sessionDetail = (sessionDetail == null ? "" : sessionDetail) + "; pre-job without AUTHENTICATED";
            }
        }
    }

    private JSONObject progressSnapshot() {
        return object(
            "stage", progressStage,
            "elapsed_ms", progressElapsedMs,
            "last_progress_at_ms", lastProgressWallMs,
            "instruction_id", progressInstructionId == null ? JSONObject.NULL : progressInstructionId,
            "stages", progressStages);
    }

    private long remaining(JSONObject row, int timeout) { return timeout - (SystemClock.elapsedRealtime() - row.optLong("received_elapsed")); }'''

if old_rem not in text:
    raise SystemExit('remaining() not found')
text = text.replace(old_rem, helpers, 1)

# Update acknowledgement to include progress
old_ack = '''    private JSONObject acknowledgement(JSONObject row) {
        return object("instruction_id", row.optString("instruction_id"), "acknowledged", true,
            "state", row.optString("state"), "received_at_ms", row.optLong("received_ms"),
            "result_url", "/instructions/" + row.optString("instruction_id"), "execution_count", row.optInt("execution_count"));
    }'''

new_ack = '''    private JSONObject acknowledgement(JSONObject row) {
        JSONObject ack = object("instruction_id", row.optString("instruction_id"), "acknowledged", true,
            "state", row.optString("state"), "received_at_ms", row.optLong("received_ms"),
            "result_url", "/instructions/" + row.optString("instruction_id"), "execution_count", row.optInt("execution_count"));
        if (row.isNull("result") && progressInstructionId != null && progressInstructionId.equals(row.optString("instruction_id"))) {
            put(ack, "progress", progressSnapshot());
            put(ack, "device_stage", progressStage);
        }
        return ack;
    }'''

if old_ack not in text:
    raise SystemExit('acknowledgement not found')
text = text.replace(old_ack, new_ack, 1)

# Update health to include progress
old_health_return = '''        return object("healthy", !closed).put("heartbeat_ms", System.currentTimeMillis()).put("uptime_ms", SystemClock.elapsedRealtime() - boot)
            .put("state", active == null ? "IDLE" : active.optString("state"))
            .put("current_instruction", active == null ? JSONObject.NULL : active.getJSONObject("payload"))
            .put("last_result", last == null ? JSONObject.NULL : last.getJSONObject("result"))
            .put("app_version", pkg.versionName).put("version_code", pkg.versionCode)
            .put("endpoint", endpoint() == null ? JSONObject.NULL : endpoint()).put("pid", android.os.Process.myPid())
            .put("device_id", DEVICE_ID).put("session", session);
    }'''

new_health_return = '''        JSONObject health = object("healthy", !closed).put("heartbeat_ms", System.currentTimeMillis()).put("uptime_ms", SystemClock.elapsedRealtime() - boot)
            .put("state", active == null ? "IDLE" : active.optString("state"))
            .put("current_instruction", active == null ? JSONObject.NULL : active.getJSONObject("payload"))
            .put("last_result", last == null ? JSONObject.NULL : last.getJSONObject("result"))
            .put("app_version", pkg.versionName).put("version_code", pkg.versionCode)
            .put("endpoint", endpoint() == null ? JSONObject.NULL : endpoint()).put("pid", android.os.Process.myPid())
            .put("device_id", DEVICE_ID).put("session", session);
        if (active != null) {
            put(health, "progress", progressSnapshot());
            put(health, "device_stage", progressStage);
        }
        return health;
    }'''

if old_health_return not in text:
    raise SystemExit('health return not found')
text = text.replace(old_health_return, new_health_return, 1)

# Fix refreshSession mid-instruction UNKNOWN race
old_mid = '''            } else if (store.active() != null) {
                // Mid-instruction: do not steal screenshots; fail closed rather than reuse a stale AUTHENTICATED claim.
                noteSession("UNKNOWN", "instruction active; deferred on-screen session check");
            } else {'''

new_mid = '''            } else if (store.active() != null) {
                // Mid-instruction: do not steal screenshots / runner. Keep AUTHENTICATED fresh via keepalive
                // so pipeline session_max_age (120s) does not race SESSION_REQUIRED while a job is active.
                // Do NOT flip to UNKNOWN here (that caused tips queued during jobs to die as SESSION_REQUIRED).
                synchronized (sessionLock) {
                    if ("AUTHENTICATED".equals(sessionState)) {
                        sessionObservedAtMs = System.currentTimeMillis();
                        sessionDetail = "job-active session keepalive (on-screen probe deferred)";
                    }
                    // Non-AUTHENTICATED mid-job: leave state unchanged (fail closed for new dispatches).
                }
            } else {'''

if old_mid not in text:
    raise SystemExit('mid-instruction session branch not found')
text = text.replace(old_mid, new_mid, 1)

# On complete, clear deadline watch + copy progress into result
old_complete_start = '''    private synchronized void complete(JSONObject row, String stage, String detail) {
        String id = row.optString("instruction_id"); JSONObject current = store.get(id);
        if (current == null || !current.isNull("result")) return;
        JSONObject result = result(id, stage, detail, Math.max(0, System.currentTimeMillis() - current.optLong("received_ms")));'''

new_complete_start = '''    private synchronized void complete(JSONObject row, String stage, String detail) {
        String id = row.optString("instruction_id"); JSONObject current = store.get(id);
        if (current == null || !current.isNull("result")) return;
        if (deadlineWatch != null) { main.removeCallbacks(deadlineWatch); deadlineWatch = null; }
        JSONObject result = result(id, stage, detail, Math.max(0, System.currentTimeMillis() - current.optLong("received_ms")));
        put(result, "progress", progressSnapshot());
        put(result, "device_stage", progressStage);'''

if old_complete_start not in text:
    raise SystemExit('complete start not found')
text = text.replace(old_complete_start, new_complete_start, 1)

# After workflow complete, if proof has session AUTHENTICATED, already handled.
# Clear progressInstructionId at end of complete before release
old_store_complete = '''        store.complete(id, result);
        runner.releaseReservation(current.optString("run_id"));
        Log.i("AgentCoordinator", "RESULT " + result);
    }'''

new_store_complete = '''        store.complete(id, result);
        runner.releaseReservation(current.optString("run_id"));
        if (id.equals(progressInstructionId)) {
            progressInstructionId = null;
            progressStage = "IDLE";
        }
        Log.i("AgentCoordinator", "RESULT " + result);
    }'''

if old_store_complete not in text:
    raise SystemExit('store.complete tail not found')
text = text.replace(old_store_complete, new_store_complete, 1)

# Need JSONArray import - check if org.json.JSONObject is imported (JSONArray via full name used)
# We used JSONArray and new JSONArray() - need import
if 'import org.json.JSONArray' not in text and 'import org.json.JSONObject' in text:
    text = text.replace('import org.json.JSONObject;', 'import org.json.JSONArray;\nimport org.json.JSONObject;', 1)

p.write_text(text, encoding='utf-8')
print('OK CoordinatorAgent', len(text))
