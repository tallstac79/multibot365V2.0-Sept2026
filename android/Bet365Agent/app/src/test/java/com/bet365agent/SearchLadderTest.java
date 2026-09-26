package com.bet365agent;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import org.junit.Test;

/** Search discovery ladder on real naming cases captured 26 Sep 2026 (evidence/timezone-probe, automatic-approval). */
public class SearchLadderTest {
    private static final Map<String, String> LANDSTEDE = Collections.singletonMap("landstede hammers", "Landstede Zwolle");

    @Test public void rawFeedNamesFirstThenTheBookmakersOwnName() {
        // Bet365 lists "Landstede Zwolle"; the feed says "Landstede Hammers" (search for the feed name returned casino-only results)
        LinkedHashMap<String, String> ladder = Bet365LiveAdapter.searchLadder("Landstede Hammers", "Antwerp Giants", LANDSTEDE);
        assertEquals("Landstede Hammers Antwerp Giants", new ArrayList<>(ladder.keySet()).get(0));
        assertEquals("feed", ladder.get("Landstede Hammers Antwerp Giants"));
        assertEquals("Landstede Zwolle Antwerp Giants", new ArrayList<>(ladder.keySet()).get(1));
        assertEquals("bookmaker_alias", ladder.get("Landstede Zwolle Antwerp Giants"));
        assertEquals("bookmaker_alias", ladder.get("Landstede Zwolle"));
        assertTrue(ladder.size() <= 8);
    }

    @Test public void withoutAnApprovedNameTheLadderIsFeedAndClubPrefixFormsOnly() {
        LinkedHashMap<String, String> ladder = Bet365LiveAdapter.searchLadder("Landstede Hammers", "Antwerp Giants", Collections.emptyMap());
        assertFalse(ladder.containsValue("bookmaker_alias"));
        assertEquals("Landstede Hammers Antwerp Giants", new ArrayList<>(ladder.keySet()).get(0));
        LinkedHashMap<String, String> prefixed = Bet365LiveAdapter.searchLadder("BC Beroe", "Ferrol", Collections.emptyMap());
        assertEquals("club_prefix", prefixed.get("Beroe Ferrol"));
        assertEquals("feed", prefixed.get("BC Beroe Ferrol"));
    }

    @Test public void aliasesAreLookedUpByTheBackendsKeyAndNeverEchoTheFeedName() {
        assertEquals("Landstede Zwolle", Bet365LiveAdapter.bookmakerName("Landstede  Hammers", LANDSTEDE));
        assertNull(Bet365LiveAdapter.bookmakerName("Antwerp Giants", LANDSTEDE));
        assertNull(Bet365LiveAdapter.bookmakerName("Antwerp Giants", Collections.singletonMap("antwerp giants", "antwerp giants")));
        assertNull(Bet365LiveAdapter.bookmakerName("Antwerp Giants", null));
    }
}
