package com.bet365agent;

import static org.junit.Assert.assertArrayEquals;
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
 * Codex daily audit, 28 Sep 2026: the current technical failure classes replayed from the stored phone frames, each fix
 * next to the cases that must still fail closed. (Event-header replays of the nine event cases are rows in
 * competition_replay/manifest.txt, run by CompetitionReplayTest.)
 */
public class DailyAudit20260928Test {
    private static List<GameLinesParser.Word> slip(String name) throws Exception {
        return EventHeader.lineWords(StakePadTest.load(name));
    }

    private static int placeTop(List<GameLinesParser.Word> lines) {
        int top = -1;
        for (GameLinesParser.Word l : lines) if (l.text.contains("Place Bet")) top = l.top;
        return top;
    }

    // ---------------------------------------------------------------- 1. header parsing with the alert's own names only
    @Test public void gluedSeparatorSplitsOnlyAtTheAlertsHomeName() {
        List<String> georgia = Arrays.asList("UEFA Nations League B 28 Sep 17:00", "Georgiav Ukraine v");
        assertNull(EventPage.teams(georgia));
        assertArrayEquals(new String[] {"Georgia", "Ukraine"}, EventPage.teams(georgia, Arrays.asList("Georgia"), Arrays.asList("Ukraine")));
        assertNull(EventPage.teams(georgia, Arrays.asList("Wales"), Arrays.asList("Ukraine")));          // another home team: no split
        assertNull(EventPage.teams(georgia, Collections.emptyList(), Arrays.asList("Ukraine")));
        assertArrayEquals(new String[] {"Belgium", "France"},
                EventPage.teams(Arrays.asList("Belgiumv France"), Arrays.asList("Belgium"), Arrays.asList("France")));
        assertNull(EventPage.teams(Arrays.asList("Rostov Kyiv Ukraine"), Arrays.asList("Rosto"), Arrays.asList("Ukraine")));  // two glued-v words
        // a real name ending in 'v' is untouched
        assertArrayEquals(new String[] {"Dynamo Kyiv", "Shakhtar"},
                EventPage.teams(Arrays.asList("Dynamo Kyiv v Shakhtar"), Arrays.asList("Dynamo Kyiv"), Arrays.asList("Shakhtar")));
    }

    @Test public void gluedChevronLeavesTheCleanApprovedName() throws Exception {
        List<GameLinesParser.Word> lines = slip("slip_engtat_final_20260928.txt");
        List<String> header = EventHeader.header(StakePadTest.load("slip_engtat_final_20260928.txt"));
        assertEquals("SG Basketballv", EventPage.teams(header)[1]);                                   // what was approved on the day
        String[] clean = EventPage.teams(header, Arrays.asList("Eng Tat Hornets"), Arrays.asList("SG", "SG Basketball"));
        assertEquals("SG Basketball", clean[1]);
        int top = placeTop(lines);
        assertFalse(HeldSlipIdentity.matches(lines, "Eng Tat Hornets", "SG Basketballv", "TOTALS", top));  // the day's refusal
        assertTrue(HeldSlipIdentity.matches(lines, clean[0], clean[1], "TOTALS", top));
        HeldSlipQuote q = HeldSlipQuote.read(lines, "Over", "TOTALS", top);
        assertNotNull(q);
        assertEquals("147.5", q.line);
        assertEquals("1.83", q.price);
        // without the alert's alias the glued chevron stays (never stripped on a guess)
        assertEquals("SG Basketballv", EventPage.teams(header, Arrays.asList("Eng Tat Hornets"), Arrays.asList("SG"))[1]);
        assertFalse(HeldSlipIdentity.matches(lines, clean[0], "SG Tigers", "TOTALS", top));
    }

    @Test public void ligaturesAreSpelledOut() {
        assertArrayEquals(new String[] {"Raelingen", "Lyn 1896 " + EventIdentity.UNREAD_TIER},
                EventPage.teams(Arrays.asList("Rælingen v Lyn 1896 I|")));
    }

    // ---------------------------------------------------------------- OCR glyph evidence (event-scoped, never an alias)
    @Test public void ocrGlyphsAreEvidenceNotAliases() {
        EventIdentity.TokenEvidence ives = EventIdentity.compareTokens("st ives town", "st lves town");
        assertEquals("ocr_glyph", ives.kind);
        assertEquals(EventIdentity.Level.VARIANT, ives.level);
        assertTrue(ives.extraOnSecond);                                                                // not alias-safe
        assertEquals("ocr_glyph", EventIdentity.compareTokens("al ittihad jeddah", "al littihad").kind);  // hyphen read as 'l'
        assertFalse("ocr_glyph".equals(EventIdentity.compareTokens("st ives town", "st eves town").kind)); // a real letter
        assertFalse("ocr_glyph".equals(EventIdentity.compareTokens("ilves", "lives").kind));             // two positions
        assertFalse(EventIdentity.matchSide("St Ives Town", "St lves Town", Collections.emptyMap()).aliasSafe);
    }

    @Test public void strokeNumeralGoesToTheRereadNeverAMismatchOrAnAcceptance() {
        EventIdentity.Side s = EventIdentity.matchSide("Polissya Zhytomyr II", "Polissya Zhytomyr Il", Collections.emptyMap());
        assertNotNull(s.recheck);                                                                      // provisional: reread required
        assertTrue(s.markersAgree);
        assertEquals(EventIdentity.Level.NONE, EventIdentity.matchSide("Polissya Zhytomyr II", "Polissya Zhytomyr", Collections.emptyMap()).level);
        assertNull(EventIdentity.matchSide("Polissya Zhytomyr", "Polissya Zhytomyr Il", Collections.emptyMap()).recheck == null ? null : "x");
        // the reread counts the strokes it shows at the same place
        assertArrayEquals(new String[] {"Polissya Zhytomyr II", "Kolos Kovalivka II"},
                EventPage.patchNumeral(Arrays.asList("Polissya Zhytomyr Il v Kolos Kovalivka l|"), Arrays.asList("Polissya Zhytomyr II v Kolos Kovalivka II")));
        assertNull(EventPage.patchNumeral(Arrays.asList("Polissya Zhytomyr Il v Kolos Kovalivka l|"), Arrays.asList("Polissya Zhytomyr v Kolos Kovalivka")));
    }

    // ---------------------------------------------------------------- competition: missing evidence vs contradiction
    @Test public void aGenericLabelIsNotAContradictionOfFriendly() {
        assertNull(CompetitionStructure.conflict("Friendlies U19", "International", "U19 International"));
        assertNotNull(CompetitionStructure.conflict("Friendlies U19", "International", "U21 International"));          // age differs
        assertNotNull(CompetitionStructure.conflict("Friendlies U19", "International", "UEFA U19 Championship Qualifiers")); // named competition
        assertNotNull(CompetitionStructure.conflict("Club Friendlies", "Spain", "Spain Copa del Rey"));                      // cup
        assertNotNull(CompetitionStructure.conflict("Professional Development League U21", "England", "England Development League 2")); // no approved mapping
    }

    // ---------------------------------------------------------------- 2. fresh slip proof: one normalization for identity and quote
    @Test public void alKharaitiyatSlipQuoteReadsWithTheIdentityChecksGlyphRule() throws Exception {
        List<GameLinesParser.Word> lines = slip("footslip_alkharaitiyat_final_20260928.txt");
        int top = placeTop(lines);
        assertTrue(HeldSlipIdentity.matches(lines, "Al Kharaitiyat SC", "Al-Wakrah SC", "MONEYLINE", top, "football"));
        HeldSlipQuote q = HeldSlipQuote.read(lines, "Al Kharaitiyat SC", "MONEYLINE", top, "football");          // slip says "AI Kharaitiyat SC"
        assertNotNull(q);
        assertEquals("2.80", q.price);
        assertNull(HeldSlipQuote.read(lines, "Al Sailiya SC", "MONEYLINE", top, "football"));
        assertNull(HeldSlipQuote.read(lines, "Al-Wakrah SC", "MONEYLINE", top, "football"));
        assertNull(FootballLineCheck.freshTerms("MONEYLINE", "HOME", "", "", q.price, "0.25", "2.62"));
    }

    // ---------------------------------------------------------------- 3. changed-price slip judged by the existing tolerances
    @Test public void sawmerChangedPriceInsideTheTolerancesIsAccepted() throws Exception {
        List<GameLinesParser.Word> raw = StakePadTest.load("footslip_sawmer_changed_stake_ui_20260928.txt");
        SlipChange.Decision d = SlipChange.decide(raw, "Sawmer SC", "Nongkseh SS & CC", "Nongkseh SS & CC", "SPREAD", "AWAY", "-2.75", "0.25", "1.81");
        assertEquals(d.detail, "ACCEPT", d.action);
        assertEquals("-3.0", d.line);
        assertEquals("1.900", d.price);
        assertNotNull(d.acceptBounds);
    }

    @Test public void changedPriceOutsideTheRulesOrUnprovenIsRefused() throws Exception {
        List<GameLinesParser.Word> raw = StakePadTest.load("footslip_sawmer_changed_stake_ui_20260928.txt");
        assertEquals("BELOW_MINIMUM", SlipChange.decide(raw, "Sawmer SC", "Nongkseh SS & CC", "Nongkseh SS & CC", "SPREAD", "AWAY", "-2.75", "0.25", "1.95").stage);
        assertEquals("LINE_CHANGED", SlipChange.decide(raw, "Sawmer SC", "Nongkseh SS & CC", "Nongkseh SS & CC", "SPREAD", "AWAY", "-2.5", "0.25", "1.81").stage);
        assertEquals("WRONG_EVENT", SlipChange.decide(raw, "Sawmer SC", "Shillong Lajong", "Nongkseh SS & CC", "SPREAD", "AWAY", "-2.75", "0.25", "1.81").stage);
        // stake entered: only the combined "Accept Change and Place Bet" is shown - never tapped
        List<GameLinesParser.Word> combined = StakePadTest.load("footslip_sawmer_changed_retyped_20260928.txt");
        SlipChange.Decision c = SlipChange.decide(combined, "Sawmer SC", "Nongkseh SS & CC", "Nongkseh SS & CC", "SPREAD", "AWAY", "-2.75", "0.25", "1.81");
        assertEquals("REFUSE", c.action);
        assertNull(c.acceptBounds);
        // no changed-price state: nothing to do
        assertEquals("NONE", SlipChange.decide(StakePadTest.load("footslip_alkharaitiyat_final_20260928.txt"), "Al Kharaitiyat SC", "Al-Wakrah SC",
                "Al Kharaitiyat SC", "MONEYLINE", "HOME", "", "0.25", "2.62").action);
    }
}
