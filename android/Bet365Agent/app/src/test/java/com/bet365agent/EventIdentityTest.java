package com.bet365agent;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.util.Collections;
import java.util.HashMap;
import java.util.Map;
import org.junit.Test;

/** Resolver unit tests, including the B10 false-positive guard. */
public class EventIdentityTest {
    private static final Map<String, String> NO_ALIASES = Collections.emptyMap();

    private static EventIdentity.Result resolve(String fh, String fa, String fko, String ph, String pa, String pko, boolean anchored) {
        return EventIdentity.resolve(new EventIdentity.Event("basketball", fh, fa, fko, null, false),
                new EventIdentity.Event("basketball", ph, pa, pko, null, anchored), NO_ALIASES);
    }

    @Test public void normalisationLayers() {
        assertEquals("hiroshima dragonflies", EventIdentity.normalise("Hiroshima Dragonﬂies"));
        assertEquals("besancon", EventIdentity.canonicalTokens(EventIdentity.normalise("Besançon AC")));
        assertEquals("berck du fliers rang", EventIdentity.canonicalTokens(EventIdentity.normalise("Berck/Rang du Fliers")));
        assertEquals("[women]", EventIdentity.markers(EventIdentity.normalise("Beroe (W)")).toString());
        assertEquals("[u21]", EventIdentity.markers(EventIdentity.normalise("Spain U21")).toString());
        assertEquals("[reserve]", EventIdentity.markers(EventIdentity.normalise("Real Madrid B")).toString());
    }

    @Test public void teamLevels() {
        assertEquals(EventIdentity.Level.EXACT, EventIdentity.matchSide("Hiroshima Dragonflies", "Hiroshima Dragonﬂies", NO_ALIASES).level);
        assertEquals(EventIdentity.Level.CANONICAL, EventIdentity.matchSide("Besancon", "Besancon AC", NO_ALIASES).level);
        assertEquals(EventIdentity.Level.EXACT, EventIdentity.matchSide("Val De Seine", "Val de Seine", NO_ALIASES).level);       // case only
        assertEquals(EventIdentity.Level.ALIAS, EventIdentity.matchSide("Shiga Lake Stars", "Shiga Lakes", NO_ALIASES).level);
        assertEquals(EventIdentity.Level.ALIAS, EventIdentity.matchSide("Berck Fliers Range", "Berck/Rang du Fliers", NO_ALIASES).level);
        assertEquals(EventIdentity.Level.ALIAS, EventIdentity.matchSide("Debreceni EAC", "DEAC Debreceni", NO_ALIASES).level);
        EventIdentity.Side sopron = EventIdentity.matchSide("Soproni", "Sopron", NO_ALIASES);        // without the registry entry
        assertEquals(EventIdentity.Level.VARIANT, sopron.level);
        assertTrue(sopron.score >= EventIdentity.DETERMINISTIC);
        Map<String, String> supplied = new HashMap<>();
        supplied.put("hapoel jlm", "Hapoel Jerusalem");
        assertEquals(EventIdentity.Level.ALIAS, EventIdentity.matchSide("Hapoel JLM", "Hapoel Jerusalem", supplied).level);
        assertEquals(EventIdentity.Level.NONE, EventIdentity.matchSide("Bayern Munich", "Shiga Lakes", NO_ALIASES).level);
    }

    @Test public void eventVerdicts() {
        assertEquals(EventIdentity.Verdict.EXACT, resolve("Hapoel Tel Aviv", "Bayern Munich", "24 Sep 17:00", "Hapoel Tel Aviv", "Bayern Munich", "24 Sep 17:00", true).verdict);
        assertEquals(EventIdentity.Verdict.CANONICAL_MATCH, resolve("Besancon", "Val De Seine", "25 Sep 19:00", "Besancon AC", "Val de Seine", "25 Sep 19:00", true).verdict);
        assertEquals(EventIdentity.Verdict.ALIAS_MATCH, resolve("Kyoto Hannaryz", "Shiga Lake Stars", "25 Sep 10:35", "Kyoto Hannaryz", "Shiga Lakes", "25 Sep 10:35", true).verdict);
        EventIdentity.Result hc = resolve("Besancon", "Valdeseine", "25 Sep 19:00", "Besancon AC", "Val de Seine", "25 Sep 19:00", true);
        assertEquals(EventIdentity.Verdict.HIGH_CONFIDENCE_EVENT_MATCH, hc.verdict);
        assertEquals("Val de Seine", hc.aliasCandidates.get("Valdeseine"));
        assertEquals("high", hc.candidateConfidence);                      // letters agree 0.80: strong, not deterministic
        // Names still match without a kick-off (in-play page / search results): the name layers decide.
        assertEquals(EventIdentity.Verdict.ALIAS_MATCH, resolve("Kyoto Hannaryz", "Shiga Lake Stars", null, "Kyoto Hannaryz", "Shiga Lakes", null, false).verdict);
    }

    @Test public void fuzzyAloneNeverApproves() {
        // Same variant, but no event anchor (search results): AMBIGUOUS, not accepted.
        EventIdentity.Result r = resolve("Besancon", "Valdeseine", "25 Sep 19:00", "Besancon AC", "Val de Seine", "25 Sep 19:00", false);
        assertEquals(EventIdentity.Verdict.AMBIGUOUS, r.verdict);
        assertFalse(r.accepted());
        // Anchored but kick-off unknown on the page: still AMBIGUOUS.
        assertEquals(EventIdentity.Verdict.AMBIGUOUS, resolve("Besancon", "Valdeseine", "25 Sep 19:00", "Besancon AC", "Val de Seine", null, true).verdict);
        // Both teams only variants: AMBIGUOUS even with the anchor.
        assertEquals(EventIdentity.Verdict.AMBIGUOUS, resolve("Besancn", "Valdeseine", "25 Sep 19:00", "Besancon AC", "Val de Seine", "25 Sep 19:00", true).verdict);
    }

    @Test public void falsePositiveGuard() {
        // wrong opponent
        assertEquals(EventIdentity.Verdict.MISMATCH, resolve("Kyoto Hannaryz", "Bayern Munich", "25 Sep 10:35", "Kyoto Hannaryz", "Shiga Lakes", "25 Sep 10:35", true).verdict);
        // similar club name (shares a generic word only)
        assertEquals(EventIdentity.Verdict.MISMATCH, resolve("Basket Club Nantes", "Val De Seine", "25 Sep 19:00", "Basket Club Besancon", "Val de Seine", "25 Sep 19:00", true).verdict);
        // women vs men
        assertEquals(EventIdentity.Verdict.MISMATCH, resolve("Bayern Munich", "Real Madrid", "25 Sep 19:00", "Bayern Munich Women", "Real Madrid Women", "25 Sep 19:00", true).verdict);
        assertEquals(EventIdentity.Verdict.MISMATCH, resolve("BC Beroe", "Ferrol", null, "Beroe (W)", "Uni Ferrol (W)", null, false).verdict);
        // reserve vs first team
        assertEquals(EventIdentity.Verdict.MISMATCH, resolve("Real Madrid", "Barcelona", "25 Sep 19:00", "Real Madrid B", "Barcelona", "25 Sep 19:00", true).verdict);
        assertEquals(EventIdentity.Verdict.MISMATCH, resolve("Spain", "France", "25 Sep 19:00", "Spain U21", "France U21", "25 Sep 19:00", true).verdict);
        // kick-off mismatch with matching names
        assertEquals(EventIdentity.Verdict.MISMATCH, resolve("Kyoto Hannaryz", "Shiga Lake Stars", "25 Sep 10:35", "Kyoto Hannaryz", "Shiga Lakes", "26 Sep 10:35", true).verdict);
        // reversed home/away is never accepted (the selection side would land on the other team)
        EventIdentity.Result rev = resolve("Val De Seine", "Besancon", "25 Sep 19:00", "Besancon AC", "Val de Seine", "25 Sep 19:00", true);
        assertEquals(EventIdentity.Verdict.MISMATCH, rev.verdict);
        assertTrue(rev.reversed);
        // wrong sport
        assertEquals(EventIdentity.Verdict.MISMATCH, EventIdentity.resolve(new EventIdentity.Event("football", "Fulham", "Crystal Palace", null, null, false),
                new EventIdentity.Event("basketball", "Fulham", "Crystal Palace", null, null, true), NO_ALIASES).verdict);
        // a sure opponent + a merely different name is MISMATCH, not a variant
        assertEquals(EventIdentity.Verdict.MISMATCH, resolve("Araraquara", "Mogi Das Cruzes", null, "Corinthians", "Mogi das Cruzes", null, false).verdict);
    }
}
