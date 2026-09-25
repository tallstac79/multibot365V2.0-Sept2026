package com.bet365agent;

import android.content.Context;
import android.content.SharedPreferences;
import androidx.security.crypto.EncryptedSharedPreferences;
import androidx.security.crypto.MasterKey;

/**
 * Bet365 login credentials in Android secure storage: EncryptedSharedPreferences under an Android Keystore
 * master key (AES-256-GCM values, AES-256-SIV keys), app-private. Values are never logged, never written to
 * evidence and never OCR-verified (the password goes through the accessibility IME into a masked field).
 *
 * Migration: the legacy plain app-private prefs (bet365_username / bet365_password) are copied into the
 * encrypted store once, read back and compared, and only then removed. If the secure store cannot be
 * opened, authentication and credential writes fail closed. Legacy data is never an authentication fallback.
 */
final class SecureCredentials {
    private static final String FILE = "bet365_credentials";
    private static volatile String lastError, storeKind = "unopened";

    private SecureCredentials() {}

    private static SharedPreferences secure(Context c) throws Exception {
        MasterKey key = new MasterKey.Builder(c).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build();
        return EncryptedSharedPreferences.create(c, FILE, key,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV, EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM);
    }

    interface Opener { SharedPreferences open() throws Exception; }

    /** Null means unavailable; callers must neither authenticate nor save plaintext. */
    private static synchronized SharedPreferences store(Context c) {
        SharedPreferences legacy = CoordinatorConfig.prefs(c);
        return open(legacy, () -> secure(c));
    }

    static synchronized SharedPreferences open(SharedPreferences legacy, Opener opener) {
        try {
            SharedPreferences enc = opener.open();
            lastError = null;
            if (legacy.contains("bet365_password") || legacy.contains("bet365_username")) {
                String u = legacy.getString("bet365_username", ""), p = legacy.getString("bet365_password", "");
                if (!enc.contains("password") && !enc.edit().putString("username", u).putString("password", p).commit())
                    throw new IllegalStateException("Secure migration write failed");
                boolean verified = u.equals(enc.getString("username", null)) && p.equals(enc.getString("password", null));
                if (verified) {
                    if (!legacy.edit().remove("bet365_username").remove("bet365_password").commit())
                        throw new IllegalStateException("Legacy migration cleanup failed");
                    storeKind = "encrypted (migrated)";
                } else throw new IllegalStateException("Secure migration read-back mismatch");
            } else storeKind = "encrypted";
            return enc;
        } catch (Exception e) {
            lastError = e.getClass().getSimpleName();
            storeKind = "unavailable (" + lastError + ")";
            return null;
        }
    }

    static String username(Context c) { SharedPreferences s = store(c); return s == null ? "" : s.getString("username", ""); }
    static String password(Context c) { SharedPreferences s = store(c); return s == null ? "" : s.getString("password", ""); }
    static boolean has(Context c) { return !username(c).isEmpty() && !password(c).isEmpty(); }

    static boolean save(Context c, String username, String password) {
        SharedPreferences s = store(c);
        if (s == null) return false;
        return s.edit().putString("username", username == null ? "" : username.trim())
                .putString("password", password == null ? "" : password).commit();
    }

    static String lastError() { return lastError; }
    static String storeKind() { return storeKind; }
}
