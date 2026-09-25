package com.bet365agent;

import android.content.Context;
import android.content.SharedPreferences;
import java.security.SecureRandom;

final class CoordinatorConfig {
    static final int PORT = 8767;
    static SharedPreferences prefs(Context context) { return context.getSharedPreferences("coordinator_config", 0); }
    // Local-only, expires automatically and is invalidated by a phone reboot (elapsed clock).
    static boolean finalActionArmed(Context c) {
        long until = prefs(c).getLong("final_action_until_elapsed", 0);
        long armed = prefs(c).getLong("final_action_at_elapsed", Long.MAX_VALUE);
        long now = android.os.SystemClock.elapsedRealtime();
        return prefs(c).getInt("final_action_boot", -1) == android.provider.Settings.Global.getInt(c.getContentResolver(), "boot_count", -2)
                && armed <= now && now < until && until - armed <= 3_600_000L;
    }
    static synchronized String token(Context context) {
        String token = prefs(context).getString("token", "");
        if (token.isEmpty()) {
            byte[] bytes = new byte[32]; new SecureRandom().nextBytes(bytes);
            StringBuilder text = new StringBuilder();
            for (byte b : bytes) text.append(String.format(java.util.Locale.US, "%02x", b & 255));
            token = text.toString();
            if (!prefs(context).edit().putString("token", token).commit()) throw new IllegalStateException("Cannot persist pairing token");
        }
        return token;
    }
    /** Bet365 username for visual login; app-private prefs only ? never written to evidence. */
    /** Milestone C11: hybrid = fast on-device OCR for every pre-tap read, Tesseract for numeric regions, the
     *  enhanced second-opinion re-read and the receipt reference. Rollback: POST /config/ocr_engine legacy (persisted)
     *  or change this default. */
    static String ocrEngine(Context context) { return prefs(context).getString("ocr_engine", "hybrid"); }
    static boolean setOcrEngine(Context context, String engine) {
        if (!java.util.Set.of("legacy", "fast", "hybrid").contains(engine)) return false;
        return prefs(context).edit().putString("ocr_engine", engine).commit();
    }
    // Credentials live in SecureCredentials (EncryptedSharedPreferences, Android Keystore master key); never in source.
    static String bet365Username(Context context) { return SecureCredentials.username(context); }
    static String bet365Password(Context context) { return SecureCredentials.password(context); }
    static boolean hasBet365Credentials(Context context) { return SecureCredentials.has(context); }
    static boolean saveBet365Credentials(Context context, String username, String password) {
        return SecureCredentials.save(context, username, password);
    }
}
