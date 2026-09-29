package com.bet365agent;

import android.accessibilityservice.AccessibilityService;
import android.app.KeyguardManager;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.os.SystemClock;
import android.util.Log;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Set;

/** Durable coordinator admission and results, adapting to the already-proven phone text runner. */
final class CoordinatorAgent implements AutoCloseable {
    private final AccessibilityService service;
    private final VisualControlRunner runner;
    private final CoordinatorStore store;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final CoordinatorHttp http;
    private final WorkerHealth workerHealth;
    private final long boot = SystemClock.elapsedRealtime();
    private volatile boolean closed;
    private static final String DEVICE_ID = "galaxy-a13-5g";
    private static final long SESSION_REFRESH_MS = 60_000L;
    private final Object sessionLock = new Object();
    private volatile String sessionState = "UNKNOWN";
    private volatile long sessionObservedAtMs = System.currentTimeMillis();
    private volatile String sessionDetail = "not checked yet";
    private final Runnable sessionRefresh = this::refreshSession;
    /** Session refresh runs on its own thread so a busy main looper can never freeze observed_at. */
    private final android.os.HandlerThread sessionThread = new android.os.HandlerThread("agent-session");
    private final Handler sessionHandler;
    private volatile long lastRefreshAtMs;
    private volatile String lastRefreshOutcome = "never";
    private volatile int refreshCount;
    /** Phone-side cap for any final-action stake, independent of the backend limits. */
    private static final String DEFAULT_MAX_STAKE = "1.00";
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

    CoordinatorAgent(AccessibilityService service, VisualControlRunner runner) {
        this.service = service; this.runner = runner;
        workerHealth = new WorkerHealth(service);
        runner.warmFastEngine();   // no-op under legacy; otherwise the model is loaded before the first live capture
        sessionThread.start();
        sessionHandler = new Handler(sessionThread.getLooper());
        CoordinatorConfig.token(service);
        store = new CoordinatorStore(service);
        // Reconcile already durable text results, but never replay unfinished work.
        for (JSONObject row : store.unfinished()) {
            JSONObject evidence = evidence(row);
            String status = evidence == null ? "INTERRUPTED" : evidence.optString("status", "INTERRUPTED");
            if (status.equals("RUNNING")) {
                status = "INTERRUPTED";
                if(row.optJSONObject("payload").optString("action").equals("ADAPTER_WORKFLOW")) {
                    put(evidence,"status","INTERNAL_ERROR");put(evidence,"detail","Process restarted; workflow not replayed");
                    VisualSession.persist(VisualSession.file(service,row.optString("run_id")),evidence);
                }
            }
            complete(row, stage(status), status.equals("INTERRUPTED") ? "Process restarted; uncertain instruction was not replayed" : evidence.optString("detail"));
        }
        runner.setResultListener(this::runnerFinished);
        http = new CoordinatorHttp(this);
        sessionHandler.post(sessionRefresh);
    }
    String token() { return CoordinatorConfig.token(service); }
    String endpoint() { return http.endpoint(); }
    private volatile long diagnosticsUntilElapsed;
    private boolean diagnosticsActive() { return android.os.SystemClock.elapsedRealtime() < diagnosticsUntilElapsed; }

    CoordinatorHttp.Reply route(String method, String path, String body) throws Exception {
        if (method.equals("GET") && Set.of("/neutral/text.html", "/neutral/simulator.html").contains(path.split("\\?", 2)[0])) {
            try (java.io.InputStream in = service.getAssets().open(path.split("\\?", 2)[0].substring(1))) {
                java.io.ByteArrayOutputStream bytes = new java.io.ByteArrayOutputStream(); byte[] buffer = new byte[4096]; int n;
                while ((n = in.read(buffer)) != -1) bytes.write(buffer, 0, n);
                return new CoordinatorHttp.Reply(200, "text/html; charset=utf-8", bytes.toByteArray());
            }
        }
        if (method.equals("GET") && (path.equals("/health") || path.equals("/state"))) return json(200, health());
        if (method.equals("POST") && path.equals("/instructions")) return accept(body);
        if (method.equals("POST") && path.equals("/diagnostics")) {
            int seconds = new JSONObject(body).getInt("seconds");
            if (seconds < 0 || seconds > 1800) return error(400, "", "INVALID_INSTRUCTION", "seconds must be 0..1800");
            diagnosticsUntilElapsed = android.os.SystemClock.elapsedRealtime() + seconds * 1000L;
            return json(200, object("diagnostics_active", diagnosticsActive(), "seconds", seconds));
        }
        if (method.equals("POST") && path.equals("/config/ocr_engine") && (service.getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0) {
            // Milestone C3 feature flag (debug builds only): legacy | fast | hybrid. Rollback = one call.
            String engine = "";
            try { engine = new JSONObject(body).optString("engine", ""); } catch (Exception ignored) {}
            if (!CoordinatorConfig.setOcrEngine(service, engine)) return error(400, "", "INVALID_INSTRUCTION", "engine must be legacy|fast|hybrid");
            runner.warmFastEngine();
            return json(200, object("ocr_engine", CoordinatorConfig.ocrEngine(service)));
        }
        if (method.equals("POST") && path.equals("/test/restart") && (service.getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0) {
            CoordinatorHttp.Reply reply = json(202, object("acknowledged", true));
            reply.afterWrite = () -> main.postDelayed(() -> android.os.Process.killProcess(android.os.Process.myPid()), 250);
            return reply;
        }
        String[] parts = path.split("/", -1);
        if (method.equals("GET") && parts.length >= 3 && parts[1].equals("instructions") && parts[2].matches("[A-Za-z0-9_-]{1,64}")) {
            JSONObject row = store.get(parts[2]);
            if (row == null) return error(404, parts[2], "INVALID_INSTRUCTION", "Unknown instruction ID");
            if (parts.length == 3) return json(row.isNull("result") ? 202 : 200, row.isNull("result") ? acknowledgement(row) : row.getJSONObject("result"));
            if (parts.length == 4 && parts[3].equals("evidence")) {
                JSONObject evidence = evidence(row);
                return evidence == null ? error(404, parts[2], "INTERNAL_ERROR", "No text evidence yet") : json(200, evidence);
            }
            if (parts.length == 5 && parts[3].equals("artifacts") && (Set.of("before.png", "after.png", "focused.png", "field_after.png", "before.txt", "after.txt", "focused.txt").contains(parts[4]) || parts[4].matches("s[0-9]{3}_[a-z_]+\\.(png|txt)"))) {
                File file = new File(service.getFilesDir(), "visual/" + row.getString("run_id") + "/" + parts[4]);
                if (file.isFile()) return new CoordinatorHttp.Reply(200, parts[4].endsWith("png") ? "image/png" : "text/plain; charset=utf-8", Files.readAllBytes(file.toPath()));
                return error(404, parts[2], "INTERNAL_ERROR", "Artifact not captured");
            }
        }
        return error(404, "", "INVALID_INSTRUCTION", "Unknown endpoint or method");
    }

    private synchronized CoordinatorHttp.Reply accept(String body) {
        CoordinatorInstruction instruction;
        try { instruction = new CoordinatorInstruction(body); }
        catch (Exception e) { return error(400, "", "INVALID_INSTRUCTION", "Schema validation failed: " + e.getMessage()); }
        JSONObject old = store.get(instruction.id);
        if (old != null) {
            JSONObject duplicate = result(instruction.id, "DUPLICATE", "Instruction ID has already been accepted; no action repeated", 0);
            put(duplicate, "result_url", "/instructions/" + instruction.id);
            put(duplicate, "execution_count", old.optInt("execution_count"));
            return json(409, duplicate);
        }
        if (instruction.action.equals("PLACE_HELD")) {
            try { HeldInstruction.verify(instruction.payload, store.get(instruction.heldInstructionId)); }
            catch (Exception e) { return error(400, instruction.id, "INVALID_INSTRUCTION", e.getMessage()); }
        }
        if (instruction.placeBet) {
            if (!"PLACE_HELD".equals(instruction.action)) return error(400, instruction.id, "INVALID_INSTRUCTION", "Final actions require the original verified hold");
            if (diagnosticsActive()) return error(400, instruction.id, "INVALID_INSTRUCTION", "Diagnostics lease prohibits final actions");
            if (!CoordinatorConfig.finalActionArmed(service)) return error(400, instruction.id, "INVALID_INSTRUCTION", "PHONE_DISARMED: local arming required");
            try {
                java.math.BigDecimal cap = new java.math.BigDecimal(CoordinatorConfig.prefs(service).getString("max_stake", DEFAULT_MAX_STAKE));
                if (new java.math.BigDecimal(instruction.stake).compareTo(cap) > 0)
                    return error(400, instruction.id, "INVALID_INSTRUCTION", "STAKE_CAP_EXCEEDED: stake " + instruction.stake + " above phone cap " + cap.toPlainString());
            } catch (NumberFormatException e) {
                return error(400, instruction.id, "INVALID_INSTRUCTION", "STAKE_CAP_EXCEEDED: unreadable stake or cap");
            }
        }
        if (closed || store.active() != null || !runner.reserve(instruction.runId)) return error(409, instruction.id, "INTERNAL_ERROR", "BUSY: one instruction at a time; ID not consumed");
        try { store.accept(instruction); }
        catch (Exception e) { runner.releaseReservation(instruction.runId); return error(500, instruction.id, "INTERNAL_ERROR", "Could not persist receipt; no action started"); }
        JSONObject row = store.get(instruction.id);
        Log.i("AgentCoordinator", "ACCEPTED id=" + instruction.id);
        CoordinatorHttp.Reply reply = json(202, acknowledgement(row));
        reply.afterWrite = () -> main.post(() -> execute(instruction));
        return reply;
    }

    private void execute(CoordinatorInstruction instruction) {
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
            if(instruction.action.equals("ADAPTER_WORKFLOW") || instruction.action.equals("SESSION_CHECK") || instruction.action.equals("SESSION_PROBE") || instruction.action.equals("OPEN_SEARCH") || instruction.action.equals("MY_BETS") || instruction.action.equals("OBSERVE") || instruction.action.equals("RESET_BETSLIP") || instruction.action.equals("PLACE_HELD") || instruction.action.equals("OCR_BENCH")) {
                if(!runner.startExternal(instruction.runId,remaining(row,instruction.timeout))) {complete(row,"INTERNAL_ERROR","Runner rejected workflow");return;}
                VisualSession session=new VisualSession(service,runner,instruction.runId,instruction.adapter);
                session.setProgressListener(this::onWorkflowProgress);
                noteProgress(instruction.id, "STARTED", 0, null);
                if(instruction.action.equals("SESSION_PROBE")) { new SessionProbeWorkflow(session).start(); return; }
                if(instruction.action.equals("OBSERVE")) { new ObserveWorkflow(session, remaining(row,instruction.timeout)).start(); return; }
                if(instruction.action.equals("OCR_BENCH")) {
                    new OcrBenchWorkflow(session, service.getFilesDir(), runner, instruction.frames, instruction.engine).start();
                    return;
                }
                if(instruction.action.equals("PLACE_HELD")) {
                    SiteAdapter mine=SiteAdapters.create(instruction.adapter,session,endpoint(),instruction.scenario,instruction.id,instruction.sport,instruction.stake);
                    if(!(mine instanceof Bet365LiveAdapter)) { runner.finish(instruction.runId,"INVALID_INSTRUCTION","PLACE_HELD requires the live adapter"); return; }
                    JSONObject held = store.get(instruction.heldInstructionId);
                    JSONObject context = HeldInstruction.verify(instruction.payload, held);
                    ((Bet365LiveAdapter)mine).set_held_context(context);
                    new PlaceHeldWorkflow(session,(Bet365LiveAdapter)mine).start(instruction.market,instruction.side,instruction.line,
                            instruction.selectionName,instruction.price,instruction.minimumPrice,instruction.stake,instruction.executionMode);
                    return;
                }
                if(instruction.action.equals("RESET_BETSLIP")) {
                    SiteAdapter mine=SiteAdapters.create(instruction.adapter,session,endpoint(),instruction.scenario,instruction.id,"football","0.00");
                    if(!(mine instanceof Bet365LiveAdapter)) { runner.finish(instruction.runId,"INVALID_INSTRUCTION","RESET_BETSLIP requires the live adapter"); return; }
                    ((Bet365LiveAdapter)mine).reset_now().whenComplete((v,error)->{
                        if(error==null){ session.put("verification_detail","Betslip/receipt reset on the current screen; whitelisted controls only"); session.finish("PASS","RESET_BETSLIP"); }
                        else session.finish("INTERNAL_ERROR",String.valueOf(error));
                    });
                    return;
                }
                if(instruction.action.equals("MY_BETS")) {
                    SiteAdapter mine=SiteAdapters.create(instruction.adapter,session,endpoint(),instruction.scenario,instruction.id,"football","0.00");
                    if(!(mine instanceof Bet365LiveAdapter)) { runner.finish(instruction.runId,"INVALID_INSTRUCTION","MY_BETS requires the live adapter"); return; }
                    new MyBetsWorkflow(session,(Bet365LiveAdapter)mine,instruction.view).start();
                    return;
                }
                SiteAdapter adapter=SiteAdapters.create(instruction.adapter,session,endpoint(),instruction.scenario,instruction.id,instruction.sport,instruction.stake);
                adapter.set_aliases(instruction.aliases);
                adapter.set_competition_women(instruction.competitionWomen);
                adapter.set_event_context(instruction.kickoffUtc, instruction.competition, instruction.period, instruction.lineTolerance);
                adapter.set_country(instruction.country);
                if(instruction.action.equals("SESSION_CHECK")) new SessionCheckWorkflow(session,adapter).start();
                else if(instruction.action.equals("OPEN_SEARCH")) new SearchOpenWorkflow(session,adapter,instruction.text).start();
                else new AdapterWorkflow(session,adapter).start(instruction.text,instruction.market,instruction.side,instruction.line,instruction.minimumPrice,instruction.stake,instruction.executionMode,instruction.confirmationStatus,instruction.eventUrl,instruction.kickoffUtc);
                return;
            }
            String url = CoordinatorConfig.prefs(service).getString("start_url", "").trim();
            if (url.isEmpty()) url = endpoint() + "/neutral/text.html";
            Uri target = Uri.parse(url).buildUpon().appendQueryParameter("coordinator_request", instruction.id).build();
            Intent intent = new Intent(Intent.ACTION_VIEW, target).setPackage("com.android.chrome").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            intent.putExtra(android.provider.Browser.EXTRA_APPLICATION_ID, service.getPackageName());
            service.startActivity(intent);
            main.postDelayed(() -> {
                JSONObject current = store.get(instruction.id);
                if (closed || current == null || !current.isNull("result")) return;
                long budget = remaining(current, instruction.timeout);
                if (budget < 100) { complete(current, "TIMEOUT", "Deadline expired while opening Chrome"); return; }
                try {
                    if (!runner.tryStartText(instruction.asText(budget))) complete(current, "INTERNAL_ERROR", "Runner rejected dispatch; no retry");
                } catch (Exception e) { complete(current, "INTERNAL_ERROR", "Dispatch failed: " + e.getClass().getSimpleName()); }
            }, Math.min(1200, remaining));
        } catch (Exception e) { runner.finish(instruction.runId,"INTERNAL_ERROR","Dispatch failed: "+e.getClass().getSimpleName()); complete(row, "INTERNAL_ERROR", "Cannot open configured Chrome page: " + e.getClass().getSimpleName()); }
    }
    private void armDeadlineWatch(CoordinatorInstruction instruction) {
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

    private static boolean advancesWatchdog(String stage) {
        if (stage == null) return false;
        // Capture/noise phases must NOT reset inactivity; only verified ladder stage advances do.
        return java.util.Set.of(
            "STARTED","SESSION_CHECK","SPORTS_HOME","SPORTS_CONTEXT","OPEN_SEARCH","FOCUS",
            "ENTER_QUERY","QUERY_VERIFY","RESULTS_WAIT","FIXTURE_VERIFY","MARKET_NAV",
            "OPEN_HOME","ENSURE_SESSION","DISCOVER_FIXTURE","SELECT_FIXTURE","VERIFY_EVENT",
            "DISCOVER_MARKETS","READ_SELECTION","READ_LINE","READ_PRICE","OPEN_SELECTION",
            "ENTER_STAKE","VERIFY_FINAL_STATE","PREPARE_COMPLETE_EXECUTION","PLACE_BET",
            "PLACE_BET_OUTCOME","RESET_BETSLIP","CLEAR_BETSLIP","MY_BETS","MY_BETS_SCROLL","OBSERVE","OPEN_EVENT","PRETAP_CHECK","RETURN_HOME"
        ).contains(stage);
    }

    private void onWorkflowProgress(String stage, long elapsedMs, JSONObject timing) {
        noteProgress(progressInstructionId, stage, elapsedMs, timing);
        if (!advancesWatchdog(stage)) return;
        // Keep AUTHENTICATED fresh while verified stage progress continues (no UNKNOWN race).
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
        boolean advance = advancesWatchdog(stage);
        if (advance && stage != null && !stage.isEmpty()) progressStage = stage;
        progressElapsedMs = elapsedMs;
        if (advance) {
            lastProgressAtElapsed = SystemClock.elapsedRealtime();
            lastProgressWallMs = System.currentTimeMillis();
        }
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

    private long remaining(JSONObject row, int timeout) { return timeout - (SystemClock.elapsedRealtime() - row.optLong("received_elapsed")); }
    private void runnerFinished(String runId, String status, String detail) {
        JSONObject row = store.byRun(runId);
        if (row != null) complete(row, stage(status), detail);
    }
    private synchronized void complete(JSONObject row, String stage, String detail) {
        String id = row.optString("instruction_id"); JSONObject current = store.get(id);
        if (current == null || !current.isNull("result")) return;
        if (deadlineWatch != null) { main.removeCallbacks(deadlineWatch); deadlineWatch = null; }
        JSONObject result = result(id, stage, detail, Math.max(0, System.currentTimeMillis() - current.optLong("received_ms")));
        put(result, "progress", progressSnapshot());
        put(result, "device_stage", progressStage);
        put(result, "execution_count", current.optInt("execution_count"));
        put(result, "run_id", current.optString("run_id"));
        JSONObject proof=evidence(current);
        String completedAction=current.optJSONObject("payload").optString("action");
        if(proof!=null && (completedAction.equals("ADAPTER_WORKFLOW") || completedAction.equals("SESSION_CHECK") || completedAction.equals("SESSION_PROBE") || completedAction.equals("OPEN_SEARCH") || completedAction.equals("MY_BETS") || completedAction.equals("OBSERVE") || completedAction.equals("RESET_BETSLIP") || completedAction.equals("PLACE_HELD") || completedAction.equals("OCR_BENCH"))) {
            JSONObject fixture=proof.optJSONObject("fixture");
            for(String key:new String[]{"fixture_name","home","away","competition"})put(result,key,fixture==null?JSONObject.NULL:fixture.opt(key));
            put(result,"selection",proof.opt("selection"));put(result,"final_state",proof.opt("final_state"));put(result,"ready_state",proof.opt("ready_state"));put(result,"complete_execution_ready",proof.opt("complete_execution_ready"));put(result,"place_bet_tapped",proof.opt("place_bet_tapped"));put(result,"place_bet_result",proof.opt("place_bet_result"));put(result,"place_bet_detail",proof.opt("place_bet_detail"));if(proof.has("wager_submitted"))put(result,"wager_submitted",proof.opt("wager_submitted"));
            put(result,"verification_detail",proof.optString("verification_detail",detail));
            if(proof.has("placement"))put(result,"placement",proof.opt("placement"));
            if(proof.has("my_bets"))put(result,"my_bets",proof.opt("my_bets"));
            if(proof.has("observe"))put(result,"observe",proof.opt("observe"));
            if(proof.has("betslip_reset"))put(result,"betslip_reset",proof.opt("betslip_reset"));
            if(proof.has("betslip_clear"))put(result,"betslip_clear",proof.opt("betslip_clear"));
            for(String key:new String[]{"event_context","route","held","returned_home","home_verified","pretap","execution_observations","stage_timings","t_start_ms","t_pretap_done_ms","t_tap_ms","t_receipt_ms","t_home_ms","alias_candidate","direct_event_rejected","stake_field_state","stake_clear","identity","identity_verdict","event_url","bench","ocr_engine","bet_reference_fast","bet_reference_legacy","bet_reference_disputed","session_path","session_machine","session_recovered","chrome_first_run_dismissed","login_submitted"})
                if(proof.has(key))put(result,key,proof.opt(key));
            JSONObject ready = proof.optJSONObject("ready_state");
            if (ready != null && ready.has("session")) noteSession(ready.optString("session"), "ready_state");
            else if (proof.has("session")) noteSession(proof.optString("session"), "workflow");
            if ("LOGIN_FAILED".equals(stage)) noteSession("LOGGED_OUT", "LOGIN_FAILED; automatic recovery did not authenticate");
        }
        store.complete(id, result);
        runner.releaseReservation(current.optString("run_id"));
        if (id.equals(progressInstructionId)) {
            progressInstructionId = null;
            progressStage = "IDLE";
        }
        Log.i("AgentCoordinator", "RESULT " + result);
    }
    private static String stage(String textStatus) {
        if (textStatus.equals("FIELD_NOT_FOUND")) return "TARGET_NOT_FOUND";
        // Every adapter outcome is kept distinct: collapsing them to INTERNAL_ERROR would hide
        // exactly the final-action outcomes (funds, stake limits, refusals) the backend must see.
        return Set.of("PASS", "LOGIN_FAILED", "SESSION_EXPIRED", "FOCUS_FAILED", "INPUT_FAILED", "TEXT_NOT_VERIFIED", "TIMEOUT",
            "NO_FIXTURE_FOUND", "AMBIGUOUS_FIXTURE", "TARGET_NOT_FOUND", "CLICK_FAILED", "WRONG_EVENT", "EVENT_NOT_VERIFIED",
            "PRICE_CHANGED", "LINE_CHANGED", "SELECTION_CHANGED", "SUSPENDED", "UNAVAILABLE", "BELOW_MINIMUM",
            "INSUFFICIENT_BALANCE", "INSUFFICIENT_FUNDS", "STAKE_LIMITED", "STAKE_REJECTED", "MARKET_SUSPENDED",
            "SELECTION_UNAVAILABLE", "SPORTS_RESULTS_NOT_FOUND", "WRONG_SPORT", "CONFIRMATION_REQUIRED",
            "BETSLIP_NOT_SINGLE", "PLACEMENT_UNKNOWN", "REJECTED", "INVALID_INSTRUCTION", "MY_BETS_UNAVAILABLE", "BOT_CHECK", "ALIAS_REQUIRED", "TWO_FACTOR_REQUIRED").contains(textStatus) ? textStatus : "INTERNAL_ERROR";
    }
    private JSONObject health() throws Exception {
        JSONObject active = store.active(), last = store.last();
        android.content.pm.PackageInfo pkg = service.getPackageManager().getPackageInfo(service.getPackageName(), 0);
        JSONObject session;
        synchronized (sessionLock) {
            session = object("state", sessionState, "observed_at_ms", sessionObservedAtMs, "detail", sessionDetail == null ? "" : sessionDetail,
                "refresh_count", refreshCount, "last_refresh_at_ms", lastRefreshAtMs, "last_refresh_outcome", lastRefreshOutcome);
            // Watchdog: ensure the 60s refresh keeps running even if a prior delayed post was dropped.
            if (!closed && System.currentTimeMillis() - sessionObservedAtMs > SESSION_REFRESH_MS + 5_000L) {
                sessionHandler.removeCallbacks(sessionRefresh);
                sessionHandler.post(sessionRefresh);
            }
        }
        JSONObject health = object("healthy", !closed).put("heartbeat_ms", System.currentTimeMillis()).put("uptime_ms", SystemClock.elapsedRealtime() - boot)
            .put("state", active == null ? "IDLE" : active.optString("state"))
            .put("current_instruction", active == null ? JSONObject.NULL : active.getJSONObject("payload"))
            .put("last_result", last == null ? JSONObject.NULL : last.getJSONObject("result"))
            .put("app_version", pkg.versionName).put("version_code", pkg.versionCode).put("phone_final_action_armed", CoordinatorConfig.finalActionArmed(service))
            .put("diagnostics_active", diagnosticsActive())
            .put("endpoint", endpoint() == null ? JSONObject.NULL : endpoint()).put("pid", android.os.Process.myPid())
            .put("device_id", DEVICE_ID).put("session", session).put("ocr_engine", CoordinatorConfig.ocrEngine(service)).put("fast_ocr_error", runner.fastEngineError() == null ? JSONObject.NULL : runner.fastEngineError())
            .put("credentials_configured", CoordinatorConfig.hasBet365Credentials(service)).put("credential_store", SecureCredentials.storeKind())
            // Non-secret identity the backend binds automatic approvals to: this installation and the configured account.
            .put("worker_id", WorkerIdentity.workerId(service))
            .put("account_fingerprint", CoordinatorConfig.hasBet365Credentials(service)
                    ? WorkerIdentity.fingerprint(CoordinatorConfig.bet365Username(service)) : JSONObject.NULL)
            // Persistent local execution permission (LocalExecution): readable here, never settable over HTTP.
            .put("local_execution", LocalExecution.state(service))
            .put("session_recovery", selfHealStatus())
            .put("worker_health", workerHealth.snapshot());
        if (active != null) {
            put(health, "progress", progressSnapshot());
            put(health, "device_stage", progressStage);
        }
        return health;
    }

    void noteSession(String state, String detail) {
        if (state == null || state.isEmpty()) state = "UNKNOWN";
        // Accept legacy adapter alias.
        if ("LOGGED_IN".equals(state)) state = "AUTHENTICATED";
        String normalized = state.toUpperCase(java.util.Locale.US);
        if (!Set.of("UNKNOWN","LOGGED_OUT","AUTHENTICATING","AUTHENTICATED","EXPIRED","RESTRICTED","ERROR").contains(normalized))
            normalized = "UNKNOWN";
        String safeDetail = detail == null ? "" : detail;
        if (safeDetail.length() > 500) safeDetail = safeDetail.substring(0, 500);
        synchronized (sessionLock) {
            sessionState = normalized;
            sessionObservedAtMs = System.currentTimeMillis();
            sessionDetail = safeDetail;
        }
    }

    // ---- Session self-heal (0.9.0-session): a LOGGED_OUT / EXPIRED idle probe starts ONE bounded SESSION_CHECK
    // (credentials configured, phone idle, >= 10 min since the last, <= 3 per hour). 2FA / challenges end it for the operator.
    private static final long SELF_HEAL_COOLDOWN_MS = 600_000L;
    private static final int SELF_HEAL_PER_HOUR = 3;
    private long lastSelfHealAtMs;
    private volatile int unknownProbes;
    private final java.util.ArrayDeque<Long> selfHeals = new java.util.ArrayDeque<>();
    private volatile String lastSelfHealOutcome = "none";

    private void maybeSelfHeal(String state) {
        if (diagnosticsActive()) return;
        if (closed || !("LOGGED_OUT".equals(state) || "EXPIRED".equals(state) || "UNKNOWN_PERSISTENT".equals(state))) return;
        if (!CoordinatorConfig.hasBet365Credentials(service)) { lastSelfHealOutcome = "skipped: no credentials configured"; return; }
        long now = System.currentTimeMillis();
        synchronized (selfHeals) {
            while (!selfHeals.isEmpty() && now - selfHeals.peekFirst() > 3_600_000L) selfHeals.pollFirst();
            if (now - lastSelfHealAtMs < SELF_HEAL_COOLDOWN_MS || selfHeals.size() >= SELF_HEAL_PER_HOUR) { lastSelfHealOutcome = "deferred: cooldown or hourly limit"; return; }
            lastSelfHealAtMs = now; selfHeals.addLast(now);
        }
        String id = "self-session-" + now;
        main.post(() -> {
            if (store.active() != null) { lastSelfHealOutcome = id + ": skipped, phone busy"; return; }
            CoordinatorHttp.Reply reply = accept(object("instruction_id", id, "action", "SESSION_CHECK", "adapter", "live_bet365",
                    "scenario", "live", "sport", "basketball", "timeout_ms", 120000).toString());
            lastSelfHealOutcome = id + " -> HTTP " + reply.code;
            Log.i("AgentCoordinator", "SELF_HEAL " + lastSelfHealOutcome);
            if (reply.afterWrite != null) reply.afterWrite.run();
        });
    }

    private JSONObject selfHealStatus() {
        int n; synchronized (selfHeals) { n = selfHeals.size(); }
        return object("last_attempt_at_ms", lastSelfHealAtMs, "attempts_last_hour", n, "last_outcome", lastSelfHealOutcome);
    }

    private void refreshSession() {
        if (closed) return;
        refreshCount++;
        lastRefreshAtMs = System.currentTimeMillis();
        lastRefreshOutcome = "started";
        try {
            PowerManager power = (PowerManager) service.getSystemService(android.content.Context.POWER_SERVICE);
            KeyguardManager keyguard = (KeyguardManager) service.getSystemService(android.content.Context.KEYGUARD_SERVICE);
            if (power == null || !power.isInteractive() || (keyguard != null && keyguard.isKeyguardLocked())) {
                noteSession("UNKNOWN", "screen locked or off");
                lastRefreshOutcome = "screen locked or off";
            } else if (store.active() != null || diagnosticsActive()) {
                // Mid-instruction: do not steal screenshots / runner. Keep AUTHENTICATED fresh via keepalive
                // so pipeline session_max_age (120s) does not race SESSION_REQUIRED while a job is active.
                // Do NOT flip to UNKNOWN here (that caused tips queued during jobs to die as SESSION_REQUIRED).
                synchronized (sessionLock) {
                    // Observation age must remain honest while the on-screen probe is deferred.
                    sessionDetail = "probe deferred: active job or diagnostics lease";
                    // Non-AUTHENTICATED mid-job: leave state unchanged (fail closed for new dispatches).
                }
                lastRefreshOutcome = "job active";
            } else {
                final long startedAt = System.currentTimeMillis();
                boolean started = runner.probeSession(ocr -> {
                    try {
                        VisualScreen screen = new VisualScreen(ocr);
                        String state = Bet365LiveAdapter.classifySessionState(screen);
                        noteSession(state, "idle probe");
                        // UNKNOWN three probes running (~3 min: Chrome's first-run screen, a non-Bet365 page) is worth one bounded check too
                        unknownProbes = "UNKNOWN".equals(state) ? unknownProbes + 1 : 0;
                        maybeSelfHeal(unknownProbes >= 3 ? "UNKNOWN_PERSISTENT" : state);
                    } catch (Exception e) {
                        noteSession("ERROR", "session probe failed: " + e.getClass().getSimpleName());
                    }
                });
                if (!started) {
                    noteSession("UNKNOWN", "runner unavailable for session probe");
                    lastRefreshOutcome = "runner unavailable";
                } else {
                    lastRefreshOutcome = "probe started";
                    // If OCR callback never arrives, age out instead of freezing observed_at.
                    sessionHandler.postDelayed(() -> {
                        synchronized (sessionLock) {
                            if (sessionObservedAtMs < startedAt) noteSession("UNKNOWN", "session probe timed out");
                        }
                    }, 15_000L);
                }
            }
        } catch (Throwable e) {
            noteSession("ERROR", "session refresh failed: " + e.getClass().getSimpleName());
            lastRefreshOutcome = "failed: " + e.getClass().getSimpleName();
        } finally {
            if (!closed) sessionHandler.postDelayed(sessionRefresh, SESSION_REFRESH_MS);
            Log.i("AgentSession", "refresh #" + refreshCount + " outcome=" + lastRefreshOutcome + " state=" + sessionState);
        }
    }
    private JSONObject acknowledgement(JSONObject row) {
        JSONObject ack = object("instruction_id", row.optString("instruction_id"), "acknowledged", true,
            "state", row.optString("state"), "received_at_ms", row.optLong("received_ms"),
            "result_url", "/instructions/" + row.optString("instruction_id"), "execution_count", row.optInt("execution_count"));
        if (row.isNull("result") && progressInstructionId != null && progressInstructionId.equals(row.optString("instruction_id"))) {
            put(ack, "progress", progressSnapshot());
            put(ack, "device_stage", progressStage);
        }
        return ack;
    }
    private JSONObject evidence(JSONObject row) {
        try {
            String action=row.getJSONObject("payload").optString("action");
            boolean workflow=action.equals("ADAPTER_WORKFLOW") || action.equals("SESSION_CHECK") || action.equals("SESSION_PROBE") || action.equals("OPEN_SEARCH") || action.equals("MY_BETS") || action.equals("OBSERVE") || action.equals("RESET_BETSLIP") || action.equals("PLACE_HELD") || action.equals("OCR_BENCH");
            File file = new File(service.getFilesDir(), (workflow?"workflow/":"text/") + row.getString("run_id") + "/result.json");
            return file.isFile() ? new JSONObject(new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8)) : null;
        } catch (Exception e) { return null; }
    }
    static JSONObject object(Object... values) {
        JSONObject json = new JSONObject();
        for (int i = 0; i < values.length; i += 2) put(json, (String) values[i], values[i + 1]);
        return json;
    }
    static void put(JSONObject json, String key, Object value) {
        try { json.put(key, value); } catch (Exception e) { throw new IllegalStateException(e); }
    }
    private static JSONObject result(String id, String stage, String detail, long duration) {
        return object("instruction_id", id, "status", stage.equals("PASS") ? "PASS" : "FAIL", "stage", stage, "detail", detail, "duration_ms", duration);
    }
    CoordinatorHttp.Reply error(int httpCode, String id, String stage, String detail) { return json(httpCode, result(id, stage, detail, 0)); }
    private CoordinatorHttp.Reply json(int code, JSONObject json) { return new CoordinatorHttp.Reply(code, "application/json; charset=utf-8", json.toString().getBytes(StandardCharsets.UTF_8)); }
    @Override public void close() {
        closed = true;
        sessionHandler.removeCallbacksAndMessages(null);
        sessionThread.quitSafely();
        main.removeCallbacksAndMessages(null);
        JSONObject active = store.active();
        if (active != null) {
            runner.finish(active.optString("run_id"), "INTERRUPTED", "Coordinator service disconnected; no replay");
            complete(active, "INTERNAL_ERROR", "Coordinator service disconnected; no replay");
        }
        runner.setResultListener(null);
        http.close();
    }
}
