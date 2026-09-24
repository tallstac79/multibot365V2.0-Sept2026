from pathlib import Path

path = Path(r"android/Bet365Agent/app/src/main/java/com/bet365agent/TextEntryFlow.java")
text = path.read_text(encoding="utf-8")

if "AccessibilityWindowInfo" not in text:
    text = text.replace(
        "import android.accessibilityservice.GestureDescription;\n",
        "import android.accessibilityservice.AccessibilityWindowInfo;\nimport android.accessibilityservice.GestureDescription;\n",
        1,
    )

old_fields = """    private volatile Rect field;
    private long initialGeneration, focusedGeneration;
    private AgentInputMethod method;
    private boolean ending;"""

new_fields = """    private volatile Rect field;
    private volatile Rect tappedField;
    private long focusBaselineGeneration, focusedGeneration;
    private long focusTapElapsedMs;
    private int focusCycle;
    private AgentInputMethod method;
    private boolean ending;
    private static final int MAX_FOCUS_CYCLES = 3;
    private static final int FOCUS_POLL_MAX = 16;"""

if old_fields not in text:
    raise SystemExit("fields block not found")
text = text.replace(old_fields, new_fields, 1)

start = text.index("    private void locate(int attempt) {")
end = text.index("    private boolean sameEditor()")

new_methods = """    private void locate(int attempt) {
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

"""

text = text[:start] + new_methods + text[end:]
path.write_text(text, encoding="utf-8")
print("patched", path)
print("FOCUS_BLUR_STALE", "FOCUS_BLUR_STALE" in text)
print("freshSessionAfterTap", "freshSessionAfterTap" in text)
print("FOCUS_RETRY_RELOCATE", "FOCUS_RETRY_RELOCATE" in text)
print("initialGeneration left", "initialGeneration" in text)