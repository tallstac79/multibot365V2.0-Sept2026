package com.bet365agent;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.fail;

import java.util.LinkedHashMap;
import java.util.Map;
import org.junit.Test;

/**
 * ADAPTER_WORKFLOW wire schema (CoordinatorInstruction.checkWorkflowExtras), on the exact payload the phone refused
 * on 2026-09-25 12:15 UTC (Milestone B): on-42935974, KSC Szekszard v NKA Universitas Pecs, Nemzeti Bajnoksag I.A
 * Women. android.util.JsonReader is not available on the JVM, so the field map is built as the reader would.
 */
public class CoordinatorInstructionTest {
    static Map<String, String> womensHold() {
        Map<String, String> f = new LinkedHashMap<>();
        f.put("action", "ADAPTER_WORKFLOW"); f.put("adapter", "live_bet365"); f.put("competition_women", "true");
        f.put("event_url", "https://www.bet365.com/#/AC/B18/C21170156/D19/E26748243/F19/"); f.put("execution_mode", "hold");
        f.put("instruction_id", "on-42935974a0ed733e4a1dc161"); f.put("kickoff_utc", "2026-09-26T16:00"); f.put("line", "3.5");
        f.put("market", "SPREAD"); f.put("minimum_price", "1.83"); f.put("query", "KSC Szekszard||NKA Universitas Pecs");
        f.put("scenario", "live"); f.put("side", "HOME"); f.put("sport", "basketball"); f.put("stake", "0.10"); f.put("timeout_ms", "300000");
        return f;
    }

    private static String refusal(Map<String, String> fields) {
        try {
            CoordinatorInstruction.checkWorkflowExtras(fields);
            return null;
        } catch (IllegalArgumentException e) {
            return e.getMessage();
        }
    }

    @Test public void womensCompetitionHoldRunIsAdmitted() {
        assertEquals(null, refusal(womensHold()));
    }

    @Test public void flagAbsentOrFalseIsAdmittedToo() {
        Map<String, String> f = womensHold(); f.remove("competition_women");
        assertEquals(null, refusal(f));
        f.put("competition_women", "false");
        assertEquals(null, refusal(f));
    }

    @Test public void flagValueIsStrict() {
        for (String bad : new String[] {"yes", "TRUE", "1", ""}) {
            Map<String, String> f = womensHold(); f.put("competition_women", bad);
            assertEquals(bad, "Invalid competition_women", refusal(f));
        }
    }

    @Test public void otherExtrasAreStillRefused() {
        Map<String, String> f = womensHold(); f.remove("competition_women"); f.put("competition_men", "true");
        assertEquals("Invalid schema extras", refusal(f));
        f = womensHold(); f.put("price", "1.90");                   // PLACE_HELD-only field on a hold run
        assertEquals("Invalid schema extras", refusal(f));
        f = womensHold(); f.remove("query");                        // base field missing
        assertEquals("Invalid ADAPTER_WORKFLOW schema", refusal(f));
        f = womensHold(); f.put("event_url", "https://bet365.com/#/AC/B18/C21170156/D19/E26748243/F19/");  // phone keeps the strict www form
        assertEquals("Invalid event_url", refusal(f));
    }
}
