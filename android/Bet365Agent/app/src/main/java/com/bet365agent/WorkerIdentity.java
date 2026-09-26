package com.bet365agent;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Locale;

/**
 * Non-secret identity the backend binds automatic approvals to (2026-09-26): which installation of this app
 * (worker) and which bookmaker account. Neither value reveals the username; both travel in the health payload
 * and must equal the backend's expected_worker_id / expected_account_fingerprint before it approves anything.
 */
final class WorkerIdentity {
    private WorkerIdentity() {}

    /** sha256 hex prefix (12) of the trimmed, lower-cased username; null when no username is configured. */
    static String fingerprint(String username) {
        String user = username == null ? "" : username.trim().toLowerCase(Locale.US);
        return user.isEmpty() ? null : sha256(user).substring(0, 12);
    }

    /** Stable per-installation id, generated once and kept in app-private prefs (survives reboot, not reinstall). */
    static synchronized String workerId(android.content.Context context) {
        android.content.SharedPreferences prefs = CoordinatorConfig.prefs(context);
        String id = prefs.getString("worker_id", "");
        if (id.isEmpty()) {
            byte[] bytes = new byte[16];
            new SecureRandom().nextBytes(bytes);
            StringBuilder hex = new StringBuilder();
            for (byte b : bytes) hex.append(String.format(Locale.US, "%02x", b & 255));
            id = "w-" + sha256(hex.toString()).substring(0, 12);
            if (!prefs.edit().putString("worker_id", id).commit()) throw new IllegalStateException("Cannot persist worker id");
        }
        return id;
    }

    static String sha256(String text) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8));
            StringBuilder hex = new StringBuilder();
            for (byte b : digest) hex.append(String.format(Locale.US, "%02x", b & 255));
            return hex.toString();
        } catch (java.security.NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }
}
