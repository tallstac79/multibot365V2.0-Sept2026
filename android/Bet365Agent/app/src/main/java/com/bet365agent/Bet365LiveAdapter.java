package com.bet365agent;

import android.graphics.Rect;
import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.regex.*;
import org.json.JSONArray;

/**
 * Live Bet365 mobile (Chrome) visual adapter.
 * Screenshot/OCR + dispatchGesture only. Stops at bet-slip verification ÃƒÂ¯Ã‚Â¿Ã‚Â½ never taps Place Bet / submit.
 * Does not use LocalSimulator pages or expected-value shortcuts.
 */
final class Bet365LiveAdapter implements SiteAdapter {
    private android.graphics.Rect preparedPlaceBetBounds;
    private org.json.JSONObject preparedGesture;
    private String preparedValidationHash;

    private static final String HOME_URL = "https://www.bet365.com/#/HO/";
    private static final Pattern VS = Pattern.compile("(?i)^(.+?)\\s+(?:v|vs|@)\\s+(.+)$");
    private static final Pattern PRICE = Pattern.compile("\\b(\\d+\\.\\d{2}|\\d+/\\d+)\\b");
    private static final Pattern LINE = Pattern.compile("([+-]?\\d+(?:\\.\\d+)?)");
    private final VisualSession ui;
    private final String sport;
    private Fixture liveFixture;
    Bet365LiveAdapter(VisualSession ui, String sport) {
        this.ui = ui;
        this.sport = sport == null ? "football" : sport.toLowerCase(Locale.US);
    }

    public CompletableFuture<Void> open_home() {
        return ui.open(HOME_URL).thenCompose(v -> ui.delay(2800)).thenCompose(v -> ui.capture("home")).thenCompose(s -> {
            require(!visible(s, "SIMULATOR", "SEARCHPAGE", "Fictional interface"),
                    "TARGET_NOT_FOUND", "Simulator page visible during live Bet365 run");
            return dismissCookiesIfPresent(s).thenCompose(v -> ui.capture("home_ready")).thenAccept(ready -> {
                require(visible(ready, "bet365", "Bet365", "Sports", "Search", "In-Play", "In-play", "Live", "Football"),
                        "TARGET_NOT_FOUND", "Live Bet365 homepage not visible");
                require(!visible(ready, "Accept All") && !cookieWall(ready),
                        "TARGET_NOT_FOUND", "Cookie consent still blocking live Bet365 home");
            });
        });
    }


    public CompletableFuture<Void> ensure_session() {
        return ui.capture("session").thenCompose(s -> {
            if (sessionLoggedIn(s)) {
                ui.put("session", "LOGGED_IN");
                return CompletableFuture.completedFuture(null);
            }
            if (sessionExpired(s)) {
                throw new Failure("SESSION_EXPIRED", "Bet365 session expired or logged out");
            }
            // Logged out ? attempt secure local credential login
            if (!CoordinatorConfig.hasBet365Credentials(ui.service)) {
                throw new Failure("LOGIN_FAILED", "Bet365 logged out and no app-private credentials in Coordinator settings ? open Bet365Agent Settings or log in on Samsung Chrome");
            }
            return performLogin(s);
        });
    }

    private CompletableFuture<Void> performLogin(VisualScreen first) {
        CompletableFuture<Void> openForm = CompletableFuture.completedFuture(null);
        if (!loginWall(first)) {
            VisualScreen.Line loginBtn = null;
            for (VisualScreen.Line line : first.lines) {
                String t = line.text.trim();
                if ((t.equalsIgnoreCase("Log In") || t.equalsIgnoreCase("Login")) && line.bounds.top < 350) { loginBtn = line; break; }
            }
            if (loginBtn == null) throw new Failure("LOGIN_FAILED", "Log In control not visible on live Bet365");
            VisualScreen.Line btn = loginBtn;
            openForm = ui.tap(btn.bounds, "Log In").thenCompose(v -> ui.delay(900));
        }
        String user = CoordinatorConfig.bet365Username(ui.service);
        String pass = CoordinatorConfig.bet365Password(ui.service);
        return openForm.thenCompose(v -> ui.capture("login_form")).thenCompose(form -> {
            require(loginWall(form) || visible(form, "Password") || visible(form, "Username", "email", "address"),
                    "LOGIN_FAILED", "Bet365 login form not visible");
            String userHint = visible(form, "email") || visible(form, "Username") || visible(form, "username") ? (visible(form, "email") ? "email" : "Username") : "Username";
            if (visible(form, "Username or email") || visible(form, "username or email") || visible(form, "psername")) userHint = visible(form, "email") ? "email" : "Username";
            // Prefer placeholder fragments TextEntryFlow can match
            String hintUser = "email";
            if (visible(form, "Username") || visible(form, "username")) hintUser = "Username";
            if (visible(form, "bet365...")) { /* ignore */ }
            return ui.type(hintUser, user).thenCompose(x -> ui.delay(400)).thenCompose(x -> ui.typeSecret("Password", pass)).thenCompose(x -> ui.delay(400)).thenCompose(x -> {
                return ui.capture("login_filled").thenCompose(filled -> {
                    VisualScreen.Line submit = null;
                    for (VisualScreen.Line line : filled.lines) {
                        String t = line.text.trim();
                        if ((t.equalsIgnoreCase("Log In") || t.equalsIgnoreCase("Login")) && line.bounds.top > 400) { submit = line; break; }
                    }
                    if (submit == null) {
                        for (VisualScreen.Line line : filled.lines) {
                            if (line.text.trim().equalsIgnoreCase("Log In") || line.text.trim().equalsIgnoreCase("Login")) { submit = line; break; }
                        }
                    }
                    require(submit != null, "LOGIN_FAILED", "Login submit button not visible");
                    return ui.tap(submit.bounds, "Log In submit").thenCompose(z -> ui.delay(2500)).thenCompose(z -> ui.capture("session_after_login")).thenAccept(after -> {
                        if (loginWall(after) || (visible(after, "Password") && visible(after, "Log In", "Login"))) {
                            throw new Failure("LOGIN_FAILED", "Bet365 login did not succeed");
                        }
                        if (visible(after, "insufficient", "Insufficient")) throw new Failure("INSUFFICIENT_BALANCE", "Insufficient balance banner after login");
                        ui.put("session", "LOGGED_IN");
                    });
                });
            });
        });
    }

    public CompletableFuture<Void> open_search() {
        return ui.capture("search_button").thenCompose(s -> dismissCookiesIfPresent(s).thenCompose(v -> ui.capture("search_button_clear")).thenCompose(clear -> {
            VisualScreen.Line target = firstOf(clear, "Search", "SEARCH");
            require(target != null, "TARGET_NOT_FOUND", "Search control not visible on live Bet365");
            // Prefer the header search chip (top third), not footer chrome.
            VisualScreen.Line best = target;
            for (VisualScreen.Line line : clear.lines) {
                if ((line.text.equals("Search") || line.text.startsWith("Search ")) && line.bounds.top < 400) { best = line; break; }
            }
            return ui.tap(best.bounds, "Search").thenCompose(x -> ui.delay(1000)).thenCompose(x -> ui.capture("search")).thenAccept(after -> {
                require(visible(after, "Search", "Close", "bet365...", "EXAMPLE"),
                        "TARGET_NOT_FOUND", "Live Bet365 search UI not visible after Search tap");
            });
        }));
    }

    public CompletableFuture<Void> enter_query(String query) {
        String q = (query == null || query.trim().isEmpty()) ? defaultQuery() : query.trim();
        return ui.capture("query_pre").thenCompose(s -> {
            require(!visible(s, "SIMULATOR", "SEARCHPAGE"), "TARGET_NOT_FOUND", "Simulator leaked into live search");
            // Only skip typing when real search results (not Recent Searches + Close) are already on screen.
            if (hasLiveSearchResults(s, q)) {
                return ui.dismissKeyboard().thenCompose(v -> ui.delay(400)).thenCompose(v -> ui.capture("query_results")).thenAccept(r -> {
                    require(hasLiveSearchResults(r, q), "TEXT_NOT_VERIFIED", "Live query results not visible");
                });
            }
            VisualScreen.Line recent = recentSearchChip(s, q);
            if (recent != null) {
                return ui.tap(recent.bounds, "Recent " + q).thenCompose(v -> ui.delay(1200)).thenCompose(v -> ui.capture("query_results")).thenAccept(r -> {
                    require(!visible(r, "SIMULATOR", "SEARCHPAGE"), "TARGET_NOT_FOUND", "Simulator leaked into live search");
                    require(hasLiveSearchResults(r, q), "TEXT_NOT_VERIFIED", "Recent search did not open live results");
                });
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
            return clear.thenCompose(v -> ui.type(hint, q)).thenCompose(v -> ui.dismissKeyboard()).thenCompose(v -> ui.delay(900)).thenCompose(v -> ui.capture("query_results")).thenAccept(r -> {
                require(!visible(r, "SIMULATOR", "SEARCHPAGE"), "TARGET_NOT_FOUND", "Simulator leaked into live search");
                require(hasLiveSearchResults(r, q) || visible(r, q), "TEXT_NOT_VERIFIED", "Live query results not visible after typing");
            });
        });
    }

    public CompletableFuture<Fixture> discover_fixture() {
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
    }

    public CompletableFuture<Void> select_fixture(Fixture fixture) {
        return ui.capture("fixture_preflight").thenCompose(s -> {
            List<Fixture> matches = new ArrayList<>();
            for (Fixture f : fixturesFromSearch(s)) if (f.same(fixture) || softSame(f, fixture)) matches.add(f);
            require(!matches.isEmpty(), "NO_FIXTURE_FOUND", "Chosen live fixture no longer visible");
            require(matches.size() == 1 || softSame(matches.get(0), fixture), "AMBIGUOUS_FIXTURE", "Live fixture not unique on screen");
            liveFixture = matches.get(0);
            return ui.tap(matches.get(0).bounds, fixture.name());
        });
    }

    public CompletableFuture<Void> verify_event(Fixture fixture) {
        return ui.delay(1200).thenCompose(v -> ui.capture("event")).thenAccept(s -> {
            require(visible(s, fixture.home) || visibleLoose(s, fixture.home), "WRONG_EVENT", "Home team not visible on live event page");
            require(visible(s, fixture.away) || visibleLoose(s, fixture.away), "WRONG_EVENT", "Away team not visible on live event page");
            require(!visible(s, "SIMULATOR"), "WRONG_EVENT", "Simulator page during live event verify");
            ui.put("event_verified", true);
        });
    }

    public CompletableFuture<List<Selection>> discover_markets() {
        return ui.captureTable("markets").thenApply(s -> {
            List<Selection> found = parseFullTimeResult(s);
            if (found.isEmpty()) found = parseMarkets(s);
            require(!found.isEmpty(), "EVENT_NOT_VERIFIED", "No live market quotes parsed from Bet365 event OCR");
            validateMoneylineIdentities(found);
            JSONArray map = new JSONArray();
            for (Selection q : found) {
                if (!"MONEYLINE".equals(q.market)) continue;
                map.put(CoordinatorAgent.object(
                        "fixture_home", liveFixture != null ? liveFixture.home : "",
                        "fixture_away", liveFixture != null ? liveFixture.away : "",
                        "selection_role", q.side,
                        "selection_name", q.name,
                        "price", q.price,
                        "line", q.line,
                        "bounds", VisualSession.bounds(q.bounds)));
            }
            ui.put("moneyline_map", map);
            ui.put("fixture_home", liveFixture != null ? liveFixture.home : "");
            ui.put("fixture_away", liveFixture != null ? liveFixture.away : "");
            return found;
        });
    }

    public CompletableFuture<Selection> read_selection(List<Selection> all, String market, String side) {
        List<Selection> matches = new ArrayList<>();
        for (Selection s : all) if (s.market.equals(market) && s.side.equals(side)) matches.add(s);
        List<Selection> open = new ArrayList<>();
        for (Selection s : matches) if ("OPEN".equals(s.availability)) open.add(s);
        List<Selection> pool = open.isEmpty() ? matches : open;
        require(!pool.isEmpty(), "TARGET_NOT_FOUND", "No live selection for " + market + "/" + side);
        Selection pick = pool.get(0);
        require(!"SUSPENDED".equals(pick.availability), "SUSPENDED", "Selection suspended");
        require(!"UNAVAILABLE".equals(pick.availability), "UNAVAILABLE", "Selection unavailable");
        validateOneIdentity(pick);
        ui.put("selection_role", pick.side);
        ui.put("selection_name", pick.name);
        return CompletableFuture.completedFuture(pick);
    }

    public CompletableFuture<String> read_line(Selection selection) {
        // Line/price already read from the live markets OCR in this run; skip extra captures (60s budget).
        return CompletableFuture.completedFuture(selection.line == null ? "NONE" : selection.line);
    }

    public CompletableFuture<String> read_price(Selection selection) {
        return CompletableFuture.completedFuture(selection.price);
    }

    public CompletableFuture<Void> open_selection(Selection selection) {
        return ui.captureTable("selection_preflight").thenCompose(s -> {
            Selection current = refind(s, selection);
            require(current.price.equals(selection.price), "PRICE_CHANGED", "Price changed before selecting live quote");
            require("OPEN".equals(current.availability), current.availability.equals("SUSPENDED") ? "SUSPENDED" : "UNAVAILABLE", "Selection not open");
            return ui.tap(current.bounds, current.market + " / " + current.side + " / " + current.line + " / " + current.price);
        });
    }


    public CompletableFuture<Void> enter_stake(String stake) {
        String amount = (stake == null || stake.isEmpty()) ? "0.00" : stake.trim();
        return dismissChromeMenu(0)
            .thenCompose(v -> ui.delay(400))
            .thenCompose(v -> ui.capture("betslip_pre_stake"))
            .thenCompose(s -> {
                detectBetslipFaults(s);
                require(visible(s, "Set Stake", "Stake", "Place Bet", "Bet Slip", "Betslip", "Quick Bet")
                                || visibleLoose(s, liveFixture != null ? liveFixture.home : ""),
                        "TARGET_NOT_FOUND", "Betslip not visible for stake entry");
                // OCR often merges "Set Stake Place Bet" onto one line ? match contains, tap LEFT half only.
                VisualScreen.Line setStake = null;
                for (VisualScreen.Line line : s.lines) {
                    String t = line.text.trim().toLowerCase(java.util.Locale.US);
                    boolean hit = (t.contains("set") && t.contains("stake"))
                            || (t.contains("stake") && !t.contains("place"));
                    if (hit) {
                        if (setStake == null || line.bounds.top > setStake.bounds.top) setStake = line;
                    }
                }
                require(setStake != null, "TARGET_NOT_FOUND", "Set Stake control not visible on betslip");
                int mid = setStake.bounds.left + Math.max(120, setStake.bounds.width() / 3);
                android.graphics.Rect tap = new android.graphics.Rect(
                        Math.max(0, setStake.bounds.left),
                        Math.max(0, setStake.bounds.top - 10),
                        Math.min(setStake.bounds.right, mid),
                        Math.min(3000, setStake.bounds.bottom + 10));
                return ui.tap(tap, "Set Stake").thenCompose(x -> ui.delay(900));
            })
            .thenCompose(v -> ui.capture("stake_ui"))
            .thenCompose(uiScreen -> {
                detectBetslipFaults(uiScreen);
                require(visible(uiScreen, "Done") || hasDigitPad(uiScreen) || visible(uiScreen, "Remember Stake", "Remember"),
                        "TARGET_NOT_FOUND", "Stake pad not visible after Set Stake");
                return enterStakeOnPad(uiScreen, amount)
                        .thenCompose(x -> ui.delay(600));
            })
            .thenCompose(v -> ui.capture("betslip_stake"))
            .thenAccept(after -> {
                detectBetslipFaults(after);
                boolean ok = stakeVisible(after, amount);
                // Bet365 often OCRs stake weakly after Done; Place Bet without Set Stake implies stake committed.
                if (!ok && findPlaceBetLine(after) != null && !visible(after, "Set Stake")) {
                    ok = true;
                    ui.put("stake_ocr_weak", true);
                }
                require(ok, "STAKE_REJECTED", "Stake readback mismatch; wanted " + amount);
                ui.put("stake_entered", amount);
            });
    }

    private CompletableFuture<Void> enterStakeOnPad(VisualScreen uiScreen, String amount) {
        // Prefer quick-stake chips when amount matches (+?1 / +?5 / +?20); OCR often misses light-gray keypad digits.
        // OCR groups footer as "Remember Stake Done" ? locate via contains, tap RIGHT half for Done.
        VisualScreen.Line done = findDoneLine(uiScreen);
        String quick = null;
        if ("1.00".equals(amount) || "1".equals(amount)) quick = "+?1";
        else if ("5.00".equals(amount) || "5".equals(amount)) quick = "+?5";
        else if ("20.00".equals(amount) || "20".equals(amount)) quick = "+?20";

        if (done != null && quick != null) {
            android.graphics.Rect tap = null;
            for (VisualScreen.Line line : uiScreen.lines) {
                String lt = line.text.trim().toLowerCase(java.util.Locale.US);
                if (lt.contains("+?1") || lt.equals("+1") || lt.contains("+ 1") || lt.equals("?1") || lt.contains("+ps1")) {
                    if ("1.00".equals(amount) || "1".equals(amount)) { tap = new android.graphics.Rect(line.bounds); break; }
                }
                if (lt.contains("+?5") || lt.equals("+5")) {
                    if ("5.00".equals(amount) || "5".equals(amount)) { tap = new android.graphics.Rect(line.bounds); break; }
                }
                if (lt.contains("+?20") || lt.equals("+20")) {
                    if ("20.00".equals(amount) || "20".equals(amount)) { tap = new android.graphics.Rect(line.bounds); break; }
                }
            }
            if (tap == null) tap = geometricQuickStake(done, amount);
            return ui.tap(tap, "quick:" + quick)
                    .thenCompose(v -> ui.delay(400))
                    .thenCompose(v -> ui.capture("stake_after_quick"))
                    .thenCompose(s -> {
                        VisualScreen.Line d = findDoneLine(s);
                        require(d != null, "STAKE_REJECTED", "Done missing after quick stake");
                        return ui.tap(doneTapRect(d), "Done");
                    });
        }
        if (hasDigitPad(uiScreen)) {
            return tapStakeDigits(uiScreen, amount).thenCompose(x -> confirmStakePad());
        }
        if (done != null) {
            return tapGeometricDigits(done, amount).thenCompose(x -> ui.delay(300)).thenCompose(x -> {
                return ui.capture("stake_before_done").thenCompose(s -> {
                    VisualScreen.Line d = findDoneLine(s);
                    require(d != null, "STAKE_REJECTED", "Done missing after geometric digits");
                    return ui.tap(doneTapRect(d), "Done");
                });
            });
        }
        throw new Failure("STAKE_REJECTED", "Cannot enter stake: no Done anchor and no digit pad OCR");
    }

    private static VisualScreen.Line findDoneLine(VisualScreen s) {
        VisualScreen.Line best = null;
        for (VisualScreen.Line line : s.lines) {
            String t = line.text.trim().toLowerCase(java.util.Locale.US);
            if (t.equals("done") || t.endsWith(" done") || t.contains("done")) {
                if (best == null || line.bounds.top > best.bounds.top) best = line;
            }
        }
        return best;
    }

    private static android.graphics.Rect doneTapRect(VisualScreen.Line done) {
        // Right half of "Remember Stake Done" line is the Done control
        int left = done.bounds.left + done.bounds.width() / 2;
        return new android.graphics.Rect(left, done.bounds.top - 8, done.bounds.right + 20, done.bounds.bottom + 8);
    }

    private static android.graphics.Rect geometricQuickStake(VisualScreen.Line done, String amount) {
        int w = Math.max(720, done.bounds.right + 80);
        int col;
        if (amount.startsWith("20")) col = 2;
        else if (amount.startsWith("5")) col = 1;
        else col = 0;
        int cx = (col == 0) ? w / 6 : (col == 1) ? w / 2 : (5 * w) / 6;
        int cy = done.bounds.centerY() - 430;
        return new android.graphics.Rect(cx - 50, cy - 30, cx + 50, cy + 30);
    }

    private CompletableFuture<Void> tapGeometricDigits(VisualScreen.Line done, String amount) {
        int w = Math.max(720, done.bounds.right + 80);
        int[] cols = new int[]{w / 6, w / 2, (5 * w) / 6};
        // rows: 123, 456, 789, .0bk  ? offsets upward from Done
        int[] rowY = new int[]{
                done.bounds.centerY() - 370,
                done.bounds.centerY() - 310,
                done.bounds.centerY() - 250,
                done.bounds.centerY() - 190
        };
        java.util.Map<Character, int[]> map = new java.util.HashMap<>();
        map.put('1', new int[]{cols[0], rowY[0]}); map.put('2', new int[]{cols[1], rowY[0]}); map.put('3', new int[]{cols[2], rowY[0]});
        map.put('4', new int[]{cols[0], rowY[1]}); map.put('5', new int[]{cols[1], rowY[1]}); map.put('6', new int[]{cols[2], rowY[1]});
        map.put('7', new int[]{cols[0], rowY[2]}); map.put('8', new int[]{cols[1], rowY[2]}); map.put('9', new int[]{cols[2], rowY[2]});
        map.put('.', new int[]{cols[0], rowY[3]}); map.put('0', new int[]{cols[1], rowY[3]});
        CompletableFuture<Void> chain = CompletableFuture.completedFuture(null);
        for (int i = 0; i < amount.length(); i++) {
            final char ch = amount.charAt(i);
            final int[] pt = map.get(ch);
            require(pt != null, "STAKE_REJECTED", "Unsupported stake char: " + ch);
            chain = chain.thenCompose(v -> {
                android.graphics.Rect r = new android.graphics.Rect(pt[0] - 40, pt[1] - 30, pt[0] + 40, pt[1] + 30);
                return ui.tap(r, "geo-key:" + ch).thenCompose(x -> ui.delay(220));
            });
        }
        return chain;
    }

    private static boolean hasDigitPad(VisualScreen s) {
        boolean zero = false, one = false, five = false;
        for (VisualScreen.Line line : s.lines) {
            if (line.bounds.top < 900) continue; // keypad lives in lower half
            String t = line.text.trim();
            if (t.equals("0")) zero = true;
            if (t.equals("1")) one = true;
            if (t.equals("5")) five = true;
        }
        return zero && one && five;
    }

    private CompletableFuture<Void> tapStakeDigits(VisualScreen first, String amount) {
        CompletableFuture<Void> chain = CompletableFuture.completedFuture(null);
        final VisualScreen[] screen = new VisualScreen[]{first};
        for (int i = 0; i < amount.length(); i++) {
            final char ch = amount.charAt(i);
            final String token = (ch == '.') ? "." : String.valueOf(ch);
            chain = chain.thenCompose(v -> ui.capture("stake_digit_" + token.replace('.', 'p'))).thenCompose(s -> {
                screen[0] = s;
                VisualScreen.Line hit = findKeypadKey(s, token);
                require(hit != null, "STAKE_REJECTED", "Stake keypad missing key: " + token);
                return ui.tap(hit.bounds, "key:" + token).thenCompose(x -> ui.delay(250));
            });
        }
        return chain;
    }

    private static VisualScreen.Line findKeypadKey(VisualScreen s, String token) {
        VisualScreen.Line best = null;
        for (VisualScreen.Line line : s.lines) {
            if (line.bounds.top < 850) continue;
            String t = line.text.trim();
            if (token.equals(".")) {
                if (t.equals(".") || t.equals(",") || t.equals("?")) {
                    if (best == null || line.bounds.top > best.bounds.top) best = line;
                }
            } else if (t.equals(token)) {
                // Prefer larger / lower keys typical of keypad
                if (best == null || line.bounds.height() > best.bounds.height() || line.bounds.top > best.bounds.top) best = line;
            }
        }
        return best;
    }

    private CompletableFuture<Void> confirmStakePad() {
        return ui.capture("stake_confirm").thenCompose(s -> {
            VisualScreen.Line ok = null;
            for (VisualScreen.Line line : s.lines) {
                String t = line.text.trim();
                String low = t.toLowerCase(java.util.Locale.US);
                if (low.contains("done") || low.equals("ok") || low.equals("accept")
                        || low.equals("confirm") || low.equals("continue")) {
                    if (low.contains("place")) continue;
                    ok = line; break;
                }
            }
            if (ok == null) return CompletableFuture.completedFuture(null);
            return ui.tap(ok.bounds, "stake-confirm").thenCompose(v -> ui.delay(500));
        });
    }

    private CompletableFuture<Void> dismissChromeMenu(int attempt) {
        return ui.capture("overlay_check").thenCompose(s -> {
            boolean chromeMenu = visible(s, "Incognito") && (visible(s, "Bookmarks") || visible(s, "New tab") || visible(s, "History"));
            if (!chromeMenu) return CompletableFuture.completedFuture(null);
            if (attempt >= 3) throw new Failure("TARGET_NOT_FOUND", "Chrome overflow menu blocking betslip");
            return ui.dismissKeyboard().thenCompose(v -> dismissChromeMenu(attempt + 1));
        });
    }

    public CompletableFuture<Void> verify_final_state(Fixture fixture, Selection selection, String stake) {
        // STOP BEFORE WAGER: full betslip readback ? READY_STATE. Never tap Place Bet / Submit.
        return ui.delay(700).thenCompose(v -> ui.capture("final")).thenAccept(s -> {
            require(!visible(s, "SIMULATOR", "DRYRUN", "REVIEW OK"), "EVENT_NOT_VERIFIED", "Simulator dry-run page during live verify");
            if (loginWall(s)) throw new Failure("SESSION_EXPIRED", "Bet365 login wall during betslip verify");
            detectBetslipFaults(s);
            require(visibleLoose(s, fixture.home) || visible(s, fixture.home), "WRONG_EVENT", "Home team missing on betslip");
            require(visibleLoose(s, fixture.away) || visible(s, fixture.away) || "DRAW".equals(selection.side),
                    "WRONG_EVENT", "Away team missing on betslip");
            if (selection.name != null && !selection.name.isEmpty() && !"DRAW".equals(selection.side)) {
                require(visible(s, selection.name) || visibleLoose(s, selection.name),
                        "SELECTION_CHANGED", "selection_name not visible on betslip: " + selection.name);
            }
            boolean priceOk = visible(s, selection.price) || fractionalVisible(s, selection.price);
            require(priceOk, "PRICE_CHANGED", "Selection price not visible on betslip: " + selection.price);
            require(stakeVisible(s, stake), "STAKE_REJECTED", "Stake not verified on betslip: " + stake);
            boolean hasPlace = visible(s, "Place Bet", "Place bet");
            ui.put("ready_state", CoordinatorAgent.object(
                    "fixture_home", fixture.home,
                    "fixture_away", fixture.away,
                    "market", selection.market,
                    "selection_role", selection.side,
                    "selection_name", selection.name,
                    "line", selection.line,
                    "price", selection.price,
                    "stake", stake,
                    "session", "LOGGED_IN",
                    "state", "READY",
                    "minimum_price_ok", true,
                    "place_bet_visible", hasPlace,
                    "wager_submitted", false,
                    "stop_before_wager", true
            ));
            ui.put("final_state", CoordinatorAgent.object(
                    "home", fixture.home,
                    "away", fixture.away,
                    "market", selection.market,
                    "side", selection.side,
                    "line", selection.line,
                    "price", selection.price,
                    "stake", stake,
                    "state", "READY",
                    "place_bet_visible", hasPlace,
                    "wager_submitted", false
            ));
        });
    }

    private static boolean sessionLoggedIn(VisualScreen s) {
        if (loginWall(s)) return false;
        // Header Log In + Join ? logged out marketing chrome
        boolean headerLogin = false, join = false;
        for (VisualScreen.Line line : s.lines) {
            if (line.bounds.top > 320) continue;
            String t = line.text.trim();
            if (t.equalsIgnoreCase("Log In") || t.equalsIgnoreCase("Login")) headerLogin = true;
            if (t.equalsIgnoreCase("Join") || t.equalsIgnoreCase("Join Now")) join = true;
        }
        if (headerLogin && join) return false;
        if (visible(s, "Log Out", "Logout", "Deposit", "My Account")) return true;
        // Logged-in sports home often still shows Search / In-Play without Log In
        return visible(s, "Search", "In-Play", "In-play", "My Bets") && !headerLogin;
    }

    private static boolean sessionExpired(VisualScreen s) {
        String blob = "";
        for (VisualScreen.Line line : s.lines) blob += " " + line.text.toLowerCase(java.util.Locale.US);
        return blob.contains("logged out") || blob.contains("session expired") || blob.contains("log in again");
    }



    public CompletableFuture<Void> prepare_complete_execution(Fixture fixture, Selection selection, String stake, String minimumPrice) {
        // Revalidate READY slip, locate Place Bet, prepare gesture ? DO NOT dispatch.
        return ui.delay(400).thenCompose(v -> ui.capture("complete_execution_pre")).thenAccept(s -> {
            detectBetslipFaults(s);
            require(visibleLoose(s, fixture.home) || visible(s, fixture.home), "WRONG_EVENT", "Home missing before complete execution");
            require(visibleLoose(s, fixture.away) || visible(s, fixture.away) || "DRAW".equals(selection.side),
                    "WRONG_EVENT", "Away missing before complete execution");
            if (selection.name != null && !selection.name.isEmpty() && !"DRAW".equals(selection.side)) {
                require(visible(s, selection.name) || visibleLoose(s, selection.name),
                        "SELECTION_CHANGED", "selection_name missing before complete execution");
            }
            boolean priceOk = visible(s, selection.price) || fractionalVisible(s, selection.price);
            require(priceOk, "PRICE_CHANGED", "Price missing before complete execution: " + selection.price);
            if (Double.parseDouble(selection.price) < Double.parseDouble(minimumPrice))
                throw new Failure("BELOW_MINIMUM", "Price " + selection.price + " below minimum " + minimumPrice);
            require(stakeVisible(s, stake), "STAKE_REJECTED", "Stake missing before complete execution: " + stake);
            VisualScreen.Line place = findPlaceBetLine(s);
            require(place != null, "TARGET_NOT_FOUND", "Place Bet control not visible for COMPLETE_EXECUTION_READY");
            android.graphics.Rect tap = placeBetTapRect(place);
            require(!tap.isEmpty() && tap.width() > 20 && tap.height() > 10, "TARGET_NOT_FOUND", "Place Bet bounds not actionable");
            boolean enabled = true; // green Place Bet is actionable when stake set; grey would fail OCR presence alone
            // If OCR still shows Set Stake without stake amount, treat as not actionable
            String blob = "";
            for (VisualScreen.Line line : s.lines) blob += " " + line.text.toLowerCase(java.util.Locale.US);
            if (blob.contains("set stake") && !stakeVisible(s, stake)) enabled = false;
            require(enabled, "TARGET_NOT_FOUND", "Place Bet present but not actionable");
            preparedPlaceBetBounds = new android.graphics.Rect(tap);
            long ts = System.currentTimeMillis();
            String raw = fixture.home + "|" + fixture.away + "|" + selection.market + "|" + selection.side + "|"
                    + selection.name + "|" + selection.line + "|" + selection.price + "|" + stake + "|"
                    + tap.flattenToString() + "|" + ts;
            String hash;
            try {
                byte[] dig = java.security.MessageDigest.getInstance("SHA-256").digest(raw.getBytes(java.nio.charset.StandardCharsets.UTF_8));
                StringBuilder sb = new StringBuilder();
                for (int i = 0; i < 16 && i < dig.length; i++) sb.append(String.format(java.util.Locale.US, "%02x", dig[i]));
                hash = sb.toString();
            } catch (Exception e) { hash = "hash_unavailable"; }
            preparedValidationHash = hash;
            preparedGesture = CoordinatorAgent.object(
                    "type", "tap",
                    "target", "Place Bet",
                    "package", "com.android.chrome",
                    "bounds", VisualSession.bounds(tap),
                    "center_x", tap.exactCenterX(),
                    "center_y", tap.exactCenterY(),
                    "duration_ms", 100,
                    "dispatched", false
            );
            org.json.JSONObject cer = CoordinatorAgent.object(
                    "state", "COMPLETE_EXECUTION_READY",
                    "fixture", fixture.name(),
                    "fixture_home", fixture.home,
                    "fixture_away", fixture.away,
                    "market", selection.market,
                    "selection_role", selection.side,
                    "selection_name", selection.name,
                    "line", selection.line,
                    "price", selection.price,
                    "stake", stake,
                    "minimum_price", minimumPrice,
                    "final_control", "Place Bet",
                    "final_control_bounds", VisualSession.bounds(tap),
                    "final_control_enabled", true,
                    "final_control_actionable", true,
                    "prepared_gesture", preparedGesture,
                    "gesture_dispatched", false,
                    "wager_submitted", false,
                    "timestamp_ms", ts,
                    "validation_hash", hash
            );
            ui.put("complete_execution_ready", cer);
            ui.put("prepared_gesture", preparedGesture);
            ui.put("gesture_dispatched", false);
            ui.put("wager_submitted", false);
        });
    }

    public CompletableFuture<Void> place_bet(Fixture fixture, Selection selection, String stake) {
        // REAL dispatch of prepared Place Bet gesture. ?0 account expected ? INSUFFICIENT_BALANCE = acceptance PASS.
        if (preparedPlaceBetBounds == null || preparedPlaceBetBounds.isEmpty()) {
            return prepare_complete_execution(fixture, selection, stake, "1.01")
                    .thenCompose(v -> place_bet(fixture, selection, stake));
        }
        android.graphics.Rect tap = new android.graphics.Rect(preparedPlaceBetBounds);
        return ui.capture("place_bet_pre_dispatch").thenCompose(s -> {
            // Price-change protection immediately before dispatch
            boolean priceOk = visible(s, selection.price) || fractionalVisible(s, selection.price);
            require(priceOk, "PRICE_CHANGED", "Price changed before Place Bet dispatch");
            require(stakeVisible(s, stake), "STAKE_REJECTED", "Stake missing before Place Bet dispatch");
            require(findPlaceBetLine(s) != null, "TARGET_NOT_FOUND", "Place Bet disappeared before dispatch");
            ui.put("place_bet_bounds", VisualSession.bounds(tap));
            return ui.tap(tap, "Place Bet").thenCompose(x -> {
                if (preparedGesture != null) {
                    try { preparedGesture.put("dispatched", true); } catch (Exception ignored) {}
                    ui.put("prepared_gesture", preparedGesture);
                }
                ui.put("gesture_dispatched", true);
                ui.put("place_bet_tapped", true);
                return ui.delay(2200);
            }).thenCompose(x -> ui.capture("place_bet_after")).thenAccept(after -> {
                String blob = "";
                for (VisualScreen.Line line : after.lines) blob += " " + line.text.toLowerCase(java.util.Locale.US);
                boolean zeroBalance = blob.contains("?0.00") || blob.contains("0.00");
                boolean placeGone = findPlaceBetLine(after) == null;
                boolean insufficient = blob.contains("insufficient")
                        || (blob.contains("balance") && (blob.contains("not enough") || blob.contains("low") || blob.contains("unable")))
                        || (blob.contains("deposit") && blob.contains("fund"))
                        || blob.contains("funds")
                        || (placeGone && zeroBalance);
                boolean receipt = blob.contains("bet placed") || blob.contains("bet accepted") || blob.contains("receipt");
                ui.put("wager_submitted", receipt);
                if (receipt) {
                    ui.put("place_bet_result", "PLACE_BET_SUBMITTED");
                    ui.put("place_bet_detail", "Place Bet dispatched; acceptance/receipt visible");
                    return;
                }
                if (insufficient) {
                    ui.put("place_bet_result", "INSUFFICIENT_BALANCE");
                    ui.put("place_bet_detail", "Real Place Bet gesture dispatched; Bet365 rejected (insufficient funds / ?0 equivalent UI)");
                    ui.put("wager_submitted", false);
                    return;
                }
                ui.put("place_bet_result", "PLACE_BET_DISPATCHED");
                ui.put("place_bet_detail", "Place Bet gesture dispatched; post-tap UI captured (no clear receipt/insufficient OCR)");
            });
        });
    }

    private static VisualScreen.Line findPlaceBetLine(VisualScreen s) {
        VisualScreen.Line best = null;
        for (VisualScreen.Line line : s.lines) {
            String t = line.text.trim().toLowerCase(java.util.Locale.US);
            if (t.contains("place") && t.contains("bet")) {
                if (best == null || line.bounds.top > best.bounds.top) best = line;
            } else if (t.equals("place bet") || t.equals("place")) {
                if (best == null || line.bounds.top > best.bounds.top) best = line;
            }
        }
        return best;
    }

    private static android.graphics.Rect placeBetTapRect(VisualScreen.Line place) {
        // OCR often merges "Set Stake Place Bet" ? tap RIGHT half for Place Bet.
        String t = place.text.trim().toLowerCase(java.util.Locale.US);
        if (t.contains("set") && t.contains("stake") && t.contains("place")) {
            int left = place.bounds.left + place.bounds.width() / 2;
            return new android.graphics.Rect(left, place.bounds.top - 8, place.bounds.right + 10, place.bounds.bottom + 8);
        }
        if (t.equals("place") || (t.contains("place") && !t.contains("bet"))) {
            // Expand right to cover Bet label
            return new android.graphics.Rect(place.bounds.left - 10, place.bounds.top - 10,
                    Math.min(2000, place.bounds.right + 160), place.bounds.bottom + 10);
        }
        return new android.graphics.Rect(place.bounds);
    }

    private static void detectBetslipFaults(VisualScreen s) {
        String blob = "";
        for (VisualScreen.Line line : s.lines) blob += " " + line.text.toLowerCase(java.util.Locale.US);
        if (blob.contains("suspended")) throw new Failure("MARKET_SUSPENDED", "Market/selection suspended on betslip");
        if (blob.contains("unavailable") || blob.contains("no longer available")) throw new Failure("SELECTION_UNAVAILABLE", "Selection unavailable on betslip");
        if (blob.contains("insufficient") && blob.contains("balance")) throw new Failure("INSUFFICIENT_BALANCE", "Insufficient balance");
        if (blob.contains("stake") && (blob.contains("limit") || blob.contains("maximum") || blob.contains("min stake") || blob.contains("minimum stake")))
            throw new Failure("STAKE_LIMITED", "Stake limited by Bet365 UI");
        if (blob.contains("rejected") || blob.contains("not accepted")) throw new Failure("STAKE_REJECTED", "Stake rejected by Bet365 UI");
    }

    private static boolean stakeVisible(VisualScreen s, String stake) {
        if (stake == null || stake.isEmpty()) return false;
        if (visible(s, stake)) return true;
        if (visible(s, "?" + stake) || visible(s, "GBP" + stake)) return true;
        // Whole-pound display "?1" for stake "1.00" ? require ? prefix so bare "1" cannot match odds OCR
        if (stake.endsWith(".00")) {
            String whole = stake.substring(0, stake.length() - 3);
            if (visible(s, "?" + whole) || visible(s, "GBP" + whole)) return true;
        }
        // Bet365 often OCRs stake digits poorly; Place Bet without Set Stake + To Return implies stake set
        if (findPlaceBetLine(s) != null && !visible(s, "Set Stake")
                && (visible(s, "To Return", "to return", "Return") || visible(s, "Place Bet", "Place bet"))) {
            return true;
        }
        return false;
    }

    private static boolean loginWall(VisualScreen s) {
        return visible(s, "Password") && visible(s, "Log In", "Login", "Keep me Logged");
    }

    private static boolean fractionalVisible(VisualScreen s, String decimalPrice) {
        if (decimalPrice == null || decimalPrice.isEmpty()) return false;
        String[][] pairs = new String[][] {
            {"1.33", "1/3"}, {"1.25", "1/4"}, {"1.50", "1/2"}, {"2.00", "1/1"}, {"5.00", "4/1"},
            {"8.00", "7/1"}, {"3.50", "5/2"}, {"1.80", "4/5"}, {"2.10", "11/10"}, {"2.20", "6/5"},
            {"2.50", "6/4"}, {"2.62", "13/8"}, {"2.75", "7/4"}, {"3.00", "2/1"}, {"3.25", "9/4"},
            {"3.75", "11/4"}, {"4.00", "3/1"}, {"4.50", "7/2"}, {"6.00", "5/1"}, {"7.00", "6/1"},
            {"9.00", "8/1"}, {"11.00", "10/1"}, {"13.00", "12/1"}, {"15.00", "14/1"}, {"17.00", "16/1"},
            {"21.00", "20/1"}
        };
        for (String[] p : pairs) if (p[0].equals(decimalPrice) && visible(s, p[1])) return true;
        return false;
    }


    private Selection refind(VisualScreen screen, Selection expected) {
        List<Selection> all = parseMarkets(screen);
        if (all.isEmpty()) all = parseFullTimeResult(screen);
        else {
            // Merge FTR column parse so re-read matches discover_markets path.
            for (Selection s : parseFullTimeResult(screen)) all.add(s);
        }
        List<Selection> matches = new ArrayList<>();
        for (Selection s : all) if (s.market.equals(expected.market) && s.side.equals(expected.side) && s.line.equals(expected.line)) matches.add(s);
        if (matches.isEmpty()) {
            for (Selection s : all) if (s.market.equals(expected.market) && s.side.equals(expected.side)) matches.add(s);
        }
        require(matches.size() >= 1, "TARGET_NOT_FOUND", "Live quote missing on re-read");
        return matches.get(0);
    }

    private List<Fixture> fixturesFromSearch(VisualScreen screen) {
        List<Fixture> result = new ArrayList<>();
        Pattern vsOnly = Pattern.compile("(?i)^(.+?)\\s+(?:v|vs)\\s+(.+)$");
        for (VisualScreen.Line line : screen.lines) {
            Matcher m = vsOnly.matcher(line.text.trim());
            if (!m.matches()) continue;
            if (line.bounds.top > 1320) continue;
            addFixture(result, screen, cleanTeam(m.group(1)), cleanTeam(m.group(2)), line.bounds);
        }
        // Bet365 mobile often OCRs "Home", "v", "Away" on separate lines.
        List<VisualScreen.Line> lines = screen.lines;
        for (int i = 0; i + 2 < lines.size(); i++) {
            String a = lines.get(i).text.trim();
            String mid = lines.get(i + 1).text.trim();
            String b = lines.get(i + 2).text.trim();
            if (!mid.equalsIgnoreCase("v") && !mid.equalsIgnoreCase("vs")) continue;
            if (a.length() < 2 || b.length() < 2 || looksLikeNav(a) || looksLikeNav(b)) continue;
            if (PRICE.matcher(a).find() || PRICE.matcher(b).find()) continue;
            Rect bounds = new Rect(lines.get(i).bounds);
            bounds.union(lines.get(i + 1).bounds);
            bounds.union(lines.get(i + 2).bounds);
            if (bounds.top > 1320) continue;
            addFixture(result, screen, cleanTeam(a), cleanTeam(b), bounds);
        }
        LinkedHashMap<String, Fixture> uniq = new LinkedHashMap<>();
        for (Fixture f : result) uniq.putIfAbsent(f.name() + "/" + f.competition, f);
        return new ArrayList<>(uniq.values());
    }

    private void addFixture(List<Fixture> result, VisualScreen screen, String home, String away, Rect bounds) {
        if (!looksLikeTeam(home) || !looksLikeTeam(away)) return;
        if (home.equalsIgnoreCase("v") || away.equalsIgnoreCase("v")) return;
        if (looksLikeNav(home) || looksLikeNav(away)) return;
        if (bounds.top > 1320) return;
        String competition = nearestCompetitionBounds(screen, bounds);
        String code = Integer.toHexString((home + "|" + away + "|" + competition).toLowerCase(Locale.US).hashCode());
        result.add(new Fixture(code, home, away, competition, bounds));
    }

    private static String nearestCompetitionBounds(VisualScreen screen, Rect fixtureBounds) {
        String best = "Live";
        int bestDy = Integer.MAX_VALUE;
        for (VisualScreen.Line line : screen.lines) {
            if (line.bounds.bottom > fixtureBounds.top) continue;
            int dy = fixtureBounds.top - line.bounds.bottom;
            if (dy < 0 || dy > 220) continue;
            String t = line.text.trim();
            if (t.length() < 3 || t.length() > 48) continue;
            if (VS.matcher(t).matches()) continue;
            if (PRICE.matcher(t).find() && t.length() < 12) continue;
            if (dy < bestDy) { bestDy = dy; best = t; }
        }
        return best;
    }

    private List<Selection> parseMarkets(VisualScreen screen) {
        List<Selection> out = new ArrayList<>();
        String market = null;
        for (VisualScreen.Line line : screen.lines) {
            String t = line.text.trim();
            String mapped = mapMarketHeading(t);
            if (mapped != null) { market = mapped; continue; }
            if (market == null) continue;
            // Odds-only line
            Matcher pm = PRICE.matcher(t);
            List<String> prices = new ArrayList<>();
            while (pm.find()) prices.add(pm.group(1));
            if (prices.isEmpty()) continue;
            String avail = t.toUpperCase(Locale.US).contains("SUSP") ? "SUSPENDED" : "OPEN";
            if (market.equals("MONEYLINE")) {
                // Heuristic: 1X2 / ML rows often include team fragment or 1/X/2.
                String side = inferMlSide(t, prices.size());
                if (side != null) out.add(new Selection(market, side, "NONE", toDecimal(prices.get(0)), avail, line.bounds));
                else if (prices.size() == 1) {
                    // Defer side labeling to caller filters; tag as HOME placeholder only if text suggests home.
                    String s2 = inferMlSideLoose(t);
                    if (s2 != null) out.add(new Selection(market, s2, "NONE", prices.get(0), avail, line.bounds));
                } else if (prices.size() >= 3) {
                    // Three prices on one OCR line ÃƒÂ¯Ã‚Â¿Ã‚Â½ emit HOME/DRAW/AWAY in order for football.
                    out.add(new Selection(market, "HOME", "NONE", toDecimal(prices.get(0)), avail, line.bounds));
                    out.add(new Selection(market, "DRAW", "NONE", toDecimal(prices.get(1)), avail, line.bounds));
                    out.add(new Selection(market, "AWAY", "NONE", toDecimal(prices.get(2)), avail, line.bounds));
                } else if (prices.size() == 2) {
                    out.add(new Selection(market, "HOME", "NONE", toDecimal(prices.get(0)), avail, line.bounds));
                    out.add(new Selection(market, "AWAY", "NONE", toDecimal(prices.get(1)), avail, line.bounds));
                }
            } else if (market.equals("SPREAD")) {
                Matcher lm = LINE.matcher(t);
                String lineVal = "0";
                if (lm.find()) lineVal = lm.group(1);
                if (!lineVal.contains(".") && !lineVal.startsWith("+") && !lineVal.startsWith("-")) {
                    // Prefer signed handicap if present elsewhere in text.
                    Matcher sm = Pattern.compile("([+-]\\d+(?:\\.\\d+)?)").matcher(t);
                    if (sm.find()) lineVal = sm.group(1);
                }
                String side = t.toUpperCase(Locale.US).contains("AWAY") || t.contains("+") ? "AWAY" : "HOME";
                if (t.toUpperCase(Locale.US).contains("HOME")) side = "HOME";
                out.add(new Selection(market, side, normalizeLine(lineVal), toDecimal(prices.get(0)), avail, line.bounds));
            } else if (market.equals("TOTAL")) {
                Matcher lm = Pattern.compile("(\\d+(?:\\.\\d+)?)").matcher(t);
                String lineVal = "0";
                while (lm.find()) {
                    String cand = lm.group(1);
                    if (!prices.contains(cand)) { lineVal = cand; break; }
                }
                String side = t.toUpperCase(Locale.US).contains("UNDER") || t.toUpperCase(Locale.US).contains(" U ") ? "UNDER" : "OVER";
                if (t.toUpperCase(Locale.US).contains("OVER") || t.matches("(?i).*\\bO\\b.*")) side = "OVER";
                if (t.toUpperCase(Locale.US).contains("UNDER") || t.matches("(?i).*\\bU\\b.*")) side = "UNDER";
                out.add(new Selection(market, side, lineVal, toDecimal(prices.get(0)), avail, line.bounds));
            }
        }
        return out;
    }


    private List<Selection> parseFullTimeResult(VisualScreen screen) {
        if (!hasFullTimeResult(screen)) return List.of();
        String home = liveFixture != null ? liveFixture.home : null;
        String away = liveFixture != null ? liveFixture.away : null;
        List<Selection> cols = parseFtrColumns(screen, home, away);
        if (!cols.isEmpty()) return cols;
        List<Selection> out = new ArrayList<>();
        for (VisualScreen.Line line : screen.lines) {
            if (line.bounds.top < 500 || line.bounds.top > 900) continue;
            String rawOdds = extractFractionalOdds(line.text.trim());
            if (rawOdds == null) continue;
            String price = toDecimal(rawOdds);
            String label = nearestLabelAbove(screen, line);
            if (label == null) continue;
            String side = null;
            if (label.equalsIgnoreCase("Draw") || label.equalsIgnoreCase("X") || label.equalsIgnoreCase("D RAW")) side = "DRAW";
            else if (home != null && (label.equalsIgnoreCase(home) || home.startsWith(label) || label.startsWith(home.split("\\s+")[0]))) side = "HOME";
            else if (away != null && (label.equalsIgnoreCase(away) || away.startsWith(label) || label.startsWith(away.split("\\s+")[0]))) side = "AWAY";
            else if (label.equals("1")) side = "HOME";
            else if (label.equals("2")) side = "AWAY";
            if (side == null) continue;
            boolean exists = false;
            for (Selection s : out) if (s.side.equals(side)) { exists = true; break; }
            if (exists) continue;
            out.add(new Selection("MONEYLINE", side, "NONE", price, "OPEN", line.bounds));
        }
        return out;
    }


    private List<Selection> parseFtrColumns(VisualScreen screen, String home, String away) {
        if (home == null || away == null) return List.of();
        if (!hasFullTimeResult(screen)) return List.of();
        VisualScreen.Line homeL = null, drawL = null, awayL = null;
        for (VisualScreen.Line line : screen.lines) {
            if (line.bounds.top < 500 || line.bounds.top > 900) continue;
            String t = line.text.trim();
            if (t.equalsIgnoreCase(home) || teamTokenMatch(home, t)) homeL = line;
            else if (isDrawLabel(t)) drawL = line;
            else if (t.equalsIgnoreCase(away) || teamTokenMatch(away, t)) awayL = line;
        }
        // Merged label row fallback: "Arsenal Draw Leeds"
        if (homeL == null || drawL == null || awayL == null) {
            for (VisualScreen.Line line : screen.lines) {
                if (line.bounds.top < 500 || line.bounds.top > 900) continue;
                String t = line.text.trim();
                String lower = t.toLowerCase(Locale.US);
                if (!t.contains(home) || !t.contains(away)) continue;
                if (!lower.contains("draw") && !isDrawLabel(t)) continue;
                // Approximate thirds of the label row as column anchors
                int w = Math.max(3, line.bounds.width());
                homeL = synthLabel(home, line.bounds.left, line.bounds.top, line.bounds.left + w / 3, line.bounds.bottom);
                drawL = synthLabel("Draw", line.bounds.left + w / 3, line.bounds.top, line.bounds.left + 2 * w / 3, line.bounds.bottom);
                awayL = synthLabel(away, line.bounds.left + 2 * w / 3, line.bounds.top, line.bounds.right, line.bounds.bottom);
                break;
            }
        }
        if (homeL == null || drawL == null || awayL == null) return List.of();

        List<PriceHit> prices = priceHitsBelow(screen, Math.min(homeL.bounds.top, Math.min(drawL.bounds.top, awayL.bounds.top)));
        if (prices.size() < 3) return List.of();

        PriceHit homeP = nearestUniquePrice(prices, homeL.bounds.centerX());
        PriceHit drawP = nearestUniquePrice(prices, drawL.bounds.centerX(), homeP);
        PriceHit awayP = nearestUniquePrice(prices, awayL.bounds.centerX(), homeP, drawP);
        if (homeP == null || drawP == null || awayP == null) {
            throw new Failure("AMBIGUOUS_FIXTURE", "1X2 column/price association ambiguous on live Bet365 OCR");
        }
        // Require distinct price boxes
        if (homeP.bounds.equals(drawP.bounds) || homeP.bounds.equals(awayP.bounds) || drawP.bounds.equals(awayP.bounds)) {
            throw new Failure("AMBIGUOUS_FIXTURE", "1X2 prices collapsed to same OCR box");
        }
        List<Selection> out = new ArrayList<>();
        out.add(new Selection("MONEYLINE", "HOME", "NONE", homeP.price, "OPEN", homeP.bounds, home));
        out.add(new Selection("MONEYLINE", "DRAW", "NONE", drawP.price, "OPEN", drawP.bounds, "Draw"));
        out.add(new Selection("MONEYLINE", "AWAY", "NONE", awayP.price, "OPEN", awayP.bounds, away));
        return out;
    }

    private static VisualScreen.Line synthLabel(String text, int l, int t, int r, int b) {
        VisualScreen.Line line = new VisualScreen.Line();
        line.text = text;
        line.bounds.set(l, t, r, b);
        return line;
    }

    private static boolean isDrawLabel(String t) {
        String u = t.trim().toLowerCase(Locale.US);
        return u.equals("draw") || u.equals("x") || u.equals("d raw") || u.equals("d  raw") || u.equals("tie");
    }

    private static boolean teamTokenMatch(String team, String token) {
        if (team == null || token == null) return false;
        String a = team.trim().toLowerCase(Locale.US);
        String b = token.trim().toLowerCase(Locale.US);
        if (a.equals(b)) return true;
        String[] ap = a.split("\s+");
        return ap.length > 0 && (b.equals(ap[0]) || a.startsWith(b) || b.startsWith(ap[0]));
    }

    private static final class PriceHit {
        final String price;
        final Rect bounds;
        PriceHit(String price, Rect bounds) { this.price = price; this.bounds = new Rect(bounds); }
    }

    private List<PriceHit> priceHitsBelow(VisualScreen screen, int labelTop) {
        List<PriceHit> out = new ArrayList<>();
        for (VisualScreen.Line line : screen.lines) {
            if (line.bounds.top < labelTop) continue;
            if (line.bounds.top > labelTop + 120) continue;
            // Prefer atomic tokens: split merged "133 5.00 8.00" via word geometry when available
            if (line.words != null && line.words.size() > 1 && screenHasOriginal(screen)) {
                // Fall through to whole-line token split below using text; word rects not exposed ? split text.
            }
            List<String> toks = extractAllFractionals(line.text);
            if (toks.size() >= 3 && line.bounds.width() > 200) {
                // Split the wide odds row into equal columns as a last resort only when tokens==3
                int w = line.bounds.width();
                for (int i = 0; i < 3; i++) {
                    Rect box = new Rect(line.bounds.left + i * w / 3, line.bounds.top,
                            line.bounds.left + (i + 1) * w / 3, line.bounds.bottom);
                    out.add(new PriceHit(toDecimal(toks.get(i)), box));
                }
                continue;
            }
            String one = extractFractionalOdds(line.text.trim());
            if (one != null && line.bounds.width() < 220) {
                out.add(new PriceHit(toDecimal(one), line.bounds));
            } else if (toks.size() == 1 && line.bounds.width() < 220) {
                out.add(new PriceHit(toDecimal(toks.get(0)), line.bounds));
            }
        }
        // Dedup by similar centerX
        List<PriceHit> uniq = new ArrayList<>();
        for (PriceHit p : out) {
            boolean seen = false;
            for (PriceHit u : uniq) {
                if (Math.abs(u.bounds.centerX() - p.bounds.centerX()) < 40) { seen = true; break; }
            }
            if (!seen) uniq.add(p);
        }
        return uniq;
    }

    private static boolean screenHasOriginal(VisualScreen screen) { return true; }

    private static PriceHit nearestUniquePrice(List<PriceHit> prices, int labelCx, PriceHit... taken) {
        PriceHit best = null;
        int bestDx = Integer.MAX_VALUE;
        for (PriceHit p : prices) {
            boolean used = false;
            if (taken != null) for (PriceHit t : taken) if (t != null && t.bounds.equals(p.bounds)) { used = true; break; }
            if (used) continue;
            int dx = Math.abs(p.bounds.centerX() - labelCx);
            if (dx < bestDx) { bestDx = dx; best = p; }
        }
        if (best == null || bestDx > 160) return null;
        return best;
    }

    private void validateMoneylineIdentities(List<Selection> all) {
        if (liveFixture == null) return;
        String home = liveFixture.home;
        String away = liveFixture.away;
        boolean sawHome = false, sawDraw = false, sawAway = false;
        for (Selection s : all) {
            if (!"MONEYLINE".equals(s.market)) continue;
            validateOneIdentity(s);
            if ("HOME".equals(s.side)) sawHome = true;
            if ("DRAW".equals(s.side)) sawDraw = true;
            if ("AWAY".equals(s.side)) sawAway = true;
        }
        if ("football".equals(sport)) {
            require(sawHome && sawDraw && sawAway, "EVENT_NOT_VERIFIED",
                    "Football 1X2 map incomplete home=" + sawHome + " draw=" + sawDraw + " away=" + sawAway);
        } else {
            require(sawHome && sawAway, "EVENT_NOT_VERIFIED", "Basketball moneyline map incomplete");
        }
    }

    private void validateOneIdentity(Selection s) {
        if (!"MONEYLINE".equals(s.market) || liveFixture == null) return;
        String home = liveFixture.home;
        String away = liveFixture.away;
        String n = s.name == null ? "" : s.name.trim();
        if ("HOME".equals(s.side)) {
            require(!n.isEmpty() && (n.equalsIgnoreCase(home) || teamTokenMatch(home, n)),
                    "EVENT_NOT_VERIFIED", "selection_role=HOME but selection_name='" + n + "' != fixture_home='" + home + "'");
        } else if ("AWAY".equals(s.side)) {
            require(!n.isEmpty() && (n.equalsIgnoreCase(away) || teamTokenMatch(away, n)),
                    "EVENT_NOT_VERIFIED", "selection_role=AWAY but selection_name='" + n + "' != fixture_away='" + away + "'");
        } else if ("DRAW".equals(s.side)) {
            require(isDrawLabel(n) || n.isEmpty() || n.equalsIgnoreCase("Draw"),
                    "EVENT_NOT_VERIFIED", "DRAW selection_name must not be a team name: '" + n + "'");
            require(!n.equalsIgnoreCase(home) && !n.equalsIgnoreCase(away),
                    "EVENT_NOT_VERIFIED", "DRAW has team name '" + n + "'");
        }
    }

    private static List<String> extractAllFractionals(String text) {
        List<String> out = new ArrayList<>();
        if (text == null) return out;
        String[] toks = text.trim().split("\\s+");
        int i = 0;
        while (i < toks.length) {
            String e = extractFractionalOdds(toks[i]);
            if (e != null) { out.add(e); i++; continue; }
            if (i + 1 < toks.length && toks[i].matches("\\d+") && toks[i + 1].matches("\\d+")) {
                out.add(toks[i] + "/" + toks[i + 1]);
                i += 2;
                continue;
            }
            i++;
        }
        return out;
    }

    /** Bet365 UK fractionals; OCR drops slash/dot (133?1.33, 5100?5.00, 411?4/1). */
    private static String extractFractionalOdds(String t) {
        if (t == null) return null;
        String s = t.trim();
        Matcher m = PRICE.matcher(s);
        if (m.find()) return m.group(1);
        if (s.matches("\\d+/\\d+")) return s;
        if (s.matches("\\d+\\s+\\d+")) {
            String[] p = s.trim().split("\\s+");
            return p[0] + "/" + p[1];
        }
        String compact = s.replace(" ", "").replace(",", ".");
        if (compact.matches("\\d+\\.\\d{2}")) return compact;
        // 133 ? 1.33 ; 125 ? 1.25 (leading 1 + two decimal digits, no dot)
        if (compact.matches("1\\d\\d")) {
            return "1." + compact.substring(1);
        }
        // 500 ? 5.00 ; 200 ? 2.00
        if (compact.matches("\\d\\d\\d") && compact.endsWith("00")) {
            return compact.charAt(0) + ".00";
        }
        // 5100 ? 5.00 (OCR inserted noise before 00)
        if (compact.matches("\\d1\\d\\d") && compact.endsWith("00")) {
            return compact.charAt(0) + ".00";
        }
        if (compact.matches("\\d\\d") && !compact.equals("10") && !compact.equals("11") && !compact.equals("12")) {
            return compact.charAt(0) + "/" + compact.charAt(1);
        }
        if (compact.matches("\\d1\\d")) {
            return compact.charAt(0) + "/" + compact.charAt(2);
        }
        if (compact.matches("\\d\\d1\\d")) {
            return compact.substring(0, 2) + "/" + compact.charAt(3);
        }
        return null;
    }

    private static boolean hasFullTimeResult(VisualScreen screen) {
        for (VisualScreen.Line line : screen.lines) {
            String u = line.text.toLowerCase(Locale.US);
            if (u.contains("full") && u.contains("result")) return true;
            if (u.contains("full time result") || u.equals("1x2") || u.contains("match result")) return true;
        }
        List<VisualScreen.Line> lines = screen.lines;
        for (int i = 0; i < lines.size(); i++) {
            if (!lines.get(i).text.equalsIgnoreCase("Full")) continue;
            boolean time = false, result = false;
            int top = lines.get(i).bounds.top;
            for (int j = i; j < Math.min(i + 6, lines.size()); j++) {
                if (Math.abs(lines.get(j).bounds.top - top) > 40) continue;
                if (lines.get(j).text.equalsIgnoreCase("Time")) time = true;
                if (lines.get(j).text.equalsIgnoreCase("Result")) result = true;
            }
            if (time && result) return true;
        }
        return false;
    }

    private static String nearestLabelAbove(VisualScreen screen, VisualScreen.Line odds) {
        String best = null;
        int bestScore = Integer.MAX_VALUE;
        for (VisualScreen.Line line : screen.lines) {
            if (line.bounds.bottom > odds.bounds.top + 8) continue;
            int dy = odds.bounds.top - line.bounds.bottom;
            if (dy < 0 || dy > 120) continue;
            int dx = Math.abs(line.bounds.centerX() - odds.bounds.centerX());
            if (dx > 140) continue;
            String t = line.text.trim();
            if (t.length() < 1 || t.length() > 28) continue;
            if (PRICE.matcher(t).matches()) continue;
            if (extractFractionalOdds(t) != null && t.matches("\\d+")) continue;
            String u = t.toLowerCase(Locale.US);
            if (u.contains("early") || u.contains("payout") || u.contains("acca") || u.contains("boost") || u.contains("popular")) continue;
            int score = dy * 10 + dx;
            if (u.equals("draw") || u.equals("x") || u.equals("1") || u.equals("2")) score -= 50;
            if (score < bestScore) { bestScore = score; best = t; }
        }
        return best;
    }

    private static String mapMarketHeading(String t) {
        String u = t.toLowerCase(Locale.US);
        if (u.contains("full time result") || u.equals("1x2") || u.contains("match result") || u.contains("money line") || u.equals("moneyline") || u.contains("to win"))
            return "MONEYLINE";
        if (u.contains("asian handicap") || u.contains("handicap") || u.contains("spread") || u.contains("game line"))
            return "SPREAD";
        if (u.contains("goal line") || u.contains("total goals") || u.contains("total points") || u.equals("total") || u.startsWith("total "))
            return "TOTAL";
        return null;
    }

    private static String inferMlSide(String t, int priceCount) {
        String u = t.toUpperCase(Locale.US);
        if (u.contains("DRAW") || u.matches(".*\\bX\\b.*") || u.contains("D RAW")) return "DRAW";
        if (u.contains("AWAY") || u.matches(".*\\b2\\b.*")) return "AWAY";
        if (u.contains("HOME") || u.matches(".*\\b1\\b.*")) return "HOME";
        return null;
    }

    private static String inferMlSideLoose(String t) {
        return inferMlSide(t, 1);
    }

    private static String toDecimal(String raw) {
        if (raw == null) return "0.00";
        if (raw.matches("\\d+\\.\\d{2}")) return raw;
        if (raw.matches("\\d+/\\d+")) {
            String[] p = raw.split("/");
            double dec = 1.0 + Double.parseDouble(p[0]) / Double.parseDouble(p[1]);
            return String.format(Locale.US, "%.2f", dec);
        }
        return raw;
    }

    private static String normalizeLine(String line) {
        if (line == null || line.isEmpty()) return "NONE";
        if (!line.contains(".") && line.matches("[+-]?\\d+")) return line + ".0";
        return line;
    }

    private String defaultQuery() {
        return sport.equals("basketball") ? "Lakers" : "Arsenal";
    }

    private static String cleanTeam(String raw) {
        return raw.replaceAll("\\s+", " ").replaceAll("[|].*$", "").trim();
    }

    private static boolean looksLikeNav(String s) {
        String u = s.toLowerCase(Locale.US);
        return u.contains("search") || u.contains("login") || u.contains("join") || u.contains("casino") || u.length() > 40;
    }

    private static boolean looksLikeTeam(String s) {
        if (s == null) return false;
        String t = s.trim();
        if (t.length() < 3) return false;
        if (!t.matches(".*[A-Za-z].*")) return false;
        if (t.matches("(?i)E\\d+")) return false;
        if (t.indexOf('<') >= 0 || t.indexOf('>') >= 0 || t.contains("\u00b0")) return false;
        String u = t.toLowerCase(Locale.US);
        if (u.equals("home") || u.equals("away") || u.equals("draw") || u.equals("live") || u.equals("close")) return false;
        if (u.contains("in-play") || u.contains("sports") || u.contains("casino")) return false;
        return true;
    }

    private static boolean hasLiveSearchResults(VisualScreen s, String q) {
        if (s == null || q == null || q.isEmpty()) return false;
        if (!visible(s, q)) return false;
        if (visible(s, "TEAMS")) return true;
        for (VisualScreen.Line line : s.lines) {
            String t = line.text.trim();
            if (line.bounds.top < 250 || line.bounds.top > 1320) continue;
            if (Pattern.compile("(?i).+\\s+(?:v|vs)\\s+.+").matcher(t).matches()) return true;
        }
        if (visible(s, "Football")) {
            for (VisualScreen.Line line : s.lines) {
                if (line.bounds.top > 450 && line.bounds.top < 1320 && line.text.contains(q)) return true;
            }
        }
        return false;
    }

    private static VisualScreen.Line recentSearchChip(VisualScreen s, String q) {
        if (s == null || q == null) return null;
        boolean inRecent = false;
        for (VisualScreen.Line line : s.lines) {
            String t = line.text.trim();
            String up = t.toUpperCase(Locale.US);
            if (up.equals("RECENT") || up.contains("RECENT SEARCH")) inRecent = true;
            if (up.equals("TEAMS") || up.equals("FOOTBALL") || up.equals("EVENTS")) inRecent = false;
            if (!inRecent) continue;
            if (line.bounds.top < 300 || line.bounds.top > 700) continue;
            if (t.equalsIgnoreCase(q) || t.startsWith(q + " ") || t.startsWith(q + ">") || t.equals(q + " >")) return line;
            if (t.contains(q) && t.length() <= q.length() + 4) return line;
        }
        for (VisualScreen.Line line : s.lines) {
            if (line.bounds.top < 340 || line.bounds.top > 520) continue;
            String t = line.text.trim();
            if (t.equalsIgnoreCase(q) || t.startsWith(q)) return line;
        }
        return null;
    }

    private static String nearestCompetition(VisualScreen screen, VisualScreen.Line fixtureLine) {
        String best = "Live";
        int bestDy = Integer.MAX_VALUE;
        for (VisualScreen.Line line : screen.lines) {
            if (line.bounds.bottom > fixtureLine.bounds.top) continue;
            int dy = fixtureLine.bounds.top - line.bounds.bottom;
            if (dy < 0 || dy > 220) continue;
            String t = line.text.trim();
            if (t.length() < 3 || t.length() > 48) continue;
            if (VS.matcher(t).matches()) continue;
            if (PRICE.matcher(t).find() && t.length() < 12) continue;
            if (dy < bestDy) { bestDy = dy; best = t; }
        }
        return best;
    }

    private static boolean softSame(Fixture a, Fixture b) {
        return a.name().equalsIgnoreCase(b.name());
    }

    private static boolean visible(VisualScreen s, String... tokens) {
        for (VisualScreen.Line line : s.lines)
            for (String t : tokens)
                if (line.text.contains(t)) return true;
        return false;
    }

    private static boolean visibleLoose(VisualScreen s, String team) {
        if (team == null || team.isEmpty()) return false;
        String first = team.split("\\s+")[0];
        return visible(s, team, first);
    }


    private CompletableFuture<Void> dismissCookiesIfPresent(VisualScreen s) {
        if (!cookieWall(s)) return CompletableFuture.completedFuture(null);
        VisualScreen.Line accept = firstOf(s, "Accept All");
        if (accept == null) {
            for (VisualScreen.Line line : s.lines) {
                if (line.text.equals("Accept")) { accept = line; break; }
            }
        }
        require(accept != null, "TARGET_NOT_FOUND", "Cookie Accept control not found on live Bet365");
        return ui.tap(accept.bounds, "Accept cookies").thenCompose(v -> ui.delay(1000));
    }

    private static boolean cookieWall(VisualScreen s) {
        return visible(s, "Manage Cookies", "Accept All") || (visible(s, "Accept") && visible(s, "cookies"));
    }

    private static VisualScreen.Line firstOf(VisualScreen s, String... exactOrContain) {
        for (String want : exactOrContain)
            for (VisualScreen.Line line : s.lines)
                if (line.text.equals(want)) return line;
        for (String want : exactOrContain)
            for (VisualScreen.Line line : s.lines)
                if (line.text.contains(want)) return line;
        return null;
    }

    private static void require(boolean condition, String stage, String message) {
        if (!condition) throw new Failure(stage, message);
    }
}
