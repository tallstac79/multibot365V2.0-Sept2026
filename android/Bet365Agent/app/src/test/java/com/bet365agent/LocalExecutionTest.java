package com.bet365agent;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

/** The persistent local execution permission's rule: a grant is valid only for the worker and account it named. */
public class LocalExecutionTest {
    private static LocalExecution.Decision decide(boolean enabled, String gw, String ga, String cw, String ca) {
        return LocalExecution.evaluate(enabled, gw, ga, cw, ca).decision;
    }

    @Test public void disabledStaysDisabledWhateverTheIdentity() {
        assertEquals(LocalExecution.Decision.DISABLED, decide(false, "w-d131ef8769de", "1457f6e497f3", "w-d131ef8769de", "1457f6e497f3"));
        assertEquals(LocalExecution.Decision.DISABLED, decide(false, "", "", "w-d131ef8769de", "1457f6e497f3"));
    }

    @Test public void enabledAllowsOnlyTheGrantedWorkerAndAccount() {
        assertEquals(LocalExecution.Decision.ALLOW, decide(true, "w-d131ef8769de", "1457f6e497f3", "w-d131ef8769de", "1457f6e497f3"));
    }

    @Test public void accountFingerprintChangeRevokes() {
        LocalExecution.Policy p = LocalExecution.evaluate(true, "w-d131ef8769de", "1457f6e497f3", "w-d131ef8769de", "0000deadbeef");
        assertEquals(LocalExecution.Decision.REVOKED, p.decision);
        assertEquals("account fingerprint changed", p.reason);
        assertEquals("no account configured", LocalExecution.evaluate(true, "w-d131ef8769de", "1457f6e497f3", "w-d131ef8769de", null).reason);
    }

    @Test public void recreatedIdentityRevokes() {
        // app data reset / reinstall: a new worker id is generated, the old grant names the old one
        assertEquals("worker identity changed", LocalExecution.evaluate(true, "w-d131ef8769de", "1457f6e497f3", "w-9999aaaa0000", "1457f6e497f3").reason);
        // a grant written without identity (never produced by enable(), defended anyway)
        assertEquals("grant lacks worker or account identity", LocalExecution.evaluate(true, "", "", "w-d131ef8769de", "1457f6e497f3").reason);
    }
}
