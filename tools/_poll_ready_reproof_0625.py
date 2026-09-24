"""Poll for ONE live READY dispatch on 0.6.25-focus; stake 0.10; disable on first terminal."""
import json, sqlite3, time, urllib.request, subprocess, os, signal
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\Users\WINDOWS11\Desktop\MultiBotV2.0\MultiBot365")
EV = ROOT / "evidence" / "ready-reproof-0.6.25-20260923"
EV.mkdir(parents=True, exist_ok=True)
DB = ROOT / ".local" / "pipeline.sqlite3"
CFG = ROOT / ".local" / "pipeline.json"
STATUS = ROOT / ".local" / "pipeline_status.json"
COORD = json.loads((ROOT / ".local" / "coordinator.json").read_text(encoding="utf-8-sig"))
PY = r"C:\Users\WINDOWS11\AppData\Local\Programs\Python\Python311\python.exe"
START = datetime.now(timezone.utc)
TIMEOUT_S = 50 * 60
POLL = 8
dispatched_id = None
seen_states = {}
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
    CFG.write_text(json.dumps(cfg, indent=4) + "\n", encoding="utf-8")
    return bool(enabled)

def restart_pipeline():
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
    # CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS
    flags = 0x00000200 | 0x00000008
    subprocess.Popen([PY, "-m", "tools.pipeline_service", "run"], cwd=str(ROOT),
                     stdout=open(ROOT / "logs" / "pipeline.stdout.log", "a"),
                     stderr=open(ROOT / "logs" / "pipeline.stderr.log", "a"),
                     creationflags=flags)
    time.sleep(5)
    st = json.loads(STATUS.read_text(encoding="utf-8-sig")) if STATUS.exists() else {}
    log("pipeline_restarted", status=st)
    return st

def is_device_terminal(state):
    return state in (
        "READY", "STALE", "REJECTED", "DEVICE_OFFLINE", "SESSION_REQUIRED",
        "FAIL", "UNKNOWN", "CANCELLED", "ABORTED", "TIMEOUT", "EXPIRED",
        "PRICE_CHANGED", "LINE_CHANGED", "BELOW_MINIMUM", "TARGET_NOT_FOUND",
        "COMPLETED",
    )

def extract_focus(rp, device_stage, failure_reason):
    if isinstance(rp, dict):
        for k in ("focus", "focus_state", "focus_result", "stage"):
            if rp.get(k):
                return rp.get(k)
        ready = rp.get("ready_state") if isinstance(rp.get("ready_state"), dict) else {}
        if ready.get("focus"):
            return ready.get("focus")
    if device_stage:
        return device_stage
    if failure_reason and "FOCUS" in str(failure_reason).upper():
        return failure_reason
    return "N/A"

con = sqlite3.connect(str(DB), timeout=30)
con.row_factory = sqlite3.Row
baseline_intake = con.execute("SELECT MAX(id) FROM intake_messages").fetchone()[0] or 0
baseline_rowid = con.execute("SELECT MAX(rowid) FROM instructions").fetchone()[0] or 0
log("poller_0625_start", intake_id=baseline_intake, instr_rowid=baseline_rowid,
    stake_target=0.10, app_version="0.6.25-focus", commit="3313ed9",
    note="Place Bet lock NOT applied (David override). execution_mode=ready.")

# Document override
(EV / "david-override-place-bet.json").write_text(json.dumps({
    "at": datetime.now(timezone.utc).isoformat(),
    "override": "Place Bet can stay ON; do not force Place Bet/final action disabled",
    "stake_rule": "Strict 0.10 only; fail STAKE_REJECTED/STAKE_BELOW_MINIMUM if Bet365 rejects; never bump stake",
    "dispatch_path": "core/pipeline.py build_payload always execution_mode=ready",
}, indent=2), encoding="utf-8")

try:
    h = health()
    (EV / "health-resume.json").write_text(json.dumps(h, indent=2), encoding="utf-8")
    log("health", app_version=h.get("app_version"), version_code=h.get("version_code"),
        session=(h.get("session") or {}).get("state"), state=h.get("state"))
    if h.get("app_version") != "0.6.25-focus" or h.get("version_code") != 37:
        raise SystemExit(f"REFUSING wrong app version: {h.get('app_version')} / {h.get('version_code')}")
except Exception as e:
    log("health_error", error=str(e))
    raise

# Enable dispatch only now (stake already wired)
before = set_dispatch(True)
(EV / "dispatch-enable.json").write_text(json.dumps({
    "before": False,
    "after": True,
    "stake_wired": 0.10,
    "at": datetime.now(timezone.utc).isoformat(),
}, indent=2), encoding="utf-8")
st = restart_pipeline()
# verify status shows dispatch true
for _ in range(10):
    time.sleep(1)
    st = json.loads(STATUS.read_text(encoding="utf-8-sig"))
    if st.get("dispatch_enabled") is True:
        break
log("pipeline_status", **{k: st.get(k) for k in ("dispatch_enabled", "intake", "heartbeat_at", "last_error")})
if not st.get("dispatch_enabled"):
    log("dispatch_not_live_after_restart", status=st)
    # fail closed: leave off
    set_dispatch(False)
    raise SystemExit("dispatch_enabled did not become true after restart")

final = {
    "FINAL_STATUS": "WAITING",
    "COMMIT": "3313ed9",
    "APP_VERSION": "0.6.25-focus",
    "VERSION_CODE": 37,
    "DISPATCH_NOW": True,
    "STAKE_TARGET": 0.10,
    "PLACE_BET_LOCK": False,
    "PARSE": "N/A",
    "RULES": "N/A",
    "SESSION": "N/A",
    "SEARCH": "N/A",
    "FOCUS": "N/A",
    "FIXTURE": "N/A",
    "MARKET": "N/A",
    "SIDE": "N/A",
    "LINE": "N/A",
    "PRICE": "N/A",
    "STAKE": "N/A",
    "READY": "N/A",
    "WAGER_SUBMITTED": False,
    "DASHBOARD": "N/A",
    "ALERT": None,
}

while True:
    elapsed = (datetime.now(timezone.utc) - START).total_seconds()
    if elapsed > TIMEOUT_S:
        log("timeout", elapsed_s=int(elapsed))
        final["FINAL_STATUS"] = "NO_ALERT"
        break

    for r in con.execute(
        "SELECT id, message_id, status, reason, instruction_id, received_at, substr(raw_text,1,200) snip "
        "FROM intake_messages WHERE id > ? ORDER BY id", (baseline_intake,)):
        if r["id"] in seen_intake:
            continue
        seen_intake.add(r["id"])
        log("intake", id=r["id"], message_id=r["message_id"], status=r["status"],
            reason=(r["reason"] or "")[:200], instruction_id=r["instruction_id"])
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
            # verify stake on accepted/queued
            if r["stake"] is not None and str(r["stake"]) not in ("0.10", "0.1"):
                log("STAKE_MISMATCH_QUEUED", instruction_id=r["instruction_id"], stake=r["stake"])
        if r["state"] == "DISPATCHED" and dispatched_id is None:
            dispatched_id = r["instruction_id"]
            log("DISPATCHED_ONE", instruction_id=dispatched_id, stake=r["stake"])
            final["ALERT"] = f"{r['home']} vs {r['away']} {r['market']} {r['selection']} line={r['line']} stake={r['stake']}"
            final["PARSE"] = "PARSED"
            final["RULES"] = "ACCEPT"
            final["SIDE"] = r["selection"]
            final["FIXTURE"] = f"{r['home']} vs {r['away']}"
            final["MARKET"] = r["market"]
            final["LINE"] = r["line"]
            final["STAKE"] = r["stake"]
            dp = slim.get("dispatch_payload") or {}
            final["execution_mode"] = dp.get("execution_mode") if isinstance(dp, dict) else None
            if isinstance(dp, dict):
                (EV / "dispatch-payload.json").write_text(json.dumps(dp, indent=2), encoding="utf-8")
                ds = str(dp.get("stake") or "")
                if ds not in ("0.10", "0.1"):
                    log("STAKE_MISMATCH_DISPATCH", stake=ds)
                    final["STAKE"] = f"MISMATCH:{ds}"
                    final["FINAL_STATUS"] = "STAKE_MISMATCH"
                    terminal_hit = True
                    break

        if dispatched_id and r["instruction_id"] == dispatched_id and is_device_terminal(r["state"]):
            log("TERMINAL", instruction_id=dispatched_id, state=r["state"],
                failure_reason=r["failure_reason"], device_stage=r["device_stage"])
            final["FINAL_STATUS"] = r["state"]
            final["READY"] = "YES" if r["state"] == "READY" else "NO"
            rp = slim.get("result_payload") or {}
            ready = rp.get("ready_state") if isinstance(rp, dict) else {}
            if not isinstance(ready, dict):
                ready = {}
            final["SESSION"] = ready.get("session") or r["session_state"] or "N/A"
            final["SEARCH"] = (rp.get("stage") if isinstance(rp, dict) else None) or r["device_stage"] or "N/A"
            final["FOCUS"] = extract_focus(rp, r["device_stage"], r["failure_reason"])
            final["FIXTURE"] = f"{ready.get('fixture_home') or r['home']} vs {ready.get('fixture_away') or r['away']}"
            final["MARKET"] = ready.get("market") or r["market"]
            final["SIDE"] = ready.get("selection_role") or ready.get("side") or r["selection"]
            final["LINE"] = ready.get("line") if ready.get("line") is not None else r["line"]
            final["PRICE"] = ready.get("price") or r["observed_price"] or "N/A"
            stake_obs = ready.get("stake") or r["stake"] or "N/A"
            final["STAKE"] = stake_obs
            fr = (r["failure_reason"] or "")
            stage = (r["device_stage"] or "")
            # Stake rejection detection (fail closed, do not bump)
            stake_reject_tokens = ("BELOW_MINIMUM", "STAKE_BELOW", "MINIMUM_STAKE", "STAKE_REJECT", "MIN STAKE", "MINIMUM STAKE")
            blob = (fr + " " + stage + " " + json.dumps(rp)[:2000]).upper()
            if r["state"] == "BELOW_MINIMUM" or any(t in blob for t in stake_reject_tokens):
                final["FINAL_STATUS"] = "STAKE_BELOW_MINIMUM" if "BELOW" in blob or r["state"] == "BELOW_MINIMUM" else "STAKE_REJECTED"
                final["STAKE"] = f"{stake_obs} (attempted 0.10; rejected)"
                # try extract min shown
                for key in ("minimum_stake", "min_stake", "stake_minimum", "shown_minimum"):
                    if isinstance(ready, dict) and ready.get(key) is not None:
                        final["MIN_STAKE_SHOWN"] = ready.get(key)
                    if isinstance(rp, dict) and rp.get(key) is not None:
                        final["MIN_STAKE_SHOWN"] = rp.get(key)
            if "wager_submitted" in ready:
                final["WAGER_SUBMITTED"] = ready.get("wager_submitted")
            elif isinstance(rp, dict) and "wager_submitted" in rp:
                final["WAGER_SUBMITTED"] = rp.get("wager_submitted")
            else:
                final["WAGER_SUBMITTED"] = False
            final["DASHBOARD"] = f"instruction {dispatched_id} state={r['state']} device_stage={r['device_stage']} failure={r['failure_reason']}"
            final["failure_reason"] = r["failure_reason"]
            final["device_stage"] = r["device_stage"]
            if isinstance(rp, dict):
                (EV / "result-payload.json").write_text(json.dumps(rp, indent=2), encoding="utf-8")
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

# IMMEDIATELY disable dispatch after first terminal or timeout
try:
    set_dispatch(False)
    log("dispatch_config_false")
    st = restart_pipeline()
    time.sleep(3)
    st = json.loads(STATUS.read_text(encoding="utf-8-sig"))
    final["DISPATCH_NOW"] = st.get("dispatch_enabled")
    (EV / "dispatch-disable.json").write_text(json.dumps({
        "at": datetime.now(timezone.utc).isoformat(),
        "dispatch_enabled": st.get("dispatch_enabled"),
        "status": st,
    }, indent=2), encoding="utf-8")
    log("dispatch_verified_off", status=st)
except Exception as e:
    log("disable_error", error=str(e))
    final["DISPATCH_NOW"] = "ERROR"

final["elapsed_s"] = int((datetime.now(timezone.utc) - START).total_seconds())
final["dispatched_id"] = dispatched_id
final["ALERT_ID"] = dispatched_id
final["evidence_dir"] = str(EV)
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
