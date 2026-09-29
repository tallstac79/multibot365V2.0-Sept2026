package com.bet365agent;

import android.app.Activity;
import android.app.KeyguardManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.WindowManager;
import android.widget.TextView;

/** Private, five-second system-keyguard request; no automation gestures or credential handling. */
public final class WorkerRecoveryActivity extends Activity {
    private final Handler main=new Handler(Looper.getMainLooper());
    private boolean requested;
    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        KeyguardManager k=(KeyguardManager)getSystemService(KEYGUARD_SERVICE);
        // Recheck at the point of use; even a trusted secure lock must never be dismissed by this feature.
        if(k==null || k.isKeyguardSecure() || !LocalExecution.enabled(this)) { done("NEEDS_OPERATOR");return; }
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON);
        TextView text=new TextView(this);text.setText("Restoring worker after restart…");text.setPadding(32,48,32,32);setContentView(text);
        main.postDelayed(()->done("NEEDS_OPERATOR_TIMEOUT"),5000);
    }
    @Override public void onResume() {
        super.onResume();
        if(isFinishing() || requested)return;
        requested=true;
        main.postDelayed(()->{
            KeyguardManager k=(KeyguardManager)getSystemService(KEYGUARD_SERVICE);
            if(k==null || k.isKeyguardSecure() || !LocalExecution.enabled(this)) { done("NEEDS_OPERATOR");return; }
            k.requestDismissKeyguard(this,new KeyguardManager.KeyguardDismissCallback(){
                @Override public void onDismissSucceeded(){done("NON_SECURE_KEYGUARD_DISMISSED");}
                @Override public void onDismissError(){done("NEEDS_OPERATOR_ERROR");}
                @Override public void onDismissCancelled(){done("NEEDS_OPERATOR_CANCELLED");}
            });
        },100);
    }
    private void done(String outcome){main.removeCallbacksAndMessages(null);StartupRecovery.note(this,outcome);finish();}
    @Override public void onDestroy(){main.removeCallbacksAndMessages(null);super.onDestroy();}
}
