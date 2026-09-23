package com.bet365agent;

import android.accessibilityservice.AccessibilityService;
import android.view.accessibility.AccessibilityWindowInfo;
import android.accessibilityservice.GestureDescription;
import android.accessibilityservice.InputMethod.AccessibilityInputConnection;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.graphics.Path;
import android.graphics.Rect;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.AtomicFile;
import android.util.Log;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.SurroundingText;
import com.googlecode.tesseract.android.TessBaseAPI;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.function.Consumer;

/** Visual field targeting + API 33 accessibility input connection. No node-tree or clipboard use. */
final class TextEntryFlow {
    private final VisualControlRunner runner;
    private final AccessibilityService service;
    private final TextInstruction instruction;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService inputWorker = Executors.newSingleThreadExecutor();
    private final JSONObject record = new JSONObject();
    private final JSONArray events = new JSONArray();
    private final long started = SystemClock.elapsedRealtime();
    private volatile Rect field;
    private volatile Rect tappedField;
    private long focusBaselineGeneration, focusedGeneration;
    private long focusTapElapsedMs;
    private int focusCycle;
    private AgentInputMethod method;
    private boolean ending;
    private static final int MAX_FOCUS_CYCLES = 3;
    private static final int FOCUS_POLL_MAX = 16;

    TextEntryFlow(VisualControlRunner runner, AccessibilityService service, TextInstruction instruction) throws Exception {
        this.runner = runner; this.service = service; this.instruction = instruction;
        record.put("run_id", instruction.id).put("requested_text", instruction.text)
            .put("field_hint", instruction.fieldHint).put("package", instruction.targetPackage)
            .put("mechanism", "AccessibilityInputConnection.commitText")
            .put("started_at_ms", System.currentTimeMillis()).put("started_elapsed_ms", started)
            .put("timeout_ms", instruction.timeoutMs).put("status", "RUNNING")
            .put("field_bounds", JSONObject.NULL).put("pre_screenshot", JSONObject.NULL)
            .put("post_screenshot", JSONObject.NULL).put("verification_result", "NOT_VERIFIED")
            .put("input_attempts", 0).put("events", events);
        checkpoint("STARTED");
    }

    void start() {
        if (android.os.Build.VERSION.SDK_INT < 33 || !(service.getInputMethod() instanceof AgentInputMethod)) {
            end("INPUT_FAILED", "Accessibility input method unavailable (requires API 33 and IME flag)"); return;
        }
        method = (AgentInputMethod) service.getInputMethod();
        locate(0);
    }

    private boolean live() { return !ending && runner.withinDeadline(instruction.id); }
    private void end(String status, String detail) {
        if (!live()) return;
        ending = true;
        if (!"PASS".equals(status) && record.isNull("post_screenshot")) {
            // Capture the actual failed state, too. The same hard deadline still applies.
            runner.frame(instruction.id, "after", ignored -> {
                put("post_screenshot", imagePath("after"));
                runner.finish(instruction.id, status, detail);
            });
        } else runner.finish(instruction.id, status, detail);
    }
    private String imagePath(String phase) { return "files/visual/" + instruction.id + "/" + phase + ".png"; }

    private void locate(int attempt) {
        if (!live()) return;
        checkpoint(attempt == 0 && focusCycle == 0 ? "LOCATING" : "LOCATING_RETRY");
        runner.frame(instruction.id, "before", ocr -> {
            put("pre_screenshot", imagePath("before"));
            if (ocr.fieldBounds == null) {
                if (attempt < 1) { main.postDelayed(() -> locate(attempt + 1), 700); return; }
                end("FIELD_NOT_FOUND", "No unique outlined field containing OCR hint " + instruction.fieldHint); return;
            }
            field = new Rect(ocr.fieldBounds);
            tappedField = new Rect(ocr.fieldBounds);
            put("field_bounds", coordinates(field));
            put("focus_cycle", focusCycle);
            // Never type into a pre-existing/stale IME session from another field or auto-focus.
            if (hasActiveEditorSession()) {
                checkpoint("FOCUS_BLUR_STALE");
                blurThenFocus();
            } else {
                dispatchFocusTap();
            }
        });
    }

    private boolean hasActiveEditorSession() {
        return method.getCurrentInputStarted() && method.getCurrentInputConnection() != null;
    }

    private void blurThenFocus() {
        if (!live() || field == null) return;
        float x = field.exactCenterX();
        float y = Math.min(field.bottom + 140f, field.exactCenterY() + 220f);
        put("blur_tap_xy", new JSONArray().put((int) x).put((int) y));
        tapAt(x, y, () -> waitForBlur(0), "Focus blur gesture cancelled/rejected");
    }

    private void waitForBlur(int attempt) {
        if (!live()) return;
        if (!hasActiveEditorSession()) {
            checkpoint("FOCUS_BLURRED");
            main.postDelayed(this::dispatchFocusTap, 180);
            return;
        }
        if (attempt < 12) {
            main.postDelayed(() -> waitForBlur(attempt + 1), 150);
            return;
        }
        // Bounded: still attempt a fresh field tap; waitForFocus rejects unchanged generation.
        checkpoint("FOCUS_BLUR_TIMEOUT");
        dispatchFocusTap();
    }

    private void dispatchFocusTap() {
        if (!live() || field == null) return;
        focusBaselineGeneration = method.generation();
        focusTapElapsedMs = SystemClock.elapsedRealtime();
        put("focus_baseline_generation", focusBaselineGeneration);
        put("focus_tap_elapsed_ms", focusTapElapsedMs);
        put("focus_tap_xy", new JSONArray().put((int) field.exactCenterX()).put((int) field.exactCenterY()));
        checkpoint("FOCUS_DISPATCHING");
        tapAt(field.exactCenterX(), field.exactCenterY(), () -> {
            checkpoint("FOCUS_GESTURE_COMPLETED");
            waitForFocus(0);
        }, "Focus gesture cancelled/rejected");
    }

    private void tapAt(float x, float y, Runnable onDone, String failDetail) {
        Path path = new Path();
        path.moveTo(x, y);
        GestureDescription tap = new GestureDescription.Builder()
            .addStroke(new GestureDescription.StrokeDescription(path, 0, 100)).build();
        boolean accepted = service.dispatchGesture(tap, new AccessibilityService.GestureResultCallback() {
            @Override public void onCompleted(GestureDescription gesture) {
                if (live()) onDone.run();
            }
            @Override public void onCancelled(GestureDescription gesture) {
                end("FOCUS_FAILED", failDetail);
            }
        }, main);
        if (!accepted) end("FOCUS_FAILED", failDetail);
    }

    private boolean editorMatches() {
        EditorInfo info = method.getCurrentInputEditorInfo();
        if (!method.getCurrentInputStarted() || info == null || !instruction.targetPackage.equals(info.packageName)
                || method.getCurrentInputConnection() == null) return false;
        int variation = info.inputType & 0xfff;
        // Never use this plaintext evidence flow for password editors.
        return variation != 0x81 && variation != 0x91 && variation != 0xe1 && variation != 0x12;
    }

    private boolean isImeWindowVisible() {
        try {
            java.util.List<AccessibilityWindowInfo> windows = service.getWindows();
            if (windows == null) return false;
            for (AccessibilityWindowInfo w : windows) {
                if (w != null && w.getType() == AccessibilityWindowInfo.TYPE_INPUT_METHOD) return true;
            }
        } catch (Exception ignored) {}
        return false;
    }

    private boolean freshSessionAfterTap() {
        if (!editorMatches()) return false;
        // Hard rule: session generation must advance after our focus tap (no stale reuse).
        if (method.generation() <= focusBaselineGeneration) return false;
        // Session start timestamp must be at/after the tap (when available).
        long started = method.lastStartElapsedMs();
        return started == 0 || started + 50 >= focusTapElapsedMs;
    }

    private void waitForFocus(int attempt) {
        if (!live()) return;
        boolean fresh = freshSessionAfterTap();
        boolean ime = isImeWindowVisible();
        if (fresh) {
            focusedGeneration = method.generation();
            put("editor_package", method.getCurrentInputEditorInfo().packageName);
            put("editor_generation", focusedGeneration);
            put("editor_start_elapsed_ms", method.lastStartElapsedMs());
            put("ime_window_visible", ime);
            try {
                put("focus_signals", new JSONObject()
                    .put("fresh_generation", true)
                    .put("generation", focusedGeneration)
                    .put("baseline_generation", focusBaselineGeneration)
                    .put("ime_window_visible", ime)
                    .put("focus_cycle", focusCycle));
            } catch (Exception e) { throw new IllegalStateException(e); }
            checkpoint("FOCUS_CONFIRMED");
            runner.frame(instruction.id, "focused", ocr -> {
                put("focused_screenshot", imagePath("focused"));
                if (ocr.fieldBounds == null) {
                    end("FOCUS_FAILED", "Field no longer visually identifiable after focus"); return;
                }
                Rect after = new Rect(ocr.fieldBounds);
                put("focused_field_bounds", coordinates(after));
                if (tappedField != null && !boundsStillMatch(tappedField, after)) {
                    put("wrong_field", true);
                    end("FOCUS_FAILED", "Focused field bounds no longer match the visually tapped target"); return;
                }
                field = after;
                put("wrong_field", false);
                readEditor(value -> replace(value));
            });
            return;
        }
        if (attempt < FOCUS_POLL_MAX) {
            main.postDelayed(() -> waitForFocus(attempt + 1), 200);
            return;
        }
        if (focusCycle + 1 < MAX_FOCUS_CYCLES) {
            focusCycle++;
            put("focus_retry", focusCycle);
            checkpoint("FOCUS_RETRY_RELOCATE");
            // Recapture -> relocate field -> tap once more (after blur if needed).
            locate(0);
            return;
        }
        put("ime_window_visible", ime);
        put("focus_baseline_generation", focusBaselineGeneration);
        put("editor_generation_final", method.generation());
        put("had_active_editor", hasActiveEditorSession());
        end("FOCUS_FAILED", "No fresh input session for the visually tapped field");
    }

    private static boolean boundsStillMatch(Rect tapped, Rect focused) {
        if (tapped == null || focused == null) return false;
        if (Math.abs(tapped.centerX() - focused.centerX()) > 96) return false;
        if (Math.abs(tapped.centerY() - focused.centerY()) > 72) return false;
        Rect overlap = new Rect(tapped);
        return overlap.intersect(focused);
    }

    private boolean sameEditor() { return editorMatches() && method.generation() == focusedGeneration; }

    private void readEditor(Consumer<String> next) {
        if (!live()) return;
        if (!sameEditor()) { end("INPUT_FAILED", "Editor focus changed or input connection disappeared"); return; }
        AccessibilityInputConnection connection = method.getCurrentInputConnection();
        inputWorker.execute(() -> {
            try {
                SurroundingText surrounding = connection.getSurroundingText(2048, 2048, 0);
                String value = surrounding == null ? null : surrounding.getText().toString();
                boolean complete = surrounding != null && surrounding.getOffset() == 0 && value.length() < 2048;
                main.post(() -> {
                    if (!live()) return;
                    if (!sameEditor() || !complete) {
                        end("INPUT_FAILED", "Cannot read the complete current editor value"); return;
                    }
                    try { next.accept(value); }
                    catch (Exception e) { end("INPUT_FAILED", "Input operation failed: " + e); }
                });
            } catch (Exception e) { main.post(() -> { if (live()) end("INPUT_FAILED", "Input read failed: " + e); }); }
        });
    }

    private void replace(String before) {
        if (!live() || !sameEditor()) { if (live()) end("INPUT_FAILED", "Focus lost before commit"); return; }
        put("prior_text_length", before.length());
        put("input_attempts", 1);
        // Persist before the effect. A restart never replays uncertain text insertion.
        checkpoint("INPUT_COMMITTING");
        AccessibilityInputConnection connection = method.getCurrentInputConnection();
        connection.setSelection(0, before.length());
        connection.commitText(instruction.text, 1, null);
        checkpoint("INPUT_SENT");
        main.postDelayed(() -> verify(0), 600);
    }

    private static final int OCR_VERIFY_ATTEMPTS = 3;

    private void verify(int attempt) {
        if (!live()) return;
        checkpoint("VERIFYING");
        runner.frame(instruction.id, "after", ocr -> {
            put("post_screenshot", imagePath("after"));
            put("visible_field_text", ocr.fieldText);
            put("ocr_verify_attempt", attempt);
            // Recapture search-field bounds after typing; refuse if the tapped field drifted.
            if (ocr.fieldBounds != null) {
                put("post_field_bounds", coordinates(ocr.fieldBounds));
                if (tappedField != null && !boundsStillMatch(tappedField, ocr.fieldBounds)) {
                    put("wrong_field", true);
                    end("TEXT_NOT_VERIFIED", "Search field bounds changed after typing");
                    return;
                }
                field = new Rect(ocr.fieldBounds);
            }
            readEditor(value -> {
                boolean exact = instruction.text.equals(value);
                boolean visible = visualFieldMatches(instruction.text, ocr);
                boolean boundsOk = tappedField != null && field != null && boundsStillMatch(tappedField, field);
                boolean fresh = focusedGeneration > focusBaselineGeneration && sameEditor();
                put("observed_text", value);
                put("exact_input_match", exact);
                put("visual_text_match", visible);
                put("bounds_unchanged", boundsOk);
                put("focus_session_fresh", fresh);
                if (!exact) {
                    if (attempt + 1 < OCR_VERIFY_ATTEMPTS) {
                        main.postDelayed(() -> verify(attempt + 1), 450);
                        return;
                    }
                    end("TEXT_NOT_VERIFIED", "Editor value differs from requested text");
                    return;
                }
                // Hard path: exact injected editor text AND OCR agree.
                if (visible) {
                    put("verification_result", "EXACT_INPUT_AND_SCREENSHOT_OCR");
                    put("ocr_gate", "HARD_MATCH");
                    end("PASS", "Exact editor value and visible field OCR verified");
                    return;
                }
                // OCR is supporting evidence only when editor is exact, bounds unchanged, and focus is fresh.
                // Retry OCR/recapture before soft-passing imperfect field OCR (B/S, I/l, 0/O, rn/m noise).
                if (boundsOk && fresh) {
                    if (attempt + 1 < OCR_VERIFY_ATTEMPTS) {
                        main.postDelayed(() -> verify(attempt + 1), 450);
                        return;
                    }
                    put("verification_result", "EXACT_INPUT_OCR_SOFT");
                    put("ocr_gate", "SOFT_SUPPORTING");
                    put("ocr_soft_pass", true);
                    end("PASS", "Exact editor value verified; OCR supporting evidence imperfect but field/focus gates held");
                    return;
                }
                if (attempt + 1 < OCR_VERIFY_ATTEMPTS) {
                    main.postDelayed(() -> verify(attempt + 1), 450);
                    return;
                }
                end("TEXT_NOT_VERIFIED", "Exact editor text present but field/focus gates failed with imperfect OCR");
            });
        });
    }

    /** Exact OCR agreement only — never a fixture-identity substitute. */
    private static boolean visualFieldMatches(String requested, VisualControlRunner.Ocr ocr) {
        if (requested == null || ocr == null) return false;
        String want = normalizeWords(requested);
        if (want.equals(ocr.fieldText)) return true;
        if (ocr.words != null) {
            for (String word : ocr.words) {
                if (requested.equalsIgnoreCase(word) || want.equalsIgnoreCase(normalizeWords(word))) return true;
            }
        }
        return false;
    }

    private static String normalizeWords(String value) { return value.trim().replaceAll("\\s+", " "); }

    /** Called only on the existing OCR worker; no UI interaction occurs here. */
    void analyze(Bitmap bitmap, VisualControlRunner.Ocr ocr, String phase) throws Exception {
        List<Rect> hints = ocr.bounds(instruction.fieldHint);
        if (hints.isEmpty() && "before".equals(phase)) {
            Bitmap clean = withoutLongRules(bitmap);
            VisualControlRunner.Ocr sparse;
            try { sparse = runner.recognize(clean, TessBaseAPI.PageSegMode.PSM_SPARSE_TEXT); }
            finally { clean.recycle(); }
            hints = sparse.bounds(instruction.fieldHint);
            if (!hints.isEmpty()) { ocr.words.clear(); ocr.rects.clear(); ocr.words.addAll(sparse.words); ocr.rects.addAll(sparse.rects); }
        }
        if (hints.size() == 1) {
            ocr.fieldBounds = findOutline(bitmap, hints.get(0));
            if (ocr.fieldBounds == null) {
                // Generic fallback for outlined-less search fields (e.g. live Bet365): expand the unique OCR hint.
                Rect h = hints.get(0);
                ocr.fieldBounds = new Rect(Math.max(0, h.left - 48), Math.max(0, h.top - 24),
                        Math.min(bitmap.getWidth() - 1, h.right + 220), Math.min(bitmap.getHeight() - 1, h.bottom + 24));
            }
        }
        Rect current = field;
        // A blinking caret can merge with placeholder text in full-screen OCR.
        // Reuse the previously measured rectangle only when its actual border is still present.
        if ("focused".equals(phase) && ocr.fieldBounds == null && current != null && validOutline(bitmap, current)) {
            ocr.fieldBounds = new Rect(current);
        }
        if ("after".equals(phase) && current != null) {
            // Recapture outlined field after typing; fall back to prior bounds when outline still valid.
            Rect recaptured = findOutline(bitmap, current);
            if (recaptured != null && boundsStillMatch(current, recaptured)) {
                ocr.fieldBounds = recaptured;
            } else if (validOutline(bitmap, current)) {
                ocr.fieldBounds = new Rect(current);
            }
            Rect cropBounds = ocr.fieldBounds != null ? ocr.fieldBounds : current;
            Rect inside = new Rect(cropBounds); inside.inset(9, 9);
            if (inside.width() > 8 && inside.height() > 8) {
                Bitmap crop = Bitmap.createBitmap(bitmap, inside.left, inside.top, inside.width(), inside.height());
                try {
                    VisualControlRunner.Ocr text = runner.recognize(crop, TessBaseAPI.PageSegMode.PSM_SINGLE_LINE);
                    ocr.fieldText = normalizeWords(String.join(" ", text.words));
                    try (FileOutputStream out = new FileOutputStream(new File(service.getFilesDir(), "visual/" + instruction.id + "/field_after.png"))) {
                        crop.compress(Bitmap.CompressFormat.PNG, 100, out);
                    }
                } finally { crop.recycle(); }
            }
        }
    }

    /** Remove long straight rules only in the OCR copy; bounds still come from original pixels. */
    private static Bitmap withoutLongRules(Bitmap source) {
        int width = source.getWidth(), height = source.getHeight();
        int[] pixels = new int[width * height]; source.getPixels(pixels, 0, width, 0, 0, width, height);
        int[] clean = pixels.clone();
        for (int y = 0; y < height; y++) {
            int start = -1;
            for (int x = 0; x <= width; x++) {
                if (x < width && darkPixel(pixels[y * width + x])) { if (start < 0) start = x; }
                else { if (start >= 0 && x - start > width / 3) for (int k = start; k < x; k++) clean[y * width + k] = Color.WHITE; start = -1; }
            }
        }
        for (int x = 0; x < width; x++) {
            int start = -1;
            for (int y = 0; y <= height; y++) {
                if (y < height && darkPixel(pixels[y * width + x])) { if (start < 0) start = y; }
                else { if (start >= 0 && y - start > 80) for (int k = start; k < y; k++) clean[k * width + x] = Color.WHITE; start = -1; }
            }
        }
        return Bitmap.createBitmap(clean, width, height, Bitmap.Config.ARGB_8888);
    }
    private static boolean darkPixel(int pixel) {
        return Color.red(pixel) * 299 + Color.green(pixel) * 587 + Color.blue(pixel) * 114 < 128000;
    }

    private static boolean dark(Bitmap bitmap, int x, int y) {
        int pixel = bitmap.getPixel(x, y);
        return Color.red(pixel) * 299 + Color.green(pixel) * 587 + Color.blue(pixel) * 114 < 128000;
    }

    /** Locate enclosing rectangular borders around an OCR placeholder, entirely from pixels. */
    static Rect findOutline(Bitmap bitmap, Rect hint) {
        int cy = hint.centerY(), left = -1, right = -1;
        int span = hint.height() / 2 + 8;
        if (cy - span < 0 || cy + span >= bitmap.getHeight()) return null;
        for (int x = hint.left - 1; x >= 0; x--) {
            if (vertical(bitmap, x, cy - span, cy + span)) { left = x; break; }
        }
        for (int x = hint.right + 1; x < bitmap.getWidth(); x++) {
            if (vertical(bitmap, x, cy - span, cy + span)) { right = x; break; }
        }
        if (left < 0 || right < 0 || right - left <= hint.width()) return null;
        int top = cy, bottom = cy;
        while (top > 0 && dark(bitmap, left, top - 1)) top--;
        while (bottom + 1 < bitmap.getHeight() && dark(bitmap, left, bottom + 1)) bottom++;
        Rect result = new Rect(left, top, right + 1, bottom + 1);
        return result.height() > hint.height() + 16 && validOutline(bitmap, result) ? result : null;
    }

    private static boolean vertical(Bitmap bitmap, int x, int top, int bottom) {
        for (int y = top; y <= bottom; y++) if (!dark(bitmap, x, y)) return false;
        return true;
    }

    private static boolean validOutline(Bitmap bitmap, Rect rect) {
        if (rect.left < 0 || rect.top < 0 || rect.right > bitmap.getWidth() || rect.bottom > bitmap.getHeight()
                || rect.width() <= 20 || rect.height() <= 20) return false;
        int hits = 0, total = 0;
        for (int x = rect.left; x < rect.right; x += 3) {
            total += 2;
            if (dark(bitmap, x, rect.top + 1)) hits++;
            if (dark(bitmap, x, rect.bottom - 2)) hits++;
        }
        return hits >= total * .9;
    }

    private static JSONArray coordinates(Rect rect) {
        return new JSONArray().put(rect.left).put(rect.top).put(rect.right).put(rect.bottom);
    }
    private void put(String key, Object value) {
        try { record.put(key, value); } catch (Exception e) { throw new IllegalStateException(e); }
    }
    private void checkpoint(String phase) {
        put("phase", phase);
        try { events.put(new JSONObject().put("phase", phase).put("elapsed_ms", SystemClock.elapsedRealtime() - started)); }
        catch (Exception e) { throw new IllegalStateException(e); }
        persist(service, record);
        Log.i("AgentText", "id=" + instruction.id + " phase=" + phase);
    }

    void finished(String status, String detail) {
        ending = true;
        main.removeCallbacksAndMessages(null);
        inputWorker.shutdownNow();
        put("status", status); put("detail", detail);
        put("ended_at_ms", System.currentTimeMillis());
        put("duration_ms", SystemClock.elapsedRealtime() - started);
        if (record.isNull("pre_screenshot") && new File(service.getFilesDir(), "visual/" + instruction.id + "/before.png").isFile()) {
            put("pre_screenshot", imagePath("before"));
        }
        if (record.isNull("post_screenshot")) put("post_screenshot_unavailable_reason", "Terminated before an after-frame completed");
        if (!"PASS".equals(status)) put("verification_result", "NOT_VERIFIED");
        checkpoint("FINISHED");
        Log.i("AgentText", "RESULT " + record);
    }

    static void recover(AccessibilityService service) {
        String saved = service.getSharedPreferences("text_agent", 0).getString("record", "");
        if (saved.isEmpty()) return;
        try {
            JSONObject value = new JSONObject(saved);
            if (!"RUNNING".equals(value.optString("status"))) return;
            value.put("status", "INTERRUPTED").put("phase", "FINISHED")
                .put("detail", "Service restarted; uncertain input is not replayed")
                .put("verification_result", "NOT_VERIFIED").put("ended_at_ms", System.currentTimeMillis())
                .put("duration_ms", SystemClock.elapsedRealtime() - value.getLong("started_elapsed_ms"));
            if (value.isNull("post_screenshot")) value.put("post_screenshot_unavailable_reason", "Process stopped before after-frame verification");
            persist(service, value);
            Log.i("AgentText", "RECOVERED " + value);
        } catch (Exception e) { Log.e("AgentText", "Recovery record failure", e); }
    }

    private static void persist(AccessibilityService service, JSONObject value) {
        try {
            String json = value.toString(2);
            File dir = new File(service.getFilesDir(), "text/" + value.getString("run_id"));
            if (!dir.isDirectory() && !dir.mkdirs()) throw new IllegalStateException("Cannot create evidence directory");
            AtomicFile file = new AtomicFile(new File(dir, "result.json"));
            FileOutputStream out = file.startWrite();
            try { out.write(json.getBytes(StandardCharsets.UTF_8)); file.finishWrite(out); }
            catch (Exception e) { file.failWrite(out); throw e; }
            SharedPreferences prefs = service.getSharedPreferences("text_agent", 0);
            if (!prefs.edit().putString("record", json).commit()) throw new IllegalStateException("Cannot persist text state");
        } catch (Exception e) { throw new IllegalStateException("Evidence persistence failed", e); }
    }
}
