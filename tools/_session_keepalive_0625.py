"""Refresh AUTHENTICATED session every ~70s while 0.6.25 dispatch watch runs."""
import json, time, subprocess
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(r"C:\Users\WINDOWS11\Desktop\MultiBotV2.0\MultiBot365")
EV = ROOT / "evidence" / "ready-reproof-0.6.25-20260923"
PY = r"C:\Users\WINDOWS11\AppData\Local\Programs\Python\Python311\python.exe"
ADB = r"C:\Users\WINDOWS11\Desktop\platform-tools\adb.exe"
STATUS = ROOT / ".local" / "pipeline_status.json"
FINAL = EV / "final-summary.json"
LOG = EV / "session-keepalive.jsonl"

def log(msg, **kw):
    row = {"t": datetime.now(timezone.utc).isoformat(), "msg": msg, **kw}
    print(json.dumps(row), flush=True)
    LOG.open("a", encoding="utf-8").write(json.dumps(row) + "\n")

start = time.time()
while time.time() - start < 55 * 60:
    if FINAL.exists():
        log("stop_final_exists")
        break
    try:
        st = json.loads(STATUS.read_text(encoding="utf-8-sig"))
        if st.get("dispatch_enabled") is False and time.time() - start > 180:
            log("stop_dispatch_off")
            break
    except Exception:
        pass
    try:
        subprocess.run([ADB, "-s", "R5CT61TE14Z", "shell", "input", "keyevent", "KEYCODE_WAKEUP"], check=False, timeout=10)
        subprocess.run([ADB, "-s", "R5CT61TE14Z", "shell", "svc", "power", "stayon", "true"], check=False, timeout=10)
    except Exception as e:
        log("adb_err", error=str(e))
    try:
        out = subprocess.check_output(
            [PY, "tools/session_check.py", "--evidence-dir", str(EV / "session-keepalive")],
            cwd=str(ROOT), text=True, timeout=90)
        data = json.loads(out[out.find("{"):])
        sess = (data.get("session") or {}).get("state")
        detail = (data.get("result") or {}).get("detail")
        log("session_refresh", state=sess, detail=detail, iid=data.get("instruction_id"))
    except Exception as e:
        log("session_check_err", error=str(e))
    time.sleep(70)
log("keepalive_exit")
