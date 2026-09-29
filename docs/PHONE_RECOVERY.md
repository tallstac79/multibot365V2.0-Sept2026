# Android worker recovery and power

The worker is an Android system-bound AccessibilityService. Once the operator enables it, Android starts it after boot/user unlock; a BOOT_COMPLETED receiver must not try to manufacture an accessibility binding. The coordinator retries discovery and binding of Wi-Fi/Tailscale addresses automatically. Neither reconnect nor process restart replays an unfinished instruction. Tailscale must be connected and selected as Android's Always-on VPN. Do not enable a second VPN or require Internet lockdown merely to recover this worker.

A private startup activity may request Android's normal dismissal of a **non-secure swipe keyguard**, once per boot, within the first two minutes, while idle, with credential storage unlocked and the existing local worker/account grant valid. It finishes within five seconds, never opens the bookmaker, never enters credentials and never clicks a selection. A secure PIN/password/SIM keyguard is never requested for dismissal, even if Android considers it trusted. A manually locked device later in the boot is left alone. The outcome is visible in `/health.worker_health.startup_recovery`.

On the dedicated phone, exempt only the agent and Tailscale from battery optimization. With the already-authorized USB connection:

```powershell
adb -s R5CT61TE14Z shell cmd deviceidle whitelist +com.bet365agent
adb -s R5CT61TE14Z shell cmd deviceidle whitelist +com.tailscale.ipn
adb -s R5CT61TE14Z shell settings get secure always_on_vpn_app
```

The final command must report `com.tailscale.ipn`; inspect Android Settings → Connections → More connection settings → VPN → Tailscale → Always-on VPN if it does not. Keep the worker's existing execution permission, account binding and approval settings unchanged. Secure-lock/credential-unlock requirements are not bypassed. Force-stopping an app or disabling accessibility is an operator action and is not undone silently.

`/health.worker_health` now reports battery percentage, actual current in microamps when supported, charge counter, charger-presence/status, OS uptime, boot count, user-unlocked/lock state and the agent's battery-optimization exemption. Unknown current is null, not zero. No field controls execution. The diagnostic warning is `BATTERY_CRITICAL` at ≤5%, `BATTERY_LOW` at ≤15%, `UNPLUGGED`, or `DRAINING_WHILE_PLUGGED` after a decline of at least two percentage points over three minutes on the same power source. An instantaneous current sample is not sufficient to declare a charger good or bad. The trend resets with process restart; charge level and boot identity are still available immediately.

The existing database audit now retains `DEVICE_AVAILABILITY` on status transitions, including the exact prior successful backend check and the phone's last retained heartbeat. `DEVICE_POWER` retains changes in level, power source, warning, boot count and exemption. These are compact allowlisted diagnostic records, without credentials, instructions or receipts. Repeated identical/offline polls do not flood the history. No new schema, betting rule, strategy, stake, slippage, dispatch or approval policy is introduced.

For a recovery proof, temporarily pause dispatch using the existing operator control, leave intake running, wait until the phone is idle, then test Wi-Fi loss/restoration and reboot. Use only `/health`, OS diagnostics and the persistent instruction ledger. Do not submit a betting workflow, replay a timed-out instruction, or tap any slip. Restore the prior pause state only if the maintenance task still owns it.

## Physical limit

A powered-off phone cannot run the agent or Tailscale. On 28 September the phone exhausted its battery while USB remained present, then charged in off-mode until manually powered on. App restart logic cannot press the hardware power button or supply missing watts. Use a power source/cable that sustains the running workload and confirm battery charge is stable or rising under load. Do not assume `USB powered=true` proves sufficient charging, disable thermal protections, root the phone or alter bootloader settings to conceal inadequate power.

References: [Android BatteryManager current semantics](https://developer.android.com/reference/android/os/BatteryManager), [Android always-on VPN](https://support.google.com/work/android/answer/9213914?hl=en), [normal keyguard dismissal](https://developer.android.com/reference/android/app/KeyguardManager). Device-specific behavior is verified by retained boot logs and the recorded recovery proofs.
