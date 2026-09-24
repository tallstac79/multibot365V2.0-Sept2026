from pathlib import Path

ba = Path('android/Bet365Agent/app/src/main/java/com/bet365agent/Bet365LiveAdapter.java')
bt = ba.read_text(encoding='utf-8')
old = '''    private CompletableFuture<VisualScreen> typeSearchQueryOnce(String queryText) {
        final String typedQuery = sanitizeSearchTyped(queryText);
        return ui.capture("query_pre").thenCompose(s -> {
            require(!visible(s, "SIMULATOR", "SEARCHPAGE"), "TARGET_NOT_FOUND", "Simulator leaked into live search");
            if (hasLiveSearchResults(s, typedQuery)) {
                return ui.dismissKeyboard().thenCompose(v -> ui.delay(400)).thenCompose(v -> ui.capture("query_results"));
            }
            VisualScreen.Line recent = recentSearchChip(s, typedQuery);
            if (recent != null) {
                return ui.tap(recent.bounds, "Recent " + typedQuery).thenCompose(v -> ui.delay(1200))
                        .thenCompose(v -> ui.capture("query_results"));
            }
            CompletableFuture<Void> clear = CompletableFuture.completedFuture(null);
            VisualScreen.Line clearBtn = null;
            for (VisualScreen.Line line : s.lines) {
                if (line.text.equalsIgnoreCase("x") && line.bounds.top < 280 && line.bounds.left > 400) { clearBtn = line; break; }
            }
            if (clearBtn != null) {
                VisualScreen.Line btn = clearBtn;
                clear = ui.tap(btn.bounds, "Clear search").thenCompose(v -> ui.delay(400));
            }
            String hint = visible(s, "bet365...") ? "bet365..." : "Search";
            return clear.thenCompose(v -> ui.type(hint, typedQuery)).thenCompose(v -> ui.dismissKeyboard())
                    .thenCompose(v -> ui.delay(900)).thenCompose(v -> ui.capture("query_results"));
        }).thenApply(r -> {
            require(!visible(r, "SIMULATOR", "SEARCHPAGE"), "TARGET_NOT_FOUND", "Simulator leaked into live search");
            return r;
        });
    }'''
new = '''    private CompletableFuture<VisualScreen> typeSearchQueryOnce(String queryText) {
        final String typedQuery = sanitizeSearchTyped(queryText);
        ui.checkpoint("ENTER_QUERY");
        return ui.capture("query_pre").thenCompose(s -> {
            require(!visible(s, "SIMULATOR", "SEARCHPAGE"), "TARGET_NOT_FOUND", "Simulator leaked into live search");
            if (hasLiveSearchResults(s, typedQuery)) {
                ui.checkpoint("RESULTS_WAIT");
                return ui.dismissKeyboard().thenCompose(v -> ui.delay(400)).thenCompose(v -> ui.capture("query_results"));
            }
            VisualScreen.Line recent = recentSearchChip(s, typedQuery);
            if (recent != null) {
                ui.checkpoint("QUERY_VERIFY");
                return ui.tap(recent.bounds, "Recent " + typedQuery).thenCompose(v -> ui.delay(1200))
                        .thenCompose(v -> { ui.checkpoint("RESULTS_WAIT"); return ui.capture("query_results"); });
            }
            CompletableFuture<Void> clear = CompletableFuture.completedFuture(null);
            VisualScreen.Line clearBtn = null;
            for (VisualScreen.Line line : s.lines) {
                if (line.text.equalsIgnoreCase("x") && line.bounds.top < 280 && line.bounds.left > 400) { clearBtn = line; break; }
            }
            if (clearBtn != null) {
                VisualScreen.Line btn = clearBtn;
                clear = ui.tap(btn.bounds, "Clear search").thenCompose(v -> ui.delay(400));
            }
            String hint = visible(s, "bet365...") ? "bet365..." : "Search";
            return clear.thenCompose(v -> ui.type(hint, typedQuery)).thenCompose(v -> {
                        ui.checkpoint("QUERY_VERIFY");
                        return ui.dismissKeyboard();
                    })
                    .thenCompose(v -> ui.delay(900)).thenCompose(v -> {
                        ui.checkpoint("RESULTS_WAIT");
                        return ui.capture("query_results");
                    });
        }).thenApply(r -> {
            require(!visible(r, "SIMULATOR", "SEARCHPAGE"), "TARGET_NOT_FOUND", "Simulator leaked into live search");
            return r;
        });
    }'''
if old not in bt:
    raise SystemExit('typeSearchQueryOnce not found exact')
ba.write_text(bt.replace(old, new, 1), encoding='utf-8')
print('OK typeSearchQueryOnce')

sc = Path('core/session_contract.py').read_text(encoding='utf-8')
assert 'DEFAULT_MAX_AGE_SECONDS = 120' in sc
pp = Path('core/pipeline.py').read_text(encoding='utf-8')
assert 'session_max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS' in pp
assert 'device_timeout_ms: int = 300000' in pp
print('session_max_age=120; absolute=300000 OK')

vr = Path('android/Bet365Agent/app/src/main/java/com/bet365agent/VisualControlRunner.java')
t = vr.read_text(encoding='utf-8')
t2 = t.replace('"Hard deadline expired"', '"Absolute deadline expired"')
vr.write_text(t2, encoding='utf-8')
print('runner absolute messages', t.count('Hard deadline expired'), '->', t2.count('Absolute deadline expired'))
