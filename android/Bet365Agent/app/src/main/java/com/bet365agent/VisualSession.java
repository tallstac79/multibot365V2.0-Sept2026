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
    VisualSession(AccessibilityService service,VisualControlRunner runner,String id,String adapter) {
        this.service=service;this.runner=runner;this.id=id;
        record=CoordinatorAgent.object("run_id",id,"adapter",adapter,"status","RUNNING","phase","STARTED","started_at_ms",System.currentTimeMillis(),"events",events,"screenshots",images,"gesture_attempts",0);
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
        put("phase",phase);events.put(CoordinatorAgent.object("phase",phase,"elapsed_ms",SystemClock.elapsedRealtime()-started));persist(file(service,id),record);
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
        service.startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse(url)).setPackage("com.android.chrome").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        return delay(1200);
    }
    CompletableFuture<VisualScreen> capture(String label) { return capture(label,false); }
    CompletableFuture<VisualScreen> captureTable(String label) { return capture(label,true); }
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
    CompletableFuture<Void> tap(Rect box,String description) {
        if(!live())return failed("TIMEOUT","Session expired");
        if(box.isEmpty()||box.left<0||box.top<0)return failed("CLICK_FAILED","Invalid visual bounds");
        put("gesture_attempts",record.optInt("gesture_attempts")+1);
        events.put(CoordinatorAgent.object("effect","gesture","target",description,"bounds",bounds(box),"elapsed_ms",SystemClock.elapsedRealtime()-started));
        checkpoint("GESTURE_DISPATCHING"); // durable intent before effect; no replay after restart
        CompletableFuture<Void> f=future();Path path=new Path();path.moveTo(box.exactCenterX(),box.exactCenterY());
        boolean accepted=service.dispatchGesture(new GestureDescription.Builder().addStroke(new GestureDescription.StrokeDescription(path,0,100)).build(),new AccessibilityService.GestureResultCallback(){
            public void onCompleted(GestureDescription gesture){if(live())main.postDelayed(()->{if(live())f.complete(null);},450);}
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

    CompletableFuture<Void> dismissKeyboard() {
        if(!live())return failed("TIMEOUT","Session expired");
        checkpoint("DISMISS_KEYBOARD");service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK);return delay(900);
    }
    void finish(String status,String detail) { if(done)return;terminated(status,detail);runner.finish(id,status,detail); }
    private void terminated(String status,String detail) {
        if(done)return;done=true;main.removeCallbacksAndMessages(null);
        put("status",status.equals("INTERRUPTED")?"INTERNAL_ERROR":status);put("detail",detail);put("duration_ms",SystemClock.elapsedRealtime()-started);checkpoint("FINISHED");
        for(CompletableFuture<?> f:new ArrayList<>(pending))f.completeExceptionally(new SiteAdapter.Failure(status,detail));
    }
    static <T> CompletableFuture<T> failed(String stage,String detail) {CompletableFuture<T> f=new CompletableFuture<>();f.completeExceptionally(new SiteAdapter.Failure(stage,detail));return f;}
}
