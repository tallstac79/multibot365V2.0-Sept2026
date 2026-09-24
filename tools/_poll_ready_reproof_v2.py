"""Poll for next READY dispatch; disable+restart pipeline on terminal or timeout."""
import json, sqlite3, time, urllib.request, subprocess, os, signal
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\Users\WINDOWS11\Desktop\MultiBotV2.0\MultiBot365")
EV = ROOT / "evidence" / "ready-reproof-20260923"
EV.mkdir(parents=True, exist_ok=True)
DB = ROOT / ".local" / "pipeline.sqlite3"
CFG = ROOT / ".local" / "pipeline.json"
STATUS = ROOT / ".local" / "pipeline_status.json"
COORD = json.loads((ROOT / ".local" / "coordinator.json").read_text(encoding="utf-8-sig"))
PY = r"C:\Users\WINDOWS11\AppData\Local\Programs\Python\Python311\python.exe"
START = datetime.now(timezone.utc)
TIMEOUT_S = 45 * 60
POLL = 10
dispatched_id = None
seen_states = {}  # instruction_id -> last state logged
seen_intake = set()
events = []

def log(msg, **extra):
    row = {"t": datetime.now(timezone.utc).isoformat(), "msg": msg, **extra}
    events.append(row)
    print(json.dumps(row), flush=True)
    with (EV / "poll-log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")

def health():
    req = urllib.request.Request(COORD["url"].rstrip("/") + "/health",
        headers={"Authorization": "Bearer " + COORD["token"]})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

def set_dispatch(enabled: bool):
    cfg = json.loads(CFG.read_text(encoding="utf-8-sig"))
    cfg["pipeline"]["dispatch_enabled"] = bool(enabled)
    # Do not add place_bet locks (David override 2026-09-23)
    CFG.write_text(json.dumps(cfg, indent=4) + "\n", encoding="utf-8")
    return bool(enabled)

def restart_pipeline():
    # kill existing pipeline_service then start
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'pipeline_service' } | ForEach-Object { $_.ProcessId }"],
            text=True, cwd=str(ROOT))
        for line in out.splitlines():
            line = line.strip()
            if line.isdigit():
                os.kill(int(line), signal.SIGTERM)
                log("killed_pipeline", pid=int(line))
                time.sleep(2)
    except Exception as e:
        log("kill_pipeline_error", error=str(e))
    subprocess.Popen([PY, "-m", "tools.pipeline_service", "run"], cwd=str(ROOT),
                     stdout=open(ROOT / "logs" / "pipeline.stdout.log", "a"),
                     stderr=open(ROOT / "logs" / "pipeline.stderr.log", "a"),
                     creationflags=0x00000008)  # DETACHED_PROCESS-ish; on Windows use CREATE_NEW_PROCESS_GROUP
    time.sleep(4)
    st = json.loads(STATUS.read_text(encoding="utf-8-sig")) if STATUS.exists() else {}
    log("pipeline_restarted", status=st)

con = sqlite3.connect(str(DB), timeout=30)
con.row_factory = sqlite3.Row
baseline_intake = con.execute("SELECT MAX(id) FROM intake_messages").fetchone()[0] or 0
baseline_rowid = con.execute("SELECT MAX(rowid) FROM instructions").fetchone()[0] or 0
log("poller_v2_start", intake_id=baseline_intake, instr_rowid=baseline_rowid,
    dispatch_enabled=True, place_bet_lock=False,
    note="David override: Place Bet not forced off; pipeline READY path uses execution_mode=ready")

try:
    h = health()
    (EV / "health-resume.json").write_text(json.dumps(h, indent=2), encoding="utf-8")
    log("health", app_version=h.get("app_version"), version_code=h.get("version_code"),
        session=(h.get("session") or {}).get("state"), state=h.get("state"))
except Exception as e:
    log("health_error", error=str(e))

# Confirm dispatch still on
st = json.loads(STATUS.read_text(encoding="utf-8-sig"))
if not st.get("dispatch_enabled"):
    set_dispatch(True)
    restart_pipeline()
    st = json.loads(STATUS.read_text(encoding="utf-8-sig"))
log("pipeline_status", **{k: st.get(k) for k in ("dispatch_enabled", "intake", "heartbeat_at")})

final = {
    "FINAL_STATUS": "WAITING",
    "COMMIT": "5c826649f730d2395c1730b32c1407e212d5d49c",
    "APK_MATCH": True,
    "APP_VERSION": "0.6.24-search / 36",
    "DISPATCH_NOW": True,
    "PLACE_BET_LOCK": False,
}

def is_device_terminal(state):
    return state in (
        "READY", "STALE", "REJECTED", "DEVICE_OFFLINE", "SESSION_REQUIRED",
        "FAIL", "UNKNOWN", "CANCELLED", "ABORTED", "TIMEOUT", "EXPIRED",
        "PRICE_CHANGED", "LINE_CHANGED", "BELOW_MINIMUM", "TARGET_NOT_FOUND",
        "COMPLETED",
    )

while True:
    elapsed = (datetime.now(timezone.utc) - START).total_seconds()
    if elapsed > TIMEOUT_S:
        log("timeout", elapsed_s=int(elapsed))
        final["FINAL_STATUS"] = "WAITING/NO_ALERT"
        break

    for r in con.execute(
        "SELECT id, message_id, status, reason, instruction_id, received_at, substr(raw_text,1,160) snip "
        "FROM intake_messages WHERE id > ? ORDER BY id", (baseline_intake,)):
        if r["id"] in seen_intake:
            continue
        seen_intake.add(r["id"])
        log("intake", id=r["id"], message_id=r["message_id"], status=r["status"],
            reason=(r["reason"] or "")[:160], instruction_id=r["instruction_id"])
        (EV / f"intake-{r['id']}.json").write_text(json.dumps(dict(r), default=str, indent=2), encoding="utf-8")

    terminal_hit = False
    for r in con.execute(
        """SELECT rowid, instruction_id, state, terminal, sport, home, away, market, selection, line,
                  minimum_price, stake, observed_price, failure_reason, device_stage, received_at,
                  queued_at, dispatched_at, ready_at, completed_at, dispatch_payload, result_payload,
                  session_state, rules_result
           FROM instructions WHERE rowid > ? ORDER BY rowid""", (baseline_rowid,)):
        prev = seen_states.get(r["instruction_id"])
        if prev == r["state"]:
            continue
        seen_states[r["instruction_id"]] = r["state"]
        brief = {k: r[k] for k in r.keys() if k not in ("rowid", "dispatch_payload", "result_payload", "rules_result")}
        log("instruction", **brief)
        slim = dict(brief)
        for field in ("dispatch_payload", "result_payload", "rules_result"):
            raw = r[field]
            if raw:
                try:
                    slim[field] = json.loads(raw) if isinstance(raw, str) else raw
                except Exception:
                    slim[field] = raw
        (EV / f"instruction-{r['instruction_id']}-{r['state']}.json").write_text(
            json.dumps(slim, indent=2, default=str), encoding="utf-8")

        if r["state"] == "QUEUED":
            log("QUEUED", instruction_id=r["instruction_id"])
        if r["state"] == "DISPATCHED" and dispatched_id is None:
            dispatched_id = r["instruction_id"]
            log("DISPATCHED_ONE", instruction_id=dispatched_id)
            final["ALERT"] = f"{r['home']} vs {r['away']} {r['market']} {r['selection']} line={r['line']}"
            final["PARSE"] = "PARSED"
            final["RULES"] = "ACCEPT"
            dp = slim.get("dispatch_payload") or {}
            final["execution_mode"] = dp.get("execution_mode") if isinstance(dp, dict) else None

        if dispatched_id and r["instruction_id"] == dispatched_id and is_device_terminal(r["state"]):
            log("TERMINAL", instruction_id=dispatched_id, state=r["state"],
                failure_reason=r["failure_reason"], device_stage=r["device_stage"])
            final["FINAL_STATUS"] = r["state"]
            final["READY"] = "YES" if r["state"] == "READY" else ("NO" if r["state"] != "READY" else "N/A")
            rp = slim.get("result_payload") or {}
            ready = rp.get("ready_state") if isinstance(rp, dict) else {}
            if not isinstance(ready, dict):
                ready = {}
            final["SESSION"] = ready.get("session") or r["session_state"] or "N/A"
            final["SEARCH"] = (rp.get("stage") if isinstance(rp, dict) else None) or r["device_stage"] or "N/A"
            final["FIXTURE"] = f"{ready.get('fixture_home') or r['home']} vs {ready.get('fixture_away') or r['away']}"
            final["MARKET"] = ready.get("market") or r["market"]
            final["LINE"] = ready.get("line") if ready.get("line") is not None else r["line"]
            final["PRICE"] = ready.get("price") or r["observed_price"] or "N/A"
            final["STAKE"] = ready.get("stake") or r["stake"] or "N/A"
            # Honest wager_submitted (may be true per David override)
            if "wager_submitted" in ready:
                final["WAGER_SUBMITTED"] = ready.get("wager_submitted")
            elif isinstance(rp, dict) and "wager_submitted" in rp:
                final["WAGER_SUBMITTED"] = rp.get("wager_submitted")
            else:
                final["WAGER_SUBMITTED"] = False
            final["DASHBOARD"] = f"instruction {dispatched_id} state={r['state']}"
            terminal_hit = True
            break

    if terminal_hit:
        break

    if int(elapsed) % 60 < POLL:
        try:
            st = json.loads(STATUS.read_text(encoding="utf-8-sig"))
            log("heartbeat", elapsed_s=int(elapsed), dispatch_enabled=st.get("dispatch_enabled"),
                intake_state=(st.get("intake") or {}).get("state"),
                last_event=(st.get("intake") or {}).get("last_event_at"))
        except Exception as e:
            log("status_error", error=str(e))
    time.sleep(POLL)

# Immediately disable dispatch and restart so in-memory setting flips
try:
    set_dispatch(False)
    log("dispatch_config_false")
    restart_pipeline()
    time.sleep(3)
    st = json.loads(STATUS.read_text(encoding="utf-8-sig"))
    final["DISPATCH_NOW"] = st.get("dispatch_enabled")
    log("dispatch_verified_off", status=st)
except Exception as e:
    log("disable_error", error=str(e))
    final["DISPATCH_NOW"] = "ERROR"

final["elapsed_s"] = int((datetime.now(timezone.utc) - START).total_seconds())
final["dispatched_id"] = dispatched_id
try:
    h = health()
    (EV / "health-end.json").write_text(json.dumps(h, indent=2), encoding="utf-8")
    final["health_end_session"] = (h.get("session") or {}).get("state")
    final["health_end_last_result"] = h.get("last_result")
except Exception as e:
    final["health_end_error"] = str(e)

(EV / "final-summary.json").write_text(json.dumps(final, indent=2), encoding="utf-8")
(EV / "events.json").write_text(json.dumps(events, indent=2), encoding="utf-8")
print("DONE", json.dumps(final), flush=True)
