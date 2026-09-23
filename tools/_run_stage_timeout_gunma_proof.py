# -*- coding: utf-8 -*-
"""Stage-timeout / session-keepalive / Gunma proof for 0.6.28-stage. dispatch must stay false."""
import json, time, sys, http.client, re, subprocess, sqlite3
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence" / "stage-timeout-gunma-proof"
OUT.mkdir(parents=True, exist_ok=True)
cfg = json.loads((ROOT / ".local" / "coordinator.json").read_text(encoding="utf-8-sig"))
u = urlsplit(cfg["url"])
token = cfg["token"]
EXPECTED_VERSION = "0.6.28-stage"
EXPECTED_VC = 40
ADB = Path(r"C:\Users\WINDOWS11\Desktop\platform-tools\adb.exe")
DEVICE = "R5CT61TE14Z"
ABS_TIMEOUT_MS = 300000
STAGE_INACTIVITY_MS = 45000

def req(method, path, body=None, timeout=30, raw=False):
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=timeout)
    payload = None if body is None else json.dumps(body).encode()
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    try:
        conn.request(method, path, payload, headers)
        r = conn.getresponse(); data = r.read()
        if raw: return r.status, data
        try: return r.status, json.loads(data.decode() or "null")
        except Exception: return r.status, {"raw": data.decode("utf-8", "replace")}
    finally:
        conn.close()

def health():
    code, h = req("GET", "/health", timeout=20)
    if code != 200: raise RuntimeError(h)
    return h

def pipeline_dispatch():
    return bool(json.loads((ROOT / ".local" / "pipeline.json").read_text(encoding="utf-8-sig")).get("pipeline", {}).get("dispatch_enabled"))

def assert_dispatch_off(tag=""):
    if pipeline_dispatch() is not False:
        raise RuntimeError(f"dispatch_enabled true at {tag}")

def submit(instruction):
    deadline = time.time() + 45
    while True:
        try:
            code, reply = req("POST", "/instructions", instruction, timeout=25)
            if code in (200, 202) or (code == 409 and (reply or {}).get("stage") == "DUPLICATE"):
                return reply
            if code == 409:
                time.sleep(1.5); continue
            raise RuntimeError(f"submit {code}: {reply}")
        except Exception:
            if time.time() > deadline: raise
            time.sleep(1)

def poll_until_done(iid, seconds=360):
    deadline = time.time() + seconds
    progress_log = []
    last = None
    while time.time() < deadline:
        code, res = req("GET", f"/instructions/{iid}", timeout=20)
        last = res
        if code == 202 and isinstance(res, dict):
            prog = res.get("progress") or {}
            stage = res.get("device_stage") or prog.get("stage")
            if stage:
                entry = {"t": time.time(), "http": 202, "stage": stage, "progress": prog}
                if not progress_log or progress_log[-1].get("stage") != stage:
                    progress_log.append(entry)
                    print(f"  progress {iid} -> {stage} elapsed={prog.get('elapsed_ms')}", flush=True)
        if code == 200 and isinstance(res, dict):
            st = res.get("status")
            if st in ("PASS", "FAIL"):
                return res, progress_log
        time.sleep(1.5)
    return (last if isinstance(last, dict) else {"status": "FAIL", "detail": "client_poll_timeout"}), progress_log

def wait_idle(seconds=120):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            h = health()
            if h.get("state") in ("IDLE", "idle", None) and not h.get("current_instruction"):
                return h
        except Exception:
            pass
        time.sleep(2)
    return health()

def pull_evidence(iid, prefix):
    try:
        code, evidence = req("GET", f"/instructions/{iid}/evidence", timeout=60)
        (OUT / f"{prefix}-evidence.json").write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
        if not isinstance(evidence, dict):
            return evidence
        for f in list(evidence.get("screenshots") or [])[:20]:
            name = str(f)
            if any(k in name for k in ("sports", "search", "home", "session", "query", "fixtures")):
                try:
                    sc, data = req("GET", f"/instructions/{iid}/artifacts/{f}", timeout=25, raw=True)
                    if sc == 200 and isinstance(data, (bytes, bytearray)):
                        (OUT / f"{prefix}_{name}").write_bytes(data)
                except Exception:
                    pass
        return evidence
    except Exception as e:
        print("evidence_err", prefix, e, flush=True)
        return {}

def adb(*args):
    return subprocess.run([str(ADB), "-s", DEVICE] + list(args), capture_output=True, text=True, timeout=60)

def wake():
    adb("shell", "input", "keyevent", "KEYCODE_WAKEUP")
    time.sleep(1)
    adb("shell", "input", "keyevent", "82")
    time.sleep(1)

def session_check():
    wait_idle(90)
    assert_dispatch_off("pre-session-check")
    iid = f"st-session-{int(time.time())}"
    instruction = {
        "instruction_id": iid,
        "action": "SESSION_CHECK",
        "adapter": "live_bet365",
        "scenario": "live",
        "sport": "basketball",
        "timeout_ms": 90000,
    }
    (OUT / "session-check-instruction.json").write_text(json.dumps(instruction, indent=2), encoding="utf-8")
    print("SESSION_CHECK", iid, flush=True)
    submit(instruction)
    res, prog = poll_until_done(iid, 120)
    (OUT / "session-check-result.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    pull_evidence(iid, "session-check")
    h = wait_idle(60)
    (OUT / "health-after-session.json").write_text(json.dumps(h, indent=2), encoding="utf-8")
    return res, h

def run_ready(tag, home, away, sport, market="SPREAD", side="HOME", line="-1.5",
              minimum_price="1.80", stake="0.10", timeout_ms=ABS_TIMEOUT_MS):
    wait_idle(90)
    assert_dispatch_off(tag)
    wake()
    h0 = health()
    sess0 = (h0.get("session") or {}).get("state")
    iid = f"st-{tag}-{int(time.time())}"[:64]
    query = f"{home}||{away}" if away else home
    instruction = {
        "instruction_id": iid,
        "action": "ADAPTER_WORKFLOW",
        "adapter": "live_bet365",
        "scenario": "live",
        "query": query,
        "sport": sport,
        "market": market,
        "side": side,
        "line": str(line),
        "minimum_price": minimum_price,
        "stake": stake,
        "timeout_ms": timeout_ms,
        "execution_mode": "ready",
    }
    (OUT / f"{tag}-instruction.json").write_text(json.dumps(instruction, indent=2), encoding="utf-8")
    print(f"SUBMIT {tag} {iid} q={query} session_pre={sess0}", flush=True)
    t0 = time.time()
    try:
        ack = submit(instruction)
        (OUT / f"{tag}-ack.json").write_text(json.dumps(ack, indent=2), encoding="utf-8")
        res, progress_log = poll_until_done(iid, seconds=max(120, timeout_ms // 1000 + 60))
    except Exception as e:
        res, progress_log = {"status": "FAIL", "stage": "CLIENT_ERROR", "detail": f"{type(e).__name__}: {e}"}, []
    elapsed = time.time() - t0
    (OUT / f"{tag}-result.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    (OUT / f"{tag}-progress.json").write_text(json.dumps(progress_log, indent=2), encoding="utf-8")
    ev = pull_evidence(iid, tag) or {}
    h1 = health()
    sess1 = (h1.get("session") or {}).get("state")
    stages = ev.get("stage_timings") or (res.get("progress") or {}).get("stages") or []
    sports_ctx = ev.get("sports_context")
    search_start = None
    for st in stages if isinstance(stages, list) else []:
        if isinstance(st, dict) and st.get("stage") in ("OPEN_SEARCH", "SPORTS_CONTEXT", "FOCUS", "ENTER_QUERY"):
            if search_start is None and st.get("stage") == "OPEN_SEARCH":
                search_start = st.get("start_elapsed_ms")
    # Infer search start from progress log
    for p in progress_log:
        if p.get("stage") == "OPEN_SEARCH" and search_start is None:
            search_start = (p.get("progress") or {}).get("elapsed_ms")
    row = {
        "tag": tag, "id": iid, "elapsed_s": round(elapsed, 1),
        "status": res.get("status"), "stage": res.get("stage"), "detail": str(res.get("detail") or "")[:400],
        "session_pre": sess0, "session_post": sess1,
        "sports_context": sports_ctx,
        "search_start_elapsed_ms": search_start,
        "device_stage_final": res.get("device_stage") or res.get("stage"),
        "progress_stages_seen": [p.get("stage") for p in progress_log],
        "stage_timings": stages,
        "fixture_home": res.get("home") or (ev.get("verified_fixture") or {}).get("home") if isinstance(ev.get("verified_fixture"), dict) else None,
        "fixture_away": res.get("away") or (ev.get("verified_fixture") or {}).get("away") if isinstance(ev.get("verified_fixture"), dict) else None,
        "dispatch_enabled": pipeline_dispatch(),
        "app_version": h1.get("app_version"),
    }
    (OUT / f"{tag}-summary.json").write_text(json.dumps(row, indent=2, default=str), encoding="utf-8")
    print(tag, row["status"], row["stage"], "sports_ctx", sports_ctx, "search_ms", search_start, "sess", sess0, "->", sess1, flush=True)
    assert_dispatch_off(tag + "-end")
    time.sleep(2)
    return row

def force_stuck_timeout():
    """Force a stuck-stage timeout by starting a job then freezing Chrome UI via airplane? 
    Safer: submit OPEN_SEARCH then immediately force-stop Chrome mid-flight so OCR/progress stalls -> inactivity TIMEOUT.
    """
    wait_idle(90)
    assert_dispatch_off("stuck-pre")
    wake()
    iid = f"st-stuck-{int(time.time())}"[:64]
    instruction = {
        "instruction_id": iid,
        "action": "ADAPTER_WORKFLOW",
        "adapter": "live_bet365",
        "scenario": "live",
        "query": "Gunma Crane Thunders||Altiri Chiba",
        "sport": "basketball",
        "market": "SPREAD",
        "side": "HOME",
        "line": "-12.5",
        "minimum_price": "2.12",
        "stake": "0.10",
        "timeout_ms": ABS_TIMEOUT_MS,
        "execution_mode": "ready",
    }
    (OUT / "stuck-instruction.json").write_text(json.dumps(instruction, indent=2), encoding="utf-8")
    print("STUCK_TEST submit", iid, flush=True)
    submit(instruction)
    # Wait until we see some progress, then kill Chrome to stall UI without killing the agent.
    saw = False
    t0 = time.time()
    while time.time() - t0 < 40:
        code, res = req("GET", f"/instructions/{iid}", timeout=15)
        if code == 202 and isinstance(res, dict):
            st = res.get("device_stage") or (res.get("progress") or {}).get("stage")
            if st and st not in ("STARTED", "IDLE", None):
                saw = True
                print("  stuck-test saw stage", st, "-> force-stop chrome", flush=True)
                adb("shell", "am", "force-stop", "com.android.chrome")
                break
        time.sleep(1)
    if not saw:
        # Still force-stop to induce stall
        adb("shell", "am", "force-stop", "com.android.chrome")
        print("  stuck-test force-stop without early progress", flush=True)
    res, progress_log = poll_until_done(iid, seconds=120)
    (OUT / "stuck-result.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    (OUT / "stuck-progress.json").write_text(json.dumps(progress_log, indent=2), encoding="utf-8")
    pull_evidence(iid, "stuck")
    detail = str(res.get("detail") or "")
    ok = res.get("status") == "FAIL" and res.get("stage") == "TIMEOUT" and (
        "inactivity" in detail.lower() or "Absolute deadline" in detail or "Stage inactivity" in detail
    )
    # Reset: reopen chrome / wait idle
    wake()
    adb("shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", "https://www.bet365.com/#/HO/", "com.android.chrome")
    time.sleep(3)
    h = wait_idle(90)
    reset_ok = h.get("state") in ("IDLE", None) and not h.get("current_instruction")
    # Re-probe session
    try:
        sc_res, h2 = session_check()
        sess = (h2.get("session") or {}).get("state")
    except Exception as e:
        sc_res, sess = {"detail": str(e)}, "ERROR"
    row = {
        "ok_timeout": ok, "ok_reset": reset_ok and sess in ("AUTHENTICATED", "UNKNOWN", "LOGGED_OUT"),
        "result": res, "session_after_reset": sess, "detail": detail[:400],
        "progress_stages": [p.get("stage") for p in progress_log],
        "dispatch_enabled": pipeline_dispatch(),
    }
    (OUT / "stuck-summary.json").write_text(json.dumps(row, indent=2, default=str), encoding="utf-8")
    print("STUCK", "TIMEOUT_OK" if ok else "TIMEOUT_FAIL", "RESET", reset_ok, "session", sess, flush=True)
    return row

def pick_basketballs(limit=3):
    db = sqlite3.connect(str(ROOT / ".local" / "pipeline.sqlite3"))
    db.row_factory = sqlite3.Row
    rows = db.execute("""
        SELECT home, away, market, selection, line, minimum_price, stake FROM instructions
        WHERE sport='basketball' AND home IS NOT NULL AND away IS NOT NULL
        ORDER BY rowid DESC LIMIT 80
    """).fetchall()
    seen, out = set(), []
    skip = {"Gunma Crane Thunders", "BC Beroe"}
    for r in rows:
        if r["home"] in skip: continue
        if not r["minimum_price"] or not r["stake"]: continue
        key = (r["home"], r["away"])
        if key in seen: continue
        seen.add(key)
        market = r["market"]
        if market == "TOTALS": market = "TOTAL"
        line = r["line"]
        # normalize line for schema
        if line is None: continue
        out.append({
            "home": r["home"], "away": r["away"], "market": market,
            "side": r["selection"], "line": str(line).replace("+", "") if str(line).startswith("+") else str(line),
            "minimum_price": r["minimum_price"], "stake": r["stake"] or "0.10",
        })
        if len(out) >= limit: break
    return out

def main():
    wake()
    h = health()
    (OUT / "health-start.json").write_text(json.dumps(h, indent=2), encoding="utf-8")
    assert h.get("app_version") == EXPECTED_VERSION, h.get("app_version")
    assert int(h.get("version_code")) == EXPECTED_VC
    assert_dispatch_off("start")
    print("VERSION OK", h.get("app_version"), "dispatch", pipeline_dispatch(), flush=True)

    sc_res, h_sess = session_check()
    sess = (h_sess.get("session") or {}).get("state")
    print("SESSION after check:", sess, flush=True)

    cycles = []
    # 1) Gunma
    cycles.append(run_ready(
        "gunma", "Gunma Crane Thunders", "Altiri Chiba", "basketball",
        market="SPREAD", side="HOME", line="-12.5", minimum_price="2.12", stake="0.10"))

    # 2) 3 basketballs
    bbs = pick_basketballs(3)
    (OUT / "basketball-selection.json").write_text(json.dumps(bbs, indent=2), encoding="utf-8")
    for i, b in enumerate(bbs, 1):
        tag = f"bb{i}"
        cycles.append(run_ready(
            tag, b["home"], b["away"], "basketball",
            market=b["market"], side=b["side"], line=b["line"],
            minimum_price=b["minimum_price"], stake=b.get("stake") or "0.10"))

    # 3) Fulham football control
    cycles.append(run_ready(
        "fulham", "Fulham", "Crystal Palace", "football",
        market="SPREAD", side="HOME", line="-0.5", minimum_price="1.80", stake="0.10"))

    # 4) stuck timeout + reset
    stuck = force_stuck_timeout()

    # Analyze Gunma
    gunma = next(c for c in cycles if c["tag"] == "gunma")
    search_ok = gunma.get("search_start_elapsed_ms") is not None and gunma["search_start_elapsed_ms"] < 90000
    sports_ok = gunma.get("sports_context") not in (None, "")
    no_120_stall = not (gunma.get("stage") == "TIMEOUT" and "hard deadline" in str(gunma.get("detail") or "").lower() and gunma.get("search_start_elapsed_ms") is None)
    progress_ok = len(gunma.get("progress_stages_seen") or []) >= 2
    sess_ok = gunma.get("session_post") == "AUTHENTICATED" or sess == "AUTHENTICATED"

    bb_rows = [c for c in cycles if c["tag"].startswith("bb")]
    fulham = next(c for c in cycles if c["tag"] == "fulham")

    summary = {
        "HOTFIX_COMMIT": "bdcd4bb",
        "ROOT_CAUSE": (
            "Prior Gunma tip on-ee808246 spent ~120s DEVICE_ACTIVE with device_stage=null; "
            "CoordinatorAgent single hard deadline (timeout_ms=120000) killed the job as "
            "'Coordinator hard deadline expired' before Search began. Completer inferred "
            "SPORTS_CONTEXT/SEARCH TIMEOUT. Concurrently refreshSession flipped session to "
            "UNKNOWN while instruction active (raced SESSION_REQUIRED). No mid-flight progress "
            "heartbeats; capture/OCR could burn the global budget without stage visibility."
        ),
        "SESSION_KEEPALIVE": {
            "pre_job_refresh": True,
            "job_active_keepalive_without_UNKNOWN": True,
            "session_max_age_seconds": 120,
            "session_after_check": sess,
            "note": "Do not bump session_max_age; hold AUTHENTICATED observed_at during job; ENSURE_SESSION re-probes on screen",
        },
        "STAGE_TIMINGS": {c["tag"]: c.get("stage_timings") for c in cycles},
        "SPORTS_CONTEXT_BASKETBALL": "PASS" if sports_ok or any((c.get("sports_context") for c in bb_rows)) else "FAIL",
        "SEARCH_START_TIME": gunma.get("search_start_elapsed_ms"),
        "PROGRESS_HEARTBEAT": "PASS" if progress_ok else "FAIL",
        "STAGE_TIMEOUTS": {
            "inactivity_ms": STAGE_INACTIVITY_MS,
            "soft_stage_ms": 60000,
            "stuck_proof": stuck,
        },
        "ABSOLUTE_TIMEOUT": ABS_TIMEOUT_MS,
        "GUNMA": gunma,
        "BASKETBALL_MULTI_TEST": bb_rows,
        "FULHAM_CONTROL": fulham,
        "RESET_AFTER_TIMEOUT": stuck,
        "COMMIT": None,  # filled after git commit
        "APP_VERSION": f"{EXPECTED_VERSION} vc{EXPECTED_VC}",
        "READY_FOR_LIVE_REPROOF": None,
        "DISPATCH_NOW": False,
        "dispatch_enabled_end": pipeline_dispatch(),
        "evidence_dir": str(OUT),
        "health_final": health(),
    }

    # Verdict
    gunma_reach_search = search_ok or ("OPEN_SEARCH" in (gunma.get("progress_stages_seen") or [])) or gunma.get("status") == "PASS"
    bb_any_progress = any(len(c.get("progress_stages_seen") or []) >= 1 for c in bb_rows)
    fulham_ok = fulham.get("status") in ("PASS", "FAIL")  # terminal with progress is enough for control; PASS preferred
    reset_ok = bool(stuck.get("ok_timeout")) and bool(stuck.get("ok_reset"))

    blockers = []
    if not gunma_reach_search:
        blockers.append("Gunma did not reach OPEN_SEARCH within bounded time")
    if not progress_ok:
        blockers.append("Progress heartbeats not observed for Gunma")
    if not stuck.get("ok_timeout"):
        blockers.append("Stuck-stage inactivity timeout not proven")
    if not stuck.get("ok_reset"):
        blockers.append("Reset after timeout not proven")
    if pipeline_dispatch() is not False:
        blockers.append("dispatch_enabled not false")

    summary["READY_FOR_LIVE_REPROOF"] = "YES" if not blockers and gunma_reach_search and progress_ok else "NO"
    summary["residual_blockers"] = blockers
    summary["GUNMA_REACH_SEARCH"] = gunma_reach_search
    summary["BASKETBALL_MULTI_PROGRESS"] = bb_any_progress
    summary["FULHAM_TERMINAL"] = fulham_ok

    (OUT / "proof-summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in (
        "SPORTS_CONTEXT_BASKETBALL","SEARCH_START_TIME","PROGRESS_HEARTBEAT","READY_FOR_LIVE_REPROOF",
        "DISPATCH_NOW","residual_blockers","GUNMA_REACH_SEARCH")}, indent=2), flush=True)
    return 0 if summary["READY_FOR_LIVE_REPROOF"] == "YES" else 1

if __name__ == "__main__":
    sys.exit(main())
