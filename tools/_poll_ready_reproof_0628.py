"""Poll for ONE live READY dispatch on 0.6.28-stage; stake 0.10; disable on first terminal."""
import json, sqlite3, time, urllib.request, subprocess, os, signal, shutil, copy
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\Users\WINDOWS11\Desktop\MultiBotV2.0\MultiBot365")
EV = ROOT / "evidence" / "ready-reproof-0.6.28-20260924"
EV.mkdir(parents=True, exist_ok=True)
DB = ROOT / ".local" / "pipeline.sqlite3"
DASH = ROOT / ".local" / "dashboard.sqlite3"
CFG = ROOT / ".local" / "pipeline.json"
STATUS = ROOT / ".local" / "pipeline_status.json"
COORD = json.loads((ROOT / ".local" / "coordinator.json").read_text(encoding="utf-8-sig"))
PY = r"C:\Users\WINDOWS11\AppData\Local\Programs\Python\Python311\python.exe"
START = datetime.now(timezone.utc)
TIMEOUT_S = 55 * 60
POLL = 5
APP_EXPECT = "0.6.28-stage"
VC_EXPECT = 40
COMMIT_EXPECT = "1e7d675"
STAKE_EXPECT = 0.1
dispatched_id = None
seen_states = {}
seen_intake = set()
events = []
stage_timeline = []
discarded_pre_dispatch = []
health_progress_snapshots = []

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
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    flags = 0x00000200 | 0x00000008
    subprocess.Popen([PY, "-m", "tools.pipeline_service", "run"], cwd=str(ROOT),
                     stdout=open(logs / "pipeline.stdout.log", "a"),
                     stderr=open(logs / "pipeline.stderr.log", "a"),
                     creationflags=flags)
    time.sleep(5)
    st = json.loads(STATUS.read_text(encoding="utf-8-sig")) if STATUS.exists() else {}
    log("pipeline_restarted", status={k: st.get(k) for k in ("dispatch_enabled", "intake", "heartbeat_at", "last_error")})
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

def capture_progress(h, note=""):
    lr = h.get("last_result") or {}
    prog = lr.get("progress") if isinstance(lr, dict) else None
    snap = {
        "t": datetime.now(timezone.utc).isoformat(),
        "note": note,
        "agent_state": h.get("state"),
        "session": (h.get("session") or {}).get("state"),
        "current_instruction": h.get("current_instruction"),
        "last_status": lr.get("status") if isinstance(lr, dict) else None,
        "last_stage": lr.get("stage") if isinstance(lr, dict) else None,
        "last_detail": lr.get("detail") if isinstance(lr, dict) else None,
        "device_stage": lr.get("device_stage") if isinstance(lr, dict) else None,
        "progress_stage": (prog or {}).get("stage") if isinstance(prog, dict) else None,
        "progress_elapsed_ms": (prog or {}).get("elapsed_ms") if isinstance(prog, dict) else None,
        "stages": (prog or {}).get("stages") if isinstance(prog, dict) else None,
        "instruction_id": (prog or {}).get("instruction_id") if isinstance(prog, dict) else (lr.get("instruction_id") if isinstance(lr, dict) else None),
    }
    health_progress_snapshots.append(snap)
    if snap.get("stages"):
        for s in snap["stages"]:
            entry = {"source": "health_progress", **s, "captured_at": snap["t"], "note": note}
            # de-dupe by stage+at_ms
            key = (s.get("stage"), s.get("at_ms"), s.get("elapsed_ms"))
            if not any((e.get("stage"), e.get("at_ms"), e.get("elapsed_ms")) == key for e in stage_timeline):
                stage_timeline.append(entry)
    return snap

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
    final["SPORTS_CONTEXT"] = sports if sports is not None else "N/A"
    final["SEARCH"] = (rp.get("stage") if isinstance(rp, dict) else None) or row["device_stage"] or "N/A"
    final["QUERY_USED"] = None
    if isinstance(qe, dict):
        final["QUERY_USED"] = qe.get("query") or qe.get("requested_text") or qe.get("text") or qe.get("query_requested")
    if final["QUERY_USED"] is None and isinstance(ready, dict):
        final["QUERY_USED"] = ready.get("query") or ready.get("query_requested")
    if final["QUERY_USED"] is None and isinstance(rp, dict):
        final["QUERY_USED"] = rp.get("query")
    if final["QUERY_USED"] is None:
        final["QUERY_USED"] = row["home"] or "N/A"
    final["FIXTURE_VERIFY"] = {
        "home": ready.get("fixture_home") or row["home"],
        "away": ready.get("fixture_away") or row["away"],
        "competition": ready.get("competition") or rp.get("competition") if isinstance(rp, dict) else None,
        "verification_detail": rp.get("verification_detail") if isinstance(rp, dict) else None,
        "fixture_name": rp.get("fixture_name") if isinstance(rp, dict) else None,
    }
    final["MARKET_NAV"] = ready.get("market") or row["market"] or (rp.get("market") if isinstance(rp, dict) else None) or "N/A"
    final["SIDE"] = ready.get("selection_role") or ready.get("side") or row["selection"]
    final["LINE"] = ready.get("line") if ready.get("line") is not None else row["line"]
    final["PRICE"] = ready.get("price") or row["observed_price"] or "N/A"
    final["STAKE"] = ready.get("stake") or row["stake"] or "N/A"
    betslip = None
    if isinstance(ready, dict):
        betslip = ready.get("betslip") or ready.get("betslip_verification")
    if betslip is None and isinstance(rp, dict):
        betslip = rp.get("betslip_verification") or rp.get("verification_detail")
    final["BETSLIP"] = betslip if betslip is not None else (row["failure_reason"] or "N/A")
    if row["state"] == "READY":
        final["READY"] = "YES"
    else:
        final["READY"] = f"NO ({row['state']})"
    fas = None
    if isinstance(ready, dict):
        fas = ready.get("final_action_state") or ready.get("complete_execution_ready")
    if fas is None and isinstance(rp, dict):
        fas = rp.get("final_action_state") or rp.get("complete_execution_ready")
    final["FINAL_ACTION"] = fas if fas is not None else (ready.get("state") or row["device_stage"] or row["state"] or "N/A")
    if isinstance(ready, dict) and "wager_submitted" in ready:
        final["WAGER_SUBMITTED"] = ready.get("wager_submitted")
    elif isinstance(rp, dict) and "wager_submitted" in rp:
        final["WAGER_SUBMITTED"] = rp.get("wager_submitted")
    else:
        final["WAGER_SUBMITTED"] = False
    # first failed stage from progress timings
    first_failed = None
    prog = rp.get("progress") if isinstance(rp, dict) else None
    if isinstance(prog, dict) and isinstance(prog.get("stages"), list):
        for s in prog["stages"]:
            timing = s.get("timing") if isinstance(s, dict) else None
            if isinstance(timing, dict) and str(timing.get("status", "")).lower() not in ("ok", "success", ""):
                first_failed = timing.get("stage") or s.get("stage")
                break
            if isinstance(s, dict) and str(s.get("status", "")).lower() in ("fail", "failed", "error", "timeout"):
                first_failed = s.get("stage")
                break
    if first_failed is None and row["state"] not in ("READY", "COMPLETED"):
        first_failed = row["device_stage"] or row["state"]
    final["first_failed_stage"] = first_failed
    if isinstance(prog, dict) and prog.get("stages"):
        for s in prog["stages"]:
            entry = {"source": "result_progress", **s}
            key = (s.get("stage"), s.get("at_ms"), s.get("elapsed_ms"))
            if not any((e.get("stage"), e.get("at_ms"), e.get("elapsed_ms")) == key for e in stage_timeline):
                stage_timeline.append(entry)
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
capture_progress(h, "precheck")
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
    "cfg_dispatch_enabled": json.loads(CFG.read_text(encoding="utf-8-sig")).get("pipeline", {}).get("dispatch_enabled"),
    "intake": st0.get("intake"),
    "commit_expected": COMMIT_EXPECT,
    "commit_repo": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(ROOT), text=True).strip(),
    "stake_target": stake,
    "healthy": h.get("healthy"),
}, indent=2), encoding="utf-8")

if h.get("app_version") != APP_EXPECT or int(h.get("version_code") or 0) != VC_EXPECT:
    raise SystemExit(f"VERSION_BLOCKER: {h.get('app_version')} / {h.get('version_code')}")
sess = (h.get("session") or {}).get("state")
if sess not in ("AUTHENTICATED",):
    # still allow if reachable AUTHENTICATED_OR_REACHABLE — user said AUTHENTICATED (or reachable)
    raise SystemExit(f"SESSION_BLOCKER: {sess}")
if st0.get("dispatch_enabled") is not False:
    log("warn_dispatch_status_not_false", value=st0.get("dispatch_enabled"))
cfg_now = json.loads(CFG.read_text(encoding="utf-8-sig"))
if cfg_now.get("pipeline", {}).get("dispatch_enabled") is not False:
    log("warn_dispatch_cfg_not_false", value=cfg_now.get("pipeline", {}).get("dispatch_enabled"))

con = sqlite3.connect(str(DB), timeout=30)
con.row_factory = sqlite3.Row
baseline_intake = con.execute("SELECT MAX(id) FROM intake_messages").fetchone()[0] or 0
baseline_rowid = con.execute("SELECT MAX(rowid) FROM instructions").fetchone()[0] or 0
log("poller_0628_start", intake_id=baseline_intake, instr_rowid=baseline_rowid,
    stake_target=STAKE_EXPECT, app_version=APP_EXPECT, commit=COMMIT_EXPECT,
    note="one-shot live READY; SESSION_REQUIRED pre-dispatch discarded; disable after first DISPATCHED terminal")

(EV / "policy-note.json").write_text(json.dumps({
    "at": datetime.now(timezone.utc).isoformat(),
    "execution_mode": "ready (from pipeline.build_payload; Place Bet policy unchanged)",
    "stake_rule": f"Strict {STAKE_EXPECT} from dashboard.sqlite3; never invent/bump",
    "hard_constraints": ["session freshness/keepalive", "45s inactivity", "300s absolute backstop", "progress heartbeat", "sports discovery/query ladder", "do not bump session_max_age"],
}, indent=2), encoding="utf-8")

# Enable dispatch
before, after = set_dispatch(True)
(EV / "dispatch-enable.json").write_text(json.dumps({
    "before": before, "after": after, "stake_wired": stake,
    "at": datetime.now(timezone.utc).isoformat(),
}, indent=2), encoding="utf-8")
st = restart_pipeline()
for _ in range(15):
    time.sleep(1)
    st = json.loads(STATUS.read_text(encoding="utf-8-sig"))
    if st.get("dispatch_enabled") is True and (st.get("intake") or {}).get("state") == "LISTENING":
        break
log("pipeline_status", **{k: st.get(k) for k in ("dispatch_enabled", "intake", "heartbeat_at", "last_error")})
if not st.get("dispatch_enabled"):
    set_dispatch(False)
    raise SystemExit("dispatch_enabled did not become true after restart")

final = {
    "ALERT": "N/A", "PARSE": "N/A", "RULES": "N/A", "SESSION": "N/A", "SPORTS_CONTEXT": "N/A",
    "SEARCH": "N/A", "QUERY_USED": "N/A", "FIXTURE_VERIFY": "N/A", "MARKET_NAV": "N/A",
    "SIDE": "N/A", "LINE": "N/A", "PRICE": "N/A", "STAKE": "N/A",
    "BETSLIP": "N/A", "READY": "N/A", "FINAL_ACTION": "N/A",
    "RESULT": "N/A", "STAGE_TIMINGS": [], "DASHBOARD": "N/A", "FINAL_STATUS": "WAITING",
    "NEXT_BLOCKER": "N/A",
    "COMMIT": COMMIT_EXPECT, "APP": APP_EXPECT, "VERSION_CODE": VC_EXPECT,
    "DISPATCH_NOW": True, "STAKE_TARGET": STAKE_EXPECT, "tip_id": None,
    "WAGER_SUBMITTED": False, "evidence_path": str(EV),
    "first_failed_stage": None, "discarded_pre_dispatch": [],
}

while True:
    elapsed = (datetime.now(timezone.utc) - START).total_seconds()
    if elapsed > TIMEOUT_S:
        log("timeout", elapsed_s=int(elapsed))
        final["FINAL_STATUS"] = "WAITING_TIMEOUT"
        final["RESULT"] = "WAITING_TIMEOUT"
        final["NEXT_BLOCKER"] = "No DISPATCHED tip within ~55m wait window"
        break

    for r in con.execute(
        "SELECT id, message_id, status, reason, instruction_id, received_at, substr(raw_text,1,240) snip "
        "FROM intake_messages WHERE id > ? ORDER BY id", (baseline_intake,)):
        if r["id"] in seen_intake:
            continue
        seen_intake.add(r["id"])
        log("intake", id=r["id"], message_id=r["message_id"], status=r["status"],
            reason=(r["reason"] or "")[:240], instruction_id=r["instruction_id"], snip=(r["snip"] or "")[:200])
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
            # still poll progress while DEVICE_ACTIVE / DISPATCHED
            if dispatched_id == r["instruction_id"] and r["state"] in ("DISPATCHED", "DEVICE_ACTIVE"):
                pass
            else:
                continue
        else:
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
                discarded_pre_dispatch.append({
                    "instruction_id": r["instruction_id"],
                    "state": r["state"],
                    "reason": r["failure_reason"],
                    "home": r["home"], "away": r["away"],
                })
                log("SESSION_REQUIRED_PRE_DISPATCH_DISCARD", instruction_id=r["instruction_id"],
                    reason=r["failure_reason"],
                    note="does not count as one-shot terminal; continue until DISPATCHED terminal")

            if r["state"] in ("STALE", "REJECTED") and dispatched_id is None and r["dispatched_at"] is None:
                discarded_pre_dispatch.append({
                    "instruction_id": r["instruction_id"],
                    "state": r["state"],
                    "reason": r["failure_reason"],
                    "home": r["home"], "away": r["away"],
                })
                log("PRE_DISPATCH_DISCARD", instruction_id=r["instruction_id"], state=r["state"], reason=r["failure_reason"])

            if r["state"] == "DISPATCHED" and dispatched_id is None:
                dispatched_id = r["instruction_id"]
                log("DISPATCHED_ONE", instruction_id=dispatched_id, stake=r["stake"])
                final["tip_id"] = dispatched_id
                final["ALERT"] = f"{r['home']} vs {r['away']} | {r['market']} | {r['selection']} | line={r['line']}"
                final["PARSE"] = "PARSED"
                final["RULES"] = "ACCEPT"
                final["SIDE"] = r["selection"]
                final["FIXTURE_VERIFY"] = f"{r['home']} vs {r['away']}"
                final["MARKET_NAV"] = r["market"]
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
                        final["NEXT_BLOCKER"] = f"stake mismatch at dispatch: {ds}"
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
                final["DASHBOARD"] = (
                    f"instruction {dispatched_id} state={r['state']} "
                    f"device_stage={r['device_stage']} failure={r['failure_reason']}"
                )
                final["failure_reason"] = r["failure_reason"]
                final["device_stage"] = r["device_stage"]
                if r["state"] == "READY":
                    final["NEXT_BLOCKER"] = None
                else:
                    final["NEXT_BLOCKER"] = (
                        f"first_failed_stage={final.get('first_failed_stage')}; "
                        f"failure_reason={r['failure_reason']}; device_stage={r['device_stage']}"
                    )
                if isinstance(rp, dict) and rp:
                    (EV / "result-payload.json").write_text(json.dumps(rp, indent=2), encoding="utf-8")
                terminal_hit = True
                break

        # live progress while active
        if dispatched_id and r["instruction_id"] == dispatched_id and r["state"] in ("DISPATCHED", "DEVICE_ACTIVE"):
            try:
                hh = health()
                snap = capture_progress(hh, f"active:{r['state']}")
                if snap.get("progress_stage"):
                    log("progress", instruction_id=dispatched_id, stage=snap.get("progress_stage"),
                        elapsed_ms=snap.get("progress_elapsed_ms"), agent_state=snap.get("agent_state"))
            except Exception as e:
                log("progress_error", error=str(e))

    if terminal_hit:
        break

    if int(elapsed) % 45 < POLL:
        try:
            st = json.loads(STATUS.read_text(encoding="utf-8-sig"))
            hbeat = health()
            capture_progress(hbeat, "heartbeat")
            log("heartbeat", elapsed_s=int(elapsed), dispatch_enabled=st.get("dispatch_enabled"),
                intake_state=(st.get("intake") or {}).get("state"),
                last_event=(st.get("intake") or {}).get("last_event_at"),
                session=(hbeat.get("session") or {}).get("state"),
                agent_state=hbeat.get("state"),
                discarded_pre_dispatch=len(discarded_pre_dispatch),
                dispatched_id=dispatched_id)
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
    final["DISPATCH_NOW"] = bool(st.get("dispatch_enabled"))
    (EV / "dispatch-disable.json").write_text(json.dumps({
        "at": datetime.now(timezone.utc).isoformat(),
        "dispatch_enabled": st.get("dispatch_enabled"),
        "status": {k: st.get(k) for k in ("dispatch_enabled", "intake", "heartbeat_at", "last_error")},
    }, indent=2), encoding="utf-8")
    log("dispatch_verified_off", dispatch_enabled=st.get("dispatch_enabled"))
    if st.get("dispatch_enabled") is not False:
        # force again
        set_dispatch(False)
        time.sleep(2)
        st2 = json.loads(STATUS.read_text(encoding="utf-8-sig"))
        final["DISPATCH_NOW"] = bool(st2.get("dispatch_enabled"))
        log("dispatch_force_recheck", dispatch_enabled=st2.get("dispatch_enabled"))
except Exception as e:
    log("disable_error", error=str(e))
    final["DISPATCH_NOW"] = "ERROR"

final["elapsed_s"] = int((datetime.now(timezone.utc) - START).total_seconds())
final["discarded_pre_dispatch"] = discarded_pre_dispatch
final["STAGE_TIMINGS"] = stage_timeline
try:
    h = health()
    capture_progress(h, "final")
    (EV / "health-final.json").write_text(json.dumps(h, indent=2), encoding="utf-8")
    final["health_end_session"] = (h.get("session") or {}).get("state")
    final["health_end_app"] = h.get("app_version")
    final["health_end_vc"] = h.get("version_code")
    lr = h.get("last_result") or {}
    if isinstance(lr, dict):
        final["health_end_last_result"] = {
            "instruction_id": lr.get("instruction_id"),
            "status": lr.get("status"),
            "stage": lr.get("stage"),
            "detail": lr.get("detail"),
            "device_stage": lr.get("device_stage"),
            "duration_ms": lr.get("duration_ms"),
        }
        # if we dispatched and health last_result matches, merge stage timings
        if dispatched_id and lr.get("instruction_id") == dispatched_id:
            prog = lr.get("progress") or {}
            if isinstance(prog, dict) and prog.get("stages"):
                for s in prog["stages"]:
                    entry = {"source": "health_final", **s}
                    key = (s.get("stage"), s.get("at_ms"), s.get("elapsed_ms"))
                    if not any((e.get("stage"), e.get("at_ms"), e.get("elapsed_ms")) == key for e in stage_timeline):
                        stage_timeline.append(entry)
                final["STAGE_TIMINGS"] = stage_timeline
except Exception as e:
    final["health_end_error"] = str(e)

(EV / "health-progress-snapshots.json").write_text(json.dumps(health_progress_snapshots, indent=2), encoding="utf-8")
(EV / "stage-timeline.json").write_text(json.dumps(stage_timeline, indent=2), encoding="utf-8")
(EV / "final-summary.json").write_text(json.dumps(final, indent=2, default=str), encoding="utf-8")
(EV / "events.json").write_text(json.dumps(events, indent=2), encoding="utf-8")
print("DONE", json.dumps(final, default=str), flush=True)
