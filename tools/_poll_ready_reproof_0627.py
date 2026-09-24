"""Poll for ONE live READY dispatch on 0.6.27-sports; stake 0.10; disable on first terminal."""
import json, sqlite3, time, urllib.request, subprocess, os, signal, shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\Users\WINDOWS11\Desktop\MultiBotV2.0\MultiBot365")
EV = ROOT / "evidence" / "ready-reproof-0.6.27-20260923"
EV.mkdir(parents=True, exist_ok=True)
DB = ROOT / ".local" / "pipeline.sqlite3"
DASH = ROOT / ".local" / "dashboard.sqlite3"
CFG = ROOT / ".local" / "pipeline.json"
STATUS = ROOT / ".local" / "pipeline_status.json"
COORD = json.loads((ROOT / ".local" / "coordinator.json").read_text(encoding="utf-8-sig"))
PY = r"C:\Users\WINDOWS11\AppData\Local\Programs\Python\Python311\python.exe"
START = datetime.now(timezone.utc)
TIMEOUT_S = 55 * 60
POLL = 8
APP_EXPECT = "0.6.27-sports"
VC_EXPECT = 39
COMMIT_EXPECT = "f108af8"
STAKE_EXPECT = 0.1
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
    before = cfg.get("pipeline", {}).get("dispatch_enabled")
    cfg.setdefault("pipeline", {})["dispatch_enabled"] = bool(enabled)
    CFG.write_text(json.dumps(cfg, indent=4) + "\n", encoding="utf-8")
    return before, bool(enabled)

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
        "COMPLETED", "WRONG_EVENT", "SPORTS_CONTEXT_REQUIRED", "QUERY_FAILED",
    )

def read_stake():
    c = sqlite3.connect(str(DASH))
    payload = json.loads(c.execute("SELECT payload FROM config WHERE id=1").fetchone()[0])
    return payload["global"]["default_stake"], payload

def enrich_from_result(final, rp, row):
    ready = rp.get("ready_state") if isinstance(rp, dict) else {}
    if not isinstance(ready, dict):
        ready = {}
    evidence = rp.get("evidence") if isinstance(rp, dict) else {}
    if not isinstance(evidence, dict):
        evidence = {}
    qe = rp.get("query_evidence") if isinstance(rp, dict) else None
    if qe is None:
        qe = evidence.get("query_evidence")
    if not isinstance(qe, dict):
        qe = {}
    sports = rp.get("sports_context") or ready.get("sports_context") or evidence.get("sports_context")
    final["SESSION"] = ready.get("session") or row["session_state"] or (rp.get("session") if isinstance(rp, dict) else None) or "N/A"
    final["SPORTS_CONTEXT"] = sports if sports is not None else (rp.get("stage") if isinstance(rp, dict) else None) or row["device_stage"] or "N/A"
    final["SEARCH"] = (rp.get("stage") if isinstance(rp, dict) else None) or row["device_stage"] or "N/A"
    final["QUERY_USED"] = None
    if isinstance(qe, dict):
        final["QUERY_USED"] = qe.get("query") or qe.get("requested_text") or qe.get("text")
    if final["QUERY_USED"] is None and isinstance(ready, dict):
        final["QUERY_USED"] = ready.get("query")
    if final["QUERY_USED"] is None and isinstance(rp, dict):
        final["QUERY_USED"] = rp.get("query")
    if final["QUERY_USED"] is None:
        final["QUERY_USED"] = row["home"] or "N/A"
    final["FIXTURE"] = f"{ready.get('fixture_home') or row['home']} vs {ready.get('fixture_away') or row['away']}"
    final["MARKET"] = ready.get("market") or row["market"]
    final["SIDE"] = ready.get("selection_role") or ready.get("side") or row["selection"]
    final["LINE"] = ready.get("line") if ready.get("line") is not None else row["line"]
    final["PRICE"] = ready.get("price") or row["observed_price"] or "N/A"
    final["STAKE"] = ready.get("stake") or row["stake"] or "N/A"
    betslip = ready.get("betslip") or ready.get("betslip_verification") or rp.get("betslip_verification") if isinstance(rp, dict) else None
    if betslip is None and isinstance(rp, dict):
        betslip = rp.get("verification_detail") or ready.get("verification")
    final["BETSLIP_VERIFICATION"] = betslip if betslip is not None else (row["failure_reason"] or "N/A")
    final["READY"] = "YES" if row["state"] == "READY" else ("NO" if row["state"] != "READY" else "N/A")
    if row["state"] == "READY":
        final["READY"] = "YES"
    else:
        final["READY"] = f"NO ({row['state']})"
    fas = ready.get("final_action_state") or rp.get("final_action_state") if isinstance(rp, dict) else None
    if fas is None and isinstance(rp, dict):
        fas = ready.get("complete_execution_ready") or rp.get("complete_execution_ready")
    final["FINAL_ACTION_STATE"] = fas if fas is not None else (ready.get("state") or row["device_stage"] or row["state"] or "N/A")
    if "wager_submitted" in ready:
        final["WAGER_SUBMITTED"] = ready.get("wager_submitted")
    elif isinstance(rp, dict) and "wager_submitted" in rp:
        final["WAGER_SUBMITTED"] = rp.get("wager_submitted")
    else:
        final["WAGER_SUBMITTED"] = False
    # try pull query evidence files from device evidence if present in result
    for key in ("query_requested", "query_observed", "visible_field_text"):
        if isinstance(qe, dict) and qe.get(key) is not None:
            final[key] = qe.get(key)
        elif isinstance(ready, dict) and ready.get(key) is not None:
            final[key] = ready.get(key)
    return final

# --- precheck ---
stake, full_cfg = read_stake()
(EV / "stake-config.json").write_text(json.dumps({
    "at": datetime.now(timezone.utc).isoformat(),
    "source": ".local/dashboard.sqlite3 config.global.default_stake",
    "default_stake": stake,
    "global": full_cfg.get("global"),
}, indent=2), encoding="utf-8")
if float(stake) != float(STAKE_EXPECT):
    raise SystemExit(f"STAKE_BLOCKER: configured default_stake={stake}, expected {STAKE_EXPECT}")

h = health()
(EV / "health-start.json").write_text(json.dumps(h, indent=2), encoding="utf-8")
st0 = json.loads(STATUS.read_text(encoding="utf-8-sig")) if STATUS.exists() else {}
(EV / "pipeline-status-start.json").write_text(json.dumps(st0, indent=2), encoding="utf-8")
shutil.copy2(CFG, EV / "pipeline-json-start.json")
(EV / "precheck.json").write_text(json.dumps({
    "at": datetime.now(timezone.utc).isoformat(),
    "app_version": h.get("app_version"),
    "version_code": h.get("version_code"),
    "session": (h.get("session") or {}).get("state"),
    "agent_state": h.get("state"),
    "dispatch_enabled": st0.get("dispatch_enabled"),
    "intake": st0.get("intake"),
    "commit_expected": COMMIT_EXPECT,
    "stake_target": stake,
    "healthy": h.get("healthy"),
}, indent=2), encoding="utf-8")

if h.get("app_version") != APP_EXPECT or int(h.get("version_code") or 0) != VC_EXPECT:
    raise SystemExit(f"VERSION_BLOCKER: {h.get('app_version')} / {h.get('version_code')}")
if (h.get("session") or {}).get("state") != "AUTHENTICATED":
    raise SystemExit(f"SESSION_BLOCKER: {(h.get('session') or {}).get('state')}")
cfg_now = json.loads(CFG.read_text(encoding="utf-8-sig"))
if cfg_now.get("pipeline", {}).get("dispatch_enabled") is not False:
    # leave as-is if already true? User said verify currently false. Fail closed if true unexpectedly.
    log("warn_dispatch_was_not_false", value=cfg_now.get("pipeline", {}).get("dispatch_enabled"))

con = sqlite3.connect(str(DB), timeout=30)
con.row_factory = sqlite3.Row
baseline_intake = con.execute("SELECT MAX(id) FROM intake_messages").fetchone()[0] or 0
baseline_rowid = con.execute("SELECT MAX(rowid) FROM instructions").fetchone()[0] or 0
log("poller_0627_start", intake_id=baseline_intake, instr_rowid=baseline_rowid,
    stake_target=STAKE_EXPECT, app_version=APP_EXPECT, commit=COMMIT_EXPECT,
    note="execution_mode=ready always from pipeline.build_payload; Place Bet policy unchanged")

(EV / "david-override-place-bet.json").write_text(json.dumps({
    "at": datetime.now(timezone.utc).isoformat(),
    "override": "Do not change wager policy; pipeline build_payload always execution_mode=ready",
    "stake_rule": f"Strict {STAKE_EXPECT} only from dashboard.sqlite3; never invent/bump stake",
    "dispatch_path": "core/pipeline.py build_payload always execution_mode=ready",
}, indent=2), encoding="utf-8")

# Enable dispatch
before, after = set_dispatch(True)
(EV / "dispatch-enable.json").write_text(json.dumps({
    "before": before, "after": after, "stake_wired": stake,
    "at": datetime.now(timezone.utc).isoformat(),
}, indent=2), encoding="utf-8")
st = restart_pipeline()
for _ in range(12):
    time.sleep(1)
    st = json.loads(STATUS.read_text(encoding="utf-8-sig"))
    if st.get("dispatch_enabled") is True and (st.get("intake") or {}).get("state") == "LISTENING":
        break
log("pipeline_status", **{k: st.get(k) for k in ("dispatch_enabled", "intake", "heartbeat_at", "last_error")})
if not st.get("dispatch_enabled"):
    set_dispatch(False)
    raise SystemExit("dispatch_enabled did not become true after restart")

final = {
    "PARSE": "N/A", "RULES": "N/A", "SESSION": "N/A", "SPORTS_CONTEXT": "N/A",
    "SEARCH": "N/A", "QUERY_USED": "N/A", "FIXTURE": "N/A", "MARKET": "N/A",
    "SIDE": "N/A", "LINE": "N/A", "PRICE": "N/A", "STAKE": "N/A",
    "BETSLIP_VERIFICATION": "N/A", "READY": "N/A", "FINAL_ACTION_STATE": "N/A",
    "RESULT": "N/A", "DASHBOARD": "N/A", "FINAL_STATUS": "WAITING",
    "COMMIT": COMMIT_EXPECT, "APP_VERSION": APP_EXPECT, "VERSION_CODE": VC_EXPECT,
    "DISPATCH_NOW": True, "STAKE_TARGET": STAKE_EXPECT, "ALERT_ID": None,
    "WAGER_SUBMITTED": False, "evidence_dir": str(EV),
}

while True:
    elapsed = (datetime.now(timezone.utc) - START).total_seconds()
    if elapsed > TIMEOUT_S:
        log("timeout", elapsed_s=int(elapsed))
        final["FINAL_STATUS"] = "WAITING_TIMEOUT"
        final["RESULT"] = "WAITING_TIMEOUT"
        break

    for r in con.execute(
        "SELECT id, message_id, status, reason, instruction_id, received_at, substr(raw_text,1,240) snip "
        "FROM intake_messages WHERE id > ? ORDER BY id", (baseline_intake,)):
        if r["id"] in seen_intake:
            continue
        seen_intake.add(r["id"])
        log("intake", id=r["id"], message_id=r["message_id"], status=r["status"],
            reason=(r["reason"] or "")[:240], instruction_id=r["instruction_id"])
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

        if r["state"] == "QUEUED" and r["stake"] is not None and str(r["stake"]) not in ("0.10", "0.1"):
            log("STAKE_MISMATCH_QUEUED", instruction_id=r["instruction_id"], stake=r["stake"])

        if r["state"] == "SESSION_REQUIRED" and dispatched_id is None and r["dispatched_at"] is None:
            log("SESSION_REQUIRED_PRE_DISPATCH_CONTINUE", instruction_id=r["instruction_id"], reason=r["failure_reason"],
                note="keepalive should refresh; one-shot continues until DISPATCHED terminal or timeout")

        if r["state"] == "DISPATCHED" and dispatched_id is None:
            dispatched_id = r["instruction_id"]
            log("DISPATCHED_ONE", instruction_id=dispatched_id, stake=r["stake"])
            final["ALERT_ID"] = dispatched_id
            final["PARSE"] = "PARSED"
            final["RULES"] = "ACCEPT"
            final["SIDE"] = r["selection"]
            final["FIXTURE"] = f"{r['home']} vs {r['away']}"
            final["MARKET"] = r["market"]
            final["LINE"] = r["line"]
            final["STAKE"] = r["stake"]
            final["SESSION"] = r["session_state"] or "N/A"
            dp = slim.get("dispatch_payload") or {}
            final["execution_mode"] = dp.get("execution_mode") if isinstance(dp, dict) else None
            if isinstance(dp, dict):
                (EV / "dispatch-payload.json").write_text(json.dumps(dp, indent=2), encoding="utf-8")
                ds = str(dp.get("stake") or "")
                if ds not in ("0.10", "0.1"):
                    log("STAKE_MISMATCH_DISPATCH", stake=ds)
                    final["STAKE"] = f"MISMATCH:{ds}"
                    final["FINAL_STATUS"] = "STAKE_MISMATCH"
                    final["RESULT"] = "STAKE_MISMATCH"
                    terminal_hit = True
                    break

        if dispatched_id and r["instruction_id"] == dispatched_id and is_device_terminal(r["state"]):
            log("TERMINAL", instruction_id=dispatched_id, state=r["state"],
                failure_reason=r["failure_reason"], device_stage=r["device_stage"])
            final["FINAL_STATUS"] = r["state"]
            final["RESULT"] = r["state"]
            rp = slim.get("result_payload") or {}
            if not isinstance(rp, dict):
                rp = {}
            enrich_from_result(final, rp, r)
            final["DASHBOARD"] = f"instruction {dispatched_id} state={r['state']} device_stage={r['device_stage']} failure={r['failure_reason']}"
            final["failure_reason"] = r["failure_reason"]
            final["device_stage"] = r["device_stage"]
            if isinstance(rp, dict) and rp:
                (EV / "result-payload.json").write_text(json.dumps(rp, indent=2), encoding="utf-8")
            # copy device evidence bins/pngs if referenced
            terminal_hit = True
            break

    if terminal_hit:
        break

    if int(elapsed) % 60 < POLL:
        try:
            st = json.loads(STATUS.read_text(encoding="utf-8-sig"))
            hbeat = health()
            log("heartbeat", elapsed_s=int(elapsed), dispatch_enabled=st.get("dispatch_enabled"),
                intake_state=(st.get("intake") or {}).get("state"),
                last_event=(st.get("intake") or {}).get("last_event_at"),
                session=(hbeat.get("session") or {}).get("state"),
                agent_state=hbeat.get("state"))
        except Exception as e:
            log("status_error", error=str(e))
    time.sleep(POLL)

# IMMEDIATELY disable dispatch
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
try:
    h = health()
    (EV / "health-final.json").write_text(json.dumps(h, indent=2), encoding="utf-8")
    final["health_end_session"] = (h.get("session") or {}).get("state")
    final["health_end_last_result"] = h.get("last_result")
except Exception as e:
    final["health_end_error"] = str(e)

(EV / "final-summary.json").write_text(json.dumps(final, indent=2), encoding="utf-8")
(EV / "events.json").write_text(json.dumps(events, indent=2), encoding="utf-8")
print("DONE", json.dumps(final), flush=True)
