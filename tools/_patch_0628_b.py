"""Patch AdapterWorkflow + Bet365LiveAdapter stage names."""
from pathlib import Path

ROOT = Path('.')

# ---- AdapterWorkflow ----
aw = Path('android/Bet365Agent/app/src/main/java/com/bet365agent/AdapterWorkflow.java')
text = aw.read_text(encoding='utf-8')

old_step = '''    private <T> CompletableFuture<T> step(String name,Supplier<CompletableFuture<T>> action){
        if(!session.live())return VisualSession.failed("TIMEOUT","Workflow expired");
        session.checkpoint(name);return action.get();
    }'''

new_step = '''    /** Per-stage soft budget; inactivity watchdog in CoordinatorAgent is the hard fail-closed. */
    private static final long STAGE_SOFT_MS = 60_000L;
    private <T> CompletableFuture<T> step(String name,Supplier<CompletableFuture<T>> action){
        if(!session.live())return VisualSession.failed("TIMEOUT","Workflow expired");
        session.checkpoint(name);
        final long stageStart = android.os.SystemClock.elapsedRealtime();
        return action.get().thenCompose(value -> {
            long took = android.os.SystemClock.elapsedRealtime() - stageStart;
            if (took > STAGE_SOFT_MS && session.live()) {
                // Soft budget exceeded but still live: record and continue; absolute/inactivity watchdogs decide.
                session.put("stage_soft_overrun_" + name, took);
            }
            return CompletableFuture.completedFuture(value);
        });
    }'''

if old_step not in text:
    raise SystemExit('AdapterWorkflow step not found')
text = text.replace(old_step, new_step, 1)

old_start = '''        step("OPEN_HOME",adapter::open_home)
        .thenCompose(v->step("ENSURE_SESSION",adapter::ensure_session))
        .thenCompose(v->step("OPEN_SEARCH",adapter::open_search))
        .thenCompose(v->step("ENTER_QUERY",()->adapter.enter_query(query)))
        .thenCompose(v->step("DISCOVER_FIXTURE",adapter::discover_fixture))'''

new_start = '''        step("SPORTS_HOME",adapter::open_home)
        .thenCompose(v->step("SESSION_CHECK",adapter::ensure_session))
        .thenCompose(v->step("OPEN_SEARCH",adapter::open_search))
        .thenCompose(v->step("ENTER_QUERY",()->adapter.enter_query(query)))
        .thenCompose(v->step("FIXTURE_VERIFY",adapter::discover_fixture))'''

if old_start not in text:
    raise SystemExit('AdapterWorkflow start chain not found')
text = text.replace(old_start, new_start, 1)

# SELECT_FIXTURE stays; DISCOVER_MARKETS -> MARKET_NAV for clarity in later step
text = text.replace('.thenCompose(v->step("DISCOVER_MARKETS",adapter::discover_markets))',
                    '.thenCompose(v->step("MARKET_NAV",adapter::discover_markets))', 1)

aw.write_text(text, encoding='utf-8')
print('OK AdapterWorkflow')

# ---- Bet365LiveAdapter ensureSportsContext / open_search checkpoints ----
ba = Path('android/Bet365Agent/app/src/main/java/com/bet365agent/Bet365LiveAdapter.java')
bt = ba.read_text(encoding='utf-8')

old_os = '''    public CompletableFuture<Void> open_search() {
        // Prefer Sports product context before Search �?" Casino (#/AX) search is not sports discovery.
        return ensureSportsContext().thenCompose(v -> openSearchAttempt(0));
    }'''

# encoding may have weird dash - find by signature
idx = bt.find('public CompletableFuture<Void> open_search()')
if idx < 0:
    raise SystemExit('open_search not found')
# find the return ensureSportsContext line
idx2 = bt.find('ensureSportsContext()', idx)
idx3 = bt.find(';', idx2)
old_block = bt[idx:idx3+1]
print('OPEN_SEARCH BLOCK:', repr(old_block[:200]))

new_os = '''    public CompletableFuture<Void> open_search() {
        // Prefer Sports product context before Search - Casino (#/AX) search is not sports discovery.
        ui.checkpoint("SPORTS_CONTEXT");
        return ensureSportsContext().thenCompose(v -> {
            ui.checkpoint("OPEN_SEARCH");
            return openSearchAttempt(0);
        });
    }'''

# Replace from method start through first semicolon ending ensureSportsContext compose - safer replace of whole method start
end = bt.find('\n    /** Robust Search open', idx)
if end < 0:
    end = bt.find('\n    private CompletableFuture<Void> openSearchAttempt', idx)
old_method_start = bt[idx:end]
bt = bt[:idx] + new_os + '\n' + bt[end:]
print('replaced open_search start')

# ensureSportsContext - add more evidence
old_esc = '''    private CompletableFuture<Void> ensureSportsContext() {
        return ui.capture("sports_context_pre").thenCompose(s -> {
            if (!screenShowsCasinoProduct(s) && !isCasinoOnlyResults(s)) {
                // Still prefer All Sports if we are clearly on Casino bottom-nav highlight with no sports chrome.
                if (visible(s, "In-Play", "In-play", "Football", "Sports", "All Sports")) {
                    ui.put("sports_context", "already_sports_or_home");
                    return CompletableFuture.completedFuture(null);
                }
            }
            VisualScreen.Line allSports = findBottomNav(s, "All Sports");
            if (allSports != null) {
                ui.put("sports_context", "tap_all_sports");
                return ui.tap(allSports.bounds, "All Sports").thenCompose(v -> ui.delay(1400));
            }
            VisualScreen.Line sports = findBottomNav(s, "Sports");
            if (sports != null) {
                ui.put("sports_context", "tap_sports");
                return ui.tap(sports.bounds, "Sports").thenCompose(v -> ui.delay(1400));
            }
            // Re-open sports home URL as fallback.
            ui.put("sports_context", "open_home_url");
            return ui.open(HOME_URL).thenCompose(v -> ui.delay(1600));
        });
    }'''

new_esc = '''    private CompletableFuture<Void> ensureSportsContext() {
        long t0 = android.os.SystemClock.elapsedRealtime();
        return ui.capture("sports_context_pre").thenCompose(s -> {
            ui.put("sports_context_pre_elapsed_ms", android.os.SystemClock.elapsedRealtime() - t0);
            ui.put("sports_context_foreground", screenTextBlob(s));
            if (!screenShowsCasinoProduct(s) && !isCasinoOnlyResults(s)) {
                // Sports chrome / home is enough; basketball uses Search after Sports context.
                if (visible(s, "In-Play", "In-play", "Football", "Basketball", "Sports", "All Sports", "Search")) {
                    ui.put("sports_context", "already_sports_or_home");
                    ui.put("sports_context_elapsed_ms", android.os.SystemClock.elapsedRealtime() - t0);
                    return CompletableFuture.completedFuture(null);
                }
            }
            VisualScreen.Line allSports = findBottomNav(s, "All Sports");
            if (allSports != null) {
                ui.put("sports_context", "tap_all_sports");
                ui.bumpStageRetry("SPORTS_CONTEXT");
                return ui.tap(allSports.bounds, "All Sports").thenCompose(v -> ui.delay(1400))
                    .thenCompose(v -> ui.capture("sports_context_after_all_sports"))
                    .thenAccept(after -> {
                        ui.put("sports_context_elapsed_ms", android.os.SystemClock.elapsedRealtime() - t0);
                        ui.put("sports_context_after", screenTextBlob(after));
                    });
            }
            VisualScreen.Line sports = findBottomNav(s, "Sports");
            if (sports != null) {
                ui.put("sports_context", "tap_sports");
                ui.bumpStageRetry("SPORTS_CONTEXT");
                return ui.tap(sports.bounds, "Sports").thenCompose(v -> ui.delay(1400))
                    .thenCompose(v -> ui.capture("sports_context_after_sports"))
                    .thenAccept(after -> {
                        ui.put("sports_context_elapsed_ms", android.os.SystemClock.elapsedRealtime() - t0);
                        ui.put("sports_context_after", screenTextBlob(after));
                    });
            }
            // Re-open sports home URL as fallback.
            ui.put("sports_context", "open_home_url");
            ui.bumpStageRetry("SPORTS_CONTEXT");
            return ui.open(HOME_URL).thenCompose(v -> ui.delay(1600))
                .thenCompose(v -> ui.capture("sports_context_after_home"))
                .thenAccept(after -> {
                    ui.put("sports_context_elapsed_ms", android.os.SystemClock.elapsedRealtime() - t0);
                    ui.put("sports_context_after", screenTextBlob(after));
                });
        });
    }'''

if old_esc not in bt:
    # try find by method signature only
    i = bt.find('private CompletableFuture<Void> ensureSportsContext()')
    print('ensureSportsContext idx', i)
    print(repr(bt[i:i+400]))
    raise SystemExit('ensureSportsContext block not found exact')
bt = bt.replace(old_esc, new_esc, 1)

# enter_query - add FOCUS / QUERY_VERIFY / RESULTS_WAIT checkpoints around ladder
# Find runSearchQueryLadder typing path - add checkpoints in enter_query
old_eq_ret = '''        List<String> ladder = buildSearchQueryLadder(homePart, expectedAway);
        ui.put("search_query_ladder", new JSONArray(ladder));
        return runSearchQueryLadder(ladder, 0, false);
    }'''
new_eq_ret = '''        List<String> ladder = buildSearchQueryLadder(homePart, expectedAway);
        ui.put("search_query_ladder", new JSONArray(ladder));
        ui.checkpoint("FOCUS");
        return runSearchQueryLadder(ladder, 0, false);
    }'''
if old_eq_ret not in bt:
    raise SystemExit('enter_query return not found')
bt = bt.replace(old_eq_ret, new_eq_ret, 1)

ba.write_text(bt, encoding='utf-8')
print('OK Bet365LiveAdapter')
