package com.bet365agent;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.graphics.Path;
import android.graphics.Rect;
import android.hardware.HardwareBuffer;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Log;
import android.view.Display;
import android.view.accessibility.AccessibilityNodeInfo;
import com.googlecode.tesseract.android.TessBaseAPI;
import com.googlecode.tesseract.android.ResultIterator;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.function.Consumer;

/** Screenshot/OCR/gesture proof on tools/neutral-visual/index.html. No guessed coordinates. */
final class VisualControlRunner {
    private static final String TAG = "AgentVisual";
    private final AccessibilityService service;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final SharedPreferences prefs;
    private volatile String active;
    private volatile String reservation;
    interface ResultListener { void onFinished(String id, String status, String detail); }
    private ResultListener listener;
    void setResultListener(ResultListener listener) { this.listener = listener; }
    synchronized boolean reserve(String id) {
        if (closed || active != null || reservation != null) return false;
        reservation = id; return true;
    }
    synchronized void releaseReservation(String id) { if (id.equals(reservation)) reservation = null; }
    private TextEntryFlow textFlow;
    private long deadline;
    private boolean closed;
    private int captureDisplay = Display.DEFAULT_DISPLAY;

    VisualControlRunner(AccessibilityService service) {
        this.service = service;
        prefs = service.getSharedPreferences("visual_agent", 0);
        if ("RUNNING".equals(prefs.getString("status", ""))) {
            prefs.edit().putString("status", "INTERRUPTED")
                .putString("detail", "Service restarted; previous action is not replayed").commit();
            ScanStore.setVisualControlTestResult(service, "INTERRUPTED", "Service restarted; previous action is not replayed");
        }
        TextEntryFlow.recover(service);
        log("SERVICE_CONNECTED sdk=" + android.os.Build.VERSION.SDK_INT
            + " capabilities=" + service.getServiceInfo().getCapabilities()
            + " pid=" + android.os.Process.myPid());
    }

    void start(String id, boolean captureOnly) {
        start(id, captureOnly, Display.DEFAULT_DISPLAY);
    }

    void start(String id, boolean captureOnly, int displayId) {
        if (!begin(id, captureOnly ? displayId : Display.DEFAULT_DISPLAY, 30000)) return;
        prepare(id, captureOnly, 0);
    }

    boolean isTextActive() { return textFlow != null || reservation != null; }

    void startText(TextInstruction instruction) { tryStartText(instruction); }

    boolean tryStartText(TextInstruction instruction) {
        if (!begin(instruction.id, Display.DEFAULT_DISPLAY, instruction.timeoutMs)) return false;
        try {
            textFlow = new TextEntryFlow(this, service, instruction);
            textFlow.start();
        } catch (Exception e) { finish(instruction.id, "INPUT_FAILED", "Cannot start text flow: " + e); }
        return true;
    }

    private synchronized boolean begin(String id, int displayId, long timeoutMs) {
        if (closed || (reservation != null && !reservation.equals(id))) return false;
        if (active != null || prefs.getStringSet("consumed_ids", new HashSet<>()).contains(id)) {
            log("DUPLICATE_OR_BUSY rejected id=" + id);
            return false;
        }
        if (!id.matches("[A-Za-z0-9_-]{1,64}")) return false;
        Set<String> consumed = new HashSet<>(prefs.getStringSet("consumed_ids", new HashSet<>()));
        consumed.add(id);
        // Persist before any effect: restart never blindly repeats a gesture.
        if (!prefs.edit().putStringSet("consumed_ids", consumed).putString("run_id", id)
                .putString("status", "RUNNING").putString("detail", "")
                .remove("target_bounds").remove("capture_result").remove("capture_error_code")
                .putString("phase", "CAPTURE_BEFORE").commit()) return false;
        active = id;
        captureDisplay = displayId;
        deadline = SystemClock.elapsedRealtime() + timeoutMs;
        ScanStore.setVisualControlTestResult(service, "RUNNING", id);
        log("START id=" + id);
        main.postDelayed(() -> { if (live(id)) finish(id, textFlow == null ? "FAIL" : "TIMEOUT", "Hard deadline expired"); }, timeoutMs);
        return true;
    }

    private void prepare(String id, boolean captureOnly, int attempt) {
        capture(id, "before", 0, bitmap -> {
            if (captureOnly) {
                process(id, bitmap, "before", result -> finish(id, "PASS", "Screenshot saved; " + result.width + "x" + result.height));
            } else {
                process(id, bitmap, "before", result -> {
                    if (!result.isNeutralPage() || !result.has("READY") || result.has("COMPLETE")) {
                        if (attempt < 2) {
                            main.postDelayed(() -> prepare(id, false, attempt + 1), 1000); return;
                        }
                        finish(id, "FAIL", "Neutral page READY precondition absent"); return;
                    }
                    List<Rect> targets = result.bounds("NEPTUNE");
                    if (targets.size() != 1) {
                        finish(id, "FAIL", "Expected exactly one NEPTUNE; found " + targets.size()); return;
                    }
                    tap(id, targets.get(0));
                });
            }
        });
    }

    private boolean live(String id) { return !closed && id.equals(active); }
    boolean withinDeadline(String id) {
        if (!live(id)) return false;
        if (SystemClock.elapsedRealtime() >= deadline) {
            finish(id, textFlow == null ? "FAIL" : "TIMEOUT", "Hard deadline expired"); return false;
        }
        return true;
    }

    private void capture(String id, String phase, int attempt, Consumer<Bitmap> next) {
        if (!withinDeadline(id)) return;
        prefs.edit().putString("phase", "CAPTURE_" + phase).apply();
        if (android.os.Build.VERSION.SDK_INT < 30) {
            finish(id, "FAIL", "Accessibility screenshots require API 30; MediaProjection required"); return;
        }
        log("TAKE_SCREENSHOT request id=" + id + " phase=" + phase + " attempt=" + attempt
            + " capabilities=" + service.getServiceInfo().getCapabilities());
        try {
            service.takeScreenshot(captureDisplay, service.getMainExecutor(),
                new AccessibilityService.TakeScreenshotCallback() {
                    public void onSuccess(AccessibilityService.ScreenshotResult result) {
                        log("TAKE_SCREENSHOT onSuccess id=" + id + " phase=" + phase + " timestamp=" + result.getTimestamp());
                        Bitmap wrapped = null;
                        try (HardwareBuffer buffer = result.getHardwareBuffer()) {
                            if (!withinDeadline(id)) return;
                            prefs.edit().putString("capture_result", "onSuccess").remove("capture_error_code").apply();
                            wrapped = Bitmap.wrapHardwareBuffer(buffer, result.getColorSpace());
                            if (wrapped == null) throw new IllegalStateException("wrapHardwareBuffer returned null");
                            Bitmap software = wrapped.copy(Bitmap.Config.ARGB_8888, false);
                            if (software == null) throw new IllegalStateException("software bitmap copy returned null");
                            next.accept(software);
                        } catch (Exception e) { finish(id, "FAIL", "Screenshot conversion: " + e); }
                        finally { if (wrapped != null) wrapped.recycle(); }
                    }
                    public void onFailure(int errorCode) {
                        String detail = "TAKE_SCREENSHOT onFailure code=" + errorCode + " name=" + errorName(errorCode);
                        log(detail + " id=" + id + " phase=" + phase);
                        if (!withinDeadline(id)) return;
                        prefs.edit().putString("capture_result", detail).putInt("capture_error_code", errorCode).apply();
                        if ((errorCode == 1 || errorCode == 3) && attempt < 2) {
                            main.postDelayed(() -> capture(id, phase, attempt + 1, next), 700);
                        } else finish(id, "FAIL", detail);
                    }
                });
        } catch (Exception e) {
            log("TAKE_SCREENSHOT exception=" + e);
            finish(id, "FAIL", "takeScreenshot exception: " + e);
        }
    }

    static String errorName(int code) {
        switch (code) {
            case 1: return "ERROR_TAKE_SCREENSHOT_INTERNAL_ERROR";
            case 2: return "ERROR_TAKE_SCREENSHOT_NO_ACCESSIBILITY_ACCESS";
            case 3: return "ERROR_TAKE_SCREENSHOT_INTERVAL_TIME_SHORT";
            case 4: return "ERROR_TAKE_SCREENSHOT_INVALID_DISPLAY";
            case 5: return "ERROR_TAKE_SCREENSHOT_INVALID_WINDOW";
            case 6: return "ERROR_TAKE_SCREENSHOT_SECURE_WINDOW";
            default: return "UNKNOWN";
        }
    }

    void frame(String id, String phase, Consumer<Ocr> next) {
        capture(id, phase, 0, bitmap -> process(id, bitmap, phase, next));
    }

    private void process(String id, Bitmap bitmap, String phase, Consumer<Ocr> next) {
        TextEntryFlow flow = textFlow;
        worker.execute(() -> {
            try {
                File dir = new File(service.getFilesDir(), "visual/" + id);
                if (!dir.isDirectory() && !dir.mkdirs()) throw new IllegalStateException("Cannot create evidence directory");
                try (FileOutputStream out = new FileOutputStream(new File(dir, phase + ".png"))) {
                    if (!bitmap.compress(Bitmap.CompressFormat.PNG, 100, out)) throw new IllegalStateException("PNG encode failed");
                }
                Ocr result = recognize(bitmap);
                if (flow != null) flow.analyze(bitmap, result, phase);
                try (FileOutputStream out = new FileOutputStream(new File(dir, phase + ".txt"))) {
                    out.write(result.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));
                }
                log("OCR id=" + id + " phase=" + phase + " " + result);
                main.post(() -> {
                    if (!withinDeadline(id)) return;
                    try { next.accept(result); }
                    catch (Exception e) { finish(id, "FAIL", "Visual action exception: " + e); }
                });
            } catch (Exception e) { main.post(() -> finish(id, "FAIL", "OCR/evidence: " + e)); }
            finally { bitmap.recycle(); }
        });
    }

    private Ocr recognize(Bitmap bitmap) throws Exception {
        return recognize(bitmap, TessBaseAPI.PageSegMode.PSM_AUTO);
    }

    Ocr recognize(Bitmap bitmap, int segmentation) throws Exception {
        File base = new File(service.getFilesDir(), "ocr");
        File data = new File(base, "tessdata/eng.traineddata");
        if (!data.exists()) {
            data.getParentFile().mkdirs();
            File temp = new File(data.getParentFile(), "eng.tmp");
            try (InputStream in = service.getAssets().open("tessdata/eng.traineddata");
                 FileOutputStream out = new FileOutputStream(temp)) {
                byte[] bytes = new byte[16384]; int count;
                while ((count = in.read(bytes)) != -1) out.write(bytes, 0, count);
            }
            if (!temp.renameTo(data)) throw new IllegalStateException("Cannot install OCR data");
        }
        TessBaseAPI tess = new TessBaseAPI();
        try {
            if (!tess.init(base.getAbsolutePath(), "eng")) throw new IllegalStateException("Tesseract init failed");
            tess.setPageSegMode(segmentation);
            tess.setImage(bitmap);
            tess.getUTF8Text();
            Ocr result = new Ocr(bitmap.getWidth(), bitmap.getHeight());
            ResultIterator iterator = tess.getResultIterator();
            if (iterator != null) {
                try {
                    iterator.begin();
                    do {
                        String word = iterator.getUTF8Text(TessBaseAPI.PageIteratorLevel.RIL_WORD);
                        Rect rect = iterator.getBoundingRect(TessBaseAPI.PageIteratorLevel.RIL_WORD);
                        if (word != null && rect != null && !rect.isEmpty()) {
                            result.words.add(word.trim()); result.rects.add(new Rect(rect));
                        }
                    } while (iterator.next(TessBaseAPI.PageIteratorLevel.RIL_WORD));
                } finally { iterator.delete(); }
            }
            return result;
        } finally { tess.end(); }
    }

    private void tap(String id, Rect bounds) {
        if (!withinDeadline(id)) return;
        AccessibilityNodeInfo root = service.getRootInActiveWindow();
        boolean chrome = root != null && "com.android.chrome".contentEquals(root.getPackageName() == null ? "" : root.getPackageName());
        if (root != null) root.recycle();
        if (!chrome) { finish(id, "FAIL", "Chrome is no longer foreground"); return; }
        if (!prefs.edit().putString("phase", "GESTURE_DISPATCHING").putString("target_bounds", bounds.toShortString()).commit()) {
            finish(id, "FAIL", "Could not persist gesture intent"); return;
        }
        Path path = new Path(); path.moveTo(bounds.exactCenterX(), bounds.exactCenterY());
        GestureDescription gesture = new GestureDescription.Builder()
            .addStroke(new GestureDescription.StrokeDescription(path, 0, 100)).build();
        log("GESTURE id=" + id + " OCR bounds=" + bounds.toShortString());
        boolean accepted = service.dispatchGesture(gesture, new AccessibilityService.GestureResultCallback() {
            public void onCompleted(GestureDescription gesture) {
                if (!withinDeadline(id)) return;
                log("GESTURE onCompleted id=" + id);
                main.postDelayed(() -> verify(id, 0), 800);
            }
            public void onCancelled(GestureDescription gesture) { finish(id, "FAIL", "Gesture cancelled; not replayed"); }
        }, main);
        if (!accepted) finish(id, "FAIL", "dispatchGesture rejected");
    }

    private void verify(String id, int attempt) {
        capture(id, "after", 0, bitmap -> process(id, bitmap, "after", result -> {
            if (result.isNeutralPage() && result.has("COMPLETE") && !result.has("READY")) {
                finish(id, "PASS", "OCR NEPTUNE bounds -> dispatchGesture completed -> OCR COMPLETE; READY absent");
            } else if (attempt < 2) {
                main.postDelayed(() -> verify(id, attempt + 1), 700);
            } else finish(id, "FAIL", "Expected COMPLETE and absence of READY not verified");
        }));
    }

    void finish(String id, String status, String detail) {
        if (!live(id)) return;
        if (textFlow != null) {
            if ("FAIL".equals(status)) status = "INPUT_FAILED";
            textFlow.finished(status, detail);
            textFlow = null;
        }
        active = null;
        prefs.edit().putString("status", status).putString("detail", detail).commit();
        ScanStore.setVisualControlTestResult(service, status, detail);
        log("RESULT id=" + id + " status=" + status + " detail=" + detail);
        if (listener != null) listener.onFinished(id, status, detail);
    }

    void close() {
        if (active != null) finish(active, "INTERRUPTED", "Service disconnected; action not replayed");
        closed = true;
        main.removeCallbacksAndMessages(null);
        worker.shutdown();
        log("SERVICE_DISCONNECTED");
    }

    private void log(String text) { Log.i(TAG, text); }

    static class Ocr {
        Rect fieldBounds;
        String fieldText = "";
        final int width, height;
        final List<String> words = new ArrayList<>();
        final List<Rect> rects = new ArrayList<>();
        Ocr(int width, int height) { this.width = width; this.height = height; }
        List<Rect> bounds(String exact) {
            List<Rect> matches = new ArrayList<>();
            for (int i = 0; i < words.size(); i++) if (exact.equals(words.get(i))) matches.add(rects.get(i));
            return matches;
        }
        boolean has(String exact) { return !bounds(exact).isEmpty(); }
        boolean isNeutralPage() { return has("Neutral") && has("visual") && has("test"); }
        public String toString() {
            StringBuilder out = new StringBuilder(width + "x" + height + "\n");
            for (int i = 0; i < words.size(); i++) out.append(words.get(i)).append(" ").append(rects.get(i).toShortString()).append('\n');
            return out.toString();
        }
    }
}
