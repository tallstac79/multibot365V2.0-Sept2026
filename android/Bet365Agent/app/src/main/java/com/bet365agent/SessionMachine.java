package com.bet365agent;

import java.util.List;
import java.util.Locale;
import java.util.regex.Pattern;

/**
 * Explicit Bet365 login / session state machine (pure Java; JVM tests: SessionMachineTest).
 *
 * The adapter observes a screen (OCR lines with their positions), {@link #observe} names what that screen
 * shows, {@link #next} names the state that follows, and the adapter performs the action that state calls
 * for (tap Log In, fill the form, stop for the operator, return home). Nothing here touches the screen,
 * the network or credentials, so every transition is unit-testable.
 *
 * Authentication is judged from ACCOUNT evidence in Bet365's header (balance pill, Deposit, My Account,
 * Log Out), never from the URL. A verification-code prompt or a security challenge always wins: those are
 * terminal states for the operator, the agent never guesses at them.
 */
final class SessionMachine {
    enum State { AUTHENTICATED, LOGIN_REQUIRED, LOGIN_IN_PROGRESS, TWO_FACTOR_REQUIRED, BOT_CHECK_OR_CHALLENGE, LOGIN_FAILED, AUTHENTICATED_RECOVERED }

    /** What one screen shows, in precedence order (a challenge beats everything, a form beats a header). */
    enum Observation { CHALLENGE, TWO_FACTOR, LOGIN_FORM, EXPIRED, ACCOUNT, LOGGED_OUT, UNKNOWN }

    /** Login submissions the machine allows before LOGIN_FAILED. */
    static final int MAX_LOGIN_ATTEMPTS = 2;

    /** One OCR line: text and where it sits (screen pixels). */
    static final class Line {
        final String text; final int top, left;
        Line(String text, int top, int left) { this.text = text == null ? "" : text; this.top = top; this.left = left; }
    }

    // Bet365 header band on a 720x1600 phone: below Chrome's URL bar, above the page content.
    static final int HEADER_TOP = 140, HEADER_BOTTOM = 240, HEADER_WORDS_BOTTOM = 320, HEADER_RIGHT_FROM = 380;
    private static final Pattern BALANCE = Pattern.compile("(?:^|[^0-9])[£€$?]?\\s?[0-9]{1,6}[.,][0-9]{2}(?![0-9])");
    private static final String[] CHALLENGE_WORDS = {"verify you are human", "i am human", "not a robot", "select all images", "captcha",
            "security verification", "checking your browser", "just a moment", "cloudflare", "unusual activity", "verify your identity", "security check"};
    private static final String[] TWO_FACTOR_WORDS = {"verification code", "security code", "enter the code", "code we sent", "code sent to",
            "sent to your", "two-step", "two step", "two-factor", "authenticator", "one-time code", "one time code"};
    private static final String[] EXPIRED_WORDS = {"logged out", "session expired", "session has expired", "log in again", "login again"};

    private SessionMachine() {}

    private static String norm(String s) { return " " + OcrText.normalize(s).toLowerCase(Locale.US).replaceAll("\\s+", " ").trim() + " "; }

    private static boolean any(String haystack, String... needles) {
        for (String n : needles) if (haystack.contains(n)) return true;
        return false;
    }

    /**
     * `lines` may be OCR words or whole rows: tokens are joined with single spaces, so a phrase split across
     * words ("Log" "In") and a merged row ("bet365 Join Log In") read the same. The balance rule needs the
     * word's own position (the adapter passes words): a row merged from x=19 would hide a right-hand balance.
     */
    static Observation observe(List<Line> lines) {
        StringBuilder all = new StringBuilder(" "), headWords = new StringBuilder(" ");
        boolean balance = false;
        for (Line l : lines) {
            String t = norm(l.text).trim();
            if (t.isEmpty()) continue;
            all.append(t).append(' ');
            if (l.top <= HEADER_WORDS_BOTTOM) headWords.append(t).append(' ');
            if (l.top >= HEADER_TOP && l.top <= HEADER_BOTTOM && l.left >= HEADER_RIGHT_FROM && BALANCE.matcher(" " + t).find()) balance = true;
        }
        String page = all.toString(), head = headWords.toString();
        if (any(page, CHALLENGE_WORDS)) return Observation.CHALLENGE;
        if (any(page, TWO_FACTOR_WORDS)) return Observation.TWO_FACTOR;
        if (page.contains(" password ") && any(page, " log in ", " login ", "keep me logged")) return Observation.LOGIN_FORM;
        if (any(page, EXPIRED_WORDS)) return Observation.EXPIRED;
        boolean headerLogIn = any(head, " log in ", " login ", " join now ");
        boolean account = balance || any(head, " log out ", " logout ", " my account ", " deposit ");
        if (account && !headerLogIn) return Observation.ACCOUNT;
        if (headerLogIn || head.contains(" join ")) return Observation.LOGGED_OUT;
        return Observation.UNKNOWN;
    }

    /**
     * Next state. `state` null = nothing observed yet. `attempts` = login submissions already made. UNKNOWN
     * changes nothing (the caller re-observes, bounded); terminal states never change.
     */
    static State next(State state, Observation seen, boolean credentials, int attempts) {
        if (seen == Observation.CHALLENGE) return State.BOT_CHECK_OR_CHALLENGE;
        if (seen == Observation.TWO_FACTOR) return State.TWO_FACTOR_REQUIRED;
        if (seen == Observation.UNKNOWN) return state;
        boolean account = seen == Observation.ACCOUNT;
        if (state == null) return account ? State.AUTHENTICATED : State.LOGIN_REQUIRED;
        switch (state) {
            case AUTHENTICATED:
            case AUTHENTICATED_RECOVERED:
                return account ? state : State.LOGIN_REQUIRED;
            case LOGIN_REQUIRED:
                if (account) return State.AUTHENTICATED;
                return credentials && attempts < MAX_LOGIN_ATTEMPTS ? State.LOGIN_IN_PROGRESS : State.LOGIN_FAILED;
            case LOGIN_IN_PROGRESS:
                if (account) return State.AUTHENTICATED_RECOVERED;
                return attempts < MAX_LOGIN_ATTEMPTS ? State.LOGIN_IN_PROGRESS : State.LOGIN_FAILED;
            default:
                return state;   // TWO_FACTOR_REQUIRED, BOT_CHECK_OR_CHALLENGE, LOGIN_FAILED are terminal
        }
    }

    static boolean terminal(State s) {
        return s == State.AUTHENTICATED || s == State.AUTHENTICATED_RECOVERED || s == State.TWO_FACTOR_REQUIRED
                || s == State.BOT_CHECK_OR_CHALLENGE || s == State.LOGIN_FAILED;
    }

    /** The backend session contract's wire state (docs/SESSION_CONTRACT.md) for a machine state. */
    static String wireState(State s) {
        if (s == null) return "UNKNOWN";
        switch (s) {
            case AUTHENTICATED: case AUTHENTICATED_RECOVERED: return "AUTHENTICATED";
            case LOGIN_IN_PROGRESS: return "AUTHENTICATING";
            case TWO_FACTOR_REQUIRED: case BOT_CHECK_OR_CHALLENGE: return "RESTRICTED";
            default: return "LOGGED_OUT";   // LOGIN_REQUIRED, LOGIN_FAILED
        }
    }

    /** Workflow failure stage for a terminal non-authenticated state, or null. */
    static String stage(State s) {
        if (s == State.LOGIN_FAILED) return "LOGIN_FAILED";
        if (s == State.TWO_FACTOR_REQUIRED) return "TWO_FACTOR_REQUIRED";
        if (s == State.BOT_CHECK_OR_CHALLENGE) return "BOT_CHECK";
        return null;
    }

    /** Idle-probe classification (health `session.state`) straight from an observation. */
    static String probeState(Observation seen) {
        switch (seen) {
            case ACCOUNT: return "AUTHENTICATED";
            case LOGIN_FORM: case LOGGED_OUT: return "LOGGED_OUT";
            case EXPIRED: return "EXPIRED";
            case TWO_FACTOR: case CHALLENGE: return "RESTRICTED";
            default: return "UNKNOWN";
        }
    }
}
