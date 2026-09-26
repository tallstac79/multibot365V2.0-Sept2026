package com.bet365agent;

import android.content.Context;
import android.content.SharedPreferences;
import org.json.JSONObject;

/**
 * Persistent, local-only permission for final actions (2026-09-26, replaces the one-hour lease).
 *
 * Enabled only by an explicit action on the phone's settings screen; stays enabled across app, Chrome and phone
 * restarts until disabled there, or revoked automatically when the worker or account identity it was granted for
 * is no longer the one present (account fingerprint changed, app data reset and identity recreated). No HTTP
 * endpoint can enable it. The backend's kill switch, dispatch and final-action switches, approval, limits and every
 * verification still block independently: this permission is necessary, never sufficient.
 */
final class LocalExecution {
    static final String ENABLED = "local_execution_enabled", ENABLED_AT = "local_execution_enabled_at",
            DISABLED_AT = "local_execution_disabled_at", WORKER = "local_execution_worker_id",
            ACCOUNT = "local_execution_account_fingerprint", REASON = "local_execution_last_reason";

    enum Decision { ALLOW, DISABLED, REVOKED }

    static final class Policy {
        final Decision decision; final String reason;
        Policy(Decision decision, String reason) { this.decision = decision; this.reason = reason; }
    }

    /** Pure rule: the stored grant must name exactly the worker and account that are present now. */
    static Policy evaluate(boolean enabled, String grantedWorker, String grantedAccount, String currentWorker, String currentAccount) {
        if (!enabled) return new Policy(Decision.DISABLED, "disabled");
        if (isEmpty(grantedWorker) || isEmpty(grantedAccount)) return new Policy(Decision.REVOKED, "grant lacks worker or account identity");
        if (isEmpty(currentWorker) || !currentWorker.equals(grantedWorker)) return new Policy(Decision.REVOKED, "worker identity changed");
        if (isEmpty(currentAccount)) return new Policy(Decision.REVOKED, "no account configured");
        if (!currentAccount.equals(grantedAccount)) return new Policy(Decision.REVOKED, "account fingerprint changed");
        return new Policy(Decision.ALLOW, "enabled for this worker and account");
    }

    private static boolean isEmpty(String s) { return s == null || s.isEmpty(); }

    private static String currentAccount(Context c) {
        return CoordinatorConfig.hasBet365Credentials(c) ? WorkerIdentity.fingerprint(CoordinatorConfig.bet365Username(c)) : null;
    }

    /** True only while the grant is valid; a grant that no longer matches the present identity is revoked first. */
    static synchronized boolean enabled(Context c) {
        SharedPreferences p = CoordinatorConfig.prefs(c);
        Policy policy = evaluate(p.getBoolean(ENABLED, false), p.getString(WORKER, ""), p.getString(ACCOUNT, ""),
                WorkerIdentity.workerId(c), currentAccount(c));
        if (policy.decision == Decision.REVOKED) {
            p.edit().putBoolean(ENABLED, false).putLong(DISABLED_AT, System.currentTimeMillis())
                    .putString(REASON, "revoked automatically: " + policy.reason).commit();
        }
        return policy.decision == Decision.ALLOW;
    }

    /** Settings screen only: records the worker and account the grant is for. False when no account is configured. */
    static synchronized boolean enable(Context c) {
        String account = currentAccount(c);
        if (isEmpty(account)) return false;
        return CoordinatorConfig.prefs(c).edit().putBoolean(ENABLED, true).putLong(ENABLED_AT, System.currentTimeMillis())
                .putString(WORKER, WorkerIdentity.workerId(c)).putString(ACCOUNT, account)
                .putString(REASON, "enabled on the phone").commit();
    }

    static synchronized boolean disable(Context c) {
        return CoordinatorConfig.prefs(c).edit().putBoolean(ENABLED, false).putLong(DISABLED_AT, System.currentTimeMillis())
                .putString(REASON, "disabled on the phone").commit();
    }

    /** Health / dashboard view. Never includes the username. */
    static JSONObject state(Context c) {
        boolean allowed = enabled(c);
        SharedPreferences p = CoordinatorConfig.prefs(c);
        JSONObject o = new JSONObject();
        CoordinatorAgent.put(o, "enabled", allowed);
        CoordinatorAgent.put(o, "enabled_at_ms", p.getLong(ENABLED_AT, 0));
        CoordinatorAgent.put(o, "disabled_at_ms", p.getLong(DISABLED_AT, 0));
        CoordinatorAgent.put(o, "worker_id", p.getString(WORKER, ""));
        CoordinatorAgent.put(o, "authorised_account_fingerprint", p.getString(ACCOUNT, ""));
        CoordinatorAgent.put(o, "last_reason", p.getString(REASON, ""));
        return o;
    }
}
