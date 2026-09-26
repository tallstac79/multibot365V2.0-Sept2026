package com.bet365agent;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import java.util.Arrays;
import java.util.List;
import org.junit.Test;

/** Remembered-account login form, real OCR 2026-09-26 19:02 after a phone reboot (evidence/local-permission). */
public class LoginAccountTest {
    private static GameLinesParser.Word w(String t, int l, int top, int r, int b) { return new GameLinesParser.Word(t, l, top, r, b); }

    /** The form as the hybrid OCR read it: the remembered account value, the Password placeholder, no clear "X" word
     *  although the icon was on screen at x 575-600 (login_form.png). */
    private static List<GameLinesParser.Word> FORM_WITHOUT_X = Arrays.asList(
            w("bet365", 19, 176, 169, 208), w("Join", 536, 183, 574, 198), w("Log", 625, 181, 656, 202), w("In", 664, 180, 678, 200),
            w("remembered_user", 110, 305, 219, 330), w("Password", 110, 422, 230, 443), w("Keep", 159, 527, 211, 550),
            w("Forgot", 165, 773, 233, 796), w("Username", 294, 773, 403, 796));

    @Test public void rememberedValueWithoutAnOcrClearGlyphIsUnknownButClearableByGeometry() {
        // inspect() never infers an account from an unread glyph (UNKNOWN); the login flow then clears by row geometry
        assertEquals(LoginAccount.State.UNKNOWN, LoginAccount.inspect(FORM_WITHOUT_X, "operator@example.com"));
        assertEquals(LoginAccount.State.MATCH, LoginAccount.inspect(FORM_WITHOUT_X, "remembered_user"));
        assertNull(LoginAccount.clearControl(FORM_WITHOUT_X));
        assertNotNull(LoginAccount.clearControlByGeometry(FORM_WITHOUT_X));
    }

    @Test public void clearControlFallsBackToTheFieldRowGeometry() {
        GameLinesParser.Word x = LoginAccount.clearControlByGeometry(FORM_WITHOUT_X);
        assertNotNull(x);
        // the icon column observed on 25 Sep ([577,308][600,330]) and 26 Sep (about x 575-600), on the value's own row
        assertTrue(x.left >= 560 && x.right <= 615);
        assertTrue(x.top <= 305 && x.bottom >= 330);
        assertEquals(LoginAccount.State.EMPTY, LoginAccount.inspect(Arrays.asList(w("Username or email address", 110, 305, 480, 330), w("Password", 110, 422, 230, 443)), "operator@example.com"));
    }

    @Test public void geometryFallbackNeedsAValueRowAndNeverAPlaceholder() {
        assertNull(LoginAccount.clearControlByGeometry(Arrays.asList(w("Username or email address", 110, 305, 480, 330), w("Password", 110, 422, 230, 443))));
        assertNull(LoginAccount.clearControlByGeometry(Arrays.asList(w("Password", 110, 422, 230, 443))));
    }

    @Test public void anOcrClearGlyphStillWinsWhenPresent() {
        List<GameLinesParser.Word> withX = Arrays.asList(w("remembered_user", 110, 305, 219, 330), w("X", 577, 308, 600, 330), w("Password", 110, 422, 230, 443));
        assertEquals(577, LoginAccount.clearControl(withX).left);
        assertEquals(LoginAccount.State.DIFFERENT, LoginAccount.inspect(withX, "operator@example.com"));
    }
}
