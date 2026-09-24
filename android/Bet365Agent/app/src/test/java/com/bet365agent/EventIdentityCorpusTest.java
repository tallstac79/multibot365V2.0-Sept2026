package com.bet365agent;

import static org.junit.Assert.assertEquals;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.EnumMap;
import java.util.Map;
import org.junit.Test;

/** B9: the resolver against the live corpus (identity_corpus.txt), with the counts printed for the report.
 *  (Pipe-delimited, not JSON: Android local unit tests only have a stubbed org.json.) */
public class EventIdentityCorpusTest {
    private static String nul(String s) { return s.equals("-") ? null : s; }

    @Test public void corpus() throws Exception {
        Map<EventIdentity.Verdict, Integer> counts = new EnumMap<>(EventIdentity.Verdict.class);
        int cases = 0, priorFailures = 0, priorFailuresNowAccepted = 0;
        StringBuilder report = new StringBuilder();
        try (BufferedReader in = new BufferedReader(new InputStreamReader(
                EventIdentityCorpusTest.class.getResourceAsStream("/identity_corpus.txt"), StandardCharsets.UTF_8))) {
            for (String line; (line = in.readLine()) != null; ) {
                if (line.isBlank() || line.startsWith("#")) continue;
                String[] f = line.split("\\s*\\|\\s*");
                assertEquals("columns in: " + line, 12, f.length);
                cases++;
                EventIdentity.Event feed = new EventIdentity.Event(f[3], f[4], f[5], nul(f[6]), null, false);
                EventIdentity.Event page = new EventIdentity.Event(f[7], f[8], f[9], nul(f[10]), null, Boolean.parseBoolean(f[11]));
                EventIdentity.Result r = EventIdentity.resolve(feed, page, Collections.emptyMap());
                counts.merge(r.verdict, 1, Integer::sum);
                boolean wasFailure = !f[1].startsWith("PASS") && !f[1].startsWith("accepted");
                if (wasFailure) { priorFailures++; if (r.accepted()) priorFailuresNowAccepted++; }
                report.append(String.format("  %-40s prior=%-24s now=%-28s %s%n", trim(f[0], 40), trim(f[1], 24), r.verdict, r.reason));
                assertEquals(f[0] + ": " + r.reason, f[2], r.verdict.name());
            }
        }
        System.out.print("IDENTITY_CORPUS " + cases + " cases\n" + report + "COUNTS " + counts
                + "\nPRIOR_FAILURES " + priorFailures + " NOW_ACCEPTED " + priorFailuresNowAccepted + "\n");
    }

    private static String trim(String s, int n) { return s.length() > n ? s.substring(0, n) : s; }
}
