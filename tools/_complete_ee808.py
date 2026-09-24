"""Complete one-shot for already-dispatched on-ee808246d3d54b48f3db0bd7."""
import json, sqlite3, time, urllib.request, subprocess, os, signal
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\Users\WINDOWS11\Desktop\MultiBotV2.0\MultiBot365")
EV = ROOT / "evidence" / "ready-reproof-0.6.27-20260923"
DB = ROOT / ".local" / "pipeline.sqlite3"
CFG = ROOT / ".local" / "pipeline.json"
STATUS = ROOT / ".local" / "pipeline_status.json"
COORD = json.loads((ROOT / ".local" / "coordinator.json").read_text(encoding="utf-8-sig"))
PY = r"C:\Users\WINDOWS11\AppData\Local\Programs\Python\Python311\python.exe"
IID = "on-ee808246d3d54b48f3db0bd7"
LOG = EV / "completer.jsonl"

def log(msg, **kw):
    row = {"t": datetime.now(timezone.utc).isoformat(), "msg": msg, **kw}
    print(json.dumps(row), flush=True)
    LOG.open("a", encoding="utf-8").write(json.dumps(row) + "\n")

def health():
    req = urllib.request.Request(COORD["url"].rstrip("/") + "/health",
        headers={"Authorization": "Bearer " + COORD["token"]})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

def set_dispatch(enabled: bool):
    cfg = json.loads(CFG.read_text(encoding="utf-8-sig"))
    cfg["pipeline"]["dispatch_enabled"] = bool(enabled)
    # keep session_max_age for now; will leave as configured
    CFG.write_text(json.dumps(cfg, indent=4) + "\n", encoding="utf-8")

def restart_pipeline():
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'pipeline_service' } | ForEach-Object { $_.ProcessId }"],
            text=True, cwd=str(ROOT))
        for line in out.splitlines():
            if line.strip().isdigit():
                os.kill(int(line.strip()), signal.SIGTERM)
                time.sleep(2)
    except Exception as e:
        log("kill_err", error=str(e))
    flags = 0x00000200 | 0x00000008
    subprocess.Popen([PY, "-u", "-m", "tools.pipeline_service", "run"], cwd=str(ROOT),
                     stdout=open(ROOT / "logs" / "pipeline.stdout.log", "a"),
                     stderr=open(ROOT / "logs" / "pipeline.stderr.log", "a"),
                     creationflags=flags)
    time.sleep(4)

TERMINALS = {
    "READY", "STALE", "REJECTED", "DEVICE_OFFLINE", "SESSION_REQUIRED",
    "FAIL", "UNKNOWN", "CANCELLED", "ABORTED", "TIMEOUT", "EXPIRED",
    "PRICE_CHANGED", "LINE_CHANGED", "BELOW_MINIMUM", "TARGET_NOT_FOUND",
    "COMPLETED", "WRONG_EVENT",
}

con = sqlite3.connect(str(DB), timeout=30)
con.row_factory = sqlite3.Row
log("completer_start", iid=IID)
deadline = time.time() + 240
final = None
while time.time() < deadline:
    r = con.execute("SELECT * FROM instructions WHERE instruction_id=?", (IID,)).fetchone()
    if r is None:
        time.sleep(2); continue
    log("state", state=r["state"], terminal=r["terminal"], stage=r["device_stage"], reason=r["failure_reason"])
    if r["terminal"] or r["state"] in TERMINALS:
        rp = {}
        if r["result_payload"]:
            try: rp = json.loads(r["result_payload"])
            except Exception: rp = {"raw": r["result_payload"]}
        (EV / "result-payload.json").write_text(json.dumps(rp, indent=2), encoding="utf-8")
        (EV / f"instruction-{IID}-{r['state']}.json").write_text(
            json.dumps(dict(r), indent=2, default=str), encoding="utf-8")
        if r["dispatch_payload"]:
            try:
                dp = json.loads(r["dispatch_payload"])
                (EV / "dispatch-payload.json").write_text(json.dumps(dp, indent=2), encoding="utf-8")
            except Exception:
                dp = {}
        else:
            dp = {}
        ready = rp.get("ready_state") if isinstance(rp.get("ready_state"), dict) else {}
        evidence = rp.get("evidence") if isinstance(rp.get("evidence"), dict) else {}
        qe = rp.get("query_evidence") or evidence.get("query_evidence") or {}
        if not isinstance(qe, dict): qe = {}
        final = {
            "PARSE": "PARSED",
            "RULES": "ACCEPT",
            "SESSION": ready.get("session") or r["session_state"] or "N/A",
            "SPORTS_CONTEXT": rp.get("sports_context") or ready.get("sports_context") or rp.get("stage") or r["device_stage"] or "N/A",
            "SEARCH": rp.get("stage") or r["device_stage"] or "N/A",
            "QUERY_USED": qe.get("query") or qe.get("requested_text") or dp.get("query") or f"{r['home']}||{r['away']}",
            "FIXTURE": f"{ready.get('fixture_home') or r['home']} vs {ready.get('fixture_away') or r['away']}",
            "MARKET": ready.get("market") or r["market"],
            "SIDE": ready.get("selection_role") or ready.get("side") or r["selection"],
            "LINE": ready.get("line") if ready.get("line") is not None else r["line"],
            "PRICE": ready.get("price") or r["observed_price"] or "N/A",
            "STAKE": ready.get("stake") or r["stake"] or "N/A",
            "BETSLIP_VERIFICATION": ready.get("betslip_verification") or ready.get("betslip") or rp.get("verification_detail") or r["failure_reason"] or "N/A",
            "READY": "YES" if r["state"] == "READY" else f"NO ({r['state']})",
            "FINAL_ACTION_STATE": ready.get("final_action_state") or ready.get("complete_execution_ready") or ready.get("state") or r["device_stage"] or r["state"],
            "RESULT": r["state"],
            "DASHBOARD": f"instruction {IID} state={r['state']} device_stage={r['device_stage']} failure={r['failure_reason']}",
            "FINAL_STATUS": r["state"],
            "COMMIT": "f108af8",
            "APP_VERSION": "0.6.27-sports",
            "VERSION_CODE": 39,
            "ALERT_ID": IID,
            "DISPATCH_NOW": None,
            "WAGER_SUBMITTED": bool(ready.get("wager_submitted") or rp.get("wager_submitted")),
            "execution_mode": dp.get("execution_mode"),
            "failure_reason": r["failure_reason"],
            "device_stage": r["device_stage"],
            "dispatched_at": r["dispatched_at"],
            "completed_at": r["completed_at"],
            "evidence_dir": str(EV),
            "hotfix": "row.get->row[] for away in build_payload",
            "session_max_age_seconds_runtime": 180,
        }
        break
    time.sleep(3)

if final is None:
    final = {"FINAL_STATUS": "WATCH_TIMEOUT", "ALERT_ID": IID, "RESULT": "WATCH_TIMEOUT"}

# disable dispatch immediately
set_dispatch(False)
log("dispatch_disabled")
restart_pipeline()
time.sleep(3)
st = json.loads(STATUS.read_text(encoding="utf-8-sig"))
final["DISPATCH_NOW"] = st.get("dispatch_enabled")
(EV / "dispatch-disable.json").write_text(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "status": st}, indent=2), encoding="utf-8")
try:
    h = health()
    (EV / "health-final.json").write_text(json.dumps(h, indent=2), encoding="utf-8")
    final["health_end_session"] = (h.get("session") or {}).get("state")
    final["health_end_last_result"] = h.get("last_result")
except Exception as e:
    final["health_end_error"] = str(e)
(EV / "final-summary.json").write_text(json.dumps(final, indent=2), encoding="utf-8")
log("DONE", **{k: final.get(k) for k in ("FINAL_STATUS","READY","SEARCH","QUERY_USED","STAKE","DISPATCH_NOW")})
print("DONE", json.dumps(final), flush=True)
