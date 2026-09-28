package com.bet365agent;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import java.util.Collections;
import java.util.List;
import org.junit.Test;

/**
 * Codex failure review, production run 27-28 Sep 2026: the captured frames of the false rejections, replayed through the
 * production code, and the genuine negatives next to each fix that must still fail closed.
 */
public class LiveFailures20260928Test {
    private static int placeTop(List<GameLinesParser.Word> lines) {
        int top = -1;
        for (GameLinesParser.Word l : lines) if (l.text.contains("Place Bet")) top = l.top;
        return top;
    }

    // ---------------------------------------------------------------- Brujos: slip OCR "lzalco" for "Izalco"
    @Test public void brujosSlipWithOcrGlyphIsTheHeldEvent() throws Exception {
        List<GameLinesParser.Word> lines = EventHeader.lineWords(StakePadTest.load("slip_brujos_final_reread_20260928.txt"));
        int top = placeTop(lines);
        assertTrue(top > 0);
        assertTrue(HeldSlipIdentity.matches(lines, "Brujos Izalco", "Santa Ana", "TOTALS", top));
        assertFalse(HeldSlipIdentity.matches(lines, "Brujos Izalco", "Santa Ana", "SPREAD", top));     // market label still required
        assertFalse(HeldSlipIdentity.matches(lines, "Brujos Izalco", "Santa Clara", "TOTALS", top));   // another opponent
        assertFalse(HeldSlipIdentity.matches(lines, "Santa Ana", "Brujos Izalco", "TOTALS", top));     // reversed
        assertFalse(HeldSlipIdentity.matches(lines, "Brujos Izalca", "Santa Ana", "TOTALS", top));     // one real letter differs
    }

    @Test public void onlyTheOcrGlyphsAreFolded() {
        assertTrue(HeldSlipIdentity.sameSlipName("Brujos Izalco", "Brujos lzalco"));
        assertTrue(HeldSlipIdentity.sameSlipName("Goianesia", "Gojanesia"));
        assertTrue(HeldSlipIdentity.sameSlipName("Fenerbahce II", "Fenerbahce Il"));
        assertFalse(HeldSlipIdentity.sameSlipName("Fenerbahce II", "Fenerbahce I"));    // squad numeral: length differs
        assertFalse(HeldSlipIdentity.sameSlipName("Energa Torun II", "Energa Torun III"));
        assertFalse(HeldSlipIdentity.sameSlipName("Brujos Izalco", "Brujos Izalca"));
        assertFalse(HeldSlipIdentity.sameSlipName("Santa Ana", "Santa Ano"));
        assertFalse(HeldSlipIdentity.sameSlipName("Lions", "Lyons"));
    }

    // ---------------------------------------------------------------- Goianesia: the pre-tap slip that was reported "unreadable"
    @Test public void goianesiaPretapSlipNowGivesTheRealReason() throws Exception {
        List<GameLinesParser.Word> lines = EventHeader.lineWords(StakePadTest.load("footslip_goianesia_pretap_20260927.txt"));
        int top = placeTop(lines);
        assertTrue(top > 0);
        assertTrue(HeldSlipIdentity.matches(lines, "Goianesia", "Mineiros", "SPREAD", top, "football"));   // slip read "Gojanesia"
        HeldSlipQuote q = HeldSlipQuote.read(lines, "Mineiros", "SPREAD", top, "football");
        assertNotNull(q);
        assertEquals("0.25", q.line);
        assertEquals("1.775", q.price);
        assertFalse(ExecutionTolerance.price(q.price, "1.86"));      // genuine: below the instruction's minimum -> BELOW_MINIMUM
        assertTrue(ExecutionTolerance.line("SPREAD", "AWAY", "0.25", q.line, "0.25"));
    }

    // ---------------------------------------------------------------- SBU: "MU Cardinals" for "Mapua Cardinals"
    static EventPage.Direct sbu(boolean anchored, String kickoffUtc) throws Exception {
        List<GameLinesParser.Word> words = StakePadTest.load("competition_replay/on-8fc5bdf94ab.txt");
        return EventPage.decide(EventHeader.header(words), "basketball", "SBU Red Lions", "Mapua Cardinals", EventPage.ukDisplay(kickoffUtc),
                "NCAA", "Philippines", anchored, Collections.emptyMap(), false);
    }

    @Test public void sbuInitialismUnderTheAlertsOwnLinkIsAccepted() throws Exception {
        EventPage.Direct d = sbu(true, "2026-09-28T07:00");
        assertTrue(d.result.reason, d.result.accepted());
        assertEquals("initialism", d.result.away.kind);
        assertFalse(d.result.away.aliasSafe);                       // event-scoped evidence only: never learned as an alias
        assertTrue(d.result.aliasCandidates.isEmpty());
    }

    @Test public void sbuInitialismNeedsTheAnchorAndTheKickoff() throws Exception {
        assertFalse(sbu(false, "2026-09-28T07:00").result.accepted());   // not from the alert's own link (Search)
        assertFalse(sbu(true, "2026-09-28T09:00").result.accepted());    // kick-off disagrees
    }

    @Test public void initialismIsNarrow() {
        assertEquals("initialism", EventIdentity.compareTokens("mapua cardinals", "mu cardinals").kind);
        assertFalse("initialism".equals(EventIdentity.compareTokens("mapua cardinals", "ma cardinals").kind));   // a prefix, not initials
        assertFalse("initialism".equals(EventIdentity.compareTokens("mapua cardinals", "xu cardinals").kind));   // another initial
        assertFalse("initialism".equals(EventIdentity.compareTokens("mapua cardinals", "um cardinals").kind));   // letters out of order
        assertFalse("initialism".equals(EventIdentity.compareTokens("tondo tigers", "td tigers").kind));        // nickname core only
        assertFalse("initialism".equals(EventIdentity.compareTokens("mapua red cardinals", "mu cardinals").kind)); // two words unexplained
        assertFalse(EventIdentity.compareTokens("mapua cardinals", "mu cardinals").level.ordinal() >= EventIdentity.Level.ALIAS.ordinal());
        // one side sure, the other only an initialism: never enough on its own (both names variants -> not token evidence)
        assertFalse(EventIdentity.matchSide("Mapua Cardinals", "MU Cardinals", Collections.emptyMap()).tokenEvidence());
    }

    // ---------------------------------------------------------------- Tesla: "Paraense 3" / "Campeonato Paraense A3"
    @Test public void gluedTierLetterIsAQualifierNotAContradiction() {
        assertNull(CompetitionStructure.conflict("Paraense 3", "Brazil", "Brazil Campeonato Paraense A3"));
        assertNull(CompetitionStructure.conflict("Paraense A3", "Brazil", "Brazil Campeonato Paraense A3"));
        assertNotNull(CompetitionStructure.conflict("Paraense 3", "Brazil", "Brazil Campeonato Paraense A2"));   // tier differs
        assertNotNull(CompetitionStructure.conflict("Paraense A3", "Brazil", "Brazil Campeonato Paraense B3"));  // letters differ
        assertNotNull(CompetitionStructure.conflict("Paraense", "Brazil", "Brazil Campeonato Paraense A3"));     // top vs 3
        assertNotNull(CompetitionStructure.conflict("Serie", "Italy", "Italy Serie B"));                         // standalone stays strict
        assertNotNull(CompetitionStructure.conflict("Serie A", "Italy", "Italy Serie B"));
        assertNotNull(CompetitionStructure.conflict("Primera B", "Chile", "Chile Primera Division"));
        assertNotNull(CompetitionStructure.conflict("Serie B 3", "Brazil", "Brazil Serie A3"));                  // standalone B vs glued A
    }
}
