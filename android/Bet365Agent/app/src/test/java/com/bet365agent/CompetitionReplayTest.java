package com.bet365agent;

import static org.junit.Assert.assertEquals;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import org.junit.Test;

/**
 * Every real direct-link instruction that failed on the competition gate on 27 Sep 2026 (live pipeline + football hold
 * proofs), replayed through the PRODUCTION decision from its stored event-page capture: raw OCR words -> EventHeader.header
 * -> EventPage.decide (anchored: the alert's own Bet365 event link) with the alert's sport, names, UK kick-off,
 * competition, country and the backend's women's-competition flag.
 */
public class CompetitionReplayTest {
    static final class Case { String id, source, sport, home, away, kickoff, competition, country, capture, expected, original; boolean women; }

    static List<Case> cases() throws Exception {
        List<Case> out = new ArrayList<>();
        try (BufferedReader in = new BufferedReader(new InputStreamReader(
                CompetitionReplayTest.class.getResourceAsStream("/competition_replay/manifest.txt"), StandardCharsets.UTF_8))) {
            for (String line; (line = in.readLine()) != null; ) {
                if (line.isBlank() || line.startsWith("#")) continue;
                String[] f = line.split("\\s*\\|\\s*", 12);
                Case c = new Case();
                c.id = f[0]; c.source = f[1]; c.sport = f[2]; c.home = f[3]; c.away = f[4]; c.kickoff = f[5].equals("-") ? null : f[5];
                c.competition = f[6].equals("-") ? null : f[6]; c.country = f[7].equals("-") ? null : f[7]; c.women = Boolean.parseBoolean(f[8]);
                c.capture = f[9]; c.expected = f[10]; c.original = f.length > 11 ? f[11] : "";
                out.add(c);
            }
        }
        return out;
    }

    static EventPage.Direct decide(Case c) throws Exception {
        List<GameLinesParser.Word> words = StakePadTest.load("competition_replay/" + c.capture);
        return EventPage.decide(EventHeader.header(words), c.sport, c.home, c.away, EventPage.ukDisplay(c.kickoff), c.competition, c.country, true,
                Collections.emptyMap(), c.women);
    }

    static String outcome(EventPage.Direct d) {
        if (d.result == null) return "NO_TEAMS";
        return d.result.accepted() ? "ACCEPT" : d.result.verdict.name();
    }

    @Test public void replayEveryCompetitionFailure() throws Exception {
        List<String> wrong = new ArrayList<>();
        for (Case c : cases()) {
            EventPage.Direct d = decide(c);
            String got = outcome(d);
            String comp = d.result == null ? "-" : String.valueOf(d.result.evidence.get("competition_match"));
            System.out.println("REPLAY " + c.id + " | " + c.competition + " / " + c.country + " | header=" + d.header + " | " + got + " | " + comp
                    + (d.result == null ? "" : " | " + d.result.reason));
            if (!c.expected.equals(got)) wrong.add(c.id + " expected " + c.expected + " got " + got + " (" + comp + ")");
        }
        assertEquals(String.join("\n", wrong), 0, wrong.size());
    }
}
