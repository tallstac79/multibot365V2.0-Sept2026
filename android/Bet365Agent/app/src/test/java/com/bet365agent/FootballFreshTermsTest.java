package com.bet365agent;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import org.junit.Test;

/**
 * Live regression, 28 Sep 2026 06:31Z on-f4d9aa2d1225697966263e9e (Jiangxi Lushan U20 v Qingdao Hainiu U20, Asian Handicap
 * HOME -0.25, alert 1.85, minimum 1.77 = 10 % net payout, line allowance 0.25 - the instruction's own values). Discovery read
 * HOME -0.25 @1.850; the pre-selection re-read two seconds later showed 1.800 and the old exact-price check refused it as
 * PRICE_CHANGED although 1.800 >= 1.77. The fresh quote must be judged by the tolerances, nothing else.
 */
public class FootballFreshTermsTest {
    static final String HOME = "Jiangxi Lushan U20", AWAY = "Qingdao Hainiu U20";
    static final String MINIMUM = "1.77", ALLOWANCE = "0.25", ALERT_LINE = "-0.25";

    static List<String[]> quotes(String frame) throws Exception {
        List<String[]> out = new ArrayList<>();
        for (FootballMarkets.Cell c : FootballMarkets.parse(StakePadTest.load(frame), HOME, AWAY).cells)
            out.add(FootballLineCheck.quote(c.market, c.side, c.line, c.price));
        return out;
    }

    @Test public void theRealFramesReadWhatThePhoneReported() throws Exception {
        List<String[]> discovery = quotes("football_jiangxi_discovery_20260928.txt");
        List<String[]> fresh = quotes("football_jiangxi_preselect_20260928.txt");
        String[] before = discovery.get(FootballLineCheck.pick(discovery, "SPREAD", "HOME", "-0.25", ALERT_LINE, ALLOWANCE));
        String[] now = fresh.get(FootballLineCheck.pick(fresh, "SPREAD", "HOME", "-0.25", ALERT_LINE, ALLOWANCE));
        assertEquals(Arrays.asList("SPREAD", "HOME", "-0.25", "1.850"), Arrays.asList(before));
        assertEquals(Arrays.asList("SPREAD", "HOME", "-0.25", "1.800"), Arrays.asList(now));
    }

    @Test public void theFreshQuoteInsideTheTolerancesIsAccepted() throws Exception {
        List<String[]> fresh = quotes("football_jiangxi_preselect_20260928.txt");
        String[] q = fresh.get(FootballLineCheck.pick(fresh, "SPREAD", "HOME", "-0.25", ALERT_LINE, ALLOWANCE));
        assertNull(FootballLineCheck.freshTerms(q[0], q[1], ALERT_LINE, q[2], q[3], ALLOWANCE, MINIMUM));   // 1.800 >= 1.77
    }

    @Test public void onlyTermsOutsideTheTolerancesAreRefused() {
        assertNull(FootballLineCheck.freshTerms("SPREAD", "HOME", ALERT_LINE, "-0.25", "1.900", ALLOWANCE, MINIMUM));   // better price
        assertNull(FootballLineCheck.freshTerms("SPREAD", "HOME", ALERT_LINE, "-0.25", "1.77", ALLOWANCE, MINIMUM));    // at the floor
        String[] low = FootballLineCheck.freshTerms("SPREAD", "HOME", ALERT_LINE, "-0.25", "1.76", ALLOWANCE, MINIMUM);
        assertNotNull(low);
        assertEquals("BELOW_MINIMUM", low[0]);
        assertTrue(low[1], low[1].contains("1.76") && low[1].contains("1.77"));
        assertNull(FootballLineCheck.freshTerms("SPREAD", "HOME", ALERT_LINE, "0.0", "1.90", ALLOWANCE, MINIMUM));      // better line
        assertNull(FootballLineCheck.freshTerms("SPREAD", "HOME", ALERT_LINE, "-0.5", "1.90", ALLOWANCE, MINIMUM));     // 0.25 worse: inside
        String[] far = FootballLineCheck.freshTerms("SPREAD", "HOME", ALERT_LINE, "-0.75", "1.90", ALLOWANCE, MINIMUM); // 0.5 worse
        assertNotNull(far);
        assertEquals("LINE_CHANGED", far[0]);
        assertNull(FootballLineCheck.freshTerms("MONEYLINE", "AWAY", "NONE", "", "2.50", ALLOWANCE, "2.35"));
        assertEquals("BELOW_MINIMUM", FootballLineCheck.freshTerms("MONEYLINE", "AWAY", "NONE", "", "2.30", ALLOWANCE, "2.35")[0]);
    }

    @Test public void aReReadKeepsTheSameLineOrOneInsideTheAllowance() {
        List<String[]> moved = Arrays.asList(FootballLineCheck.quote("SPREAD", "HOME", "-0.5", "1.95"), FootballLineCheck.quote("SPREAD", "AWAY", "0.5", "1.85"));
        assertEquals(0, FootballLineCheck.pick(moved, "SPREAD", "HOME", "-0.25", ALERT_LINE, ALLOWANCE));
        List<String[]> tooFar = Arrays.<String[]>asList(FootballLineCheck.quote("SPREAD", "HOME", "-0.75", "2.10"));
        assertEquals(-1, FootballLineCheck.pick(tooFar, "SPREAD", "HOME", "-0.25", ALERT_LINE, ALLOWANCE));
        List<String[]> both = Arrays.asList(FootballLineCheck.quote("SPREAD", "HOME", "-0.5", "1.95"), FootballLineCheck.quote("SPREAD", "HOME", "-0.25", "1.80"));
        assertEquals(1, FootballLineCheck.pick(both, "SPREAD", "HOME", "-0.25", ALERT_LINE, ALLOWANCE));      // the same line first
    }
}
