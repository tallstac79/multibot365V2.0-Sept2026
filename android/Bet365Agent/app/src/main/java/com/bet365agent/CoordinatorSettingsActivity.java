package com.bet365agent;

import android.app.Activity;
import android.os.Bundle;
import android.widget.*;
import android.text.method.PasswordTransformationMethod;

/** Local pairing, start-page, and Bet365 login secrets; stay in app-private storage. */
public class CoordinatorSettingsActivity extends Activity {
    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        getWindow().addFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE);
        LinearLayout layout = new LinearLayout(this); layout.setOrientation(1); layout.setPadding(24,24,24,24);
        ScrollView scroll = new ScrollView(this); scroll.addView(layout); setContentView(scroll);
        TextView address = new TextView(this);
        address.setText("Coordinator HTTP: " + Bet365AccessibilityService.coordinatorEndpoint() + "\nTrusted private Wi-Fi or Tailscale. Phone awake/unlocked. Pair token with Windows."); layout.addView(address);
        EditText token = new EditText(this); token.setText(CoordinatorConfig.token(this)); token.setSingleLine(true); token.setTransformationMethod(PasswordTransformationMethod.getInstance()); layout.addView(token);
        Button show = new Button(this); show.setText("Show pairing token"); layout.addView(show); show.setOnClickListener(v -> token.setTransformationMethod(null));
        TextView label = new TextView(this); label.setText("Start page URL (blank = built-in neutral test page)"); layout.addView(label);
        EditText url = new EditText(this); url.setSingleLine(true); url.setText(CoordinatorConfig.prefs(this).getString("start_url", "")); layout.addView(url);
        TextView b365 = new TextView(this); b365.setText("Bet365 login (app-private; used only for visual session restore; never logged to evidence)"); layout.addView(b365);
        EditText user = new EditText(this); user.setSingleLine(true); user.setHint("Bet365 username / email"); user.setText(CoordinatorConfig.bet365Username(this)); layout.addView(user);
        EditText pass = new EditText(this); pass.setSingleLine(true); pass.setHint("Bet365 password"); pass.setTransformationMethod(PasswordTransformationMethod.getInstance()); pass.setText(CoordinatorConfig.bet365Password(this)); layout.addView(pass);
        Button save = new Button(this); save.setText("Save connection + Bet365 settings"); layout.addView(save);
        save.setOnClickListener(v -> {
            String secret = token.getText().toString(), target = url.getText().toString().trim();
            android.net.Uri uri = android.net.Uri.parse(target);
            if (secret.length() < 32 || (!target.isEmpty() && (!("http".equals(uri.getScheme()) || "https".equals(uri.getScheme())) || uri.getHost() == null || uri.getUserInfo() != null))) {
                Toast.makeText(this, "Use a token of at least 32 characters and a valid HTTP(S) URL", Toast.LENGTH_LONG).show(); return;
            }
            boolean ok = CoordinatorConfig.prefs(this).edit().putString("token", secret).putString("start_url", target).commit()
                    && CoordinatorConfig.saveBet365Credentials(this, user.getText().toString(), pass.getText().toString());
            Toast.makeText(this, ok ? "Saved" : "Could not save", Toast.LENGTH_SHORT).show();
        });
    }
}
