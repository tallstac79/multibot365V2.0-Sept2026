package com.bet365agent;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import org.junit.Test;

/**
 * Codex identity-v2 operational corpus (46 real direct-link failures, frozen 2026-09-27 11:21Z) replayed through the
 * PRODUCTION decision: raw OCR words of the stored capture -> EventHeader.header -> EventPage.decide (teams, kick-off,
 * EventIdentity.resolveVerified with the alert's sport, names, UK kick-off, competition, country and the backend's
 * women's-competition flag). Acceptance baseline (docs/OFFLINE_EVENT_IDENTITY_V2.md):
 *   V2 DIRECT_URL_CONFIRMED[_NAME_VARIANT] -> production must accept
 *   V2 AMBIGUOUS / NEEDS_RECHECK            -> production must NOT accept (a recheck may only be cleared by a reread)
 *   V2 CONFLICT on identity fields          -> production must NOT accept
 *   V2 CONFLICT only on market_fingerprint  -> identity is not decided by the quote in production: the alert-to-live
 *                                              execution terms judge the quote after identity (not an identity verdict)
 */
public class EventIdentityV2ReplayTest {
    static final class Case {
        String id, oldStage, v2, v2Conflicts, v2Rechecks, v2Missing, sport, home, away, kickoff, competition, country, capture; boolean women;
    }

    static List<Case> cases() throws Exception {
        List<Case> out = new ArrayList<>();
        try (BufferedReader in = new BufferedReader(new InputStreamReader(
                EventIdentityV2ReplayTest.class.getResourceAsStream("/identity_v2/manifest.txt"), StandardCharsets.UTF_8))) {
            for (String line; (line = in.readLine()) != null; ) {
                if (line.isBlank() || line.startsWith("#")) continue;
                String[] f = line.split("\\s*\\|\\s*");
                assertEquals(line, 14, f.length);
                Case c = new Case();
                c.id = f[0]; c.oldStage = f[1]; c.v2 = f[2]; c.v2Conflicts = f[3]; c.v2Rechecks = f[4]; c.v2Missing = f[5]; c.sport = f[6];
                c.home = f[7]; c.away = f[8]; c.kickoff = f[9].equals("-") ? null : f[9]; c.competition = f[10].equals("-") ? null : f[10];
                c.country = f[11].equals("-") ? null : f[11]; c.women = Boolean.parseBoolean(f[12]); c.capture = f[13];
                out.add(c);
            }
        }
        return out;
    }

    static EventPage.Direct decide(Case c) throws Exception {
        List<GameLinesParser.Word> words = StakePadTest.load("identity_v2/" + c.capture);
        return EventPage.decide(EventHeader.header(words), c.sport, c.home, c.away, c.kickoff, c.competition, c.country, true,
                Collections.emptyMap(), c.women);
    }

    /** V2 inputs whose header extraction missed a line that is visible in the stored screenshot. on-25d0bcd6 (Suwon v Goyang,
     *  s005): "Club Friendlies • 27 Sep 06:00" at y=168 (checked on the PNG, 27 Sep 2026); V2 recorded kick-off and
     *  competition as missing and returned AMBIGUOUS. Production reads that line and decides on complete evidence. */
    static final java.util.Set<String> V2_EXTRACTION_GAPS = java.util.Set.of("on-25d0bcd66293960cc8e084ac");

    /** Confirmed by V2 through an independent visual review of the squad numeral (evidence/identity-v2/visual-reviews.json). */
    static final java.util.Set<String> V2_VISUAL_REVIEW = java.util.Set.of("on-7568867893977163a3442a04", "on-508cf995276ef58b04a1bb71",
            "on-8d9ec0935d6e1241f712a8db");

    static boolean identityConflict(Case c) {
        if (!c.v2.equals("CONFLICT")) return false;
        for (String k : c.v2Conflicts.split(",")) if (!k.equals("market_fingerprint")) return true;
        return false;
    }

    @Test public void operationalCorpusThroughTheProductionDecision() throws Exception {
        Map<String, Integer> counts = new TreeMap<>();
        StringBuilder report = new StringBuilder();
        int accepted = 0;
        List<String> violations = new ArrayList<>();
        for (Case c : cases()) {
            EventPage.Direct d = decide(c);
            String verdict = d.result == null ? "NO_TEAMS" : d.result.verdict.name();
            boolean ok = d.result != null && d.result.accepted();
            if (ok) accepted++;
            counts.merge(verdict, 1, Integer::sum);
            String reason = d.result == null ? "header teams not read " + d.header : d.result.reason;
            report.append(String.format("%-12s old=%-16s v2=%-34s prod=%-28s teams=%s | %s%n", c.id.substring(0, 11), c.oldStage, c.v2
                    + (c.v2.equals("CONFLICT") ? "[" + c.v2Conflicts + "]" : ""), verdict,
                    d.teams == null ? "-" : d.teams[0] + " v " + d.teams[1], reason.length() > 150 ? reason.substring(0, 150) : reason));
            boolean v2Confirms = c.v2.startsWith("DIRECT_URL_CONFIRMED");
            if (V2_VISUAL_REVIEW.contains(c.id)) {
                // V2 confirmed these only with a human visual review of the numeral (visual-reviews.json); on the stored OCR alone
                // V2 itself says NEEDS_RECHECK. Production must ask for its independent enhanced reread, never accept the glyph.
                if (!verdict.equals("NEEDS_RECHECK")) violations.add(c.id + " expected NEEDS_RECHECK (reread) on the stored OCR, production " + verdict);
            } else if (v2Confirms && !ok) violations.add(c.id + " V2 confirms, production " + verdict + ": " + reason);
            if ((c.v2.equals("AMBIGUOUS") || c.v2.equals("NEEDS_RECHECK") || identityConflict(c)) && ok && !V2_EXTRACTION_GAPS.contains(c.id))
                violations.add(c.id + " V2 " + c.v2 + ", production accepted: " + reason);
        }
        System.out.print("IDENTITY_V2_PRODUCTION_REPLAY\n" + report + "PRODUCTION_VERDICTS " + counts + " ACCEPTED " + accepted + "\n"
                + "VIOLATIONS " + violations.size() + "\n" + String.join("\n", violations) + "\n");
        if (Boolean.getBoolean("identity.v2.baseline")) return;
        assertTrue(String.join("\n", violations), violations.isEmpty());
    }

    /** The three Bydgoszcz frames re-read ON THE PHONE with the live enhanced-reread routine (OCR_BENCH legacy table =
     *  recognizeLines, 27 Sep 2026; evidence/identity-v2-integration/reread-bench): the reread shows the numeral as "ll"
     *  (two strokes, as the first engine's "I|"/"||"). Patched into the first read, identity is accepted. */
    @Test public void bydgoszczRereadOnTheDeviceClearsTheRecheck() throws Exception {
        for (Case c : cases()) {
            if (!V2_VISUAL_REVIEW.contains(c.id)) continue;
            List<String> first = EventHeader.header(StakePadTest.load("identity_v2/" + c.capture));
            List<String> reread = EventHeader.header(StakePadTest.load("identity_v2/reread_" + c.capture));
            String[] patched = EventPage.patchNumeral(first, reread);
            assertTrue(c.id + " reread " + reread, patched != null);
            assertEquals("KS Basket 25 II Bydgoszcz (W)", patched[0]);
            assertEquals("Katarzynki II Torun (W)", patched[1]);
            EventPage.Direct d = EventPage.decide(first, patched, c.sport, c.home, c.away, c.kickoff, c.competition, c.country, true,
                    Collections.emptyMap(), c.women);
            System.out.println("BYDGOSZCZ_REREAD " + c.id + " " + d.result.verdict + " | " + d.result.reason);
            assertEquals(d.result.reason, EventIdentity.Verdict.HIGH_CONFIDENCE_EVENT_MATCH, d.result.verdict);
            assertTrue(d.result.aliasCandidates.isEmpty() || !d.result.aliasCandidates.containsKey("Energa Torun II"));
        }
        // a reread that does not show the numeral where it belongs leaves the recheck unresolved
        List<String> first = java.util.Arrays.asList("Poland 1 Liga Women 27 Sep 12:30", "KS Basket 25 I| Bydgoszcz (W) vs Katarzynki II", "Torun (W)");
        assertEquals(null, EventPage.patchNumeral(first, java.util.Arrays.asList("Poland 1 Liga Women", "KS Basket 25 Bydgoszcz (W) vs Katarzynki II")));
        // one stroke is I, which against the feed's II stays a recheck (and fails closed after the one reread)
        String[] one = EventPage.patchNumeral(first, java.util.Arrays.asList("KS Basket 25 l Bydgoszcz (W) vs Katarzynki II Torun (W)"));
        EventPage.Direct d = EventPage.decide(first, one, "basketball", "KS Basket 25 II Bydgoszcz", "Energa Torun II", "27 Sep 12:30", "Liga 1 Women",
                "Poland", true, Collections.emptyMap(), true);
        assertFalse(d.result.accepted());
    }
}
