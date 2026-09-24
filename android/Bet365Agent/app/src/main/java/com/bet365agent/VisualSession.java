package com.bet365agent;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.content.Intent;
import android.graphics.Path;
import android.graphics.Rect;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.AtomicFile;
import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.CompletableFuture;

/** Site-independent visual effects, deadlines and durable evidence. All action callbacks run on main. */
final class VisualSession {
    final AccessibilityService service;
    final VisualControlRunner runner;
    final String id;
    final JSONObject record;
    private final Handler main=new Handler(Looper.getMainLooper());
    private final long started=SystemClock.elapsedRealtime();
    private final JSONArray events=new JSONArray(), images=new JSONArray();
    private final Set<CompletableFuture<?>> pending=new HashSet<>();
    private boolean done;
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
    }
    static JSONArray bounds(Rect r) { return new JSONArray(Arrays.asList(r.left,r.top,r.right,r.bottom)); }
    static File file(android.content.Context context,String id) { return new File(context.getFilesDir(),"workflow/"+id+"/result.json"); }
    static void persist(File file,JSONObject value) {
        file.getParentFile().mkdirs();AtomicFile atomic=new AtomicFile(file);FileOutputStream out=null;
        try {out=atomic.startWrite();out.write(value.toString().getBytes(StandardCharsets.UTF_8));atomic.finishWrite(out);}
        catch(Exception e){if(out!=null)atomic.failWrite(out);throw new IllegalStateException("Workflow evidence persistence failed",e);}
    }
    void put(String key,Object value) {try{record.put(key,value);}catch(JSONException e){throw new IllegalStateException(e);}}
    void checkpoint(String phase) {
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
            "ENTER_STAKE","VERIFY_FINAL_STATE","PREPARE_COMPLETE_EXECUTION","PLACE_BET",
            "PLACE_BET_OUTCOME","RESET_BETSLIP","MY_BETS","MY_BETS_SCROLL","OBSERVE"
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
    }
    boolean live() { return !done && runner.withinDeadline(id); }
    private <T> CompletableFuture<T> future() {
        CompletableFuture<T> f=new CompletableFuture<>();pending.add(f);f.whenComplete((v,e)->pending.remove(f));return f;
    }
    CompletableFuture<Void> delay(long ms) {
        CompletableFuture<Void> f=future();main.postDelayed(()->{if(live())f.complete(null);},ms);return f;
    }
    CompletableFuture<Void> open(String url) {
        if(!live())return failed("TIMEOUT","Session expired");
        checkpoint("OPEN_HOME");
        // EXTRA_APPLICATION_ID makes Chrome reuse this app's tab instead of opening a new one per workflow.
        service.startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse(url)).setPackage("com.android.chrome").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            .putExtra(android.provider.Browser.EXTRA_APPLICATION_ID,service.getPackageName()));
        return delay(1200);
    }
    CompletableFuture<VisualScreen> capture(String label) { return capture(label,false); }
    CompletableFuture<VisualScreen> captureTable(String label) { return capture(label,true); }
    CompletableFuture<VisualScreen> captureTableBelow(String label,int top) {
        if(!live())return failed("TIMEOUT","Session expired");
        String name=String.format(java.util.Locale.US,"s%03d_%s",++sequence,label);
        checkpoint("CAPTURE_"+label);
        CompletableFuture<VisualScreen> f=future();
        runner.tableFrameBelow(id,name,top,ocr->{if(live()){images.put(name+".png");checkpoint("CAPTURED_"+label);f.complete(new VisualScreen(ocr));}});
        return f;
    }
    private CompletableFuture<VisualScreen> capture(String label,boolean table) {
        if(!live())return failed("TIMEOUT","Session expired");
        String name=String.format(java.util.Locale.US,"s%03d_%s",++sequence,label);
        checkpoint("CAPTURE_"+label);
        CompletableFuture<VisualScreen> f=future();
        java.util.function.Consumer<VisualControlRunner.Ocr> next=ocr->{if(live()){images.put(name+".png");checkpoint("CAPTURED_"+label);f.complete(new VisualScreen(ocr));}};
        if(table)runner.tableFrame(id,name,next);else runner.frame(id,name,next);
        return f;
    }
    CompletableFuture<String> readRegion(String label,Rect bounds,boolean numeric) {
        if(!live())return failed("TIMEOUT","Session expired");
        String name=String.format(java.util.Locale.US,"s%03d_%s",++sequence,label);
        events.put(CoordinatorAgent.object("effect","region_ocr","bounds",bounds(bounds),"artifact",name+".png"));
        checkpoint("READ_REGION_"+label);CompletableFuture<String> f=future();
        runner.regionFrame(id,name,bounds,numeric,ocr->{if(live()){images.put(name+".png");checkpoint("READ_REGION_DONE_"+label);f.complete(String.join(" ",ocr.words));}});
        return f;
    }
    CompletableFuture<Void> tap(Rect box,String description) { return tap(box,description,450); }
    CompletableFuture<Void> tap(Rect box,String description,long settleMs) {
        if(!live())return failed("TIMEOUT","Session expired");
        if(box.isEmpty()||box.left<0||box.top<0)return failed("CLICK_FAILED","Invalid visual bounds");
        put("gesture_attempts",record.optInt("gesture_attempts")+1);
        events.put(CoordinatorAgent.object("effect","gesture","target",description,"bounds",bounds(box),"elapsed_ms",SystemClock.elapsedRealtime()-started));
        checkpoint("GESTURE_DISPATCHING"); // durable intent before effect; no replay after restart
        CompletableFuture<Void> f=future();Path path=new Path();path.moveTo(box.exactCenterX(),box.exactCenterY());
        boolean accepted=service.dispatchGesture(new GestureDescription.Builder().addStroke(new GestureDescription.StrokeDescription(path,0,100)).build(),new AccessibilityService.GestureResultCallback(){
            public void onCompleted(GestureDescription gesture){if(live())main.postDelayed(()->{if(live())f.complete(null);},settleMs);}
            public void onCancelled(GestureDescription gesture){f.completeExceptionally(new SiteAdapter.Failure("CLICK_FAILED","Gesture cancelled"));}
        },main);
        if(!accepted)f.completeExceptionally(new SiteAdapter.Failure("CLICK_FAILED","Gesture rejected"));
        return f;
    }
    CompletableFuture<Void> type(String hint,String query) {
        if(!live())return failed("TIMEOUT","Session expired");
        checkpoint("ENTER_QUERY");CompletableFuture<Void> f=future();
        try {
            TextInstruction instruction=new TextInstruction(CoordinatorAgent.object("run_id",id,"text",query,"field_hint",hint,"package","com.android.chrome","timeout_ms",60000));
            runner.textStep(instruction,(run,status,detail)->{
                try { put("query_evidence",new JSONObject(new String(java.nio.file.Files.readAllBytes(new File(service.getFilesDir(),"text/"+id+"/result.json").toPath()),StandardCharsets.UTF_8))); }
                catch(Exception e){f.completeExceptionally(e);return;}
                if(status.equals("PASS")) {checkpoint("QUERY_VERIFIED");f.complete(null);}
                else f.completeExceptionally(new SiteAdapter.Failure(status.equals("FIELD_NOT_FOUND")?"TARGET_NOT_FOUND":status,detail));
            });
        }catch(Exception e){f.completeExceptionally(e);}
        return f;
    }
    /** Tap a visual hint and commit text via Accessibility IME without TextEntryFlow focus/OCR gating. */
    CompletableFuture<Void> typeDirect(String hint, String value) {
        if(!live())return failed("TIMEOUT","Session expired");
        checkpoint("ENTER_DIRECT");
        CompletableFuture<Void> f=future();
        capture("direct_field").thenCompose(screen -> {
            Rect box = null;
            String want = hint.toLowerCase(java.util.Locale.US);
            for (VisualScreen.Line line : screen.lines) {
                String t = line.text.trim().toLowerCase(java.util.Locale.US);
                if (t.equals(want) || t.contains(want)) {
                    // Prefer tapping below label for "Stake"; for "0.00" tap the value itself
                    if (want.equals("stake") || want.equals("amount")) {
                        box = new Rect(Math.max(0, line.bounds.left - 20), line.bounds.top,
                                Math.min(2000, line.bounds.right + 400), Math.min(3000, line.bounds.bottom + 160));
                    } else {
                        box = new Rect(line.bounds);
                    }
                    break;
                }
            }
            if (box == null) {
                f.completeExceptionally(new SiteAdapter.Failure("TARGET_NOT_FOUND","Field not visible for direct type: " + hint));
                return CompletableFuture.<Void>completedFuture(null);
            }
            return tap(box, "direct-field:" + hint);
        }).thenCompose(v -> pollCommit(value, 0, f));
        return f;
    }

    private CompletableFuture<Void> pollCommit(String value, int attempt, CompletableFuture<Void> f) {
        return delay(450).thenCompose(v -> {
            try {
                if (android.os.Build.VERSION.SDK_INT < 33 || !(service.getInputMethod() instanceof AgentInputMethod)) {
                    f.completeExceptionally(new SiteAdapter.Failure("INPUT_FAILED","Accessibility IME unavailable"));
                    return CompletableFuture.<Void>completedFuture(null);
                }
                AgentInputMethod method = (AgentInputMethod) service.getInputMethod();
                android.accessibilityservice.InputMethod.AccessibilityInputConnection ac = method.getCurrentInputConnection();
                if (ac == null) {
                    if (attempt < 10) return pollCommit(value, attempt + 1, f);
                    f.completeExceptionally(new SiteAdapter.Failure("FOCUS_FAILED","No input connection after tapping stake/field"));
                    return CompletableFuture.<Void>completedFuture(null);
                }
                try {
                    // Clear existing then commit
                    android.view.inputmethod.SurroundingText surrounding = ac.getSurroundingText(64, 64, 0);
                    if (surrounding != null) {
                        CharSequence cur = surrounding.getText();
                        if (cur != null && cur.length() > 0) ac.setSelection(0, cur.length());
                    }
                } catch (Exception ignored) {}
                ac.commitText(value, 1, null);
                put("direct_entered", true);
                put("direct_value", value);
                checkpoint("DIRECT_SENT");
                f.complete(null);
            } catch (Exception e) {
                f.completeExceptionally(new SiteAdapter.Failure("INPUT_FAILED","Direct type failed: " + e.getClass().getSimpleName()));
            }
            return CompletableFuture.<Void>completedFuture(null);
        });
    }

    /** Commit into a password/secret field. Never OCR-verifies or stores the secret value. */
    CompletableFuture<Void> typeSecret(String hint, String secret) {
        if(!live())return failed("TIMEOUT","Session expired");
        checkpoint("ENTER_SECRET");
        CompletableFuture<Void> f=future();
        capture("secret_field").thenCompose(screen -> {
            Rect box = null;
            for (VisualScreen.Line line : screen.lines) {
                String t = line.text.trim().toLowerCase(java.util.Locale.US);
                if (t.contains(hint.toLowerCase(java.util.Locale.US)) || t.contains("password")) {
                    box = new Rect(line.bounds.left, line.bounds.top, line.bounds.right, Math.min(line.bounds.bottom + 140, line.bounds.top + 200));
                    break;
                }
            }
            if (box == null) {
                f.completeExceptionally(new SiteAdapter.Failure("LOGIN_FAILED","Password field not visible"));
                return CompletableFuture.<Void>completedFuture(null);
            }
            return tap(box, "secret-field");
        }).thenCompose(v -> delay(700)).thenAccept(v -> {
            try {
                if (android.os.Build.VERSION.SDK_INT < 33 || !(service.getInputMethod() instanceof AgentInputMethod)) {
                    f.completeExceptionally(new SiteAdapter.Failure("LOGIN_FAILED","Accessibility IME unavailable for secret entry"));
                    return;
                }
                AgentInputMethod method = (AgentInputMethod) service.getInputMethod();
                android.accessibilityservice.InputMethod.AccessibilityInputConnection ac = method.getCurrentInputConnection();
                if (ac == null) {
                    f.completeExceptionally(new SiteAdapter.Failure("LOGIN_FAILED","No input connection for secret field"));
                    return;
                }
                ac.commitText(secret, 1, null);
                put("secret_field_hint", hint);
                put("secret_entered", true);
                checkpoint("SECRET_SENT");
                f.complete(null);
            } catch (Exception e) {
                f.completeExceptionally(new SiteAdapter.Failure("LOGIN_FAILED","Secret entry failed: " + e.getClass().getSimpleName()));
            }
        });
        return f;
    }

    /** Vertical swipe (scroll) gesture. Never used for selection; only to reveal more lines. */
    CompletableFuture<Void> swipe(int x,int fromY,int toY,long durationMs) {
        if(!live())return failed("TIMEOUT","Session expired");
        events.put(CoordinatorAgent.object("effect","swipe","x",x,"from_y",fromY,"to_y",toY,"elapsed_ms",SystemClock.elapsedRealtime()-started));
        CompletableFuture<Void> f=future();Path path=new Path();path.moveTo(x,fromY);path.lineTo(x,toY);
        boolean accepted=service.dispatchGesture(new GestureDescription.Builder().addStroke(new GestureDescription.StrokeDescription(path,0,durationMs)).build(),new AccessibilityService.GestureResultCallback(){
            public void onCompleted(GestureDescription gesture){if(live())main.postDelayed(()->{if(live())f.complete(null);},600);}
            public void onCancelled(GestureDescription gesture){f.completeExceptionally(new SiteAdapter.Failure("CLICK_FAILED","Swipe cancelled"));}
        },main);
        if(!accepted)f.completeExceptionally(new SiteAdapter.Failure("CLICK_FAILED","Swipe rejected"));
        return f;
    }

    /** Artifact name of the most recent capture (e.g. s012_place_bet_after.png), or null. */
    String lastImage() { return images.length()==0?null:images.optString(images.length()-1,null); }

    CompletableFuture<Void> dismissKeyboard() {
        if(!live())return failed("TIMEOUT","Session expired");
        checkpoint("DISMISS_KEYBOARD");service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK);return delay(900);
    }
    void finish(String status,String detail) { if(done)return;terminated(status,detail);runner.finish(id,status,detail); }
    private void terminated(String status,String detail) {
        if(done)return;done=true;main.removeCallbacksAndMessages(null);
        closeStage(SystemClock.elapsedRealtime(), status.equals("PASS")?"ok":"fail");put("stage_timings",stageTimings);put("status",status.equals("INTERRUPTED")?"INTERNAL_ERROR":status);put("detail",detail);put("duration_ms",SystemClock.elapsedRealtime()-started);checkpoint("FINISHED");
        for(CompletableFuture<?> f:new ArrayList<>(pending))f.completeExceptionally(new SiteAdapter.Failure(status,detail));
    }
    static <T> CompletableFuture<T> failed(String stage,String detail) {CompletableFuture<T> f=new CompletableFuture<>();f.completeExceptionally(new SiteAdapter.Failure(stage,detail));return f;}
}
