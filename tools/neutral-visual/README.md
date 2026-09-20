# Physical Samsung visual acceptance

The phone captures the display, uses Tesseract word bounds to find the unique NEPTUNE button, taps via dispatchGesture and verifies COMPLETE from a new screenshot. SATURN is a distractor; a repeated click produces FAILED.

From the project root in PowerShell, using this host's installed toolchain:

```powershell
$env:JAVA_HOME = 'C:\Program Files\Microsoft\jdk-17.0.20.101-hotspot'
$env:JAVA_TOOL_OPTIONS = '-Djdk.net.unixdomain.tmpdir=C:\Users\WINDOWS11\Desktop\MultiBotV2.0\tmp'
New-Item -ItemType Directory -Force 'C:\Users\WINDOWS11\Desktop\MultiBotV2.0\tmp' | Out-Null
& 'C:\Users\WINDOWS11\AppData\Local\gradle-bootstrap\gradle-8.7\bin\gradle.bat' --offline -p android/Bet365Agent assembleDebug
$adb = 'C:\Users\WINDOWS11\AppData\Local\Android\Sdk\platform-tools\adb.exe'
& $adb -s R5CT61TE14Z install -r android/Bet365Agent/app/build/outputs/apk/debug/app-debug.apk
python tools/test_android_visual.py --adb $adb --serial R5CT61TE14Z --output evidence/my-run
```

The Java socket-directory setting resolves this host's Windows Unix-domain socket failure. The wrapper distribution is not cached, so use the existing Gradle 8.7 installation. Accessibility must be enabled, the phone unlocked, and Chrome onboarding complete. Allow service rebind after installation. The suite deliberately kills only com.bet365agent to test recovery. It closes its own server and forwarding afterward.

For the app's Visual Control button, keep this server running in a separate terminal:

```powershell
python -m http.server 8765 --bind 127.0.0.1 --directory tools/neutral-visual
```

Forward the port and open the app:

```powershell
& $adb -s R5CT61TE14Z reverse tcp:8765 tcp:8765
& $adb -s R5CT61TE14Z shell am start -n com.bet365agent/.MainActivity
```

Tap Visual Control. It opens a fresh neutral page and starts. Logs use AgentVisual; app-private evidence is files/visual/<run_id>/; runner state is shared_prefs/visual_agent.xml. The UI receives a mirrored result in ScanStore.

To trigger against an already opened page:

```powershell
& $adb -s R5CT61TE14Z shell am broadcast -n com.bet365agent/.VisualTestReceiver --es run_id unique-test-id
```

Use a new ID for new work. Reusing an ID intentionally does nothing. Add `--ez capture_only true --ei display_id 999` to probe the real invalid-display error. The debug-only receiver requires the shell's DUMP permission; it is not a coordinator interface.

Page variants: `?mode=duplicate`, `?mode=missing`, `?mode=unchanged`. Each must fail for its specific reason. Review results, screenshots and OCR bounds together; gesture acceptance alone is not a pass.
