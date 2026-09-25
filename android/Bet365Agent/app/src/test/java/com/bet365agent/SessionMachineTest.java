package com.bet365agent;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import com.bet365agent.SessionMachine.Line;
import com.bet365agent.SessionMachine.Observation;
import com.bet365agent.SessionMachine.State;
import java.util.Arrays;
import java.util.List;
import org.junit.Test;

/** Every session state transition, on OCR lines shaped like the real Bet365 screens (2026-09-25 frames). */
public class SessionMachineTest {
    private static Line l(String text, int top, int left) { return new Line(text, top, left); }

    // Real logged-in header as the hybrid engine reads it: "bet365 ?3.69 +)" (the pound sign misread), y=176
    static final List<Line> HOME_LOGGED_IN = Arrays.asList(l("01:09", 14, 56), l("bet365.com/#/HO/", 85, 153),
            l("bet365", 176, 19), l("?3.69 +)", 178, 520), l("Popular Bet Builder", 327, 35), l("Home All Sports In-Play My Bets Casino", 1470, 40));
    static final List<Line> HOME_LOGGED_OUT = Arrays.asList(l("01:09", 14, 56), l("bet365.com/#/HO/", 85, 153),
            l("bet365 Join Log In", 176, 19), l("Sports", 327, 35), l("Home All Sports In-Play", 1470, 40));
    static final List<Line> LOGIN_FORM = Arrays.asList(l("bet365.com/#/HO/", 85, 153), l("Log In", 300, 300),
            l("Username or email", 420, 40), l("Password", 520, 40), l("Keep me logged in", 640, 40), l("Log In", 760, 300), l("Forgot password?", 830, 40));
    static final List<Line> TWO_FACTOR = Arrays.asList(l("bet365", 176, 19), l("Enter the verification code we sent to your mobile", 400, 40), l("Continue", 700, 300));
    static final List<Line> CHALLENGE = Arrays.asList(l("bet365", 176, 19), l("Verify you are human", 500, 100), l("I am human", 620, 200));
    static final List<Line> EXPIRED = Arrays.asList(l("bet365", 176, 19), l("You have been logged out", 500, 100), l("Log In", 700, 300));
    static final List<Line> SEARCH_OVERLAY = Arrays.asList(l("bet365.com/#/AX/", 85, 153), l("Search bet365...", 177, 87), l("RECENT SEARCHES", 276, 20), l("Kyoto Hannaryz >", 852, 38));

    @Test public void screensAreRecognised() {
        assertEquals(Observation.ACCOUNT, SessionMachine.observe(HOME_LOGGED_IN));
        assertEquals(Observation.LOGGED_OUT, SessionMachine.observe(HOME_LOGGED_OUT));
        assertEquals(Observation.LOGIN_FORM, SessionMachine.observe(LOGIN_FORM));
        assertEquals(Observation.TWO_FACTOR, SessionMachine.observe(TWO_FACTOR));
        assertEquals(Observation.CHALLENGE, SessionMachine.observe(CHALLENGE));
        assertEquals(Observation.EXPIRED, SessionMachine.observe(EXPIRED));
        assertEquals(Observation.UNKNOWN, SessionMachine.observe(SEARCH_OVERLAY));   // no header: nothing is assumed
    }

    @Test public void realHomeHeaderWordsFromTheSessionFrame() {
        // s003_session.txt, 2026-09-25 (hybrid engine): "bet365" [19,176], "?3.69" [537,183], "Search" [113,279]
        assertEquals(Observation.ACCOUNT, SessionMachine.observe(Arrays.asList(l("bet365", 176, 19), l("?3.69", 183, 537), l("Search", 279, 113))));
        // phrases split into words still read as phrases; a logged-out header as words
        assertEquals(Observation.LOGGED_OUT, SessionMachine.observe(Arrays.asList(l("bet365", 176, 19), l("Join", 178, 480), l("Log", 178, 560), l("In", 178, 600))));
        assertEquals(Observation.TWO_FACTOR, SessionMachine.observe(Arrays.asList(l("Enter", 400, 40), l("the", 400, 100), l("verification", 400, 140), l("code", 400, 260))));
    }

    @Test public void accountEvidenceComesFromTheHeaderNotTheUrlOrOdds() {
        // a price in the page body is not a balance; a balance-like number in the status bar is ignored
        assertEquals(Observation.UNKNOWN, SessionMachine.observe(Arrays.asList(l("bet365.com/#/AC/B18", 85, 153), l("bet365", 176, 19), l("1.83", 828, 457))));
        assertEquals(Observation.UNKNOWN, SessionMachine.observe(Arrays.asList(l("12.30", 14, 56), l("bet365", 176, 19))));
        // Deposit / My Account / Log Out in the header count; the same words in the footer do not
        assertEquals(Observation.ACCOUNT, SessionMachine.observe(Arrays.asList(l("bet365 My Account", 176, 19))));
        assertEquals(Observation.UNKNOWN, SessionMachine.observe(Arrays.asList(l("bet365", 176, 19), l("Deposits Withdrawals", 1300, 40))));
        // a header that shows both a balance and Log In is contradictory: never AUTHENTICATED
        assertEquals(Observation.LOGGED_OUT, SessionMachine.observe(Arrays.asList(l("bet365 Log In", 176, 19), l("?3.69", 178, 520))));
    }

    @Test public void alreadyAuthenticated() {
        assertEquals(State.AUTHENTICATED, SessionMachine.next(null, Observation.ACCOUNT, true, 0));
        assertEquals(State.AUTHENTICATED, SessionMachine.next(null, Observation.ACCOUNT, false, 0));   // no credentials needed
        assertTrue(SessionMachine.terminal(State.AUTHENTICATED));
        assertEquals("AUTHENTICATED", SessionMachine.wireState(State.AUTHENTICATED));
        assertNull(SessionMachine.stage(State.AUTHENTICATED));
    }

    @Test public void loggedOutWithCredentialsLogsInThenRecovers() {
        State s = SessionMachine.next(null, Observation.LOGGED_OUT, true, 0);
        assertEquals(State.LOGIN_REQUIRED, s);
        s = SessionMachine.next(s, Observation.LOGGED_OUT, true, 0);
        assertEquals(State.LOGIN_IN_PROGRESS, s);                         // the adapter submits the form (attempt 1)
        assertEquals("AUTHENTICATING", SessionMachine.wireState(s));
        assertEquals(State.LOGIN_IN_PROGRESS, SessionMachine.next(s, Observation.UNKNOWN, true, 1));   // redirect still loading: re-look
        s = SessionMachine.next(s, Observation.ACCOUNT, true, 1);
        assertEquals(State.AUTHENTICATED_RECOVERED, s);
        assertTrue(SessionMachine.terminal(s));
        assertEquals("AUTHENTICATED", SessionMachine.wireState(s));
    }

    @Test public void loggedOutWithoutCredentialsFailsClosed() {
        State s = SessionMachine.next(State.LOGIN_REQUIRED, Observation.LOGGED_OUT, false, 0);
        assertEquals(State.LOGIN_FAILED, s);
        assertEquals("LOGIN_FAILED", SessionMachine.stage(s));
        assertEquals("LOGGED_OUT", SessionMachine.wireState(s));
        assertEquals(State.LOGIN_FAILED, SessionMachine.next(State.LOGIN_REQUIRED, Observation.LOGIN_FORM, false, 0));
        assertEquals(State.LOGIN_FAILED, SessionMachine.next(State.LOGIN_REQUIRED, Observation.EXPIRED, false, 0));
    }

    @Test public void loginIsAttemptedAtMostTwice() {
        State s = State.LOGIN_IN_PROGRESS;
        assertEquals(State.LOGIN_IN_PROGRESS, SessionMachine.next(s, Observation.LOGIN_FORM, true, 1));   // one retry
        assertEquals(State.LOGIN_FAILED, SessionMachine.next(s, Observation.LOGIN_FORM, true, 2));        // then stop
        assertEquals(State.LOGIN_FAILED, SessionMachine.next(State.LOGIN_REQUIRED, Observation.LOGGED_OUT, true, 2));
        assertEquals(State.LOGIN_FAILED, SessionMachine.next(State.LOGIN_FAILED, Observation.LOGGED_OUT, true, 0));   // terminal stays
    }

    @Test public void twoFactorAndChallengesStopForTheOperator() {
        for (State from : new State[] {null, State.LOGIN_REQUIRED, State.LOGIN_IN_PROGRESS, State.AUTHENTICATED}) {
            assertEquals(State.TWO_FACTOR_REQUIRED, SessionMachine.next(from, Observation.TWO_FACTOR, true, 0));
            assertEquals(State.BOT_CHECK_OR_CHALLENGE, SessionMachine.next(from, Observation.CHALLENGE, true, 0));
        }
        assertTrue(SessionMachine.terminal(State.TWO_FACTOR_REQUIRED));
        assertTrue(SessionMachine.terminal(State.BOT_CHECK_OR_CHALLENGE));
        assertEquals("TWO_FACTOR_REQUIRED", SessionMachine.stage(State.TWO_FACTOR_REQUIRED));
        assertEquals("BOT_CHECK", SessionMachine.stage(State.BOT_CHECK_OR_CHALLENGE));
        assertEquals("RESTRICTED", SessionMachine.wireState(State.TWO_FACTOR_REQUIRED));
        assertEquals("RESTRICTED", SessionMachine.wireState(State.BOT_CHECK_OR_CHALLENGE));
        // even with credentials and attempts left, a challenge is never "logged in"
        assertEquals(State.TWO_FACTOR_REQUIRED, SessionMachine.next(State.TWO_FACTOR_REQUIRED, Observation.ACCOUNT, true, 0));
    }

    @Test public void expiryDuringAnAuthenticatedSessionRequiresLoginAgain() {
        assertEquals(State.LOGIN_REQUIRED, SessionMachine.next(State.AUTHENTICATED, Observation.EXPIRED, true, 0));
        assertEquals(State.LOGIN_REQUIRED, SessionMachine.next(State.AUTHENTICATED_RECOVERED, Observation.LOGGED_OUT, true, 0));
        assertEquals(State.AUTHENTICATED, SessionMachine.next(State.AUTHENTICATED, Observation.ACCOUNT, true, 0));
    }

    @Test public void unknownScreensDecideNothing() {
        assertNull(SessionMachine.next(null, Observation.UNKNOWN, true, 0));
        assertEquals(State.LOGIN_REQUIRED, SessionMachine.next(State.LOGIN_REQUIRED, Observation.UNKNOWN, true, 0));
        assertFalse(SessionMachine.terminal(State.LOGIN_REQUIRED));
        assertFalse(SessionMachine.terminal(State.LOGIN_IN_PROGRESS));
    }

    @Test public void probeStatesMatchTheBackendContract() {
        assertEquals("AUTHENTICATED", SessionMachine.probeState(Observation.ACCOUNT));
        assertEquals("LOGGED_OUT", SessionMachine.probeState(Observation.LOGGED_OUT));
        assertEquals("LOGGED_OUT", SessionMachine.probeState(Observation.LOGIN_FORM));
        assertEquals("EXPIRED", SessionMachine.probeState(Observation.EXPIRED));
        assertEquals("RESTRICTED", SessionMachine.probeState(Observation.TWO_FACTOR));
        assertEquals("RESTRICTED", SessionMachine.probeState(Observation.CHALLENGE));
        assertEquals("UNKNOWN", SessionMachine.probeState(Observation.UNKNOWN));
    }
}
