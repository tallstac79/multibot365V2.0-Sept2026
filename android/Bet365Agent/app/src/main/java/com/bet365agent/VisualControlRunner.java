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
    private ResultListener textStepListener, terminalObserver;
    void setTerminalObserver(ResultListener listener) { terminalObserver = listener; }
    boolean startExternal(String id, long timeout) { return begin(id, Display.DEFAULT_DISPLAY, timeout); }
    void textStep(TextInstruction instruction, ResultListener callback) throws Exception {
        if (!withinDeadline(instruction.id) || textFlow != null) throw new IllegalStateException("Text step unavailable");
        textStepListener = callback;
        textFlow = new TextEntryFlow(this, service, instruction);
        textFlow.start();
    }
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

    /** Idle on-screen OCR probe for session health. Does not reserve an instruction or fire result listeners. */
    synchronized boolean probeSession(Consumer<Ocr> callback) {
        if (closed || active != null || reservation != null || textFlow != null) return false;
        if (android.os.Build.VERSION.SDK_INT < 30) return false;
        try {
            service.takeScreenshot(Display.DEFAULT_DISPLAY, service.getMainExecutor(),
                new AccessibilityService.TakeScreenshotCallback() {
                    @Override public void onSuccess(AccessibilityService.ScreenshotResult result) {
                        if (closed || worker.isShutdown()) { result.getHardwareBuffer().close(); return; }
                        try { worker.execute(() -> {
                            Bitmap copy = null;
                            try {
                                Bitmap bitmap = Bitmap.wrapHardwareBuffer(result.getHardwareBuffer(), result.getColorSpace());
                                copy = bitmap.copy(Bitmap.Config.ARGB_8888, false);
                                bitmap.recycle();
                                result.getHardwareBuffer().close();
                                Ocr ocr = recognizeLive(copy, TessBaseAPI.PageSegMode.PSM_AUTO);
                                main.post(() -> {
                                    try { callback.accept(ocr); }
                                    catch (Exception ignored) {}
                                });
                            } catch (Exception e) {
                                log("SESSION_PROBE OCR failed: " + e);
                            } finally {
                                if (copy != null) copy.recycle();
                            }
                        }); } catch (java.util.concurrent.RejectedExecutionException e) {
                            // Runner closed while a screenshot was in flight: previously crashed the whole app.
                            log("SESSION_PROBE dropped after runner shutdown");
                        }
                    }
                    @Override public void onFailure(int errorCode) {
                        log("SESSION_PROBE capture failed code=" + errorCode);
                    }
                });
            return true;
        } catch (Exception e) {
            log("SESSION_PROBE exception: " + e);
            return false;
        }
    }

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
        main.postDelayed(() -> { if (live(id)) finish(id, textFlow == null && terminalObserver == null ? "FAIL" : "TIMEOUT", "Absolute deadline expired"); }, timeoutMs);
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
            finish(id, textFlow == null && terminalObserver == null ? "FAIL" : "TIMEOUT", "Absolute deadline expired"); return false;
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

    /** Runs `onMain` once every OCR/evidence job queued so far has finished: frames are on disk before a final gesture. */
    void flush(Runnable onMain) {
        if (closed || worker.isShutdown()) { main.post(onMain); return; }
        worker.execute(() -> main.post(onMain));
    }

    void tableFrame(String id, String phase, Consumer<Ocr> next) {
        capture(id, phase, 0, bitmap -> process(id, bitmap, phase, -1, next));
    }
    /** Second-opinion frame: Tesseract's enhanced per-word pass regardless of the engine flag (except pure fast). */
    void enhancedFrame(String id, String phase, Consumer<Ocr> next) {
        capture(id, phase, 0, bitmap -> process(id, bitmap, phase, -3, next));
    }
    /** Enhanced table OCR of the screen below y=top only (the betslip); word rects are full-screen coordinates. */
    void tableFrameBelow(String id, String phase, int top, Consumer<Ocr> next) {
        capture(id, phase, 0, bitmap -> {
            int y = Math.max(0, Math.min(top, bitmap.getHeight() - 20));
            Bitmap region = Bitmap.createBitmap(bitmap, 0, y, bitmap.getWidth(), bitmap.getHeight() - y);
            if (region != bitmap) bitmap.recycle();
            process(id, region, phase, -1, ocr -> {
                for (Rect r : ocr.rects) r.offset(0, y);
                next.accept(ocr);
            });
        });
    }

    void regionFrame(String id, String phase, Rect bounds, boolean numeric, Consumer<Ocr> next) {
        capture(id, phase, 0, bitmap -> {
            Rect crop = new Rect(bounds); crop.inset(-8, -8);
            if (!crop.intersect(0, 0, bitmap.getWidth(), bitmap.getHeight())) { bitmap.recycle(); finish(id,"INTERNAL_ERROR","Invalid OCR region"); return; }
            Bitmap region = Bitmap.createBitmap(bitmap, crop.left, crop.top, crop.width(), crop.height());
            if (region != bitmap) bitmap.recycle();
            process(id, region, phase, numeric ? -2 : -4, next);
        });
    }

    private void process(String id, Bitmap bitmap, String phase, Consumer<Ocr> next) {
        process(id, bitmap, phase, TessBaseAPI.PageSegMode.PSM_AUTO, next);
    }
    private void process(String id, Bitmap bitmap, String phase, int segmentation, Consumer<Ocr> next) {
        TextEntryFlow flow = textFlow;
        if (closed || worker.isShutdown()) { log("OCR dropped after runner shutdown id=" + id + " phase=" + phase); return; }
        worker.execute(() -> {
            try {
                File dir = new File(service.getFilesDir(), "visual/" + id);
                if (!dir.isDirectory() && !dir.mkdirs()) throw new IllegalStateException("Cannot create evidence directory");
                Ocr result = recognizeLive(bitmap, segmentation);
                if (flow != null) flow.analyze(bitmap, result, phase);
                log("OCR id=" + id + " phase=" + phase + " " + result);
                main.post(() -> {
                    if (!withinDeadline(id)) return;
                    try { next.accept(result); }
                    catch (Exception e) { finish(id, "FAIL", "Visual action exception: " + e); }
                });
                // Task 1: the evidence PNG (~250 ms to encode) is written after the result is handed on. The worker is
                // single-threaded, so the next capture's OCR queues behind it, flush() lets the one Place Bet tap wait
                // for every pending write, and a write failure still fails the run.
                try (FileOutputStream out = new FileOutputStream(new File(dir, phase + ".png"))) {
                    if (!bitmap.compress(Bitmap.CompressFormat.PNG, 100, out)) throw new IllegalStateException("PNG encode failed");
                }
                try (FileOutputStream out = new FileOutputStream(new File(dir, phase + ".txt"))) {
                    out.write(result.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));
                }
            } catch (Exception e) { main.post(() -> finish(id, "FAIL", "OCR/evidence: " + e)); }
            finally { bitmap.recycle(); }
        });
    }

    /**
     * OCR engine selection (Milestone C3). "legacy" = Tesseract everywhere (the proven path); "fast" = the fast
     * on-device engine for every read; "hybrid" = fast for plain reads, Tesseract's enhanced per-word pass for
     * table/region re-reads. Read from the phone's config on every capture, so rollback is immediate.
     */
    String engine() { return CoordinatorConfig.ocrEngine(service); }

    /** Benchmark / A-B entry (OCR_BENCH): OCR a stored frame with the named engine (legacy: table = enhanced path). */
    Ocr benchOcr(Bitmap bitmap, boolean table, String engine) throws Exception {
        if ("legacy".equals(engine)) return table ? recognizeLines(bitmap) : recognize(bitmap);
        return fastOcr(bitmap);
    }

    private com.google.mlkit.vision.text.TextRecognizer fastRecognizer;
    private volatile String fastEngineError;

    /**
     * The fast engine (Milestone C2): ML Kit on-device Latin text recognition, model bundled in the APK.
     * Word-level elements with bounding boxes map straight onto the Ocr word/rect shape every parser uses.
     * Must not run on the main thread (waits on the recogniser task).
     */
    Ocr fastOcr(Bitmap bitmap) throws Exception {
        if (Looper.myLooper() == Looper.getMainLooper()) throw new IllegalStateException("fast OCR on main thread");
        if (fastRecognizer == null)
            fastRecognizer = com.google.mlkit.vision.text.TextRecognition.getClient(
                    com.google.mlkit.vision.text.latin.TextRecognizerOptions.DEFAULT_OPTIONS);
        com.google.mlkit.vision.common.InputImage image = com.google.mlkit.vision.common.InputImage.fromBitmap(bitmap, 0);
        com.google.mlkit.vision.text.Text text = com.google.android.gms.tasks.Tasks.await(fastRecognizer.process(image), 20, java.util.concurrent.TimeUnit.SECONDS);
        Ocr result = new Ocr(bitmap.getWidth(), bitmap.getHeight());
        for (com.google.mlkit.vision.text.Text.TextBlock block : text.getTextBlocks())
            for (com.google.mlkit.vision.text.Text.Line line : block.getLines())
                for (com.google.mlkit.vision.text.Text.Element element : line.getElements()) {
                    Rect box = element.getBoundingBox();
                    String word = element.getText() == null ? "" : element.getText().trim();
                    if (box == null || box.isEmpty() || word.isEmpty()) continue;
                    result.words.add(word); result.rects.add(new Rect(box));
                }
        return result;
    }

    /**
     * Live-path engine dispatch (Milestone C5, from the C4 A/B on 68 real frames):
     *   plain / table (-1) reads : fast (ML Kit) under fast and hybrid; Tesseract (enhanced for tables) under legacy
     *   numeric region (-2)      : Tesseract with a numeric alphabet under every engine (targeted price/amount read)
     *   enhanced re-read (-3)    : Tesseract enhanced per-word pass (the second opinion after a failed readback);
     *                              only the pure "fast" engine uses ML Kit here too
     *   single-line region (-4)  : Tesseract (targeted legacy re-read, e.g. the receipt's Bet Ref line); pure fast = ML Kit
     * A fast-engine failure never fails a run: that frame falls back to Tesseract and the error is recorded for /health.
     */
    private Ocr recognizeLive(Bitmap bitmap, int segmentation) throws Exception {
        String engine = engine();
        if (segmentation == -2) return recognize(bitmap, TessBaseAPI.PageSegMode.PSM_SINGLE_LINE, "0123456789.+-");
        boolean pureFast = "fast".equals(engine);
        if (segmentation == -3) return pureFast ? fastOrTesseract(bitmap, -1) : recognizeLines(bitmap);
        if (segmentation == -4) {
            if (pureFast) return fastOrTesseract(bitmap, TessBaseAPI.PageSegMode.PSM_SINGLE_LINE);
            // small receipt text: the same 3x upscale + contrast pass the table re-read uses (native size read nothing)
            Bitmap big = enhance(bitmap);
            try { return recognize(big, TessBaseAPI.PageSegMode.PSM_SINGLE_LINE); } finally { big.recycle(); }
        }
        if (pureFast || "hybrid".equals(engine)) return fastOrTesseract(bitmap, segmentation);
        return segmentation == -1 ? recognizeLines(bitmap) : recognize(bitmap, segmentation);
    }

    private Ocr fastOrTesseract(Bitmap bitmap, int segmentation) throws Exception {
        try { return fastOcr(bitmap); }
        catch (Exception e) { fastEngineError = e.getClass().getSimpleName() + ": " + e.getMessage(); log("FAST_OCR_FALLBACK " + fastEngineError); }
        return segmentation == -1 ? recognizeLines(bitmap) : recognize(bitmap, segmentation);
    }

    String fastEngineError() { return fastEngineError; }

    /** Warm the fast recogniser (first call loads the model) so the first live capture pays nothing. */
    void warmFastEngine() {
        if ("legacy".equals(engine())) return;
        worker.execute(() -> {
            Bitmap tiny = Bitmap.createBitmap(64, 64, Bitmap.Config.ARGB_8888);
            try { fastOcr(tiny); } catch (Exception e) { fastEngineError = "warm-up: " + e; } finally { tiny.recycle(); }
        });
    }

    /** Refine separately detected table tokens; numeric crops use a numeric alphabet, never expected values. */
    private Ocr recognizeLines(Bitmap bitmap) throws Exception {
        Ocr coarse = recognize(bitmap);
        Ocr result = new Ocr(bitmap.getWidth(), bitmap.getHeight());
        TessBaseAPI tess = new TessBaseAPI();
        try {
            if (!tess.init(new File(service.getFilesDir(), "ocr").getAbsolutePath(), "eng")) throw new IllegalStateException("Tesseract cell init failed");
            tess.setPageSegMode(TessBaseAPI.PageSegMode.PSM_SINGLE_LINE);
            for (int index=0;index<coarse.words.size();index++) {
                String rough=coarse.words.get(index); if(rough.isEmpty())continue;
                Rect box = new Rect(coarse.rects.get(index)); box.inset(-8, -8); box.intersect(0,0,bitmap.getWidth(),bitmap.getHeight());
                Bitmap crop = Bitmap.createBitmap(bitmap, box.left, box.top, box.width(), box.height());
                Bitmap clear = enhance(crop);
                try {
                    tess.setVariable("tessedit_char_whitelist",rough.matches(".*[0-9].*") && rough.replaceAll("[^A-Za-z]", "").length() <= 1 ? "0123456789.+-" : "");
                    if (coarse.rects.get(index).height() > 34) {
                        // Coarse pass merged a stacked cell ("-9.5" over "1.83"): re-read as a block, one word per
                        // text line, each with its own bounds mapped back from the 3x enhanced crop.
                        tess.setPageSegMode(TessBaseAPI.PageSegMode.PSM_SINGLE_BLOCK);
                        tess.setImage(clear); tess.getUTF8Text();
                        ResultIterator it = tess.getResultIterator();
                        if (it != null) {
                            try {
                                it.begin();
                                do {
                                    String line = it.getUTF8Text(TessBaseAPI.PageIteratorLevel.RIL_TEXTLINE);
                                    Rect r = it.getBoundingRect(TessBaseAPI.PageIteratorLevel.RIL_TEXTLINE);
                                    if (line == null || line.trim().isEmpty() || r == null || r.isEmpty()) continue;
                                    Rect mapped = new Rect(box.left + (r.left - 24) / 3, box.top + (r.top - 24) / 3,
                                            box.left + (r.right - 24) / 3, box.top + (r.bottom - 24) / 3);
                                    mapped.intersect(coarse.rects.get(index));
                                    result.words.add(line.trim().replaceAll("\\s+", " ")); result.rects.add(mapped);
                                } while (it.next(TessBaseAPI.PageIteratorLevel.RIL_TEXTLINE));
                            } finally { it.delete(); }
                        }
                        tess.setPageSegMode(TessBaseAPI.PageSegMode.PSM_SINGLE_LINE);
                        continue;
                    }
                    tess.setImage(clear); String text = tess.getUTF8Text();
                    if (text != null && !text.trim().isEmpty()) { result.words.add(text.trim().replaceAll("\\s+", " ")); result.rects.add(new Rect(coarse.rects.get(index))); }
                } finally { if(crop!=bitmap)crop.recycle(); if(clear!=crop)clear.recycle(); }
            }
            return result;
        } finally { tess.end(); }
    }

    /** Table cell crop for the re-read: 3x upscale, grayscale, inverted when the background is dark (bet365's
     *  yellow prices on grey read as "1083" for 1.83 at native size), plus a plain border. Never adds content. */
    static Bitmap enhance(Bitmap crop) {
        int w = crop.getWidth() * 3, h = crop.getHeight() * 3, pad = 24;
        Bitmap big = Bitmap.createScaledBitmap(crop, w, h, true);
        int[] px = new int[w * h];
        big.getPixels(px, 0, w, 0, 0, w, h);
        if (big != crop) big.recycle();
        long sum = 0;
        for (int i = 0; i < px.length; i++) { int p = px[i]; int l = (299 * ((p >> 16) & 255) + 587 * ((p >> 8) & 255) + 114 * (p & 255)) / 1000; px[i] = l; sum += l; }
        boolean dark = sum / Math.max(1, px.length) < 128;
        int bg = dark ? 255 - (int) (sum / Math.max(1, px.length)) : (int) (sum / Math.max(1, px.length));
        for (int i = 0; i < px.length; i++) { int l = dark ? 255 - px[i] : px[i]; px[i] = 0xFF000000 | (l << 16) | (l << 8) | l; }
        Bitmap out = Bitmap.createBitmap(w + 2 * pad, h + 2 * pad, Bitmap.Config.ARGB_8888);
        out.eraseColor(0xFF000000 | (bg << 16) | (bg << 8) | bg);
        out.setPixels(px, 0, w, pad, pad, w, h);
        return out;
    }

    private Ocr recognize(Bitmap bitmap) throws Exception {
        return recognize(bitmap, TessBaseAPI.PageSegMode.PSM_AUTO);
    }

    Ocr recognize(Bitmap bitmap, int segmentation) throws Exception { return recognize(bitmap,segmentation,null); }
    private Ocr recognize(Bitmap bitmap, int segmentation, String alphabet) throws Exception {
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
            if(alphabet!=null)tess.setVariable("tessedit_char_whitelist",alphabet);
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
        if (textStepListener != null) {
            ResultListener callback = textStepListener; textStepListener = null;
            callback.onFinished(id, status, detail); return;
        }
        active = null;
        ResultListener observer = terminalObserver; terminalObserver = null;
        if (observer != null) observer.onFinished(id, status, detail);
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
