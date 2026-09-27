package com.bet365agent;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.EnumMap;
import java.util.Map;
import org.junit.Test;

/** B9: the resolver against the live corpus (identity_corpus.txt), with the counts printed for the report.
 *  (Pipe-delimited, not JSON: Android local unit tests only have a stubbed org.json.)
 *  12 columns: resolve() on names + kick-off. 16 columns (feed competition | country | page header | women): the
 *  production gate resolveVerified(), exactly as the phone runs it on the direct-link route. */
public class EventIdentityCorpusTest {
    private static String nul(String s) { return s.equals("-") ? null : s; }

    @Test public void corpus() throws Exception {
        Map<EventIdentity.Verdict, Integer> counts = new EnumMap<>(EventIdentity.Verdict.class);
        Map<EventIdentity.Verdict, Integer> aliasRequiredNow = new EnumMap<>(EventIdentity.Verdict.class);
        int cases = 0, priorFailures = 0, priorFailuresNowAccepted = 0, constructed = 0, constructedAccepted = 0;
        StringBuilder report = new StringBuilder();
        try (BufferedReader in = new BufferedReader(new InputStreamReader(
                EventIdentityCorpusTest.class.getResourceAsStream("/identity_corpus.txt"), StandardCharsets.UTF_8))) {
            for (String line; (line = in.readLine()) != null; ) {
                if (line.isBlank() || line.startsWith("#")) continue;
                String[] f = line.split("\\s*\\|\\s*");
                assertTrue("columns in: " + line, f.length == 12 || f.length == 16);
                cases++;
                boolean verified = f.length == 16 && !f[12].equals("-");
                EventIdentity.Event feed = new EventIdentity.Event(f[3], f[4], f[5], nul(f[6]), verified ? f[12] : null, false);
                EventIdentity.Event page = new EventIdentity.Event(f[7], f[8], f[9], nul(f[10]), verified ? f[14] : null, Boolean.parseBoolean(f[11]));
                EventIdentity.Result r = verified
                        ? EventIdentity.resolveVerified(feed, page, Collections.emptyMap(), Boolean.parseBoolean(f[15]), nul(f[13]))
                        : EventIdentity.resolve(feed, page, Collections.emptyMap());
                counts.merge(r.verdict, 1, Integer::sum);
                boolean wasFailure = !f[1].startsWith("PASS") && !f[1].startsWith("accepted") && !f[1].startsWith("constructed");
                if (wasFailure) { priorFailures++; if (r.accepted()) priorFailuresNowAccepted++; }
                if (f[1].startsWith("ALIAS_REQUIRED")) aliasRequiredNow.merge(r.verdict, 1, Integer::sum);
                if (f[1].startsWith("constructed")) { constructed++; if (r.accepted()) constructedAccepted++; }
                report.append(String.format("  %-44s prior=%-26s now=%-28s %s%n", trim(f[0], 44), trim(f[1], 26), r.verdict, trim(r.reason, 110)));
                assertEquals(f[0] + ": " + r.reason, f[2], r.verdict.name());
            }
        }
        System.out.print("IDENTITY_CORPUS " + cases + " cases\n" + report + "COUNTS " + counts
                + "\nPRIOR_FAILURES " + priorFailures + " NOW_ACCEPTED " + priorFailuresNowAccepted
                + "\nHISTORICAL_ALIAS_REQUIRED_NOW " + aliasRequiredNow
                + "\nCONSTRUCTED_LOOKALIKES " + constructed + " ACCEPTED " + constructedAccepted + "\n");
        assertEquals("a constructed lookalike was accepted", 0, constructedAccepted);
    }

    private static String trim(String s, int n) { return s.length() > n ? s.substring(0, n) : s; }
}
