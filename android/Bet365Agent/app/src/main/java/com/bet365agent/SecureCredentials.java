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
 * opened on this device the legacy copy keeps working and {@link #storeKind} says so on /health.
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

    /** The store to read/write: encrypted when it opens (with a verified one-time migration), else legacy. */
    private static synchronized SharedPreferences store(Context c) {
        SharedPreferences legacy = CoordinatorConfig.prefs(c);
        try {
            SharedPreferences enc = secure(c);
            lastError = null;
            if (legacy.contains("bet365_password") || legacy.contains("bet365_username")) {
                String u = legacy.getString("bet365_username", ""), p = legacy.getString("bet365_password", "");
                if (!enc.contains("password")) enc.edit().putString("username", u).putString("password", p).commit();
                boolean verified = u.equals(enc.getString("username", null)) && p.equals(enc.getString("password", null));
                if (verified) { legacy.edit().remove("bet365_username").remove("bet365_password").commit(); storeKind = "encrypted (migrated)"; }
                else { storeKind = "legacy_plain (migration read-back mismatch)"; return legacy; }
            } else storeKind = "encrypted";
            return enc;
        } catch (Exception e) {
            lastError = e.getClass().getSimpleName();
            storeKind = "legacy_plain (" + lastError + ")";
            return legacy;
        }
    }

    private static String key(SharedPreferences s, String encKey, String legacyKey) {
        return s.contains(encKey) ? encKey : legacyKey;
    }

    static String username(Context c) { SharedPreferences s = store(c); return s.getString(key(s, "username", "bet365_username"), ""); }
    static String password(Context c) { SharedPreferences s = store(c); return s.getString(key(s, "password", "bet365_password"), ""); }
    static boolean has(Context c) { return !username(c).isEmpty() && !password(c).isEmpty(); }

    static boolean save(Context c, String username, String password) {
        SharedPreferences s = store(c);
        boolean encrypted = storeKind.startsWith("encrypted");
        return s.edit().putString(encrypted ? "username" : "bet365_username", username == null ? "" : username.trim())
                .putString(encrypted ? "password" : "bet365_password", password == null ? "" : password).commit();
    }

    static String lastError() { return lastError; }
    static String storeKind() { return storeKind; }
}
