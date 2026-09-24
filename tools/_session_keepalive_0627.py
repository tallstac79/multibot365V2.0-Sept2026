"""Aggressive-but-safe keepalive: refresh session before 120s gate; never while tips open."""
import json, time, subprocess, sqlite3, urllib.request
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(r"C:\Users\WINDOWS11\Desktop\MultiBotV2.0\MultiBot365")
EV = ROOT / "evidence" / "ready-reproof-0.6.27-20260923"
PY = r"C:\Users\WINDOWS11\AppData\Local\Programs\Python\Python311\python.exe"
ADB = r"C:\Users\WINDOWS11\Desktop\platform-tools\adb.exe"
STATUS = ROOT / ".local" / "pipeline_status.json"
DB = ROOT / ".local" / "pipeline.sqlite3"
COORD = json.loads((ROOT / ".local" / "coordinator.json").read_text(encoding="utf-8-sig"))
FINAL = EV / "final-summary.json"
LOG = EV / "session-keepalive.jsonl"
LOCK = EV / "session-check.lock"
EV.mkdir(parents=True, exist_ok=True)
(EV / "session-keepalive").mkdir(parents=True, exist_ok=True)

def log(msg, **kw):
    row = {"t": datetime.now(timezone.utc).isoformat(), "msg": msg, **kw}
    print(json.dumps(row), flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")

def health():
    req = urllib.request.Request(COORD["url"].rstrip("/") + "/health",
        headers={"Authorization": "Bearer " + COORD["token"]})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

def open_tips():
    con = sqlite3.connect(str(DB), timeout=10)
    n = con.execute(
        "SELECT COUNT(*) FROM instructions WHERE terminal=0 AND state IN ('QUEUED','DISPATCHED','DEVICE_ACTIVE','READY')"
    ).fetchone()[0]
    con.close()
    return n

def store_session_age():
    con = sqlite3.connect(str(DB), timeout=10)
    row = con.execute("SELECT state, observed_at FROM session_state WHERE device_id='galaxy-a13-5g'").fetchone()
    con.close()
    if not row:
        return "NONE", 9999
    observed = datetime.fromisoformat(row[1])
    age = (datetime.now(timezone.utc) - observed).total_seconds()
    return row[0], age

def health_age(h):
    sess = h.get("session") or {}
    ms = sess.get("observed_at_ms")
    if not ms:
        return (sess.get("state") or "NONE"), 9999
    return sess.get("state"), max(0, (time.time() * 1000 - float(ms)) / 1000.0)

start = time.time()
log("keepalive_v3_start", note="refresh at store_age>90 when IDLE and no open tips; never overlap")
while time.time() - start < 55 * 60:
    if FINAL.exists():
        log("stop_final_exists"); break
    try:
        st = json.loads(STATUS.read_text(encoding="utf-8-sig"))
        if st.get("dispatch_enabled") is False and time.time() - start > 180:
            log("stop_dispatch_off"); break
    except Exception:
        pass
    try:
        subprocess.run([ADB, "-s", "R5CT61TE14Z", "shell", "input", "keyevent", "KEYCODE_WAKEUP"], check=False, timeout=10)
        subprocess.run([ADB, "-s", "R5CT61TE14Z", "shell", "svc", "power", "stayon", "true"], check=False, timeout=10)
    except Exception as e:
        log("adb_err", error=str(e))
    try:
        h = health()
        open_n = open_tips()
        h_state, h_age = health_age(h)
        s_state, s_age = store_session_age()
        agent = h.get("state")
        cur = h.get("current_instruction")
        log("probe", agent=agent, health_session=h_state, health_age=int(h_age),
            store_session=s_state, store_age=int(s_age), open_tips=open_n, current=cur)
        need = (s_state != "AUTHENTICATED") or (s_age > 90) or (h_state != "AUTHENTICATED") or (h_age > 90)
        safe = agent == "IDLE" and open_n == 0 and not cur and not LOCK.exists()
        if need and safe:
            LOCK.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
            try:
                out = subprocess.check_output(
                    [PY, "tools/session_check.py", "--evidence-dir", str(EV / "session-keepalive")],
                    cwd=str(ROOT), text=True, timeout=90)
                data = json.loads(out[out.find("{"):])
                log("session_refresh", state=(data.get("session") or {}).get("state"),
                    detail=(data.get("result") or {}).get("detail"), iid=data.get("instruction_id"))
            finally:
                if LOCK.exists():
                    LOCK.unlink()
        else:
            log("skip", need=need, safe=safe, reason=("fresh" if not need else "not_safe"))
    except Exception as e:
        log("keepalive_err", error=str(e))
        if LOCK.exists():
            try: LOCK.unlink()
            except Exception: pass
    time.sleep(12)
log("keepalive_exit")
