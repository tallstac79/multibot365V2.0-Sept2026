package com.bet365agent;

import android.app.KeyguardManager;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.SystemClock;
import android.os.UserManager;
import android.provider.Settings;
import org.json.JSONObject;

/** One boot-only, non-secure keyguard request. Never launches a bookmaker or submits/replays work. */
final class StartupRecovery {
    static boolean eligible(boolean granted, boolean secure, boolean unlocked, boolean locked,
                            boolean busy, long uptime, int boot, int attemptedBoot) {
        return granted && !secure && unlocked && locked && !busy && uptime >= 0 && uptime < 120_000L
                && boot >= 0 && boot != attemptedBoot;
    }
    static SharedPreferences prefs(Context c) { return c.getSharedPreferences("worker_recovery", Context.MODE_PRIVATE); }
    static void note(Context c, String outcome) {
        prefs(c).edit().putString("outcome",outcome).putLong("updated_at_ms",System.currentTimeMillis()).apply();
    }
    static void request(Context c, boolean busy) {
        try {
            KeyguardManager k=(KeyguardManager)c.getSystemService(Context.KEYGUARD_SERVICE);
            UserManager u=(UserManager)c.getSystemService(Context.USER_SERVICE);
            int boot=Settings.Global.getInt(c.getContentResolver(),Settings.Global.BOOT_COUNT,-1);
            if(k==null || u==null || !eligible(LocalExecution.enabled(c),k.isKeyguardSecure(),u.isUserUnlocked(),
                    k.isKeyguardLocked(),busy,SystemClock.elapsedRealtime(),boot,prefs(c).getInt("attempted_boot",-1))) return;
            // Durable bound: a process reconnect during this boot cannot repeatedly take over the screen.
            if(!prefs(c).edit().putInt("attempted_boot",boot).commit()) return;
            note(c,"REQUESTED_NON_SECURE_DISMISS");
            c.startActivity(new Intent(c,WorkerRecoveryActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        } catch(Exception e) { note(c,"NEEDS_OPERATOR_"+e.getClass().getSimpleName()); }
    }
    static JSONObject state(Context c) {
        JSONObject o=new JSONObject();
        CoordinatorAgent.put(o,"attempted_boot",prefs(c).getInt("attempted_boot",-1));
        CoordinatorAgent.put(o,"outcome",prefs(c).getString("outcome","not requested"));
        CoordinatorAgent.put(o,"updated_at_ms",prefs(c).getLong("updated_at_ms",0));
        return o;
    }
}
