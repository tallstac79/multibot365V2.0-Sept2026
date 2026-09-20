package com.bet365agent;

import android.app.Activity;
import android.os.Bundle;
import android.widget.*;
import android.text.method.PasswordTransformationMethod;

/** Local pairing and start-page configuration; secrets stay in app-private storage. */
public class CoordinatorSettingsActivity extends Activity {
    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        getWindow().addFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE);
        LinearLayout layout = new LinearLayout(this); layout.setOrientation(1); layout.setPadding(24,24,24,24);
        setContentView(layout);
        TextView address = new TextView(this);
        address.setText("Coordinator HTTP: " + Bet365AccessibilityService.coordinatorEndpoint() + "\nUse a trusted private Wi-Fi network. Keep the phone awake and unlocked. Pair the token below with Windows."); layout.addView(address);
        EditText token = new EditText(this); token.setText(CoordinatorConfig.token(this)); token.setSingleLine(true); token.setTransformationMethod(PasswordTransformationMethod.getInstance()); layout.addView(token);
        Button show = new Button(this); show.setText("Show pairing token"); layout.addView(show); show.setOnClickListener(v -> token.setTransformationMethod(null));
        TextView label = new TextView(this); label.setText("Start page URL (blank uses built-in neutral test page)"); layout.addView(label);
        EditText url = new EditText(this); url.setSingleLine(true); url.setText(CoordinatorConfig.prefs(this).getString("start_url", "")); layout.addView(url);
        Button save = new Button(this); save.setText("Save connection settings"); layout.addView(save);
        save.setOnClickListener(v -> {
            String secret = token.getText().toString(), target = url.getText().toString().trim();
            android.net.Uri uri = android.net.Uri.parse(target);
            if (secret.length() < 32 || (!target.isEmpty() && (!("http".equals(uri.getScheme()) || "https".equals(uri.getScheme())) || uri.getHost() == null || uri.getUserInfo() != null))) {
                Toast.makeText(this, "Use a token of at least 32 characters and a valid HTTP(S) URL", Toast.LENGTH_LONG).show(); return;
            }
            boolean ok = CoordinatorConfig.prefs(this).edit().putString("token", secret).putString("start_url", target).commit();
            Toast.makeText(this, ok ? "Saved" : "Could not save", Toast.LENGTH_SHORT).show();
        });
    }
}
