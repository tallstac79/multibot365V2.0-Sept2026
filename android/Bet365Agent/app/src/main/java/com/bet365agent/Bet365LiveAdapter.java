package com.bet365agent;

import android.graphics.Rect;
import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.regex.*;
import org.json.JSONArray;

/**
 * Live Bet365 mobile (Chrome) visual adapter.
 * Screenshot/OCR + dispatchGesture only. READY mode stops at bet-slip verification. Place Bet is
 * tapped only for execution_mode=dispatch with confirmation_status=APPROVED (operator/limits
 * approved in the backend), once, and its outcome is classified from the screen afterwards.
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
    /** Price of the selection put on the betslip in this run (stake x price is cross-checked with "To Return"). */
    private String openedPrice;
    private String targetMarket = "", targetSide = "", targetLine = "";
    /** Instruction-supplied aliases (feed -> bookmaker). Static because the fixture gates are static; the
     *  coordinator runs one instruction at a time and every run sets it before use. */
    private static volatile java.util.Map<String, String> instructionAliases = java.util.Collections.emptyMap();

    @Override
    public void set_aliases(java.util.Map<String, String> aliases) {
        instructionAliases = aliases == null ? java.util.Collections.emptyMap() : aliases;
    }

    private static org.json.JSONObject sideJson(EventIdentity.Side side) {
        return side == null ? null : CoordinatorAgent.object("feed", side.feed, "bookmaker", side.bookmaker, "level", side.level.name(),
                "score", Math.round(side.score * 100) / 100.0, "note", side.note);
    }
    private String expectedPrice;    // price the slip must show (set by the check that uses readbackRetry)
    private String slipPriceRead;    // targeted numeric read of the slip's price box, once per check

    /** Price box at the right end of the slip's selection row (the row that shows the signed line / Over-Under). */
    private android.graphics.Rect slipPriceBox(VisualScreen s) {
        if (targetLine == null) return null;
        String token = targetLine.replace("+", "").replace("-", "");
        for (VisualScreen.Line line : s.lines) {
            if (line.bounds.top < 900 || line.bounds.top > 1350) continue;
            String t = line.text;
            if (token.isEmpty() ? false : t.contains(token)) {
                int left = Math.max(line.bounds.right + 10, 540);
                return new android.graphics.Rect(left, line.bounds.top - 10, 715, line.bounds.bottom + 12);
            }
        }
        return null;
    }

    /** Price shown on the slip: plain OCR anywhere, or the targeted read of the slip's own price box. */
    private boolean slipPriceShown(VisualScreen s, String price) {
        return visible(s, price) || fractionalVisible(s, price) || price.equals(slipPriceRead);
    }
    private long cleanGridAtMs = 0;                 // when a clean (fast-path) grid read was taken
    private VisualScreen lastFinal; private long lastFinalAtMs = 0;   // frame that passed verify_final_state

    @Override
    public void set_target(String market, String side, String line) {
        targetMarket = market == null ? "" : market; targetSide = side == null ? "" : side; targetLine = line == null ? "" : line;
    }

    /** First grid read is clean for THIS bet: the target cell was read and no parser note concerns its market. */
    private boolean targetClean(GameLinesParser.Result r) {
        if (!r.grid || targetMarket.isEmpty()) return false;
        String key = targetMarket.toLowerCase(Locale.US);
        for (String note : r.notes) if (note.toLowerCase(Locale.US).contains(key)) return false;
        for (GameLinesParser.Cell c : r.cells)
            if (c.market.equals(targetMarket) && c.side.equals(targetSide)
                    && (targetLine.isEmpty() || "NONE".equals(c.line) || lineEquals(c.line, targetLine))) return true;
        return false;
    }
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
    }

    public CompletableFuture<Void> open_home() {
        return ui.open(HOME_URL).thenCompose(v -> ui.delay(2800)).thenCompose(v -> settle("home", 0)).thenCompose(s -> {
            require(!visible(s, "SIMULATOR", "SEARCHPAGE", "Fictional interface"),
                    "TARGET_NOT_FOUND", "Simulator page visible during live Bet365 run");
            return dismissCookiesIfPresent(s).thenCompose(v -> ui.capture("home_ready")).thenAccept(ready -> {
                // Login wall is a valid home arrival (intentional LOGGED_OUT / expiry recovery).
                if (loginWall(ready) || (visible(ready, "Password") && visible(ready, "Log In", "Login"))) {
                    require(!visible(ready, "Accept All") && !cookieWall(ready),
                            "TARGET_NOT_FOUND", "Cookie consent still blocking live Bet365 home");
                    return;
                }
                require(visible(ready, "bet365", "Bet365", "Sports", "Search", "In-Play", "In-play", "Live", "Football"),
                        "TARGET_NOT_FOUND", "Live Bet365 homepage not visible");
                require(!visible(ready, "Accept All") && !cookieWall(ready),
                        "TARGET_NOT_FOUND", "Cookie consent still blocking live Bet365 home");
            });
        });
    }


    /** Passive wait while Bet365 shows its security verification or loading splash. Never taps it:
     *  an interactive challenge, or one that does not clear by itself, fails closed as BOT_CHECK. */
    private CompletableFuture<VisualScreen> settle(String label, int attempt) {
        return ui.capture(label).thenCompose(s -> {
            if (!settling(s)) return CompletableFuture.completedFuture(s);
            boolean interactive = interactiveBotCheck(s);
            if (interactive || attempt >= 6) {
                ui.put("bot_check", CoordinatorAgent.object("interactive", interactive, "waited_attempts", attempt));
                throw new Failure("BOT_CHECK", interactive
                        ? "Bet365 security check needs a human; the agent never interacts with it"
                        : "Bet365 security verification or splash did not clear automatically");
            }
            ui.checkpoint("OPEN_HOME");
            return ui.delay(4000).thenCompose(v -> settle(label + "_settle", attempt + 1));
        });
    }

    static boolean botCheck(VisualScreen s) {
        return visible(s, "security verification", "Security verification", "Verifying", "not a bot", "Cloudflare", "CLOUDFLARE",
                "Verify you are human", "Checking your browser", "Just a moment");
    }

    static boolean interactiveBotCheck(VisualScreen s) {
        return visible(s, "Verify you are human", "I am human", "not a robot", "Select all images");
    }

    /** Security check, or the bare Bet365 logo splash before the page has rendered. */
    private static boolean settling(VisualScreen s) {
        if (botCheck(s)) return true;
        return s.lines.size() <= 16 && visible(s, "bet365")
                && !visible(s, "Log In", "Login", "Search", "In-Play", "In-play", "Sports", "My Bets", "Football", "Password");
    }

    public CompletableFuture<Void> ensure_session() {
        return settle("session", 0).thenCompose(s -> {
            if (sessionLoggedIn(s)) {
                ui.put("session", "AUTHENTICATED");
                return CompletableFuture.completedFuture(null);
            }
            // LOGGED_OUT / EXPIRED / login wall: restore with app-private credentials (no betting).
            boolean needsLogin = loginWall(s) || sessionExpired(s)
                    || visible(s, "Log In", "Login")
                    || visible(s, "Password");
            if (!needsLogin) {
                // Ambiguous mid-navigation (common after Search reset): reopen home once, then reclassify.
                return ui.open(HOME_URL).thenCompose(v -> ui.delay(900)).thenCompose(v -> settle("session_rehome", 0)).thenCompose(s2 -> {
                    if (sessionLoggedIn(s2)) {
                        ui.put("session", "AUTHENTICATED");
                        return CompletableFuture.completedFuture(null);
                    }
                    boolean needs2 = loginWall(s2) || sessionExpired(s2) || visible(s2, "Log In", "Login") || visible(s2, "Password");
                    if (!needs2) {
                        throw new Failure("LOGIN_FAILED", "Bet365 session state unclear; login wall not confirmed");
                    }
                    if (!CoordinatorConfig.hasBet365Credentials(ui.service)) {
                        boolean expired = sessionExpired(s2);
                        ui.put("session", expired ? "EXPIRED" : "LOGGED_OUT");
                        throw new Failure(expired ? "SESSION_EXPIRED" : "LOGIN_FAILED", "Bet365 logged out and no app-private credentials in Coordinator settings ? open Bet365Agent Settings or log in on Samsung Chrome");
                    }
                    ui.put("session", "AUTHENTICATING");
                    return performLogin(s2);
                });
            }
            if (!CoordinatorConfig.hasBet365Credentials(ui.service)) {
                boolean expired = sessionExpired(s);
                ui.put("session", expired ? "EXPIRED" : "LOGGED_OUT");
                String stage = expired ? "SESSION_EXPIRED" : "LOGIN_FAILED";
                throw new Failure(stage, "Bet365 logged out and no app-private credentials in Coordinator settings ? open Bet365Agent Settings or log in on Samsung Chrome");
            }
            ui.put("session", "AUTHENTICATING");
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
            android.graphics.Rect loginRect = loginBtn != null ? loginBtn.bounds : first.phraseBounds("Log In", 0, 350);
            if (loginRect == null) throw new Failure("LOGIN_FAILED", "Log In control not visible on live Bet365");
            openForm = ui.tap(loginRect, "Log In").thenCompose(v -> ui.delay(900));
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
                    android.graphics.Rect submitRect = submit != null ? submit.bounds : filled.phraseBounds("Log In", 400, 2000);
                    require(submitRect != null, "LOGIN_FAILED", "Login submit button not visible");
                    return ui.tap(submitRect, "Log In submit").thenCompose(z -> ui.delay(2500)).thenCompose(z -> ui.capture("session_after_login")).thenAccept(after -> {
                        if (loginWall(after) || visible(after, "Log In", "Login") || visible(after, "Password")) {
                            throw new Failure("LOGIN_FAILED", "Bet365 login did not succeed: Log In still visible");
                        }
                        if (!sessionLoggedIn(after)) {
                            throw new Failure("LOGIN_FAILED", "Bet365 authenticated account UI not visible after submit");
                        }
                        if (visible(after, "insufficient", "Insufficient")) throw new Failure("INSUFFICIENT_BALANCE", "Insufficient balance banner after login");
                        ui.put("session", "AUTHENTICATED");
                    });
                });
            });
        });
    }

        public CompletableFuture<Void> open_search() {
        // Prefer Sports product context before Search - Casino (#/AX) search is not sports discovery.
        ui.checkpoint("SPORTS_CONTEXT");
        return ensureSportsContext().thenCompose(v -> {
            ui.checkpoint("OPEN_SEARCH");
            return openSearchAttempt(0);
        });
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
            if (best == null && attempt == 0) {
                // Home chrome often not ready / wrong tab after prior reset — re-home then one relocate.
                return ui.open(HOME_URL).thenCompose(v -> ui.delay(800)).thenCompose(v -> {
                    VisualScreen.Line homeTab = null;
                    // capture after home
                    return ui.capture("search_rehome").thenCompose(home -> {
                        VisualScreen.Line tab = null;
                        for (VisualScreen.Line line : home.lines) {
                            String tt = line.text.trim();
                            if (tt.equalsIgnoreCase("Home") && line.bounds.top > 1200) { tab = line; break; }
                        }
                        CompletableFuture<Void> go = CompletableFuture.completedFuture(null);
                        if (tab != null) {
                            final VisualScreen.Line tapHome = tab;
                            go = ui.tap(tapHome.bounds, "Home tab").thenCompose(x -> ui.delay(700));
                        }
                        return go.thenCompose(x -> openSearchAttempt(1));
                    });
                });
            }
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

    public CompletableFuture<Void> enter_query(String query) {
        String homePart = setIdentity(query);
        List<String> ladder = buildSearchQueryLadder(homePart, expectedAway);
        ui.put("search_query_ladder", new JSONArray(ladder));
        ui.checkpoint("FOCUS");
        return runSearchQueryLadder(ladder, 0, false);
    }

    /** Identity from "Home||Away": identityHome / expectedAway (both checked by every fixture gate). */
    private String setIdentity(String query) {
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
        return homePart;
    }

    // ------------------------------------------------------------------ direct event link
    /**
     * Open the alert's exact Bet365 event link and verify it: sport (link B-code), login, both teams from
     * the header (explicit aliases only, correct home/away pairing), kick-off vs the alert's UTC time.
     * Returns null (caller searches instead) if the link is unusable or the teams cannot be verified;
     * a kick-off mismatch with matching teams fails closed (WRONG_EVENT).
     */
    @Override
    public CompletableFuture<Fixture> open_event_direct(String url, String query, String kickoffUtc) {
        setIdentity(query);
        if (!EventPage.validUrl(url)) { ui.put("direct_event_rejected", "invalid link"); return CompletableFuture.completedFuture(null); }
        String linkSport = EventPage.sportOf(url);
        if (linkSport == null || !linkSport.equals(sport)) {
            ui.put("direct_event_rejected", "link sport " + linkSport + " is not " + sport);
            return CompletableFuture.completedFuture(null);
        }
        ui.put("event_url", url);
        return ui.open(url).thenCompose(v -> directEventLoaded(1)).thenCompose(s -> {
            if (sessionLoggedIn(s)) { ui.put("session", "AUTHENTICATED"); return CompletableFuture.completedFuture(s); }
            // Not clearly logged in: the normal session step (may re-home / log in), then back to the event.
            return ensure_session().thenCompose(v -> ui.open(url)).thenCompose(v -> directEventLoaded(1));
        }).thenApply(s -> verifyDirectEvent(s, kickoffUtc));
    }

    private CompletableFuture<VisualScreen> directEventLoaded(int attempt) {
        return ui.delay(attempt == 1 ? 2200 : 900).thenCompose(v -> ui.capture("event_direct")).thenCompose(s -> {
            if (EventPage.teams(headerLines(s)) != null || EventPage.closed(texts(s)) || attempt >= 5)
                return CompletableFuture.completedFuture(s);
            ui.put("event_direct_wait", attempt);
            return directEventLoaded(attempt + 1);
        });
    }

    private static List<String> headerLines(VisualScreen s) {
        List<String> out = new ArrayList<>();
        for (VisualScreen.Line line : s.lines) if (line.bounds.top >= 230 && line.bounds.top <= 480) out.add(line.text);
        return out;
    }

    private Fixture verifyDirectEvent(VisualScreen s, String kickoffUtc) {
        require(!visible(s, "SIMULATOR"), "WRONG_EVENT", "Simulator page on direct event link");
        if (EventPage.closed(texts(s))) {
            ui.put("direct_event_closed", true);
            throw new Failure("SUSPENDED", "Bet365 event page: betting has closed or been suspended (no search fallback)");
        }
        List<String> header = headerLines(s);
        String[] teams = EventPage.teams(header);
        ui.put("direct_event_header", new JSONArray(header));
        if (teams == null) { ui.put("direct_event_rejected", "header teams not read"); return null; }
        // Milestone B: the event identity resolver decides (sport, both teams, pairing, kick-off). The page was
        // opened from the alert's own link, so it is the anchor; the resolver's verdict is authoritative (A1).
        String shown = EventPage.kickoffText(header);
        String want = kickoffUtc == null || kickoffUtc.isEmpty() ? null : EventPage.ukDisplay(kickoffUtc);
        String feedAway = expectedAway.isEmpty() ? teams[1] : expectedAway;
        EventIdentity.Result id = EventIdentity.resolve(
                new EventIdentity.Event(sport, identityHome, feedAway, want, null, false),
                new EventIdentity.Event(sport, teams[0], teams[1], shown, header.isEmpty() ? null : header.get(0), true), instructionAliases);
        ui.put("identity", CoordinatorAgent.object("verdict", id.verdict.name(), "reason", id.reason, "home", sideJson(id.home),
                "away", sideJson(id.away), "kickoff_known", id.kickoffKnown, "kickoff_agrees", id.kickoffAgrees, "reversed", id.reversed));
        ui.put("identity_verdict", id.verdict.name());
        ui.put("route", "event_link");
        if (!id.aliasCandidates.isEmpty()) {
            org.json.JSONObject cands = new org.json.JSONObject();
            for (java.util.Map.Entry<String, String> e : id.aliasCandidates.entrySet()) { try { cands.put(e.getKey(), e.getValue()); } catch (Exception ignored) {} }
            ui.put("alias_candidate", CoordinatorAgent.object("feed_home", identityHome, "feed_away", feedAway, "bet365_home", teams[0],
                    "bet365_away", teams[1], "event_url", ui.record.optString("event_url"),
                    "kickoff_shown", shown == null ? org.json.JSONObject.NULL : shown, "kickoff_expected", want == null ? org.json.JSONObject.NULL : want,
                    "verdict", id.verdict.name(), "confidence", id.candidateConfidence == null ? org.json.JSONObject.NULL : id.candidateConfidence,
                    "candidates", cands, "sport", sport));
        }
        if (!id.accepted()) {
            ui.put("direct_event_rejected", "identity: " + id.reason);
            String detail = "Event link shows '" + teams[0] + " v " + teams[1] + "'; alert says '" + identityHome + " v " + feedAway + "': " + id.reason;
            // AMBIGUOUS = a naming variant without corroboration -> needs an alias; everything else is the wrong event.
            throw new Failure(id.verdict == EventIdentity.Verdict.AMBIGUOUS ? "ALIAS_REQUIRED" : "WRONG_EVENT", detail);
        }
        ui.put("kickoff_verified", id.kickoffKnown ? shown : (shown == null ? "not shown (in-play or unread)" : "no alert kick-off"));
        android.graphics.Rect bounds = new android.graphics.Rect();
        for (VisualScreen.Line line : s.lines) if (line.bounds.top >= 230 && line.bounds.top <= 480) bounds.union(line.bounds);
        Fixture f = new Fixture(Integer.toHexString((teams[0] + "|" + teams[1]).toLowerCase(Locale.US).hashCode()),
                teams[0], teams[1], header.isEmpty() ? "" : header.get(0), bounds);
        liveFixture = f;
        ui.put("verified_fixture", f.json());
        ui.put("fixture_home", f.home);
        ui.put("fixture_away", f.away);
        ui.put("identity_verified_home", identityHome);
        ui.put("identity_verified_away", expectedAway);
        ui.put("event_verified", true);
        return f;
    }

    /**
     * Bounded discovery ladder (SEARCH ONLY):
     * A "Home Away" | B "Home" | C "Away" | D deterministic aliases (strip BC/KK/BK/FC/HJK…).
     * Fixture identity always uses identityHome + expectedAway, never the alias alone.
     */
    private static List<String> buildSearchQueryLadder(String home, String away) {
        // Prefer alias forms early: "BC …" queries often resolve Casino-only on Bet365.
        LinkedHashSet<String> out = new LinkedHashSet<>();
        String h = home == null ? "" : home.trim();
        String a = away == null ? "" : away.trim();
        List<String> homeAliases = searchAliasesFor(h);
        List<String> awayAliases = searchAliasesFor(a);
        boolean awayLooksReal = a.length() >= 3 && a.length() <= 28 && a.matches("(?i)[A-Za-z0-9 .'-]+");
        // A/D first when prefix alias exists: "Beroe Ferrol", then full "BC Beroe Ferrol"
        if (!h.isEmpty() && !a.isEmpty() && awayLooksReal) {
            for (String ha : homeAliases) out.add(ha + " " + a);
            for (String ha : homeAliases) {
                for (String aa : awayAliases) out.add(ha + " " + aa);
            }
            out.add(h + " " + a);
        }
        // D single-team aliases before raw prefixed home (Casino magnet)
        for (String ha : homeAliases) out.add(ha);
        if (!h.isEmpty()) out.add(h);
        // Non-real away: still try once so wrong-opponent fails closed via identity gate on home hits
        if (!a.isEmpty() && awayLooksReal) out.add(a);
        for (String aa : awayAliases) out.add(aa);
        if (!h.isEmpty() && !a.isEmpty() && !awayLooksReal) {
            // Keep one combined attempt last (bounded); identity still requires both teams.
            out.add(h + " " + a);
        }
        out.removeIf(s -> s == null || s.trim().isEmpty());
        // Bound ladder length for 120s instruction budget
        ArrayList<String> list = new ArrayList<>(out);
        if (list.size() > 6) return new ArrayList<>(list.subList(0, 6));
        return list;
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
                            ui.put("discovery_query", typed);
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

    private static String sanitizeSearchTyped(String q) {
        if (q == null) return "";
        // Bet365 search rejects or OCR-breaks on slash-heavy club names; discovery only.
        return q.replace('/', ' ').replaceAll("\\s+", " ").trim();
    }

    private CompletableFuture<VisualScreen> typeSearchQueryOnce(String queryText) {
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
            // Type only into a verifiably empty field (placeholder showing): see ensureEmptySearch.
            return ensureEmptySearch(0).thenCompose(v -> ui.capture("query_ready")).thenCompose(ready -> {
                String hint = visible(ready, "bet365...") ? "bet365..." : "Search";
                return ui.type(hint, typedQuery);
            }).thenCompose(v -> {
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
    }

    private CompletableFuture<Void> clearSearchField() {
        return ensureEmptySearch(0);
    }

    /**
     * Leave the open search bar verifiably empty (only the "Search bet365..." placeholder), found by
     * geometry (SearchBar: magnifier left, Close right), not by the word "Search". Bounded:
     * attempts 0-1 tap the word-level clear X and re-check; then Close, re-home to Sports and re-open
     * Search once (attempt 3); otherwise fail closed. Never types into, or taps, an ambiguous bar.
     * Real failure fixed: the old line-level "x" match missed the X in "Q Kyoto ... Stars X Close".
     */
    private CompletableFuture<Void> ensureEmptySearch(int attempt) {
        return ui.capture("search_field_" + attempt).thenCompose(s -> {
            SearchBar.Bar bar = SearchBar.locate(wordsOf(s));
            JSONArray log = ui.record.optJSONArray("search_bar_checks");
            if (log == null) { log = new JSONArray(); ui.put("search_bar_checks", log); }
            log.put(bar == null ? CoordinatorAgent.object("attempt", attempt, "bar", false)
                    : CoordinatorAgent.object("attempt", attempt, "bar", true, "candidates", bar.candidates, "text", bar.text,
                    "empty", bar.empty, "clear", bar.clear == null ? org.json.JSONObject.NULL : new JSONArray(java.util.Arrays.asList(
                            bar.clear[0], bar.clear[1], bar.clear[2], bar.clear[3]))));
            if (bar != null && bar.candidates != 1)
                throw new Failure("TARGET_NOT_FOUND", bar.candidates + " search-bar candidates; not tapping an ambiguous control");
            if (bar != null && bar.empty) return CompletableFuture.completedFuture(null);
            if (bar != null && bar.clear != null && attempt < 2) {
                android.graphics.Rect x = new android.graphics.Rect(bar.clear[0], bar.clear[1], bar.clear[2], bar.clear[3]);
                return ui.tap(x, "Clear search (X)").thenCompose(v -> ui.delay(600)).thenCompose(v -> ensureEmptySearch(attempt + 1));
            }
            if (attempt < 3) {
                ui.bumpStageRetry("OPEN_SEARCH");
                CompletableFuture<Void> close = bar == null ? CompletableFuture.completedFuture(null)
                        : ui.tap(new android.graphics.Rect(bar.close[0], bar.close[1], bar.close[2], bar.close[3]), "Close search")
                            .thenCompose(v -> ui.delay(700));
                return close.thenCompose(v -> ensureSportsContext()).thenCompose(v -> openSearchAttempt(0))
                        .thenCompose(v -> ui.delay(400)).thenCompose(v -> ensureEmptySearch(3));
            }
            throw new Failure("TARGET_NOT_FOUND", bar == null ? "Search bar not identified after re-opening Search"
                    : "Search field still holds '" + bar.text + "' after clear and re-open; not typing");
        });
    }

    /** Casino product / Casino-only search pane — never treat as sports fixture results. */
    private boolean isCasinoOnlyResults(VisualScreen s) {
        if (s == null) return false;
        // Sports fixture rows win — never classify as casino-only when v/vs pairs parse.
        if (!fixturesFromSearch(s).isEmpty()) return false;
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
        // Require Casino filter chip or Casino URL; sports chip means not casino-only.
        if (!(casinoChip || casinoUrl)) return false;
        if (sportsChip) return false;
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

    public CompletableFuture<Fixture> discover_fixture() {
        return ui.capture("fixtures").thenApply(s -> {
            require(!visible(s, "SIMULATOR"), "NO_FIXTURE_FOUND", "Simulator page during live fixture discovery");
            List<Fixture> all = fixturesFromSearch(s);
            JSONArray observed = new JSONArray();
            for (Fixture f : all) observed.put(f.json());
            ui.put("discovered_fixtures", observed);
            require(!all.isEmpty(), "NO_FIXTURE_FOUND", "No live fixture row parsed from Bet365 search OCR");
            String q = (identityHome != null && !identityHome.isEmpty())
                    ? identityHome
                    : ((lastQuery == null || lastQuery.isEmpty()) ? defaultQuery() : lastQuery);
            Fixture chosen = selectUniqueFixtureForQuery(all, q, expectedAway);
            liveFixture = chosen;
            ui.put("sport_observed", sport);
            ui.put("verified_fixture", chosen.json());
            return chosen;
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
        return ui.delay(1200).thenCompose(v -> eventLoaded(fixture, 1)).thenAccept(s -> {
            require(visible(s, fixture.home) || visibleLoose(s, fixture.home), "WRONG_EVENT", "Home team not visible on live event page");
            require(visible(s, fixture.away) || visibleLoose(s, fixture.away), "WRONG_EVENT", "Away team not visible on live event page");
            require(!visible(s, "SIMULATOR"), "WRONG_EVENT", "Simulator page during live event verify");
            ui.put("event_verified", true);
        });
    }

    /** The event page can still show a loading spinner (real: Crvena Zvezda v Zalgiris). Re-capture up to 5 times
     *  until both team names are visible; the caller then verifies the frame strictly. */
    private CompletableFuture<VisualScreen> eventLoaded(Fixture fixture, int attempt) {
        return ui.capture("event").thenCompose(s -> {
            boolean both = (visible(s, fixture.home) || visibleLoose(s, fixture.home))
                    && (visible(s, fixture.away) || visibleLoose(s, fixture.away));
            if (both || attempt >= 5) return CompletableFuture.completedFuture(s);
            ui.put("event_wait_attempts", attempt);
            return ui.delay(1500).thenCompose(v -> eventLoaded(fixture, attempt + 1));
        });
    }

    public CompletableFuture<List<Selection>> discover_markets() {
        if ("basketball".equals(sport) && liveFixture != null) {
            // Game Lines grid: several OCR reads must agree (single frames misread digits).
            return gridConsensus("markets", 1, new ArrayList<>(), new JSONArray()).thenApply(found -> {
                require(!found.isEmpty(), "EVENT_NOT_VERIFIED", "Game Lines grid not read consistently (see game_lines_reads)");
                ui.put("fixture_home", liveFixture.home);
                ui.put("fixture_away", liveFixture.away);
                return found;
            });
        }
        return ui.captureTable("markets").thenApply(s -> {
            // Basketball Game Lines grid first: rows are identified by the fixture's team labels.
            List<Selection> found = parseGameLines(s, true);
            boolean grid = !found.isEmpty();
            if (!grid) found = parseFullTimeResult(s);
            if (found.isEmpty()) found = parseMarkets(s);
            require(!found.isEmpty(), "EVENT_NOT_VERIFIED", "No live market quotes parsed from Bet365 event OCR");
            if (!grid) validateMoneylineIdentities(found);
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

    public CompletableFuture<Selection> read_selection(List<Selection> all, String market, String side, String line) {
        List<Selection> matches = new ArrayList<>();
        for (Selection s : all) {
            if (!s.market.equals(market) || !s.side.equals(side)) continue;
            if (line != null && !line.isEmpty() && !line.equalsIgnoreCase("NONE") && !lineEquals(s.line, line)) continue;
            matches.add(s);
        }
        List<Selection> open = new ArrayList<>();
        for (Selection s : matches) if ("OPEN".equals(s.availability)) open.add(s);
        List<Selection> pool = open.isEmpty() ? matches : open;
        require(!pool.isEmpty(), "TARGET_NOT_FOUND", "No live selection for " + market + "/" + side
                + (line == null || line.isEmpty() ? "" : ("/" + line)));
        Selection pick = pool.get(0);
        require(!"SUSPENDED".equals(pick.availability), "SUSPENDED", "Selection suspended");
        require(!"UNAVAILABLE".equals(pick.availability), "UNAVAILABLE", "Selection unavailable");
        validateOneIdentity(pick);
        ui.put("selection_role", pick.side);
        ui.put("selection_name", pick.name);
        return CompletableFuture.completedFuture(pick);
    }
    private static boolean lineEquals(String a, String b) {
        if (a == null || b == null) return a == b;
        if (a.equals(b)) return true;
        try { return new java.math.BigDecimal(a).compareTo(new java.math.BigDecimal(b)) == 0; }
        catch (Exception e) { return false; }
    }

    public CompletableFuture<String> read_line(Selection selection) {
        // Line/price already read from the live markets OCR in this run; skip extra captures (60s budget).
        return CompletableFuture.completedFuture(selection.line == null ? "NONE" : selection.line);
    }

    public CompletableFuture<String> read_price(Selection selection) {
        return CompletableFuture.completedFuture(selection.price);
    }

    public CompletableFuture<Void> open_selection(Selection selection) {
        if ("basketball".equals(sport) && liveFixture != null && cleanGridAtMs > 0
                && android.os.SystemClock.elapsedRealtime() - cleanGridAtMs < 8000) {
            // The static event page was read cleanly <8 s ago; the betslip then re-shows the exact line and
            // price (verify_final_state), so a second full grid read before tapping the cell adds nothing.
            ui.put("selection_preflight", "reused clean grid read");
            openedPrice = selection.price;
            return ui.tap(selection.bounds, selection.market + " / " + selection.side + " / " + selection.line + " / " + selection.price);
        }
        if ("basketball".equals(sport) && liveFixture != null) {
            return gridConsensus("selection_preflight", 1, new ArrayList<>(), new JSONArray()).thenCompose(grid -> {
                Selection current = null;
                for (Selection q : grid)
                    if (q.market.equals(selection.market) && q.side.equals(selection.side) && lineEquals(q.line, selection.line)) current = q;
                if (current == null) {
                    boolean sideSeen = false;
                    for (Selection q : grid) if (q.market.equals(selection.market) && q.side.equals(selection.side)) sideSeen = true;
                    throw new Failure(sideSeen ? "LINE_CHANGED" : "TARGET_NOT_FOUND",
                            "Re-read has no agreed " + selection.market + "/" + selection.side + "/" + selection.line);
                }
                require(current.price.equals(selection.price), "PRICE_CHANGED", "Price changed before selecting live quote: " + current.price);
                openedPrice = current.price;
                return ui.tap(current.bounds, current.market + " / " + current.side + " / " + current.line + " / " + current.price);
            });
        }
        return ui.captureTable("selection_preflight").thenCompose(s -> {
            Selection current = refind(s, selection);
            require(current.price.equals(selection.price), "PRICE_CHANGED", "Price changed before selecting live quote");
            require("OPEN".equals(current.availability), current.availability.equals("SUSPENDED") ? "SUSPENDED" : "UNAVAILABLE", "Selection not open");
            openedPrice = current.price;
            return ui.tap(current.bounds, current.market + " / " + current.side + " / " + current.line + " / " + current.price);
        });
    }


    public CompletableFuture<Void> enter_stake(String stake) {
        String amount = (stake == null || stake.isEmpty()) ? "0.00" : stake.trim();
        return ui.delay(300)
            .thenCompose(v -> ui.capture("betslip_pre_stake"))
            .thenCompose(first -> {
                boolean chromeMenu = visible(first, "Incognito") && (visible(first, "Bookmarks") || visible(first, "New tab") || visible(first, "History"));
                if (!chromeMenu) return CompletableFuture.completedFuture(first);
                return dismissChromeMenu(0).thenCompose(v -> ui.capture("betslip_pre_stake"));
            })
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
                        .thenCompose(x -> ui.delay(400));
            })
            .thenAccept(v -> {
                // Typed stake was verified before Done (stake digits AND To Return). The slip after Done is
                // re-verified strictly by verify_final_state (and again before the tap): no extra read here.
                ui.put("stake_entered", amount);
            });
    }

    /** Type the stake on the betslip keypad. Keys are located only from OCR'd digit words on a validated
     *  grid (StakePad.keypad); the field is cleared first; the typed stake must read back (stake digits AND
     *  To Return) before Done is tapped. Otherwise the field is erased and the run fails. No guessed taps. */
    private CompletableFuture<Void> enterStakeOnPad(VisualScreen uiScreen, String requested) {
        String amount;
        try { amount = new java.math.BigDecimal(requested.trim()).setScale(2, java.math.RoundingMode.UNNECESSARY).toPlainString(); }
        catch (Exception e) { throw new Failure("STAKE_REJECTED", "Stake must have at most 2 decimals: " + requested); }
        require(amount.matches("\\d{1,3}\\.\\d{2}"), "STAKE_REJECTED", "Stake must be like 0.10: " + amount);
        java.util.Map<Character, int[]> keys = StakePad.keypad(wordsOf(uiScreen), 850);
        require(keys != null, "STAKE_REJECTED", "Stake keypad not located from OCR; not guessing key positions");
        ui.put("stake_keypad", CoordinatorAgent.object("zero", new JSONArray(java.util.Arrays.asList(keys.get('0')[0], keys.get('0')[1])),
                "dot", new JSONArray(java.util.Arrays.asList(keys.get('.')[0], keys.get('.')[1]))));
        // A5: read the field first (StakePad.fieldState on the stake-pad frame already captured):
        //   EMPTY   "Place Bet" without a To Return line = £0.00 selected  -> type directly (no clearing)
        //   FILLED  a To Return line = an amount is present               -> clear only its characters, verify empty, type
        //   UNKNOWN Place Bet not read                                      -> bounded safe clear, verify empty, type
        // The readback stays the safety: the typed stake must show exactly (stake digits AND To Return) or it is
        // cleared and typed ONCE more; a second mismatch clears and fails closed.
        String fieldState = StakePad.fieldState(wordsOf(uiScreen));
        ui.put("stake_field_state", fieldState);
        CompletableFuture<Void> ready = "EMPTY".equals(fieldState) ? CompletableFuture.completedFuture(null)
                : clearToVerifiedEmpty(uiScreen, keys, "FILLED".equals(fieldState) ? "known" : "unknown");
        return ready.thenCompose(v -> typeAmount(keys, amount)).thenCompose(v -> ui.delay(400)).thenCompose(v -> ui.capture("stake_typed")).thenCompose(first -> {
            if (stakeVerified(first, amount, openedPrice, "stake_check_typed")) return CompletableFuture.completedFuture(first);
            ui.put("stake_retyped", true);
            return clearToVerifiedEmpty(first, keys, "retype").thenCompose(v -> typeAmount(keys, amount)).thenCompose(v -> ui.delay(400))
                    .thenCompose(v -> ui.capture("stake_retyped")).thenCompose(second -> {
                        if (stakeVerified(second, amount, openedPrice, "stake_check_retyped")) return CompletableFuture.completedFuture(second);
                        return erase(keys, 10).<VisualScreen>thenCompose(v -> {
                            throw new Failure("STAKE_REJECTED", "Typed stake did not read back as " + amount + " after one retype; field erased");
                        });
                    });
        }).thenCompose(s -> {
            VisualScreen.Line done = findDoneLine(s);
            if (done == null) {
                return erase(keys, 10).<Void>thenCompose(v -> {
                    throw new Failure("STAKE_REJECTED", "Done not visible after typing stake; field erased");
                });
            }
            return ui.tap(doneTapRect(done), "Done");
        });
    }

    /**
     * Clear the stake field to a VERIFIED empty state (no To Return on the Place Bet button). A known amount:
     * backspace its character count + 1 separator; unknown: 10 backspaces. Then re-read; one more bounded
     * clear if still filled; otherwise fail closed. Nothing is typed into an unverified field.
     */
    private CompletableFuture<Void> clearToVerifiedEmpty(VisualScreen frame, java.util.Map<Character, int[]> keys, String why) {
        int count = 10;
        if ("known".equals(why)) {
            String read = stakeBoxDigits(frame);
            count = read.isEmpty() ? 10 : Math.min(10, read.length() + 2);
        }
        ui.put("stake_clear", CoordinatorAgent.object("why", why, "backspaces", count));
        return erase(keys, count).thenCompose(v -> ui.delay(300)).thenCompose(v -> ui.capture("stake_cleared")).thenCompose(s -> {
            if (!"FILLED".equals(StakePad.fieldState(wordsOf(s)))) return CompletableFuture.<Void>completedFuture(null);
            return erase(keys, 10).thenCompose(v -> ui.delay(300)).thenCompose(v -> ui.capture("stake_cleared_2")).thenAccept(s2 ->
                    require(!"FILLED".equals(StakePad.fieldState(wordsOf(s2))), "STAKE_REJECTED",
                            "Stake field still holds an amount after clearing; not typing"));
        });
    }

    /** Digits of the amount in the stake box (left of Place Bet) on a plain frame; "" if unreadable. */
    private static String stakeBoxDigits(VisualScreen s) {
        VisualScreen.Line place = findPlaceBetLine(s);
        if (place == null) return "";
        StringBuilder b = new StringBuilder();
        for (VisualScreen.Line line : s.lines) {
            if (line.bounds.right >= Math.min(place.bounds.left - 30, 360)) continue;
            if (line.bounds.top < place.bounds.top - 40 || line.bounds.top > place.bounds.bottom + 60) continue;
            if (line.text.toLowerCase(Locale.US).contains("stake")) continue;
            b.append(line.text.replaceAll("[^0-9]", ""));
        }
        return b.toString();
    }

    private CompletableFuture<Void> typeAmount(java.util.Map<Character, int[]> keys, String amount) {
        CompletableFuture<Void> chain = CompletableFuture.completedFuture(null);
        for (int i = 0; i < amount.length(); i++) {
            final char ch = amount.charAt(i);
            chain = chain.thenCompose(v -> tapKey(keys, ch));
        }
        return chain;
    }

    private CompletableFuture<Void> tapKey(java.util.Map<Character, int[]> keys, char key) {
        int[] c = keys.get(key);
        require(c != null, "STAKE_REJECTED", "No keypad key for '" + key + "'");
        android.graphics.Rect r = new android.graphics.Rect(c[0] - 30, c[1] - 22, c[0] + 30, c[1] + 22);
        return ui.tap(r, "key:" + key, 150);   // keypad keys register at once; no 450 ms page settle
    }

    private CompletableFuture<Void> erase(java.util.Map<Character, int[]> keys, int times) {
        CompletableFuture<Void> chain = CompletableFuture.completedFuture(null);
        for (int i = 0; i < times; i++) chain = chain.thenCompose(v -> tapKey(keys, StakePad.BACKSPACE));
        return chain;
    }

    static List<GameLinesParser.Word> wordsOf(VisualScreen screen) {
        List<GameLinesParser.Word> words = new ArrayList<>();
        for (VisualScreen.Line line : screen.lines) {
            List<String> texts = screen.words(line);
            for (int i = 0; i < texts.size(); i++) {
                android.graphics.Rect b = screen.wordBounds(line, i);
                words.add(new GameLinesParser.Word(texts.get(i), b.left, b.top, b.right, b.bottom));
            }
        }
        return words;
    }

    /** Strict stake check (StakePad.check); records the evidence under the given key. */
    private boolean stakeVerified(VisualScreen s, String stake, String price, String key) {
        if (stake == null || price == null) {
            ui.put(key, CoordinatorAgent.object("ok", false, "detail", "stake or price unknown"));
            return false;
        }
        StakePad.Check c = StakePad.check(wordsOf(s), stake, price);
        ui.put(key, CoordinatorAgent.object("ok", c.ok, "detail", c.detail, "stake_digits", String.valueOf(c.stakeDigits),
                "return_digits", String.valueOf(c.returnDigits), "stake", stake, "price", price));
        return c.ok;
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
        expectedPrice = selection.price; slipPriceRead = null;
        return ui.delay(300).thenCompose(v -> readbackRetry("final", 1, (s, enhanced) -> {
            require(!visible(s, "SIMULATOR", "DRYRUN", "REVIEW OK"), "EVENT_NOT_VERIFIED", "Simulator dry-run page during live verify");
            if (loginWall(s)) throw new Failure("SESSION_EXPIRED", "Bet365 login wall during betslip verify");
            detectBetslipFaults(s);
            require(!PlacementClassifier.multipleSelections(texts(s)), "BETSLIP_NOT_SINGLE",
                    "Betslip shows more than one selection; a multiple would be placed");
            require(visibleLoose(s, fixture.home) || visible(s, fixture.home), "WRONG_EVENT", "Home team missing on betslip");
            require(visibleLoose(s, fixture.away) || visible(s, fixture.away) || "DRAW".equals(selection.side),
                    "WRONG_EVENT", "Away team missing on betslip");
            if (selection.name != null && !selection.name.isEmpty() && !"DRAW".equals(selection.side)) {
                require(visible(s, selection.name) || visibleLoose(s, selection.name),
                        "SELECTION_CHANGED", "selection_name not visible on betslip: " + selection.name);
            }
            boolean priceOk = slipPriceShown(s, selection.price);
            require(priceOk, "PRICE_CHANGED", "Selection price not visible on betslip: " + selection.price);
            require(PlacementClassifier.slipShowsLine(texts(s), selection.market, selection.side, selection.name, selection.line),
                    "LINE_CHANGED", "Betslip does not show " + selection.side + " " + selection.line);
            require(stakeVerified(s, stake, selection.price, "stake_check_final"), "STAKE_REJECTED", "Stake not verified on betslip: " + stake);
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
        })).thenAccept(s -> { lastFinal = s; lastFinalAtMs = android.os.SystemClock.elapsedRealtime(); });
    }

    /** Readback stages the slip may fail on one OCR frame ("+3.5" read as "+315"): re-captured, max 3 reads. */
    private static final java.util.Set<String> REREAD_STAGES = java.util.Set.of(
            "LINE_CHANGED", "PRICE_CHANGED", "STAKE_REJECTED", "SELECTION_CHANGED", "WRONG_EVENT", "TARGET_NOT_FOUND");

    /**
     * Capture and run the checks; if they fail on a readback stage, capture again (max 3 reads). A pass
     * still needs every check on ONE frame; a real difference fails all three and is reported as is.
     */
    private CompletableFuture<VisualScreen> readbackRetry(String label, int attempt, java.util.function.BiConsumer<VisualScreen, Boolean> checks) {
        // Re-reads use the enhanced per-word OCR (3x, contrast): real slips where the plain read missed
        // "1.83" and read "£0.18" as "£0118" (Berck v Pays Salonais). The checks themselves never change.
        CompletableFuture<VisualScreen> frame = attempt == 1 ? ui.capture(label) : ui.captureEnhanced(label + "_enhanced");
        return frame.thenCompose(s -> {
            try {
                checks.accept(s, attempt > 1);   // true = enhanced re-read frame
                return CompletableFuture.completedFuture(s);
            } catch (Failure f) {
                if (attempt >= 3 || !REREAD_STAGES.contains(f.stage)) throw f;
                // The slip's right-aligned price is often missed by the plain read (real: Berck slip): read just
                // that box (numeric, single line) once and re-check THIS frame; it must equal the price exactly.
                if (attempt == 1 && "PRICE_CHANGED".equals(f.stage) && expectedPrice != null && slipPriceRead == null) {
                    android.graphics.Rect box = slipPriceBox(s);
                    if (box != null) {
                        return ui.readRegion(label + "_price", box, true).thenCompose(text -> {
                            slipPriceRead = text == null ? "" : text.replaceAll("[^0-9.]", "");
                            ui.put("slip_price_region", CoordinatorAgent.object("read", slipPriceRead, "bounds", VisualSession.bounds(box)));
                            try { checks.accept(s, false); return CompletableFuture.completedFuture(s); }
                            catch (Failure again) {
                                if (!REREAD_STAGES.contains(again.stage)) throw again;
                                return ui.delay(300).thenCompose(v -> readbackRetry(label, attempt + 1, checks));
                            }
                        });
                    }
                }
                JSONArray log = ui.record.optJSONArray("readback_rereads");
                if (log == null) { log = new JSONArray(); ui.put("readback_rereads", log); }
                log.put(label + " " + attempt + ": " + f.stage + " " + f.getMessage());
                return ui.delay(300).thenCompose(v -> readbackRetry(label, attempt + 1, checks));
            }
        });
    }


    static String classifySessionState(VisualScreen s) {
        if (s == null) return "UNKNOWN";
        if (sessionExpired(s)) return "EXPIRED";
        if (sessionLoggedIn(s)) return "AUTHENTICATED";
        if (loginWall(s) || headerLogIn(s)) return "LOGGED_OUT";
        return "UNKNOWN";
    }

    /** Bet365 header offers "Log In" (possibly OCR-merged, e.g. "bet365 Rewards Log In"): logged out. */
    private static boolean headerLogIn(VisualScreen s) {
        for (VisualScreen.Line line : s.lines) {
            if (line.bounds.top > 320) continue;
            String t = " " + line.text.trim().toLowerCase(Locale.US) + " ";
            if (t.contains(" log in ") || t.contains(" login ")) return true;
        }
        return false;
    }

    private static boolean sessionLoggedIn(VisualScreen s) {
        if (loginWall(s)) return false;
        // Header Log In + Join ? logged out marketing chrome
        boolean headerLogin = false, join = false;
        for (VisualScreen.Line line : s.lines) {
            if (line.bounds.top > 320) continue;
            String t = " " + line.text.trim().toLowerCase(Locale.US) + " ";
            // Contains, not equals: OCR often merges the header into "bet365 Rewards Log In".
            if (t.contains(" log in ") || t.contains(" login ")) headerLogin = true;
            if (t.contains(" join ") || t.contains(" join now ")) join = true;
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
        CompletableFuture<VisualScreen> frame = lastFinal != null && android.os.SystemClock.elapsedRealtime() - lastFinalAtMs < 4000
                ? CompletableFuture.completedFuture(lastFinal)
                : ui.delay(400).thenCompose(v -> ui.capture("complete_execution_pre"));
        if (lastFinal != null) ui.put("prepare_frame", "reused verified final frame");
        return frame.thenAccept(s -> {
            detectBetslipFaults(s);
            require(!PlacementClassifier.multipleSelections(texts(s)), "BETSLIP_NOT_SINGLE",
                    "Betslip shows more than one selection before Place Bet");
            require(visibleLoose(s, fixture.home) || visible(s, fixture.home), "WRONG_EVENT", "Home missing before complete execution");
            require(visibleLoose(s, fixture.away) || visible(s, fixture.away) || "DRAW".equals(selection.side),
                    "WRONG_EVENT", "Away missing before complete execution");
            if (selection.name != null && !selection.name.isEmpty() && !"DRAW".equals(selection.side)) {
                require(visible(s, selection.name) || visibleLoose(s, selection.name),
                        "SELECTION_CHANGED", "selection_name missing before complete execution");
            }
            boolean priceOk = slipPriceShown(s, selection.price);   // same evidence as verify_final_state (incl. targeted price read)
            require(priceOk, "PRICE_CHANGED", "Price missing before complete execution: " + selection.price);
            if (Double.parseDouble(selection.price) < Double.parseDouble(minimumPrice))
                throw new Failure("BELOW_MINIMUM", "Price " + selection.price + " below minimum " + minimumPrice);
            require(stakeVerified(s, stake, selection.price, "stake_check_prepare"), "STAKE_REJECTED", "Stake missing before complete execution: " + stake);
            VisualScreen.Line place = findPlaceBetLine(s);
            require(place != null, "TARGET_NOT_FOUND", "Place Bet control not visible for COMPLETE_EXECUTION_READY");
            android.graphics.Rect tap = placeBetTapRect(place);
            require(!tap.isEmpty() && tap.width() > 20 && tap.height() > 10, "TARGET_NOT_FOUND", "Place Bet bounds not actionable");
            boolean enabled = true; // green Place Bet is actionable when stake set; grey would fail OCR presence alone
            // If OCR still shows Set Stake without stake amount, treat as not actionable
            String blob = "";
            for (VisualScreen.Line line : s.lines) blob += " " + line.text.toLowerCase(java.util.Locale.US);
            if (blob.contains("set stake")) enabled = false;
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

    /** Waits between post-tap frames (ms): outcome is classified from up to five screens (~12 s). */
    private static final long[] OUTCOME_WAITS_MS = {1500, 1500, 2000, 3000, 4000};

    public CompletableFuture<Void> place_bet(Fixture fixture, Selection selection, String stake) {
        // REAL Place Bet tap, once. Only reached for execution_mode=dispatch + confirmation APPROVED.
        if (preparedPlaceBetBounds == null || preparedPlaceBetBounds.isEmpty())
            return VisualSession.failed("TARGET_NOT_FOUND", "Place Bet was not prepared with the instruction's minimum price");
        android.graphics.Rect tap = new android.graphics.Rect(preparedPlaceBetBounds);
        return ui.capture("place_bet_pre_dispatch").thenCompose(s -> {
            detectBetslipFaults(s);
            require(!PlacementClassifier.multipleSelections(texts(s)), "BETSLIP_NOT_SINGLE", "Betslip not a single before Place Bet");
            boolean priceOk = visible(s, selection.price) || fractionalVisible(s, selection.price);
            require(priceOk, "PRICE_CHANGED", "Price changed before Place Bet dispatch");
            require(stakeVerified(s, stake, selection.price, "stake_check_pre_dispatch"), "STAKE_REJECTED", "Stake missing before Place Bet dispatch");
            require(findPlaceBetLine(s) != null, "TARGET_NOT_FOUND", "Place Bet disappeared before dispatch");
            return tapPlaceBetOnce(tap, selection, stake);
        });
    }

    /** The single Place Bet tap: durable intent first, one gesture, then outcome classification. */
    private CompletableFuture<Void> tapPlaceBetOnce(android.graphics.Rect tap, Selection selection, String stake) {
        {
            ui.put("place_bet_bounds", VisualSession.bounds(tap));
            // Durable intent BEFORE the gesture: from here on, any failure is reported as a
            // possible placement (never "not tapped"), so the backend reconciles and never re-taps.
            ui.put("placement", placement("PLACEMENT_UNKNOWN", "Place Bet tap dispatching; outcome not yet classified",
                    null, null, stake, selection.price, new JSONArray(), null));
            ui.checkpoint("PLACE_BET");
            ui.put("t_tap_ms", System.currentTimeMillis());
            return ui.tap(tap, "Place Bet").thenCompose(x -> {
                if (preparedGesture != null) {
                    try { preparedGesture.put("dispatched", true); } catch (Exception ignored) {}
                    ui.put("prepared_gesture", preparedGesture);
                }
                ui.put("gesture_dispatched", true);
                ui.put("place_bet_tapped", true);
                return observeOutcome(1, new JSONArray(), selection, stake);
            });
        }
    }

    /**
     * PLACE_HELD pre-tap check on the CURRENT screen (one capture, no navigation): logged in, one selection,
     * the approved selection and exact line on the slip, the approved price (>= minimum), the stake with
     * a matching To Return, and Place Bet present. Then one tap (dispatch) or nothing (prepare).
     * Anything different fails closed; the bet is never rebuilt after approval.
     */
    CompletableFuture<Void> place_held(String market, String side, String line, String name, String price,
                                       String minimumPrice, String stake, boolean dispatch) {
        ui.checkpoint("PRETAP_CHECK");
        expectedPrice = price; slipPriceRead = null; targetLine = line == null ? "" : line;
        final android.graphics.Rect[] tapHolder = new android.graphics.Rect[1];
        return readbackRetry("pretap", 1, (s, enhanced) -> {
            List<String> t = texts(s);
            // Login is judged on the plain first frame (checked first; a login failure is never re-read).
            // Enhanced re-read frames distort the header, so they only re-check the slip.
            if (!enhanced) require(sessionLoggedIn(s), "SESSION_EXPIRED", "Not logged in at the pre-tap check");
            detectBetslipFaults(s);
            require(!PlacementClassifier.receiptVisible(t), "REJECTED", "A receipt is showing, not the held slip");
            require(!PlacementClassifier.multipleSelections(t), "BETSLIP_NOT_SINGLE", "Betslip is not a single");
            require(visible(s, name) || visibleLoose(s, name), "SELECTION_CHANGED", "Held selection '" + name + "' not on the slip");
            require(PlacementClassifier.slipShowsLine(t, market, side, name, line), "LINE_CHANGED", "Slip does not show " + side + " " + line);
            require(slipPriceShown(s, price), "PRICE_CHANGED", "Approved price " + price + " not on the slip");
            require(new java.math.BigDecimal(price).compareTo(new java.math.BigDecimal(minimumPrice)) >= 0,
                    "BELOW_MINIMUM", "Price " + price + " below minimum " + minimumPrice);
            require(stakeVerified(s, stake, price, "stake_check_pretap"), "STAKE_REJECTED", "Held stake does not read back as " + stake);
            VisualScreen.Line place = findPlaceBetLine(s);
            require(place != null, "TARGET_NOT_FOUND", "Place Bet not on the held slip");
            android.graphics.Rect tap = placeBetTapRect(place);
            require(!tap.isEmpty() && tap.width() > 20 && tap.height() > 10, "TARGET_NOT_FOUND", "Place Bet bounds not actionable");
            ui.put("pretap", CoordinatorAgent.object("ok", true, "selection", name, "line", line, "price", price, "stake", stake,
                    "place_bet_bounds", VisualSession.bounds(tap)));
            ui.put("t_pretap_done_ms", System.currentTimeMillis());
            tapHolder[0] = tap;
        }).thenCompose(s -> {
            if (!dispatch) return CompletableFuture.<Void>completedFuture(null);
            Selection selection = new Selection(market, side, line, price, "OPEN", tapHolder[0], name);
            return tapPlaceBetOnce(tapHolder[0], selection, stake);
        });
    }

    private CompletableFuture<Void> observeOutcome(int attempt, JSONArray frames, Selection selection, String stake) {
        return ui.delay(OUTCOME_WAITS_MS[attempt - 1])
                .thenCompose(v -> { ui.checkpoint("PLACE_BET_OUTCOME"); return ui.capture("place_bet_after"); })
                .thenCompose(after -> {
                    frames.put(ui.lastImage());
                    List<String> lines = texts(after);
                    PlacementClassifier.Result r = PlacementClassifier.classify(lines, findPlaceBetLine(after) != null);
                    if (!r.definitive && attempt < OUTCOME_WAITS_MS.length) return observeOutcome(attempt + 1, frames, selection, stake);
                    return confirmReference(after, r).thenCompose(reference -> {
                        String outcome = r.definitive ? r.outcome : "PLACEMENT_UNKNOWN";
                        String detail = r.definitive ? r.detail
                                : "No definitive outcome after " + attempt + " frames (" + r.detail + "); never re-tapped";
                        ui.put("placement", placement(outcome, detail, reference, r.potentialReturn,
                                r.stake != null ? r.stake : stake, selection.price, frames, PlacementClassifier.receiptLines(lines)));
                        ui.put("wager_submitted", "PLACED".equals(outcome));
                        ui.put("place_bet_result", outcome);
                        ui.put("place_bet_detail", detail);
                        ui.put("t_receipt_ms", System.currentTimeMillis());
                        return resetBetslip().thenCompose(v -> returnHome());
                    });
                });
    }

    /**
     * Hybrid engine (Milestone C5): the receipt's reference is read by both engines. On the two real receipts the
     * fast engine read both exactly; Tesseract's full-page read had reported the second as "W6334352221W" where
     * the screen shows "YT6334352221W" (evidence/ocr-bench). After the tap (not time-critical) the "Bet Ref" line
     * is re-read with Tesseract's enhanced pass; the fast reading is kept and a disagreement is recorded as
     * bet_reference_disputed with both readings, never silently resolved. My Bets reconciliation identifies the
     * bet by fixture, selection and stake, never by reference. The placement outcome is never changed here.
     */
    private CompletableFuture<String> confirmReference(VisualScreen after, PlacementClassifier.Result r) {
        if (r.betReference == null || "legacy".equals(ui.runner().engine())) return CompletableFuture.completedFuture(r.betReference);
        VisualScreen.Line refLine = null;
        for (VisualScreen.Line line : after.lines) if (line.text.toLowerCase(Locale.US).contains("bet ref")) { refLine = line; break; }
        if (refLine == null) return CompletableFuture.completedFuture(r.betReference);
        return ui.readRegion("receipt_ref", refLine.bounds, false).handle((text, e) -> {
            String legacy = e == null ? PlacementClassifier.reference(java.util.Collections.singletonList(text == null ? "" : text)) : null;
            ui.put("bet_reference_fast", r.betReference);
            ui.put("bet_reference_legacy", legacy == null ? "" : legacy);
            if (legacy != null && !legacy.equals(r.betReference)) ui.put("bet_reference_disputed", true);
            return r.betReference;
        });
    }

    /** After a placement: Bet365 HOME is the clean idle state (never re-taps anything). */
    private CompletableFuture<Void> returnHome() { return return_home_verified(); }

    /** Bet365 HOME as the clean idle state, VERIFIED on screen (nav bar visible, not on My Bets). Never taps. */
    CompletableFuture<Void> return_home_verified() {
        ui.checkpoint("RETURN_HOME");
        return ui.open(HOME_URL).thenCompose(v -> homeVerified(1)).thenAccept(ok -> {
            ui.put("returned_home", ok);
            ui.put("home_verified", ok);
            ui.put("t_home_ms", System.currentTimeMillis());
        }).exceptionally(e -> { ui.put("returned_home", false); ui.put("home_verified", false); return null; });
    }

    /** HOME is verified when the address bar reads #/HO/ (or the Search bar shows) and nothing reads #/MB;
     *  the page settles over a few seconds, so up to three captures. Nothing is tapped. */
    private CompletableFuture<Boolean> homeVerified(int attempt) {
        return ui.delay(attempt == 1 ? 1500 : 1200).thenCompose(v -> ui.capture("home_verify")).thenCompose(s -> {
            boolean homeUrl = false, myBets = false;
            for (VisualScreen.Line line : s.lines) {
                String t = line.text;
                if (t.contains("#/HO")) homeUrl = true;
                if (t.contains("#/MB")) myBets = true;
            }
            boolean ok = !myBets && (homeUrl || visible(s, "Search"));
            if (ok || attempt >= 3) return CompletableFuture.completedFuture(ok);
            return homeVerified(attempt + 1);
        });
    }

    private static org.json.JSONObject placement(String outcome, String detail, String reference, String potentialReturn,
                                                String stake, String odds, JSONArray frames, List<String> receiptLines) {
        return CoordinatorAgent.object("tapped", true, "outcome", outcome, "detail", detail,
                "bet_reference", reference == null ? org.json.JSONObject.NULL : reference,
                "potential_return", potentialReturn == null ? org.json.JSONObject.NULL : potentialReturn,
                "stake", stake, "odds", odds, "frames", frames,
                "receipt_lines", receiptLines == null ? new JSONArray() : new JSONArray(receiptLines),
                "classified_at_ms", System.currentTimeMillis());
    }

    /** Clear the betslip after any outcome so the next instruction starts with an empty slip.
     *  A receipt is closed with its banner X (right of "Share"); otherwise only whitelisted controls
     *  (Done/Continue/Close/Remove All/Clear) are tapped. Never "Reuse Selections". */
    /** RESET_BETSLIP instruction: close a receipt / reset the slip on the current screen, no navigation. */
    CompletableFuture<Void> reset_now() { return resetBetslip(); }

    private CompletableFuture<Void> resetBetslip() {
        ui.checkpoint("RESET_BETSLIP");
        return ui.capture("reset_pre").thenCompose(s -> {
            if (PlacementClassifier.receiptVisible(texts(s))) return dismissReceipt(s);
            // A selection still on the slip is removed by its own X (never "Done", which would keep it).
            android.graphics.Rect icon = removeIcon(s, null);
            if (icon != null) {
                return ui.tap(icon, "Remove selection").thenCompose(v -> ui.delay(1200))
                        .thenCompose(v -> ui.capture("reset_after")).thenAccept(after ->
                                ui.put("betslip_reset", CoordinatorAgent.object("tapped", true, "control", "remove selection X",
                                        "bounds", VisualSession.bounds(icon), "place_bet_still_visible", findPlaceBetLine(after) != null)));
            }
            VisualScreen.Line control = null;
            for (String want : new String[] {"Done", "Continue", "Remove All", "Clear All", "Close"}) {
                for (VisualScreen.Line line : s.lines) {
                    if (line.text.trim().equalsIgnoreCase(want) && PlacementClassifier.safeResetControl(line.text)) { control = line; break; }
                }
                if (control != null) break;
            }
            if (control == null) {
                ui.put("betslip_reset", CoordinatorAgent.object("tapped", false, "detail", "No safe reset control visible"));
                return CompletableFuture.<Void>completedFuture(null);
            }
            final String label = control.text.trim();
            return ui.tap(control.bounds, "Reset betslip: " + label).thenCompose(v -> ui.delay(900))
                    .thenCompose(v -> ui.capture("reset_after")).thenAccept(after ->
                            ui.put("betslip_reset", CoordinatorAgent.object("tapped", true, "control", label,
                                    "place_bet_still_visible", findPlaceBetLine(after) != null)));
        }).exceptionally(error -> {
            ui.put("betslip_reset", CoordinatorAgent.object("tapped", false, "detail", "Reset failed: " + error.getClass().getSimpleName()));
            return null;
        });
    }

    /** Close the "Bet Placed" receipt banner by its X. Real layout: "Bet Placed" / "Bet Ref ..." on the left,
     *  "Share" and the X on the right of the same green banner. */
    private CompletableFuture<Void> dismissReceipt(VisualScreen s) {
        android.graphics.Rect close = null;
        String how = null;
        for (VisualScreen.Line line : s.lines) {
            List<String> words = s.words(line);
            int share = -1;
            for (int i = 0; i < words.size(); i++) if (words.get(i).trim().equalsIgnoreCase("share")) share = i;
            if (share < 0) continue;
            int x = PlacementClassifier.receiptCloseWord(words);
            if (x >= 0) { close = s.wordBounds(line, x); how = "ocr_x"; }
            else {
                // OCR missed the icon: it sits one icon-width right of "Share" on the same banner line.
                android.graphics.Rect sh = s.wordBounds(line, share);
                int cx = sh.right + Math.round(sh.width() * 1.25f);
                close = new android.graphics.Rect(cx - 22, sh.centerY() - 22, cx + 22, sh.centerY() + 22);
                how = "right_of_share";
            }
            break;
        }
        if (close == null) {
            ui.put("betslip_reset", CoordinatorAgent.object("tapped", false, "detail", "Receipt visible but its close control was not found"));
            return CompletableFuture.completedFuture(null);
        }
        final String method = how;
        final android.graphics.Rect target = close;
        return ui.tap(target, "Close receipt").thenCompose(v -> ui.delay(1200))
                .thenCompose(v -> ui.capture("receipt_closed")).thenAccept(after ->
                        ui.put("betslip_reset", CoordinatorAgent.object("tapped", true, "control", "receipt X",
                                "method", method, "bounds", VisualSession.bounds(target),
                                "receipt_still_visible", PlacementClassifier.receiptVisible(texts(after)))));
    }

    /** Remove icon of a selection on the slip: the OCR'd X glyph, else (glyph not read) the icon area left of an
     *  indented selection line with the market name beneath. Null if no selection line is recognised. */
    private static android.graphics.Rect removeIcon(VisualScreen s, String selectionName) {
        for (int i = 0; i < s.lines.size(); i++) {
            VisualScreen.Line line = s.lines.get(i);
            if (line.bounds.top < 300) continue;
            List<String> words = s.words(line);
            int glyph = selectionName == null ? PlacementClassifier.removeAnySelectionWord(words)
                    : PlacementClassifier.removeSelectionWord(words, selectionName);
            if (glyph == 0) return s.wordBounds(line, 0);
            String next = i + 1 < s.lines.size() && s.lines.get(i + 1).bounds.top - line.bounds.bottom < 60 ? s.lines.get(i + 1).text : null;
            if (PlacementClassifier.selectionLineByIndent(line.text, line.bounds.left, next, selectionName)) {
                int cx = line.bounds.left - 28, cy = line.bounds.centerY();
                return new android.graphics.Rect(cx - 14, cy - 16, cx + 14, cy + 16);
            }
        }
        return null;
    }

    @Override
    public CompletableFuture<Void> clear_betslip(Selection selection) {
        ui.checkpoint("CLEAR_BETSLIP");
        return ui.capture("clear_betslip_pre").thenCompose(s -> {
            android.graphics.Rect icon = removeIcon(s, selection == null || selection.name.isEmpty() ? null : selection.name);
            if (icon != null) {
                return ui.tap(icon, "Remove selection from betslip").thenCompose(v -> ui.delay(1200))
                        .thenCompose(v -> ui.capture("clear_betslip_after")).thenAccept(after ->
                                ui.put("betslip_clear", CoordinatorAgent.object("tapped", true,
                                        "bounds", VisualSession.bounds(icon),
                                        "place_bet_still_visible", findPlaceBetLine(after) != null)));
            }
            ui.put("betslip_clear", CoordinatorAgent.object("tapped", false, "detail", "No remove icon on a selection line"));
            return CompletableFuture.<Void>completedFuture(null);
        });
    }

    // ------------------------------------------------------------------ My Bets (reconciliation)
    /** Open My Bets (OPEN = unsettled, SETTLED = settled) and return every OCR line over a few scrolled frames.
     *  Read-only: taps only the My Bets entry and its tabs; never a bet, cash-out or edit control. */
    CompletableFuture<org.json.JSONObject> read_my_bets(String view) {
        // Direct address, not tab taps: real screens showed the tab labelled "Open" is the Live tab
        // (in-play only), which would make a placed bet look absent. The backend also checks the
        // address bar (#/MB/U or #/MB/S) before trusting absence.
        String url = "SETTLED".equals(view) ? "https://www.bet365.com/#/MB/S" : "https://www.bet365.com/#/MB/U";
        ui.checkpoint("MY_BETS");
        ui.put("my_bets_url", url);
        ui.put("my_bets_tab", "SETTLED".equals(view) ? "Settled" : "Unsettled");
        return ui.open(url).thenCompose(v -> ui.delay(2500)).thenCompose(v -> settle("my_bets_view", 0))
                .thenCompose(s -> collectMyBets(0, new JSONArray(), new JSONArray(), view));
    }

    private CompletableFuture<org.json.JSONObject> collectMyBets(int frame, JSONArray lines, JSONArray frames, String view) {
        ui.checkpoint("MY_BETS_SCROLL");
        return ui.capture("my_bets_" + (frame + 1)).thenCompose(s -> {
            frames.put(ui.lastImage());
            for (VisualScreen.Line line : s.lines)
                lines.put(CoordinatorAgent.object("text", line.text, "top", line.bounds.top, "left", line.bounds.left, "frame", frame));
            boolean empty = visible(s, "No bets", "no bets to display", "no open bets", "no unsettled", "You have no", "No Settled");
            if (empty || frame >= 3) {
                return CompletableFuture.completedFuture(CoordinatorAgent.object("view", view, "tab", ui.record.opt("my_bets_tab"),
                        "empty", empty, "frames", frames, "lines", lines));
            }
            return ui.swipe(360, 1150, 450, 450).thenCompose(v -> ui.delay(1200))
                    .thenCompose(v -> collectMyBets(frame + 1, lines, frames, view));
        });
    }

    private static VisualScreen.Line exactLine(VisualScreen s, String text) {
        for (VisualScreen.Line line : s.lines) if (line.text.trim().equalsIgnoreCase(text)) return line;
        return null;
    }

    static List<String> texts(VisualScreen s) {
        List<String> out = new ArrayList<>();
        for (VisualScreen.Line line : s.lines) out.add(line.text);
        return out;
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


    /** Capture the Game Lines grid until two consecutive reads are identical (max 4 captures) and return the
     *  cells agreed across reads (GameLinesParser.consensus). Every read is recorded in game_lines_reads. */
    private CompletableFuture<List<Selection>> gridConsensus(String tag, int attempt, List<List<GameLinesParser.Cell>> reads, JSONArray log) {
        return ui.captureTable(tag).thenCompose(s -> {
            GameLinesParser.Result r = GameLinesParser.parse(wordsOf(s), liveFixture.home, liveFixture.away);
            JSONArray cells = new JSONArray();
            for (GameLinesParser.Cell c : r.cells) cells.put(c.toString());
            log.put(CoordinatorAgent.object("tag", tag, "cells", cells, "notes", new JSONArray(r.notes)));
            ui.put("game_lines_reads", log);
            List<GameLinesParser.Cell> previous = reads.isEmpty() ? null : reads.get(reads.size() - 1);
            if (!r.cells.isEmpty()) reads.add(r.cells);
            boolean stable = previous != null && !r.cells.isEmpty() && String.valueOf(previous).equals(String.valueOf(r.cells));
            // Fast path: a first read with no parser notes (every cell read, signs explicit or paired, O/U
            // consistent) is used as is: the betslip re-shows the exact line and price before READY/tap.
            boolean clean = attempt == 1 && ((r.grid && r.notes.isEmpty() && r.cells.size() >= 4) || targetClean(r));
            if (!stable && !clean && attempt < 4) return ui.delay(600).thenCompose(v -> gridConsensus(tag, attempt + 1, reads, log));
            List<Selection> out = new ArrayList<>();
            JSONArray agreed = new JSONArray();
            for (GameLinesParser.Cell c : clean ? r.cells : GameLinesParser.consensus(reads)) {
                android.graphics.Rect b = new android.graphics.Rect(c.bounds[0], c.bounds[1], c.bounds[2], c.bounds[3]);
                out.add(new Selection(c.market, c.side, c.line, c.price, "OPEN", b, c.name));
                agreed.put(c.toString());
            }
            ui.put("game_lines", CoordinatorAgent.object("reads", reads.size(), "agreed", agreed, "fast_path", clean));
            if (clean) cleanGridAtMs = android.os.SystemClock.elapsedRealtime();
            return CompletableFuture.completedFuture(out);
        });
    }

    /** Basketball Game Lines grid (GameLinesParser) as selections; empty if not a basketball grid. */
    private List<Selection> parseGameLines(VisualScreen screen, boolean record) {
        List<Selection> out = new ArrayList<>();
        if (!"basketball".equals(sport) || liveFixture == null) return out;
        GameLinesParser.Result r = GameLinesParser.parse(wordsOf(screen), liveFixture.home, liveFixture.away);
        JSONArray cells = new JSONArray();
        for (GameLinesParser.Cell c : r.cells) {
            android.graphics.Rect b = new android.graphics.Rect(c.bounds[0], c.bounds[1], c.bounds[2], c.bounds[3]);
            out.add(new Selection(c.market, c.side, c.line, c.price, "OPEN", b, c.name));
            cells.put(c.toString());
        }
        if (record) ui.put("game_lines", CoordinatorAgent.object("grid", r.grid, "cells", cells, "notes", new JSONArray(r.notes)));
        return out;
    }

    private Selection refind(VisualScreen screen, Selection expected) {
        List<Selection> grid = parseGameLines(screen, false);
        if (!grid.isEmpty()) {
            for (Selection s : grid) if (s.market.equals(expected.market) && s.side.equals(expected.side) && lineEquals(s.line, expected.line)) return s;
            // Line moved or cell unreadable: never fall back to another line.
            throw new Failure("LINE_CHANGED", "Game Lines re-read has no " + expected.market + "/" + expected.side + "/" + expected.line);
        }
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
        for (int li = 0; li < screen.lines.size(); li++) {
            VisualScreen.Line line = screen.lines.get(li);
            Matcher m = vsOnly.matcher(line.text.trim());
            if (!m.matches()) continue;
            if (line.bounds.top > 1320) continue;
            String away = cleanTeam(m.group(2));
            // Real search card (2026-09-24): "Hapoel Tel Aviv vs Bayern" + "1 2" column headers on one OCR
            // line, "Munich" wrapped onto the next line. Append a letters-only continuation line.
            if (li + 1 < screen.lines.size() && !m.group(2).trim().endsWith(">")) {
                VisualScreen.Line next = screen.lines.get(li + 1);
                String nt = next.text.trim();
                if (continuationWord(nt) && Math.abs(next.bounds.left - line.bounds.left) <= 30
                        && next.bounds.top - line.bounds.bottom <= 40) away = away + " " + nt;
            }
            addFixture(result, screen, cleanTeam(m.group(1)), away, line.bounds);
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
                    // Three prices on one OCR line ÃƒÆ’Ã‚Â¯Ãƒâ€šÃ‚Â¿Ãƒâ€šÃ‚Â½ emit HOME/DRAW/AWAY in order for football.
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

    static String cleanTeam(String raw) {
        String t = raw.replaceAll("\\s+", " ").replaceAll("[|].*$", "").trim();
        t = t.replaceAll("\\s*[>\u203a\u00bb]+$", "").trim();          // "Bayern Munich >" (event link chevron)
        t = t.replaceAll("(?:\\s+(?:1|X|x|2)){2,}$", "").trim();       // merged "1 2" / "1 X 2" column headers
        return t;
    }

    /** A wrapped team-name tail such as "Munich": 1-3 letter words, not a day, time or nav word. */
    static boolean continuationWord(String t) {
        return t.matches("[A-Za-z][A-Za-z.'-]*(?: [A-Za-z][A-Za-z.'-]*){0,2}") && !looksLikeNav(t)
                && !t.matches("(?i)(mon|tue|wed|thu|fri|sat|sun|today|tomorrow|live|in-play|close)(\\s.*)?");
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

    /**
     * When Bet365 search surfaces Casino-first hits (common for "BC ?" queries),
     * tap a Sports/Football/Basketball/Events/TEAMS chip before fixture identity.
     * Does not weaken fixture matching ? only changes which results pane is OCR'd.
     */
    private CompletableFuture<Void> steerSearchResultsToSports(VisualScreen s) {
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
    }

    /**
     * Hard fixture identity gate (search results): positively identify the queried team,
     * require a single home/away pairing, and when expectedAway is set require that away too.
     * No fuzzy OCR confusion mapping — imperfect OCR must not select a market.
     */
    private void assertUniqueFixtureForQuery(VisualScreen s, String q) {
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
    }

    private static Fixture selectUniqueFixtureForQuery(List<Fixture> all, String query, String expectedAway) {
        String q = query == null ? "" : query.trim();
        String away = expectedAway == null ? "" : expectedAway.trim();
        require(!q.isEmpty(), "NO_FIXTURE_FOUND", "No search query available for fixture identity");
        List<Fixture> matches = new ArrayList<>();
        for (Fixture f : all) {
            boolean qHit = teamPositivelyIdentified(f.home, q) || teamPositivelyIdentified(f.away, q);
            if (!qHit) continue;
            if (!away.isEmpty()) {
                boolean awayHit = teamPositivelyIdentified(f.home, away) || teamPositivelyIdentified(f.away, away);
                if (!awayHit) continue;
                // Both teams must sit on opposite sides (correct pairing).
                boolean queryHome = teamPositivelyIdentified(f.home, q);
                boolean queryAway = teamPositivelyIdentified(f.away, q);
                boolean awayHome = teamPositivelyIdentified(f.home, away);
                boolean awayAwaySide = teamPositivelyIdentified(f.away, away);
                if (!((queryHome && awayAwaySide) || (queryAway && awayHome))) continue;
            }
            matches.add(f);
        }
        if (matches.isEmpty()) {
            throw new Failure(!away.isEmpty() ? "WRONG_EVENT" : "NO_FIXTURE_FOUND",
                    !away.isEmpty()
                            ? ("No fixture pairing for '" + q + "' vs '" + away + "'")
                            : ("No search result fixture positively identifies query '" + q + "'"));
        }
        // Collapse to unique home|away pairings (ignore competition duplicates).
        LinkedHashMap<String, Fixture> pairings = new LinkedHashMap<>();
        for (Fixture f : matches) {
            String key = f.home.toLowerCase(Locale.US) + "|" + f.away.toLowerCase(Locale.US);
            pairings.putIfAbsent(key, f);
        }
        require(pairings.size() == 1, "AMBIGUOUS_FIXTURE",
                "Multiple plausible fixtures for query '" + q + "'"
                        + (away.isEmpty() ? "" : (" vs '" + away + "'"))
                        + ": " + pairings.keySet());
        return pairings.values().iterator().next();
    }

        /** Strip gender/competition suffixes for identity compare (W)/(M)/Women — not search aliases. */
        private static String normalizeTeamIdentity(String raw) {
        if (raw == null) return "";
        String t = OcrText.normalize(raw).trim().replaceAll("\\s+", " ");
        t = t.replaceAll("(?i)\\s*\\((?:W|M|F|Women|Men)\\)\\s*$", "");
        t = t.replaceAll("(?i)\\s+(?:Women|Men|Womens|Ladies)$", "");
        // Explicit per-team canonical names only (TeamAliases), e.g. Shiga Lake Stars -> Shiga Lakes.
        return TeamAliases.canonical(t.trim().toLowerCase(Locale.US));
    }

    /** Test hook: the fixture identity gate used on search results. */
    static boolean identityForTest(String teamName, String requested) { return teamPositivelyIdentified(teamName, requested); }

    /** Positive team identity: exact or contains full multi-word query; no OCR confusion aliases. */
    private static boolean teamPositivelyIdentified(String teamName, String requested) {
        if (teamName == null || requested == null) return false;
        // Milestone B: exact / canonical / alias (registry or instruction) through the resolver; protected
        // markers (women, reserves, age groups) that differ never match, whatever the text below says.
        EventIdentity.Side side = EventIdentity.matchSide(requested, teamName, instructionAliases);
        if (side.atLeast(EventIdentity.Level.ALIAS)) return true;
        if (!side.markersAgree) return false;
        String t = normalizeTeamIdentity(teamName);
        String r = normalizeTeamIdentity(requested);
        if (t.isEmpty() || r.isEmpty()) return false;
        if (t.equals(r)) return true;
        if (t.contains(r)) return true;
        if (r.contains(t) && t.length() >= 4) return true;
        // Allow requested "BC Beroe" to match team "Beroe" when requested ends with that token.
        if (r.endsWith(" " + t) && t.length() >= 4) return true;
        // Allow requested "Ferrol" to match "Uni Ferrol" (team ends with requested token).
        if (t.endsWith(" " + r) && r.length() >= 4) return true;
        return false;
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

