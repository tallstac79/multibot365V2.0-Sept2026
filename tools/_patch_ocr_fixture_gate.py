from pathlib import Path

path = Path(r"android/Bet365Agent/app/src/main/java/com/bet365agent/Bet365LiveAdapter.java")
text = path.read_text(encoding="utf-8")

old_fields = """    private final VisualSession ui;
    private final String sport;
    private Fixture liveFixture;
    Bet365LiveAdapter(VisualSession ui, String sport) {
        this.ui = ui;
        this.sport = sport == null ? \"football\" : sport.toLowerCase(Locale.US);
    }"""
# Fix - use normal quotes in the java source
old_fields = """    private final VisualSession ui;
    private final String sport;
    private Fixture liveFixture;
    Bet365LiveAdapter(VisualSession ui, String sport) {
        this.ui = ui;
        this.sport = sport == null ? "football" : sport.toLowerCase(Locale.US);
    }"""

new_fields = """    private final VisualSession ui;
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
    }"""

if old_fields not in text:
    raise SystemExit("fields block missing")
text = text.replace(old_fields, new_fields, 1)

old_eq = """    public CompletableFuture<Void> enter_query(String query) {
        String q = (query == null || query.trim().isEmpty()) ? defaultQuery() : query.trim();
        return ui.capture("query_pre").thenCompose(s -> {"""

new_eq = """    public CompletableFuture<Void> enter_query(String query) {
        String q = (query == null || query.trim().isEmpty()) ? defaultQuery() : query.trim();
        // Support optional "Home||Away" proof encoding: type Home only; hard-verify Away in results.
        String awayHint = "";
        int sep = q.indexOf("||");
        if (sep > 0) {
            awayHint = q.substring(sep + 2).trim();
            q = q.substring(0, sep).trim();
        }
        if (!awayHint.isEmpty()) expectedAway = awayHint;
        lastQuery = q;
        ui.put("search_query", q);
        if (!expectedAway.isEmpty()) ui.put("expected_away", expectedAway);
        return ui.capture("query_pre").thenCompose(s -> {"""

if old_eq not in text:
    raise SystemExit("enter_query missing")
text = text.replace(old_eq, new_eq, 1)

old_has = """            if (hasLiveSearchResults(s, q)) {
                return ui.dismissKeyboard().thenCompose(v -> ui.delay(400)).thenCompose(v -> ui.capture("query_results")).thenAccept(r -> {
                    require(hasLiveSearchResults(r, q), "TEXT_NOT_VERIFIED", "Live query results not visible");
                });
            }"""
new_has = """            if (hasLiveSearchResults(s, q)) {
                final String typed = q;
                return ui.dismissKeyboard().thenCompose(v -> ui.delay(400)).thenCompose(v -> ui.capture("query_results")).thenAccept(r -> {
                    require(hasLiveSearchResults(r, typed), "TEXT_NOT_VERIFIED", "Live query results not visible");
                    assertUniqueFixtureForQuery(r, typed);
                });
            }"""
if old_has not in text:
    raise SystemExit("hasLive path missing")
text = text.replace(old_has, new_has, 1)

old_recent = """            if (recent != null) {
                return ui.tap(recent.bounds, "Recent " + q).thenCompose(v -> ui.delay(1200)).thenCompose(v -> ui.capture("query_results")).thenAccept(r -> {
                    require(!visible(r, "SIMULATOR", "SEARCHPAGE"), "TARGET_NOT_FOUND", "Simulator leaked into live search");
                    require(hasLiveSearchResults(r, q), "TEXT_NOT_VERIFIED", "Recent search did not open live results");
                });
            }"""
new_recent = """            if (recent != null) {
                final String typed = q;
                return ui.tap(recent.bounds, "Recent " + typed).thenCompose(v -> ui.delay(1200)).thenCompose(v -> ui.capture("query_results")).thenAccept(r -> {
                    require(!visible(r, "SIMULATOR", "SEARCHPAGE"), "TARGET_NOT_FOUND", "Simulator leaked into live search");
                    require(hasLiveSearchResults(r, typed), "TEXT_NOT_VERIFIED", "Recent search did not open live results");
                    assertUniqueFixtureForQuery(r, typed);
                });
            }"""
if old_recent not in text:
    raise SystemExit("recent path missing")
text = text.replace(old_recent, new_recent, 1)

old_final = """            return clear.thenCompose(v -> ui.type(hint, q)).thenCompose(v -> ui.dismissKeyboard()).thenCompose(v -> ui.delay(900)).thenCompose(v -> ui.capture("query_results")).thenAccept(r -> {
                require(!visible(r, "SIMULATOR", "SEARCHPAGE"), "TARGET_NOT_FOUND", "Simulator leaked into live search");
                require(hasLiveSearchResults(r, q) || visible(r, q), "TEXT_NOT_VERIFIED", "Live query results not visible after typing");
            });
        });
    }"""
new_final = """            final String typed = q;
            return clear.thenCompose(v -> ui.type(hint, typed)).thenCompose(v -> ui.dismissKeyboard()).thenCompose(v -> ui.delay(900)).thenCompose(v -> ui.capture("query_results")).thenAccept(r -> {
                require(!visible(r, "SIMULATOR", "SEARCHPAGE"), "TARGET_NOT_FOUND", "Simulator leaked into live search");
                require(hasLiveSearchResults(r, typed) || visible(r, typed), "TEXT_NOT_VERIFIED", "Live query results not visible after typing");
                assertUniqueFixtureForQuery(r, typed);
            });
        });
    }"""
if old_final not in text:
    raise SystemExit("final enter_query block missing")
text = text.replace(old_final, new_final, 1)

old_disc = """    public CompletableFuture<Fixture> discover_fixture() {
        return ui.capture("fixtures").thenApply(s -> {
            require(!visible(s, "SIMULATOR"), "NO_FIXTURE_FOUND", "Simulator page during live fixture discovery");
            List<Fixture> all = fixturesFromSearch(s);
            JSONArray observed = new JSONArray();
            for (Fixture f : all) observed.put(f.json());
            ui.put("discovered_fixtures", observed);
            require(!all.isEmpty(), "NO_FIXTURE_FOUND", "No live fixture row parsed from Bet365 search OCR");
            String q = defaultQuery().toLowerCase(Locale.US);
            Fixture first = all.get(0);
            for (Fixture f : all) {
                String blob = (f.home + " " + f.away).toLowerCase(Locale.US);
                if (blob.contains(q)) { first = f; break; }
            }
            ui.put("sport_observed", sport);
            return first;
        });
    }"""
new_disc = """    public CompletableFuture<Fixture> discover_fixture() {
        return ui.capture("fixtures").thenApply(s -> {
            require(!visible(s, "SIMULATOR"), "NO_FIXTURE_FOUND", "Simulator page during live fixture discovery");
            List<Fixture> all = fixturesFromSearch(s);
            JSONArray observed = new JSONArray();
            for (Fixture f : all) observed.put(f.json());
            ui.put("discovered_fixtures", observed);
            require(!all.isEmpty(), "NO_FIXTURE_FOUND", "No live fixture row parsed from Bet365 search OCR");
            String q = (lastQuery == null || lastQuery.isEmpty()) ? defaultQuery() : lastQuery;
            Fixture chosen = selectUniqueFixtureForQuery(all, q, expectedAway);
            liveFixture = chosen;
            ui.put("sport_observed", sport);
            ui.put("verified_fixture", chosen.json());
            return chosen;
        });
    }"""
if old_disc not in text:
    raise SystemExit("discover_fixture missing")
text = text.replace(old_disc, new_disc, 1)

marker = "    private static boolean hasLiveSearchResults(VisualScreen s, String q) {"
helpers = r'''    /**
     * Hard fixture identity gate (search results): positively identify the queried team,
     * require a single home/away pairing, and when expectedAway is set require that away too.
     * No fuzzy OCR confusion mapping — imperfect OCR must not select a market.
     */
    private void assertUniqueFixtureForQuery(VisualScreen s, String q) {
        List<Fixture> all = fixturesFromSearch(s);
        JSONArray observed = new JSONArray();
        for (Fixture f : all) observed.put(f.json());
        ui.put("search_result_fixtures", observed);
        Fixture chosen = selectUniqueFixtureForQuery(all, q, expectedAway);
        liveFixture = chosen;
        ui.put("verified_fixture", chosen.json());
        ui.put("fixture_home", chosen.home);
        ui.put("fixture_away", chosen.away);
    }

    private static Fixture selectUniqueFixtureForQuery(List<Fixture> all, String query, String expectedAway) {
        String q = query == null ? "" : query.trim();
        require(!q.isEmpty(), "NO_FIXTURE_FOUND", "No search query available for fixture identity");
        List<Fixture> matches = new ArrayList<>();
        for (Fixture f : all) {
            if (teamPositivelyIdentified(f.home, q) || teamPositivelyIdentified(f.away, q)) {
                matches.add(f);
            }
        }
        require(!matches.isEmpty(), "NO_FIXTURE_FOUND", "No search result fixture positively identifies query '" + q + "'");
        // Collapse to unique home|away pairings (ignore competition duplicates).
        LinkedHashMap<String, Fixture> pairings = new LinkedHashMap<>();
        for (Fixture f : matches) {
            String key = f.home.toLowerCase(Locale.US) + "|" + f.away.toLowerCase(Locale.US);
            pairings.putIfAbsent(key, f);
        }
        require(pairings.size() == 1, "AMBIGUOUS_FIXTURE",
                "Multiple plausible fixtures for query '" + q + "': " + pairings.keySet());
        Fixture chosen = pairings.values().iterator().next();
        String away = expectedAway == null ? "" : expectedAway.trim();
        if (!away.isEmpty()) {
            require(teamPositivelyIdentified(chosen.home, away) || teamPositivelyIdentified(chosen.away, away),
                    "WRONG_EVENT", "Expected away '" + away + "' not positively identified on fixture " + chosen.name());
            // Correct pairing: query team and away on opposite sides.
            boolean queryHome = teamPositivelyIdentified(chosen.home, q);
            boolean queryAway = teamPositivelyIdentified(chosen.away, q);
            boolean awayHome = teamPositivelyIdentified(chosen.home, away);
            boolean awayAwaySide = teamPositivelyIdentified(chosen.away, away);
            require((queryHome && awayAwaySide) || (queryAway && awayHome),
                    "WRONG_EVENT", "Fixture pairing mismatch for '" + q + "' vs '" + away + "' on " + chosen.name());
        }
        return chosen;
    }

    /** Positive team identity: exact or contains full multi-word query; no OCR confusion aliases. */
    private static boolean teamPositivelyIdentified(String teamName, String requested) {
        if (teamName == null || requested == null) return false;
        String t = teamName.trim().replaceAll("\\s+", " ").toLowerCase(Locale.US);
        String r = requested.trim().replaceAll("\\s+", " ").toLowerCase(Locale.US);
        if (t.isEmpty() || r.isEmpty()) return false;
        if (t.equals(r)) return true;
        if (t.contains(r)) return true;
        // Allow requested "BC Beroe" to match team "Beroe" only when requested ends with that token.
        if (r.endsWith(" " + t) && t.length() >= 4) return true;
        return false;
    }

'''
if marker not in text:
    raise SystemExit("hasLiveSearchResults marker missing")
text = text.replace(marker, helpers + marker, 1)

path.write_text(text, encoding="utf-8")
print("Bet365LiveAdapter patched OK")
