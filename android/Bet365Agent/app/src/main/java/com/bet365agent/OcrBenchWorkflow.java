package com.bet365agent;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.os.Handler;
import android.os.Looper;
import java.io.File;
import java.util.ArrayList;
import java.util.List;
import org.json.JSONArray;
import org.json.JSONObject;

/**
 * OCR_BENCH (Milestone C1/C4): OCR stored frames (files/visual/<run>/<name>.png) with a named engine and
 * run the SAME parsers the live workflow uses on the result, so accuracy is measured on what matters
 * (lines, signs, prices, stake, To Return, receipt, header, My Bets), not on raw text. Never touches the
 * screen, never taps. Frames: JSON array of {p: "run/name.png", c: class, ...truth fields the parser needs}.
 */
final class OcrBenchWorkflow {
    private final VisualSession session;
    private final File filesDir;
    private final VisualControlRunner runner;
    private final String framesJson, engine;
    private final Handler main = new Handler(Looper.getMainLooper());

    OcrBenchWorkflow(VisualSession session, File filesDir, VisualControlRunner runner, String framesJson, String engine) {
        this.session = session; this.filesDir = filesDir; this.runner = runner; this.framesJson = framesJson; this.engine = engine;
    }

    void start() {
        session.checkpoint("OCR_BENCH");
        new Thread(() -> {
            JSONArray out = new JSONArray();
            try {
                JSONArray frames = new JSONArray(framesJson);
                for (int i = 0; i < frames.length(); i++) out.put(one(frames.getJSONObject(i)));
                JSONArray result = out;
                main.post(() -> {
                    session.put("bench", CoordinatorAgent.object("engine", engine, "frames", result));
                    session.put("verification_detail", "OCR benchmark: " + result.length() + " stored frames, engine " + engine + "; no screen interaction");
                    session.finish("PASS", "OCR_BENCH");
                });
            } catch (Exception e) {
                main.post(() -> session.finish("INTERNAL_ERROR", "OCR_BENCH: " + e));
            }
        }, "ocr-bench").start();
    }

    private JSONObject one(JSONObject spec) {
        String path = spec.optString("p", ""), cls = spec.optString("c", "other");
        JSONObject r = CoordinatorAgent.object("p", path, "c", cls, "engine", engine);
        if (!path.matches("[A-Za-z0-9_-]{1,64}/[A-Za-z0-9_.-]{1,80}\\.png")) { CoordinatorAgent.put(r, "error", "bad path"); return r; }
        File file = new File(filesDir, "visual/" + path);
        if (!file.isFile()) { CoordinatorAgent.put(r, "error", "missing"); return r; }
        Bitmap bitmap = BitmapFactory.decodeFile(file.getAbsolutePath());
        if (bitmap == null) { CoordinatorAgent.put(r, "error", "undecodable"); return r; }
        boolean table = "grid".equals(cls) || spec.optBoolean("table", false);
        try {
            long t0 = android.os.SystemClock.elapsedRealtime();
            VisualControlRunner.Ocr ocr = runner.benchOcr(bitmap, table, engine);
            long ms = android.os.SystemClock.elapsedRealtime() - t0;
            VisualScreen s = new VisualScreen(ocr);
            CoordinatorAgent.put(r, "latency_ms", ms);
            CoordinatorAgent.put(r, "table", table);
            CoordinatorAgent.put(r, "word_count", ocr.words.size());
            List<String> texts = Bet365LiveAdapter.texts(s);
            List<GameLinesParser.Word> words = Bet365LiveAdapter.wordsOf(s);
            StringBuilder joined = new StringBuilder();
            for (String t : texts) { if (joined.length() > 500) break; joined.append(t).append(" | "); }
            CoordinatorAgent.put(r, "text", joined.toString());
            switch (cls) {
                case "grid": {
                    GameLinesParser.Result g = GameLinesParser.parse(words, spec.optString("home"), spec.optString("away"));
                    JSONArray cells = new JSONArray();
                    for (GameLinesParser.Cell c : g.cells) cells.put(c.toString());
                    CoordinatorAgent.put(r, "parsed", CoordinatorAgent.object("grid", g.grid, "cells", cells, "notes", new JSONArray(g.notes)));
                    break;
                }
                case "slip": {
                    StakePad.Check c = StakePad.check(words, spec.optString("stake", "0.10"), spec.optString("price", "1.83"));
                    boolean line = PlacementClassifier.slipShowsLine(texts, spec.optString("market"), spec.optString("side"), spec.optString("name"), spec.optString("line"));
                    boolean price = false, place = false;
                    for (String t : texts) { if (t.contains(spec.optString("price", "1.83"))) price = true; if (t.toLowerCase().contains("place bet")) place = true; }
                    CoordinatorAgent.put(r, "parsed", CoordinatorAgent.object("stake_ok", c.ok, "stake_detail", c.detail, "stake_digits", String.valueOf(c.stakeDigits),
                            "return_digits", String.valueOf(c.returnDigits), "line_shown", line, "price_shown", price, "place_bet", place,
                            "field_state", StakePad.fieldState(words)));
                    break;
                }
                case "keypad": {
                    java.util.Map<Character, int[]> keys = StakePad.keypad(words, 850);
                    JSONObject parsed = CoordinatorAgent.object("keypad", keys != null, "field_state", StakePad.fieldState(words),
                            "zero", keys == null ? JSONObject.NULL : new JSONArray(java.util.Arrays.asList(keys.get('0')[0], keys.get('0')[1])));
                    if (spec.has("stake")) {
                        // typed-stake frames: the live check at this stage is the strict stake + To Return readback
                        StakePad.Check c = StakePad.check(words, spec.optString("stake", "0.10"), spec.optString("price", "1.83"));
                        CoordinatorAgent.put(parsed, "stake_ok", c.ok); CoordinatorAgent.put(parsed, "stake_detail", c.detail);
                        CoordinatorAgent.put(parsed, "stake_digits", String.valueOf(c.stakeDigits)); CoordinatorAgent.put(parsed, "return_digits", String.valueOf(c.returnDigits));
                    }
                    CoordinatorAgent.put(r, "parsed", parsed);
                    break;
                }
                case "receipt": {
                    boolean place = false;
                    for (String t : texts) if (t.toLowerCase().contains("place bet")) place = true;
                    PlacementClassifier.Result c = PlacementClassifier.classify(texts, place);
                    String reference = c.betReference, legacyRef = null;
                    if ("hybrid".equals(engine) && reference != null) {
                        // same rule as the live path: Tesseract re-reads the Bet Ref line; the fast reading is kept, a disagreement is flagged
                        for (VisualScreen.Line line : s.lines) if (line.text.toLowerCase(java.util.Locale.US).contains("bet ref")) {
                            android.graphics.Rect crop = new android.graphics.Rect(line.bounds); crop.inset(-8, -8);
                            if (crop.intersect(0, 0, bitmap.getWidth(), bitmap.getHeight())) {
                                Bitmap region = Bitmap.createBitmap(bitmap, crop.left, crop.top, crop.width(), crop.height());
                                Bitmap big = VisualControlRunner.enhance(region);
                                VisualControlRunner.Ocr o = runner.recognize(big, com.googlecode.tesseract.android.TessBaseAPI.PageSegMode.PSM_SINGLE_LINE);
                                big.recycle();
                                if (region != bitmap) region.recycle();
                                legacyRef = PlacementClassifier.reference(java.util.Collections.singletonList(String.join(" ", o.words)));
                            }
                            break;
                        }
                    }
                    CoordinatorAgent.put(r, "parsed", CoordinatorAgent.object("outcome", c.outcome, "definitive", c.definitive,
                            "bet_reference", reference == null ? JSONObject.NULL : reference, "bet_reference_fast", c.betReference == null ? JSONObject.NULL : c.betReference,
                            "bet_reference_legacy", legacyRef == null ? JSONObject.NULL : legacyRef, "bet_reference_disputed", legacyRef != null && !legacyRef.equals(reference),
                            "stake", c.stake == null ? JSONObject.NULL : c.stake,
                            "return", c.potentialReturn == null ? JSONObject.NULL : c.potentialReturn));
                    break;
                }
                case "header": {
                    List<String> header = new ArrayList<>();
                    for (VisualScreen.Line line : s.lines) if (line.bounds.top >= 230 && line.bounds.top <= 480) header.add(line.text);
                    String[] teams = EventPage.teams(header);
                    CoordinatorAgent.put(r, "parsed", CoordinatorAgent.object("home", teams == null ? JSONObject.NULL : teams[0], "away", teams == null ? JSONObject.NULL : teams[1],
                            "kickoff", EventPage.kickoffText(header) == null ? JSONObject.NULL : EventPage.kickoffText(header), "closed", EventPage.closed(texts)));
                    break;
                }
                case "mybets": {
                    JSONArray lines = new JSONArray();
                    for (VisualScreen.Line line : s.lines) lines.put(CoordinatorAgent.object("text", line.text, "top", line.bounds.top, "left", line.bounds.left, "frame", 0));
                    CoordinatorAgent.put(r, "parsed", CoordinatorAgent.object("lines", lines));
                    break;
                }
                default:
                    break;
            }
        } catch (Exception e) {
            CoordinatorAgent.put(r, "error", String.valueOf(e));
        } finally {
            bitmap.recycle();
        }
        return r;
    }
}
