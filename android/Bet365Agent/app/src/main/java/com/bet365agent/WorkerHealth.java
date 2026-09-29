package com.bet365agent;

import android.app.KeyguardManager;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.BatteryManager;
import android.os.PowerManager;
import android.os.SystemClock;
import android.os.UserManager;
import android.provider.Settings;
import org.json.JSONObject;

/** Low-cost power and boot diagnostics. No UI, external requests, wake locks or execution changes. */
final class WorkerHealth {
    private final Context context;
    private final PowerTrend trend = new PowerTrend();
    private long sampledAt = -1;
    private JSONObject battery = new JSONObject();

    WorkerHealth(Context context) { this.context = context; }

    synchronized JSONObject snapshot() {
        JSONObject result = new JSONObject();
        long elapsed = SystemClock.elapsedRealtime();
        try {
            if (sampledAt < 0 || elapsed - sampledAt >= 10_000L) {
                Intent b = context.registerReceiver(null, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
                JSONObject next = new JSONObject();
                if (b != null) {
                    int raw = b.getIntExtra(BatteryManager.EXTRA_LEVEL, -1);
                    int scale = b.getIntExtra(BatteryManager.EXTRA_SCALE, -1);
                    int level = raw >= 0 && scale > 0 ? Math.round(raw * 100f / scale) : -1;
                    int plug = b.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0);
                    int status = b.getIntExtra(BatteryManager.EXTRA_STATUS, BatteryManager.BATTERY_STATUS_UNKNOWN);
                    next.put("level_percent", level < 0 ? JSONObject.NULL : level);
                    next.put("plugged", plug).put("status", status);
                    next.put("charging", status == BatteryManager.BATTERY_STATUS_CHARGING || status == BatteryManager.BATTERY_STATUS_FULL);
                    next.put("temperature_tenths_c", b.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, 0));
                    next.put("warning", trend.observe(elapsed, level, plug));
                    BatteryManager manager = (BatteryManager) context.getSystemService(Context.BATTERY_SERVICE);
                    next.put("current_now_ua", property(manager, BatteryManager.BATTERY_PROPERTY_CURRENT_NOW));
                    next.put("charge_counter_uah", property(manager, BatteryManager.BATTERY_PROPERTY_CHARGE_COUNTER));
                } else next.put("warning", "UNKNOWN");
                next.put("observed_at_ms", System.currentTimeMillis());
                battery = next; sampledAt = elapsed;
            }
            result.put("battery", battery).put("os_uptime_ms", elapsed);
            result.put("boot_count", Settings.Global.getInt(context.getContentResolver(), Settings.Global.BOOT_COUNT, -1));
            UserManager users = (UserManager) context.getSystemService(Context.USER_SERVICE);
            result.put("user_unlocked", users != null && users.isUserUnlocked());
            PowerManager power = (PowerManager) context.getSystemService(Context.POWER_SERVICE);
            result.put("interactive", power != null && power.isInteractive());
            result.put("battery_optimization_exempt", power != null && power.isIgnoringBatteryOptimizations(context.getPackageName()));
            KeyguardManager keyguard = (KeyguardManager) context.getSystemService(Context.KEYGUARD_SERVICE);
            result.put("keyguard_locked", keyguard != null && keyguard.isKeyguardLocked());
            result.put("keyguard_secure", keyguard != null && keyguard.isKeyguardSecure());
            result.put("startup_recovery", StartupRecovery.state(context));
        } catch (Exception error) {
            // Diagnostic collection must never make /health fail or decide that an otherwise healthy worker is offline.
            try { result.put("diagnostic_error", error.getClass().getSimpleName()); } catch (Exception ignored) { }
        }
        return result;
    }

    private static Object property(BatteryManager manager, int property) {
        if (manager == null) return JSONObject.NULL;
        int value = manager.getIntProperty(property);
        return value == Integer.MIN_VALUE ? JSONObject.NULL : value;
    }
}
