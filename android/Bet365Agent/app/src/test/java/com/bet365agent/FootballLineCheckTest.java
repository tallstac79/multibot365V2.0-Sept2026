package com.bet365agent;

import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import org.junit.Test;

/** The exact live reads of 27 Sep 2026 (phone football_market_reads, Santa Cruz RJ v Cardoso Moreira). */
public class FootballLineCheckTest {
    // on-ee666445bd94332e47037d46: popular + asia views (the asia_scroll and last-resort scroll frames were empty)
    static final List<String[]> SANTA_CRUZ = Arrays.asList(
            FootballLineCheck.quote("MONEYLINE", "HOME", "NONE", "2.30"), FootballLineCheck.quote("MONEYLINE", "DRAW", "NONE", "3.50"),
            FootballLineCheck.quote("MONEYLINE", "AWAY", "NONE", "2.62"), FootballLineCheck.quote("TOTAL", "OVER", "2.5", "1.90"),
            FootballLineCheck.quote("TOTAL", "UNDER", "2.5", "1.90"), FootballLineCheck.quote("SPREAD", "HOME", "0.0", "1.750"),
            FootballLineCheck.quote("SPREAD", "AWAY", "0.0", "2.050"), FootballLineCheck.quote("TOTAL", "OVER", "2.5", "1.900"),
            FootballLineCheck.quote("TOTAL", "UNDER", "2.5", "1.900"));

    @Test public void alertAwayPlusHalfIsAGenuineLineRefusal() {
        String r = FootballLineCheck.lineRefusal(SANTA_CRUZ, "SPREAD", "AWAY", "+0.5", "0.25");
        assertTrue(r, r != null && r.contains("AWAY shows 0.0 @ 2.050") && r.contains("no line within 0.25 of the alert line"));
    }

    @Test public void theNextAlertAtPlusQuarterIsWithinAllowance() {
        // on-728c2c3d06a66870420086fa, same page 15 s later: alert AWAY +0.25 -> 0.0 is exactly the 0.25 allowance (held PASS)
        assertNull(FootballLineCheck.lineRefusal(SANTA_CRUZ, "SPREAD", "AWAY", "+0.25", "0.25"));
    }

    @Test public void nothingReadIsNotALineReason() {
        assertNull(FootballLineCheck.lineRefusal(Collections.emptyList(), "SPREAD", "AWAY", "+0.5", "0.25"));
        assertNull(FootballLineCheck.lineRefusal(SANTA_CRUZ, "SPREAD", "AWAY", "", "0.25"));
        assertNull(FootballLineCheck.lineRefusal(SANTA_CRUZ, "MONEYLINE", "AWAY", "NONE", "0.25"));
        // a line 0.5 away is refused in either direction since 28 Sep 2026 (two-sided football band), a 0.25 move is not
        assertNotNull(FootballLineCheck.lineRefusal(SANTA_CRUZ, "SPREAD", "HOME", "-0.5", "0.25"));
        assertNull(FootballLineCheck.lineRefusal(SANTA_CRUZ, "SPREAD", "HOME", "-0.25", "0.25"));
    }
}
