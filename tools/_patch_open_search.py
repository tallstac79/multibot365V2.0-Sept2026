from pathlib import Path

path = Path(r"android/Bet365Agent/app/src/main/java/com/bet365agent/Bet365LiveAdapter.java")
text = path.read_text(encoding="utf-8")
start = text.find("    public CompletableFuture<Void> open_search()")
end = text.find("    public CompletableFuture<Void> enter_query(")
if start < 0 or end < 0:
    raise SystemExit(f"markers not found start={start} end={end}")

new = r'''    public CompletableFuture<Void> open_search() {
        return openSearchAttempt(0);
    }

    /** Robust Search open: OCR label+bounds, multi-frame verify, one relocate retry. */
    private CompletableFuture<Void> openSearchAttempt(int attempt) {
        String preLabel = attempt == 0 ? "search_button" : "search_button_retry";
        String clearLabel = attempt == 0 ? "search_button_clear" : "search_button_clear_retry";
        return ui.capture(preLabel).thenCompose(s -> dismissCookiesIfPresent(s).thenCompose(v -> ui.capture(clearLabel)).thenCompose(clear -> {
            if (isSearchUiOpen(clear)) {
                ui.put("search_ui_open", true);
                ui.put("search_open_via", "already_open");
                return CompletableFuture.completedFuture(null);
            }
            VisualScreen.Line best = findHeaderSearchControl(clear);
            require(best != null, "TARGET_NOT_FOUND", "Search control not visible on live Bet365");
            android.graphics.Rect tapBox = expandSearchTapBounds(clear, best);
            require(tapBox.width() > 20 && tapBox.height() > 10, "TARGET_NOT_FOUND", "Search bounds not actionable");
            ui.put("search_control_text", best.text);
            ui.put("search_control_bounds", VisualSession.bounds(best.bounds));
            ui.put("search_tap_bounds", VisualSession.bounds(tapBox));
            ui.put("search_tap_xy", new org.json.JSONArray(java.util.Arrays.asList(tapBox.centerX(), tapBox.centerY())));
            ui.put("search_tap_attempt", attempt + 1);
            // Evidence cadence: pre-tap captured above; post-tap ~0.5s / 1.5s / 3s.
            return ui.tap(tapBox, "Search").thenCompose(x -> ui.delay(500)).thenCompose(x -> ui.capture(attempt == 0 ? "search_after_0_5s" : "search_retry_after_0_5s")).thenCompose(a1 -> {
                if (isSearchUiOpen(a1)) {
                    ui.put("search_ui_open", true);
                    ui.put("search_open_via", "verify_0_5s");
                    return CompletableFuture.completedFuture(null);
                }
                return ui.delay(1000).thenCompose(z -> ui.capture(attempt == 0 ? "search_after_1_5s" : "search_retry_after_1_5s")).thenCompose(a2 -> {
                    if (isSearchUiOpen(a2)) {
                        ui.put("search_ui_open", true);
                        ui.put("search_open_via", "verify_1_5s");
                        return CompletableFuture.completedFuture(null);
                    }
                    return ui.delay(1500).thenCompose(z2 -> ui.capture(attempt == 0 ? "search_after_3s" : "search_retry_after_3s")).thenCompose(a3 -> {
                        if (isSearchUiOpen(a3)) {
                            ui.put("search_ui_open", true);
                            ui.put("search_open_via", "verify_3s");
                            return CompletableFuture.completedFuture(null);
                        }
                        if (attempt < 1) {
                            return ui.dismissKeyboard().thenCompose(b -> ui.delay(500)).thenCompose(b -> openSearchAttempt(1));
                        }
                        ui.put("search_ui_open", false);
                        ui.put("search_ocr_readback", screenTextBlob(a3));
                        throw new Failure("TARGET_NOT_FOUND", "Live Bet365 search UI not visible after Search tap");
                    });
                });
            });
        }));
    }

    /** Positive Search UI recognition — not merely the home Search chip still visible. */
    static boolean isSearchUiOpen(VisualScreen s) {
        if (s == null) return false;
        if (visible(s, "SIMULATOR", "SEARCHPAGE", "Fictional interface")) return false;
        boolean close = visible(s, "Close");
        boolean placeholder = visible(s, "bet365...", "bet365..", "EXAMPLE", "Example");
        boolean recent = false;
        for (VisualScreen.Line line : s.lines) {
            String up = line.text.trim().toUpperCase(Locale.US);
            if (up.equals("RECENT") || up.contains("RECENT SEARCH")) { recent = true; break; }
        }
        boolean headerSearch = false;
        for (VisualScreen.Line line : s.lines) {
            String t = line.text.trim();
            if ((t.equals("Search") || t.startsWith("Search") || t.contains("Search")) && line.bounds.top < 280) {
                headerSearch = true; break;
            }
        }
        if (close && (placeholder || recent || headerSearch)) return true;
        if (placeholder && headerSearch) return true;
        if (recent && headerSearch) return true;
        for (VisualScreen.Line line : s.lines) {
            String t = line.text.toLowerCase(Locale.US);
            if (t.contains("#/ax") || t.contains("/ax/") || t.contains("#/AX")) {
                if (headerSearch || placeholder || close) return true;
            }
        }
        return false;
    }

    private static VisualScreen.Line findHeaderSearchControl(VisualScreen s) {
        VisualScreen.Line best = null;
        int bestScore = Integer.MIN_VALUE;
        for (VisualScreen.Line line : s.lines) {
            String t = line.text.trim();
            if (t.isEmpty()) continue;
            boolean exact = t.equals("Search") || t.equals("SEARCH");
            boolean soft = t.startsWith("Search") || t.contains(" Search") || t.endsWith(" Search") || t.contains("Search");
            if (!exact && !soft) continue;
            if (line.bounds.top > 700) continue;
            if (line.bounds.height() < 8 || line.bounds.width() < 20) continue;
            int score = 0;
            if (exact) score += 50;
            if (line.bounds.top < 400) score += 40;
            if (line.bounds.top < 320) score += 20;
            if (line.bounds.left < 250) score += 15;
            if (line.bounds.width() < 420) score += 10;
            if (score > bestScore) { bestScore = score; best = line; }
        }
        if (best != null) return best;
        for (VisualScreen.Line line : s.lines) {
            String t = line.text.trim();
            if ((t.equals("Q") || t.equals("q")) && line.bounds.top < 360 && line.bounds.left < 120) return line;
        }
        return null;
    }

    private static android.graphics.Rect expandSearchTapBounds(VisualScreen s, VisualScreen.Line search) {
        android.graphics.Rect box = new android.graphics.Rect(search.bounds);
        for (VisualScreen.Line line : s.lines) {
            String t = line.text.trim();
            if (!(t.equals("Q") || t.equals("q"))) continue;
            if (Math.abs(line.bounds.centerY() - search.bounds.centerY()) > 30) continue;
            if (line.bounds.left > search.bounds.right + 40) continue;
            box.union(line.bounds);
        }
        box.inset(-6, -6);
        if (box.left < 0) box.left = 0;
        if (box.top < 0) box.top = 0;
        return box;
    }

    private static String screenTextBlob(VisualScreen s) {
        StringBuilder sb = new StringBuilder();
        int n = 0;
        for (VisualScreen.Line line : s.lines) {
            if (n++ > 80) break;
            if (sb.length() > 0) sb.append(" | ");
            sb.append(line.text.trim());
            if (sb.length() > 1800) break;
        }
        return sb.toString();
    }

    /** Best-effort close of Search UI between harness iterations. */
    public CompletableFuture<Void> reset_search_ui() {
        return ui.capture("reset_search_pre").thenCompose(s -> {
            if (!isSearchUiOpen(s) && visible(s, "In-Play", "In-play", "Football", "Sports")) {
                return CompletableFuture.completedFuture(null);
            }
            VisualScreen.Line close = firstOf(s, "Close");
            if (close != null && close.bounds.top < 320) {
                return ui.tap(close.bounds, "Close search").thenCompose(v -> ui.delay(700));
            }
            return ui.dismissKeyboard().thenCompose(v -> ui.delay(400));
        });
    }

'''

path.write_text(text[:start] + new + text[end:], encoding="utf-8")
print("patched open_search ok", start, end)
