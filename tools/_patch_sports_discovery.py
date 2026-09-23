# -*- coding: utf-8 -*-
"""Patch Bet365LiveAdapter for sports discovery 0.6.27-sports."""
from pathlib import Path

path = Path("android/Bet365Agent/app/src/main/java/com/bet365agent/Bet365LiveAdapter.java")
text = path.read_text(encoding="utf-8")

# --- fields ---
old_fields = '''    private final VisualSession ui;
    private final String sport;
    private Fixture liveFixture;
    /** Last typed search query (exact). Used for fixture identity, never fuzzy OCR. */
    private String lastQuery = "";
    /** Optional expected away team for hard fixture pairing (OPEN_SEARCH proofs / future schema). */
    private String expectedAway = "";
    Bet365LiveAdapter(VisualSession ui, String sport) {
        this.ui = ui;
        this.sport = sport == null ? "football" : sport.toLowerCase(Locale.US);
    }

    void setExpectedAway(String away) {
        this.expectedAway = away == null ? "" : away.trim();
    }'''

new_fields = '''    private final VisualSession ui;
    private final String sport;
    private Fixture liveFixture;
    /** Last typed search query (exact). Discovery only — identity uses identityHome/Away. */
    private String lastQuery = "";
    /** Intended home team for hard fixture identity (never diluted by search aliases). */
    private String identityHome = "";
    /** Intended away team for hard fixture pairing; empty when unknown. */
    private String expectedAway = "";
    /** Club-name prefixes stripped only when building SEARCH aliases (not identity). */
    private static final String[] CLUB_PREFIXES = new String[] {
            "BC", "KK", "BK", "FC", "HJK", "KD", "KK", "NK", "SK", "FK", "AC", "AS", "CF", "CD"
    };
    Bet365LiveAdapter(VisualSession ui, String sport) {
        this.ui = ui;
        this.sport = sport == null ? "football" : sport.toLowerCase(Locale.US);
    }

    void setExpectedAway(String away) {
        this.expectedAway = away == null ? "" : away.trim();
    }'''

if old_fields not in text:
    raise SystemExit("fields block missing")
text = text.replace(old_fields, new_fields, 1)

# --- open_search: ensure sports context first ---
old_open = '''    public CompletableFuture<Void> open_search() {
        return openSearchAttempt(0);
    }'''
new_open = '''    public CompletableFuture<Void> open_search() {
        // Prefer Sports product context before Search — Casino (#/AX) search is not sports discovery.
        return ensureSportsContext().thenCompose(v -> openSearchAttempt(0));
    }'''
if old_open not in text:
    raise SystemExit("open_search missing")
text = text.replace(old_open, new_open, 1)

# --- replace entire enter_query ---
start = text.index("    public CompletableFuture<Void> enter_query(String query) {")
end = text.index("    public CompletableFuture<Fixture> discover_fixture() {")
new_enter = r'''    public CompletableFuture<Void> enter_query(String query) {
        String raw = (query == null || query.trim().isEmpty()) ? defaultQuery() : query.trim();
        // Support optional "Home||Away" encoding: discovery ladder may alias; identity stays hard.
        String awayHint = "";
        int sep = raw.indexOf("||");
        String homePart = raw;
        if (sep > 0) {
            awayHint = raw.substring(sep + 2).trim();
            homePart = raw.substring(0, sep).trim();
        }
        if (!awayHint.isEmpty()) expectedAway = awayHint;
        identityHome = homePart;
        lastQuery = homePart;
        ui.put("search_query", homePart);
        ui.put("identity_home", identityHome);
        if (!expectedAway.isEmpty()) ui.put("expected_away", expectedAway);
        ui.put("identity_away", expectedAway);
        List<String> ladder = buildSearchQueryLadder(homePart, expectedAway);
        ui.put("search_query_ladder", new JSONArray(ladder));
        return runSearchQueryLadder(ladder, 0, false);
    }

    /**
     * Bounded discovery ladder (SEARCH ONLY):
     * A "Home Away" | B "Home" | C "Away" | D deterministic aliases (strip BC/KK/BK/FC/HJK…).
     * Fixture identity always uses identityHome + expectedAway, never the alias alone.
     */
    private static List<String> buildSearchQueryLadder(String home, String away) {
        LinkedHashSet<String> out = new LinkedHashSet<>();
        String h = home == null ? "" : home.trim();
        String a = away == null ? "" : away.trim();
        if (!h.isEmpty() && !a.isEmpty()) out.add(h + " " + a);
        if (!h.isEmpty()) out.add(h);
        if (!a.isEmpty()) out.add(a);
        for (String alias : searchAliasesFor(h)) out.add(alias);
        if (!a.isEmpty()) {
            for (String alias : searchAliasesFor(a)) out.add(alias);
            // Alias home + full away, and alias-home + alias-away
            for (String ha : searchAliasesFor(h)) {
                out.add(ha + " " + a);
                for (String aa : searchAliasesFor(a)) out.add(ha + " " + aa);
            }
        }
        out.removeIf(s -> s == null || s.trim().isEmpty());
        return new ArrayList<>(out);
    }

    /** Deterministic club-prefix aliases for SEARCH discovery only. */
    private static List<String> searchAliasesFor(String name) {
        List<String> aliases = new ArrayList<>();
        if (name == null) return aliases;
        String t = name.trim().replaceAll("\\s+", " ");
        if (t.isEmpty()) return aliases;
        String[] parts = t.split(" ");
        if (parts.length >= 2) {
            String p0 = parts[0].toUpperCase(Locale.US);
            for (String pref : CLUB_PREFIXES) {
                if (p0.equals(pref)) {
                    String rest = t.substring(parts[0].length()).trim();
                    if (rest.length() >= 3) aliases.add(rest);
                    break;
                }
            }
        }
        return aliases;
    }

    private CompletableFuture<Void> runSearchQueryLadder(List<String> ladder, int index, boolean recoveredSports) {
        if (index >= ladder.size()) {
            throw new Failure("SPORTS_RESULTS_NOT_FOUND",
                    "No sports fixture after query ladder " + ladder
                            + " for identity '" + identityHome + "'"
                            + (expectedAway.isEmpty() ? "" : (" vs '" + expectedAway + "'")));
        }
        final String typed = ladder.get(index);
        lastQuery = typed;
        ui.put("search_query", typed);
        ui.put("search_ladder_index", index);
        ui.put("search_ladder_query", typed);
        return typeSearchQueryOnce(typed).thenCompose(screen -> {
            if (isCasinoOnlyResults(screen)) {
                ui.put("casino_only_rejected", true);
                ui.put("casino_only_query", typed);
                // Prefer leave-Casino / Sports recover once, then continue ladder (never accept Casino).
                if (!recoveredSports) {
                    return recoverSportsContextThenSearch()
                            .thenCompose(v -> runSearchQueryLadder(ladder, index, true));
                }
                return clearSearchField().thenCompose(v -> runSearchQueryLadder(ladder, index + 1, true));
            }
            // Steer chips when present; then hard fixture gate on identity teams.
            return steerSearchResultsToSports(screen)
                    .thenCompose(v2 -> ui.capture("query_results_sports"))
                    .thenCompose(sports -> {
                        if (isCasinoOnlyResults(sports)) {
                            ui.put("casino_only_rejected", true);
                            if (!recoveredSports) {
                                return recoverSportsContextThenSearch()
                                        .thenCompose(v -> runSearchQueryLadder(ladder, index, true));
                            }
                            return clearSearchField().thenCompose(v -> runSearchQueryLadder(ladder, index + 1, true));
                        }
                        List<Fixture> parsed = fixturesFromSearch(sports);
                        if (parsed.isEmpty()) {
                            // No rows yet — try next ladder step (do not fail on first query).
                            return clearSearchField().thenCompose(v -> runSearchQueryLadder(ladder, index + 1, recoveredSports));
                        }
                        try {
                            assertUniqueFixtureForQuery(sports, identityHome);
                            rejectWrongSportIfEvident(sports);
                            return CompletableFuture.completedFuture(null);
                        } catch (Failure f) {
                            String stage = f.stage;
                            // Ambiguous / wrong pairing on this query: try next ladder step when identity incomplete,
                            // but hard-fail wrong opponent / ambiguity when both teams were required and matched wrongly.
                            if ("AMBIGUOUS_FIXTURE".equals(stage) || "WRONG_EVENT".equals(stage) || "WRONG_SPORT".equals(stage)) {
                                throw f;
                            }
                            return clearSearchField().thenCompose(v -> runSearchQueryLadder(ladder, index + 1, recoveredSports));
                        }
                    });
        });
    }

    private CompletableFuture<VisualScreen> typeSearchQueryOnce(String queryText) {
        return ui.capture("query_pre").thenCompose(s -> {
            require(!visible(s, "SIMULATOR", "SEARCHPAGE"), "TARGET_NOT_FOUND", "Simulator leaked into live search");
            if (hasLiveSearchResults(s, queryText)) {
                return ui.dismissKeyboard().thenCompose(v -> ui.delay(400)).thenCompose(v -> ui.capture("query_results"));
            }
            VisualScreen.Line recent = recentSearchChip(s, queryText);
            if (recent != null) {
                return ui.tap(recent.bounds, "Recent " + queryText).thenCompose(v -> ui.delay(1200))
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
            return clear.thenCompose(v -> ui.type(hint, queryText)).thenCompose(v -> ui.dismissKeyboard())
                    .thenCompose(v -> ui.delay(1200)).thenCompose(v -> ui.capture("query_results"));
        }).thenApply(r -> {
            require(!visible(r, "SIMULATOR", "SEARCHPAGE"), "TARGET_NOT_FOUND", "Simulator leaked into live search");
            return r;
        });
    }

    private CompletableFuture<Void> clearSearchField() {
        return ui.capture("ladder_clear").thenCompose(s -> {
            VisualScreen.Line clearBtn = null;
            for (VisualScreen.Line line : s.lines) {
                if (line.text.equalsIgnoreCase("x") && line.bounds.top < 280 && line.bounds.left > 400) { clearBtn = line; break; }
            }
            if (clearBtn != null) {
                return ui.tap(clearBtn.bounds, "Clear search ladder").thenCompose(v -> ui.delay(500));
            }
            return CompletableFuture.completedFuture(null);
        });
    }

    /** Casino product / Casino-only search pane — never treat as sports fixture results. */
    private static boolean isCasinoOnlyResults(VisualScreen s) {
        if (s == null) return false;
        boolean casinoUrl = false;
        for (VisualScreen.Line line : s.lines) {
            String t = line.text.toLowerCase(Locale.US);
            if (t.contains("#/ax") || t.contains("/ax/") || t.contains("#/ax/k")) { casinoUrl = true; break; }
        }
        boolean casinoChip = false;
        boolean sportsChip = false;
        for (VisualScreen.Line line : s.lines) {
            if (line.bounds.top < 180 || line.bounds.top > 560) continue;
            String up = line.text.trim().toUpperCase(Locale.US);
            if (up.equals("CASINO")) casinoChip = true;
            if (up.equals("SPORTS") || up.equals("FOOTBALL") || up.equals("BASKETBALL")
                    || up.equals("EVENTS") || up.equals("TEAMS") || up.equals("TENNIS")) sportsChip = true;
        }
        // Bottom-nav "Casino" alone is not enough; require Casino filter chip or Casino URL without sports rows.
        if (!(casinoChip || casinoUrl)) return false;
        if (sportsChip) return false;
        // If sports fixture rows already parse, it is not casino-only.
        // (Caller may still reject wrong sport.)
        return true;
    }

    private static boolean screenShowsCasinoProduct(VisualScreen s) {
        if (s == null) return false;
        for (VisualScreen.Line line : s.lines) {
            String t = line.text.toLowerCase(Locale.US);
            if (t.contains("#/ax") || t.contains("/ax/")) return true;
        }
        // Active Casino bottom tab while Search closed
        for (VisualScreen.Line line : s.lines) {
            if (line.bounds.top < 1200) continue;
            if (line.text.trim().equalsIgnoreCase("Casino")) return true;
        }
        return false;
    }

    /** Leave Casino / land on Sports before Search when Bet365 supports it. */
    private CompletableFuture<Void> ensureSportsContext() {
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
    }

    private CompletableFuture<Void> recoverSportsContextThenSearch() {
        return ui.capture("casino_recover_pre").thenCompose(s -> {
            VisualScreen.Line close = firstOf(s, "Close");
            CompletableFuture<Void> closeF = CompletableFuture.completedFuture(null);
            if (close != null && close.bounds.top < 320) {
                closeF = ui.tap(close.bounds, "Close casino search").thenCompose(v -> ui.delay(700));
            }
            return closeF.thenCompose(v -> ensureSportsContext())
                    .thenCompose(v -> openSearchAttempt(0));
        });
    }

    private static VisualScreen.Line findBottomNav(VisualScreen s, String label) {
        if (s == null || label == null) return null;
        VisualScreen.Line best = null;
        for (VisualScreen.Line line : s.lines) {
            if (line.bounds.top < 1180) continue;
            String t = line.text.trim();
            if (t.equalsIgnoreCase(label) || t.equalsIgnoreCase(label.replace(" ", ""))) {
                best = line;
                break;
            }
            if (t.toLowerCase(Locale.US).contains(label.toLowerCase(Locale.US)) && t.length() <= label.length() + 4) {
                best = line;
            }
        }
        return best;
    }

    private void rejectWrongSportIfEvident(VisualScreen s) {
        if (s == null) return;
        String want = sport == null ? "" : sport.toLowerCase(Locale.US);
        if (want.isEmpty()) return;
        boolean sawFootball = false, sawBasketball = false;
        for (VisualScreen.Line line : s.lines) {
            if (line.bounds.top < 200 || line.bounds.top > 700) continue;
            String up = line.text.trim().toUpperCase(Locale.US);
            if (up.equals("FOOTBALL") || up.equals("SOCCER")) sawFootball = true;
            if (up.equals("BASKETBALL")) sawBasketball = true;
        }
        if (want.contains("basket") && sawFootball && !sawBasketball) {
            throw new Failure("WRONG_SPORT", "Search results show Football chip for basketball identity");
        }
        if (want.contains("football") || want.equals("soccer")) {
            if (sawBasketball && !sawFootball) {
                throw new Failure("WRONG_SPORT", "Search results show Basketball chip for football identity");
            }
        }
    }

'''
text = text[:start] + new_enter + text[end:]

# --- update assertUniqueFixtureForQuery to use identity + expectedAway, casino guard ---
old_assert = '''    private void assertUniqueFixtureForQuery(VisualScreen s, String q) {
        List<Fixture> all = fixturesFromSearch(s);
        JSONArray observed = new JSONArray();
        for (Fixture f : all) observed.put(f.json());
        ui.put("search_result_fixtures", observed);
        ui.put("search_ocr_readback", screenTextBlob(s));
        if (all.isEmpty()) {
            throw new Failure("NO_FIXTURE_FOUND",
                    "No sports fixture rows parsed after query '" + q + "'; OCR=" + screenTextBlob(s));
        }
        Fixture chosen = selectUniqueFixtureForQuery(all, q, expectedAway);
        liveFixture = chosen;
        ui.put("verified_fixture", chosen.json());
        ui.put("fixture_home", chosen.home);
        ui.put("fixture_away", chosen.away);
    }'''

new_assert = '''    private void assertUniqueFixtureForQuery(VisualScreen s, String q) {
        if (isCasinoOnlyResults(s)) {
            throw new Failure("SPORTS_RESULTS_NOT_FOUND",
                    "Casino-only search results rejected for query '" + q + "'; OCR=" + screenTextBlob(s));
        }
        List<Fixture> all = fixturesFromSearch(s);
        JSONArray observed = new JSONArray();
        for (Fixture f : all) observed.put(f.json());
        ui.put("search_result_fixtures", observed);
        ui.put("search_ocr_readback", screenTextBlob(s));
        if (all.isEmpty()) {
            throw new Failure("SPORTS_RESULTS_NOT_FOUND",
                    "No sports fixture rows parsed after query '" + q + "'; OCR=" + screenTextBlob(s));
        }
        // Identity gate uses intended home/away — never the discovery alias alone.
        String idHome = (identityHome != null && !identityHome.isEmpty()) ? identityHome : q;
        String idAway = expectedAway;
        Fixture chosen = selectUniqueFixtureForQuery(all, idHome, idAway);
        // One-team discovery must still verify opponent when expectedAway is set (already in select).
        liveFixture = chosen;
        ui.put("verified_fixture", chosen.json());
        ui.put("fixture_home", chosen.home);
        ui.put("fixture_away", chosen.away);
        ui.put("discovery_query", q);
        ui.put("identity_verified_home", idHome);
        ui.put("identity_verified_away", idAway);
    }'''

if old_assert not in text:
    raise SystemExit("assertUniqueFixtureForQuery missing")
text = text.replace(old_assert, new_assert, 1)

# --- enhance steerSearchResultsToSports to also try All Sports bottom nav ---
old_steer = '''    private CompletableFuture<Void> steerSearchResultsToSports(VisualScreen s) {
        if (s == null) return CompletableFuture.completedFuture(null);
        if (!fixturesFromSearch(s).isEmpty()) return CompletableFuture.completedFuture(null);
        VisualScreen.Line chip = null;
        String[] prefer = new String[] {"Sports", "Football", "Basketball", "Events", "TEAMS", "Teams"};
        for (String label : prefer) {
            for (VisualScreen.Line line : s.lines) {
                String t = line.text.trim();
                if (!t.equalsIgnoreCase(label) && !t.equalsIgnoreCase(label + " ")) continue;
                if (line.bounds.top < 200 || line.bounds.top > 520) continue;
                chip = line;
                break;
            }
            if (chip != null) break;
        }
        // Casino-only pane: still try a broader Sports token anywhere in the filter strip.
        if (chip == null && visible(s, "Casino")) {
            for (VisualScreen.Line line : s.lines) {
                String up = line.text.trim().toUpperCase(Locale.US);
                if (line.bounds.top < 200 || line.bounds.top > 560) continue;
                if (up.equals("SPORTS") || up.equals("FOOTBALL") || up.equals("BASKETBALL") || up.equals("EVENTS") || up.equals("TEAMS")) {
                    chip = line;
                    break;
                }
            }
        }
        if (chip == null) return CompletableFuture.completedFuture(null);
        ui.put("search_results_steer", chip.text);
        return ui.tap(chip.bounds, "Search filter " + chip.text).thenCompose(v -> ui.delay(1100));
    }'''

new_steer = '''    private CompletableFuture<Void> steerSearchResultsToSports(VisualScreen s) {
        if (s == null) return CompletableFuture.completedFuture(null);
        if (!fixturesFromSearch(s).isEmpty() && !isCasinoOnlyResults(s)) {
            return CompletableFuture.completedFuture(null);
        }
        VisualScreen.Line chip = null;
        String[] prefer = new String[] {"Sports", "Football", "Basketball", "Events", "TEAMS", "Teams"};
        for (String label : prefer) {
            for (VisualScreen.Line line : s.lines) {
                String t = line.text.trim();
                if (!t.equalsIgnoreCase(label) && !t.equalsIgnoreCase(label + " ")) continue;
                if (line.bounds.top < 200 || line.bounds.top > 520) continue;
                chip = line;
                break;
            }
            if (chip != null) break;
        }
        // Casino-only pane: still try a broader Sports token anywhere in the filter strip.
        if (chip == null && visible(s, "Casino")) {
            for (VisualScreen.Line line : s.lines) {
                String up = line.text.trim().toUpperCase(Locale.US);
                if (line.bounds.top < 200 || line.bounds.top > 560) continue;
                if (up.equals("SPORTS") || up.equals("FOOTBALL") || up.equals("BASKETBALL") || up.equals("EVENTS") || up.equals("TEAMS")) {
                    chip = line;
                    break;
                }
            }
        }
        if (chip != null) {
            ui.put("search_results_steer", chip.text);
            return ui.tap(chip.bounds, "Search filter " + chip.text).thenCompose(v -> ui.delay(1100));
        }
        // No sports chip in Casino-only search — do not accept; recover path handled by ladder.
        if (isCasinoOnlyResults(s)) {
            ui.put("search_results_steer", "casino_only_no_sports_chip");
        }
        return CompletableFuture.completedFuture(null);
    }'''

if old_steer not in text:
    raise SystemExit("steerSearchResultsToSports missing")
text = text.replace(old_steer, new_steer, 1)

# --- discover_fixture: use identityHome ---
old_disc = '''            String q = (lastQuery == null || lastQuery.isEmpty()) ? defaultQuery() : lastQuery;
            Fixture chosen = selectUniqueFixtureForQuery(all, q, expectedAway);'''
new_disc = '''            String q = (identityHome != null && !identityHome.isEmpty())
                    ? identityHome
                    : ((lastQuery == null || lastQuery.isEmpty()) ? defaultQuery() : lastQuery);
            Fixture chosen = selectUniqueFixtureForQuery(all, q, expectedAway);'''
if old_disc not in text:
    raise SystemExit("discover_fixture select missing")
text = text.replace(old_disc, new_disc, 1)

# --- teamPositivelyIdentified: keep as-is (alias identity for BC Beroe↔Beroe already allowed) ---

path.write_text(text, encoding="utf-8")
print("Patched", path, "lines", len(text.splitlines()))

# gradle bump
g = Path("android/Bet365Agent/app/build.gradle.kts")
gt = g.read_text(encoding="utf-8")
gt2 = gt.replace("versionCode = 38", "versionCode = 39").replace('versionName = "0.6.26-ocr"', 'versionName = "0.6.27-sports"')
if "0.6.27-sports" not in gt2:
    raise SystemExit("gradle bump failed")
g.write_text(gt2, encoding="utf-8")
print("gradle", "0.6.27-sports", "vc39")

# pipeline query includes home||away
pp = Path("core/pipeline.py")
pt = pp.read_text(encoding="utf-8")
old_q = "scenario='live', query=row['home'], sport=row['sport'], market=row['market'],"
new_q = "scenario='live', query=(f\"{row['home']}||{row['away']}\" if row.get('away') else row['home']), sport=row['sport'], market=row['market'],"
if old_q not in pt:
    raise SystemExit("pipeline query line missing")
pp.write_text(pt.replace(old_q, new_q, 1), encoding="utf-8")
print("pipeline query home||away")
