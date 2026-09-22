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
    private final long boot = SystemClock.elapsedRealtime();
    private volatile boolean closed;

    CoordinatorAgent(AccessibilityService service, VisualControlRunner runner) {
        this.service = service; this.runner = runner;
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
    }
    String token() { return CoordinatorConfig.token(service); }
    String endpoint() { return http.endpoint(); }

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
            if (!power.isInteractive() || keyguard.isKeyguardLocked()) { complete(row, "FOCUS_FAILED", "Phone must be awake and unlocked"); return; }
            store.executing(instruction.id);
            if(instruction.action.equals("ADAPTER_WORKFLOW")) {
                if(!runner.startExternal(instruction.runId,remaining(row,instruction.timeout))) {complete(row,"INTERNAL_ERROR","Runner rejected workflow");return;}
                VisualSession session=new VisualSession(service,runner,instruction.runId,instruction.adapter);
                SiteAdapter adapter=SiteAdapters.create(instruction.adapter,session,endpoint(),instruction.scenario,instruction.id,instruction.sport,instruction.stake);
                new AdapterWorkflow(session,adapter).start(instruction.text,instruction.market,instruction.side,instruction.minimumPrice,instruction.stake);
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
    private long remaining(JSONObject row, int timeout) { return timeout - (SystemClock.elapsedRealtime() - row.optLong("received_elapsed")); }
    private void runnerFinished(String runId, String status, String detail) {
        JSONObject row = store.byRun(runId);
        if (row != null) complete(row, stage(status), detail);
    }
    private synchronized void complete(JSONObject row, String stage, String detail) {
        String id = row.optString("instruction_id"); JSONObject current = store.get(id);
        if (current == null || !current.isNull("result")) return;
        JSONObject result = result(id, stage, detail, Math.max(0, System.currentTimeMillis() - current.optLong("received_ms")));
        put(result, "execution_count", current.optInt("execution_count"));
        put(result, "run_id", current.optString("run_id"));
        JSONObject proof=evidence(current);
        if(proof!=null && current.optJSONObject("payload").optString("action").equals("ADAPTER_WORKFLOW")) {
            JSONObject fixture=proof.optJSONObject("fixture");
            for(String key:new String[]{"fixture_name","home","away","competition"})put(result,key,fixture==null?JSONObject.NULL:fixture.opt(key));
            put(result,"selection",proof.opt("selection"));put(result,"final_state",proof.opt("final_state"));
            put(result,"verification_detail",proof.optString("verification_detail",detail));
        }
        store.complete(id, result);
        runner.releaseReservation(current.optString("run_id"));
        Log.i("AgentCoordinator", "RESULT " + result);
    }
    private static String stage(String textStatus) {
        if (textStatus.equals("FIELD_NOT_FOUND")) return "TARGET_NOT_FOUND";
        return Set.of("PASS", "FOCUS_FAILED", "INPUT_FAILED", "TEXT_NOT_VERIFIED", "TIMEOUT", "NO_FIXTURE_FOUND", "AMBIGUOUS_FIXTURE", "TARGET_NOT_FOUND", "CLICK_FAILED", "WRONG_EVENT", "EVENT_NOT_VERIFIED", "PRICE_CHANGED", "LINE_CHANGED", "SELECTION_CHANGED", "SUSPENDED", "UNAVAILABLE", "BELOW_MINIMUM").contains(textStatus) ? textStatus : "INTERNAL_ERROR";
    }
    private JSONObject health() throws Exception {
        JSONObject active = store.active(), last = store.last();
        android.content.pm.PackageInfo pkg = service.getPackageManager().getPackageInfo(service.getPackageName(), 0);
        return object("healthy", !closed).put("heartbeat_ms", System.currentTimeMillis()).put("uptime_ms", SystemClock.elapsedRealtime() - boot)
            .put("state", active == null ? "IDLE" : active.optString("state"))
            .put("current_instruction", active == null ? JSONObject.NULL : active.getJSONObject("payload"))
            .put("last_result", last == null ? JSONObject.NULL : last.getJSONObject("result"))
            .put("app_version", pkg.versionName).put("version_code", pkg.versionCode)
            .put("endpoint", endpoint() == null ? JSONObject.NULL : endpoint()).put("pid", android.os.Process.myPid());
    }
    private JSONObject acknowledgement(JSONObject row) {
        return object("instruction_id", row.optString("instruction_id"), "acknowledged", true,
            "state", row.optString("state"), "received_at_ms", row.optLong("received_ms"),
            "result_url", "/instructions/" + row.optString("instruction_id"), "execution_count", row.optInt("execution_count"));
    }
    private JSONObject evidence(JSONObject row) {
        try {
            boolean workflow=row.getJSONObject("payload").optString("action").equals("ADAPTER_WORKFLOW");
            File file = new File(service.getFilesDir(), (workflow?"workflow/":"text/") + row.getString("run_id") + "/result.json");
            return file.isFile() ? new JSONObject(new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8)) : null;
        } catch (Exception e) { return null; }
    }
    static JSONObject object(Object... values) {
        JSONObject json = new JSONObject();
        for (int i = 0; i < values.length; i += 2) put(json, (String) values[i], values[i + 1]);
        return json;
    }
    private static void put(JSONObject json, String key, Object value) {
        try { json.put(key, value); } catch (Exception e) { throw new IllegalStateException(e); }
    }
    private static JSONObject result(String id, String stage, String detail, long duration) {
        return object("instruction_id", id, "status", stage.equals("PASS") ? "PASS" : "FAIL", "stage", stage, "detail", detail, "duration_ms", duration);
    }
    CoordinatorHttp.Reply error(int httpCode, String id, String stage, String detail) { return json(httpCode, result(id, stage, detail, 0)); }
    private CoordinatorHttp.Reply json(int code, JSONObject json) { return new CoordinatorHttp.Reply(code, "application/json; charset=utf-8", json.toString().getBytes(StandardCharsets.UTF_8)); }
    @Override public void close() {
        closed = true;
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
