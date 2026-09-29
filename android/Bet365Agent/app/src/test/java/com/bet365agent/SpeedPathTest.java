package com.bet365agent;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import org.junit.Test;

/**
 * 29 Sep 2026 hot-path speed work: the waiting policies that replaced fixed sleeps (PageReady, OutcomeWatch). They only
 * decide WHEN to look again; identity, line, price, stake and receipt proof are judged by the unchanged checks. Every case
 * uses a real captured frame or real classifier output.
 */
public class SpeedPathTest {
    private static List<String> header(String resource) throws Exception {
        return EventHeader.header(StakePadTest.load(resource));
    }

    // ---------------------------------------------------------------- event page: drawn AND this event's
    private static boolean ready(List<String> h, String[] teams, String home, String away, String want, long waited) {
        return PageReady.eventReady(h, teams, Arrays.asList(home), Arrays.asList(away), want, waited);
    }

    @Test public void aRealAbbreviatedHeaderIsReadyAtOnceWhenTheOpponentAndKickOffAgree() throws Exception {
        List<String> h = header("event_sscr_stags_20260929.txt");           // "SSC-R Stags vs EAC Generals" for the San Sebastian alert
        String[] teams = EventPage.teams(h);
        assertNotNull(teams);
        assertTrue(PageReady.eventReady(h, teams, Arrays.asList("San Sebastian Golden Stags"), Arrays.asList("EAC Generals"), "29 Sep 08:00", 0));
        // the same page, but the alert's kick-off differs: not strong evidence, and a shared word alone waits
        assertFalse(PageReady.eventReady(h, teams, Arrays.asList("San Sebastian Golden Stags"), Arrays.asList("EAC Generals"), "29 Sep 10:00", 1_000));
    }

    @Test public void theWomensFriendlyHeaderIsReadyAtOnce() throws Exception {
        List<String> h = header("event_fiji_nc_20260929.txt");               // "Fiji (W) v New Caledonia (W)": the (W) is judged later, by identity
        assertTrue(ready(h, EventPage.teams(h), "Fiji", "New Caledonia", "29 Sep 08:00", 0));
    }

    @Test public void thePreviousPageStillOnScreenIsNeverReady() throws Exception {
        List<String> h = header("event_fiji_nc_20260929.txt");               // the last event's page while the next one loads
        for (long waited : new long[] {0, 1_000, 4_000, 8_000})
            assertFalse("waited " + waited, ready(h, EventPage.teams(h), "Mohun Bagan", "NorthEast United", "29 Sep 10:00", waited));
    }

    @Test public void aStalePageSharingACommonWordWaitsOutThePageSwap() throws Exception {
        List<String> h = header("event_fiji_nc_20260929.txt");               // still on screen; the alert is Fiji Warriors v Samoa at 11:00
        assertFalse(ready(h, EventPage.teams(h), "Fiji Warriors", "Samoa", "29 Sep 11:00", 0));
        assertFalse(ready(h, EventPage.teams(h), "Fiji Warriors", "Samoa", "29 Sep 11:00", 3_000));   // the new page has had time to draw by 5 s
        assertTrue(ready(h, EventPage.teams(h), "Fiji Warriors", "Samoa", "29 Sep 11:00", PageReady.LOOSE_AFTER_MS));   // then the identity check judges it
    }

    @Test public void aKickOffMatchAloneReadiesAPageOnlyAfterTheSwapWindow() throws Exception {
        List<String> h = header("event_fiji_nc_20260929.txt");
        String[] teams = EventPage.teams(h);
        assertFalse(ready(h, teams, "Viti Levu XI", "Kanak Selection", "29 Sep 08:00", 1_000));   // same 08:00, names share nothing
        assertTrue(ready(h, teams, "Viti Levu XI", "Kanak Selection", "29 Sep 08:00", PageReady.LOOSE_AFTER_MS));
        assertFalse(ready(h, teams, "Viti Levu XI", "Kanak Selection", "29 Sep 10:00", 8_000));
    }

    @Test public void withoutAShownKickOffBothTeamsMustBeIdentified() {
        List<String> h = Arrays.asList("Some League", "Fiji v New Caledonia");
        String[] teams = EventPage.teams(h);
        assertNotNull(teams);
        assertTrue(ready(h, teams, "Fiji", "New Caledonia", "29 Sep 08:00", 0));
        assertFalse(ready(h, teams, "Fiji", "Samoa", "29 Sep 08:00", 1_000));                     // one team is not enough without a kick-off
        assertTrue(ready(h, teams, "Fiji", "Samoa", "29 Sep 08:00", PageReady.LOOSE_AFTER_MS));
    }

    @Test public void aPageWithoutAHeaderIsNeverReady() throws Exception {
        List<String> home = header("home_ready_20260929.txt");
        assertNull(EventPage.teams(home));
        assertFalse(ready(home, EventPage.teams(home), "Fiji", "New Caledonia", "29 Sep 08:00", 60_000));
    }

    // ---------------------------------------------------------------- football tabs: the tab's OWN section is drawn
    private static FootballMarkets.Result parse(String resource, String home, String away) throws Exception {
        return FootballMarkets.parse(StakePadTest.load(resource), home, away);
    }

    @Test public void popularTabReadyOnlyWithTheItsOwnSectionAndAfterASettle() throws Exception {
        FootballMarkets.Result popular = parse("football_wenzhou_popular_20260928.txt", "Wenzhou Yincai U20", "Qingdao Red Lions U20");
        assertTrue(popular.goalsOverUnder || popular.fullTimeResult);
        assertFalse(popular.asianHandicap);
        assertFalse(PageReady.footballTabReady("popular", popular, 100));     // too soon: may still be the previous tab
        assertTrue(PageReady.footballTabReady("popular", popular, 300));
        assertFalse(PageReady.footballTabReady("asia", popular, 3000));        // the Popular frame is never the Asian Lines tab
    }

    @Test public void asianLinesTabIsReadyAsSoonAsItsHandicapRowsAreOnScreen() throws Exception {
        FootballMarkets.Result asia = parse("football_jiangxi_discovery_20260928.txt", "Jiangxi Lushan U20", "Qingdao Hainiu U20");
        assertTrue(asia.asianHandicap);
        assertTrue(PageReady.footballTabReady("asia", asia, 0));
        assertFalse(PageReady.footballTabReady("popular", asia, 3000));        // a stale Asian Lines frame is not the Popular tab
    }

    @Test public void anEmptyFrameIsNeverReady() {
        FootballMarkets.Result empty = FootballMarkets.parse(Collections.<GameLinesParser.Word>emptyList(), "A", "B");
        for (String tab : new String[] {"asia", "goals", "popular", "other"}) assertFalse(tab, PageReady.footballTabReady(tab, empty, 5000));
    }

    // ---------------------------------------------------------------- outcome watch
    private static PlacementClassifier.Result classify(String... lines) {
        return PlacementClassifier.classify(Arrays.asList(lines), false);
    }

    @Test public void framesAreDenseWhileAReceiptIsExpected() {
        assertEquals(120, OutcomeWatch.gapMs(0));
        assertEquals(120, OutcomeWatch.gapMs(5_999));
        assertEquals(400, OutcomeWatch.gapMs(6_000));
        assertEquals(1_000, OutcomeWatch.gapMs(10_000));
        assertTrue(OutcomeWatch.BUDGET_MS >= 12_000);                          // never a shorter watch than the old 5-frame schedule
    }

    @Test public void aCompleteReceiptEndsTheWatchAtOnce() {
        PlacementClassifier.Result r = classify("Bet Placed", "Bet Ref BT1234567890W", "Stake  To Return", "£0.10 £0.19");
        assertTrue(r.definitive);
        assertEquals("PLACED", r.outcome);
        assertFalse(OutcomeWatch.thinReceipt(r));
        assertFalse(OutcomeWatch.lookAgain(r, 2_500, 0));
    }

    @Test public void aBannerWithoutItsProofIsLookedAtAgainButOnlyBoundedly() {
        PlacementClassifier.Result thin = classify("Bet Placed");                // banner drawn, reference and terms not yet
        assertTrue(thin.definitive);
        assertTrue(OutcomeWatch.thinReceipt(thin));
        assertTrue(OutcomeWatch.lookAgain(thin, 900, 0));
        assertTrue(OutcomeWatch.lookAgain(thin, 1_500, OutcomeWatch.RECEIPT_EXTRA_LOOKS - 1));
        assertFalse(OutcomeWatch.lookAgain(thin, 2_000, OutcomeWatch.RECEIPT_EXTRA_LOOKS));   // the old code would have taken it at once
    }

    @Test public void noOutcomeYetKeepsWatchingUntilTheBudgetThenStops() {
        PlacementClassifier.Result pending = PlacementClassifier.classify(Arrays.asList("Stake", "Place Bet"), true);
        assertFalse(pending.definitive);
        assertTrue(OutcomeWatch.lookAgain(pending, 700, 0));
        assertTrue(OutcomeWatch.lookAgain(pending, OutcomeWatch.BUDGET_MS - 1, 0));
        assertFalse(OutcomeWatch.lookAgain(pending, OutcomeWatch.BUDGET_MS, 0));   // caller then reports PLACEMENT_UNKNOWN, never re-tapping
    }

    @Test public void aDefinitiveRefusalStopsTheWatchImmediately() {
        for (PlacementClassifier.Result r : Arrays.asList(classify("The price of your selection changed", "Accept Change and Place Bet"),
                classify("Your bet has been rejected"), classify("Selection suspended"))) {
            assertTrue(r.definitive);
            assertFalse(r.outcome, OutcomeWatch.lookAgain(r, 500, 0));
        }
    }
}
