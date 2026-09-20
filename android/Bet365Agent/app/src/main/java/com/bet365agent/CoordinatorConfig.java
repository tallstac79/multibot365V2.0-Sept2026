package com.bet365agent;

import android.content.Context;
import android.content.SharedPreferences;
import java.security.SecureRandom;

final class CoordinatorConfig {
    static final int PORT = 8767;
    static SharedPreferences prefs(Context context) { return context.getSharedPreferences("coordinator_config", 0); }
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
}
