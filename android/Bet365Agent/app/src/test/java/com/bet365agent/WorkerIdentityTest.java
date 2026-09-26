package com.bet365agent;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotEquals;
import static org.junit.Assert.assertNull;

import org.junit.Test;

/** The account fingerprint the backend binds automatic approvals to: deterministic, normalised, never the username. */
public class WorkerIdentityTest {
    @Test public void fingerprintIsDeterministicAndNormalised() {
        String a = WorkerIdentity.fingerprint("Operator@Example.com");
        assertEquals(12, a.length());
        assertEquals(a, WorkerIdentity.fingerprint("  operator@example.com "));
        assertEquals(WorkerIdentity.sha256("operator@example.com").substring(0, 12), a);
        assertNotEquals(a, WorkerIdentity.fingerprint("operator2@example.com"));
        assertEquals(-1, a.indexOf('@'));
    }

    @Test public void noUsernameMeansNoFingerprint() {
        assertNull(WorkerIdentity.fingerprint(null));
        assertNull(WorkerIdentity.fingerprint("   "));
    }
}
