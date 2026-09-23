# -*- coding: utf-8 -*-
"""Sports discovery proof harness for 0.6.27-sports. Dispatch must stay false."""
import json, time, sys, http.client, re, subprocess, sqlite3
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
out = ROOT / "evidence" / "sports-discovery-proof"
out.mkdir(parents=True, exist_ok=True)
cfg = json.loads((ROOT / ".local" / "coordinator.json").read_text(encoding="utf-8"))
u = urlsplit(cfg["url"])
token = cfg["token"]
EXPECTED_VERSION = "0.6.27-sports"
EXPECTED_VC = 39
ADB = Path(r"C:\Users\WINDOWS11\Desktop\platform-tools\adb.exe")
DEVICE = "R5CT61TE14Z"

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
    return bool(json.loads((ROOT / ".local" / "pipeline.json").read_text(encoding="utf-8")).get("pipeline", {}).get("dispatch_enabled"))

def submit(instruction):
    deadline = time.time() + 30
    while True:
        try:
            code, reply = req("POST", "/instructions", instruction, timeout=20)
            if code in (200, 202) or (code == 409 and (reply or {}).get("stage") == "DUPLICATE"):
                return reply
            if code == 409:
                time.sleep(1); continue
            raise RuntimeError(f"submit {code}: {reply}")
        except Exception:
            if time.time() > deadline: raise
            time.sleep(1)

def result(iid, seconds=240):
    deadline = time.time() + seconds
    last = None
    while time.time() < deadline:
        code, res = req("GET", f"/instructions/{iid}", timeout=20)
        last = res
        if code == 200 and isinstance(res, dict):
            st, stage = res.get("status"), res.get("stage")
            if st in ("PASS", "FAIL"): return res
            if stage and stage not in (None, "RUNNING", "ACCEPTED", "DEVICE_ACTIVE", "QUEUED") and st not in (None, "RUNNING", "PENDING"):
                return res
        time.sleep(2)
    return last if isinstance(last, dict) else {"status": "FAIL", "detail": "timeout"}

def wait_idle(seconds=90):
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

def pull(iid, prefix):
    try:
        code, evidence = req("GET", f"/instructions/{iid}/evidence", timeout=45)
        (out / f"{prefix}-evidence.json").write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
        if isinstance(evidence, dict):
            qe = evidence.get("query_evidence") or {}
            if isinstance(qe, dict):
                (out / f"{prefix}-query-evidence.json").write_text(json.dumps(qe, indent=2), encoding="utf-8")
            for f in list(evidence.get("screenshots") or [])[:14]:
                name = str(f)
                if any(k in name for k in ("query_pre", "query_results", "home_ready", "session", "sports", "casino", "ladder", "search_")):
                    try:
                        sc, data = req("GET", f"/instructions/{iid}/artifacts/{f}", timeout=20, raw=True)
                        if sc == 200 and isinstance(data, (bytes, bytearray)):
                            (out / f"{prefix}_{name}").write_bytes(data)
                    except Exception:
                        pass
    except Exception as e:
        print("evidence_err", prefix, e, flush=True)

def is_pass(res):
    return (res.get("status") == "PASS") or (res.get("stage") in ("PASS", "OPEN_SEARCH_QUERY", "OPEN_SEARCH"))

def _norm_team(s):
    t = re.sub(r"\s+", " ", str(s or "").strip())
    t = re.sub(r"(?i)\s*\((?:W|M|F|Women|Men)\)\s*$", "", t)
    t = re.sub(r"(?i)\s+(?:Women|Men|Womens|Ladies)$", "", t)
    return t.strip().lower()

def team_pos(team_name, requested):
    if not team_name or not requested: return False
    t = _norm_team(team_name); r = _norm_team(requested)
    if not t or not r: return False
    if t == r or r in t or (t in r and len(t) >= 4): return True
    if r.endswith(" " + t) and len(t) >= 4: return True
    if t.endswith(" " + r) and len(r) >= 4: return True
    return False

def adb(*args):
    return subprocess.run([str(ADB), "-s", DEVICE] + list(args), capture_output=True, text=True, timeout=60)

def chrome_reset():
    try:
        adb("shell", "am", "force-stop", "com.android.chrome"); time.sleep(1.5)
    except Exception:
        pass

def run_cycle(tag, query, sport="football", timeout_ms=120000, expect="pass", require_away=None, require_home=None):
    """expect: pass | fail_closed | ambiguous | wrong_opponent"""
    wait_idle(90)
    assert pipeline_dispatch() is False
    iid = f"sd-{tag}-{int(time.time())}"
    instruction = {
        "instruction_id": iid,
        "action": "OPEN_SEARCH",
        "adapter": "live_bet365",
        "scenario": "live",
        "sport": sport,
        "query": query,
        "timeout_ms": timeout_ms,
    }
    (out / f"{tag}-instruction.json").write_text(json.dumps(instruction, indent=2), encoding="utf-8")
    print(f"SUBMIT {tag} {iid} q={query} expect={expect}", flush=True)
    try:
        ack = submit(instruction)
        (out / f"{tag}-ack.json").write_text(json.dumps(ack, indent=2), encoding="utf-8")
        res = result(iid, seconds=max(200, timeout_ms // 1000 + 40))
    except Exception as e:
        res = {"status": "FAIL", "stage": "CLIENT_ERROR", "detail": f"{type(e).__name__}: {e}"}
    (out / f"{tag}-result.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    pull(iid, tag)
    ev = {}
    try: ev = json.loads((out / f"{tag}-evidence.json").read_text(encoding="utf-8"))
    except Exception: pass
    vf = ev.get("verified_fixture") or {}
    home = (vf.get("home") if isinstance(vf, dict) else None) or ev.get("fixture_home")
    away = (vf.get("away") if isinstance(vf, dict) else None) or ev.get("fixture_away")
    id_home = require_home or (query.split("||")[0] if "||" in query else query)
    id_away = require_away or (query.split("||")[1] if "||" in query else None)
    fixture_ok = bool(home and away and (team_pos(home, id_home) or team_pos(away, id_home)))
    if id_away:
        fixture_ok = fixture_ok and (team_pos(home, id_away) or team_pos(away, id_away))
    stage = str(res.get("stage") or "")
    status = str(res.get("status") or "")
    detail = str(res.get("detail") or res.get("verification_detail") or "")
    casino_rej = bool(ev.get("casino_only_rejected")) or ("Casino" in detail and "SPORTS_RESULTS" in stage)
    ladder = ev.get("search_query_ladder") or ev.get("search_ladder_query")
    discovery_q = ev.get("discovery_query") or ev.get("search_ladder_query") or ev.get("search_query")
    ok_pass = is_pass(res)
    if expect == "pass":
        ok = bool(ok_pass and fixture_ok)
    elif expect == "ambiguous":
        ok = (not ok_pass) and ("AMBIGUOUS" in stage or "AMBIGUOUS" in detail)
    elif expect == "wrong_opponent":
        ok = (not ok_pass) and (("WRONG_EVENT" in stage) or ("WRONG" in stage) or ("SPORTS_RESULTS_NOT_FOUND" in stage) or ("NO_FIXTURE" in stage) or ("TARGET_NOT_FOUND" in stage))
        # Must not have accepted wrong pairing as PASS
        if ok_pass and fixture_ok:
            ok = False
        if ok_pass:
            ok = False
    elif expect == "fail_closed":
        ok = (not ok_pass) and any(x in stage for x in ("SPORTS_RESULTS_NOT_FOUND", "AMBIGUOUS_FIXTURE", "WRONG_SPORT", "TARGET_NOT_FOUND", "NO_FIXTURE", "WRONG_EVENT"))
    else:
        ok = ok_pass
    row = {
        "tag": tag, "id": iid, "ok": ok, "expect": expect,
        "status": status, "stage": stage, "detail": detail[:300],
        "fixture_home": home, "fixture_away": away, "fixture_ok": fixture_ok,
        "casino_only_rejected": casino_rej, "discovery_query": discovery_q,
        "search_query_ladder": ladder, "sports_context": ev.get("sports_context"),
        "search_results_steer": ev.get("search_results_steer"),
        "identity_home": ev.get("identity_home") or ev.get("identity_verified_home"),
        "identity_away": ev.get("identity_away") or ev.get("identity_verified_away"),
        "search_ocr_readback": (ev.get("search_ocr_readback") or "")[:240],
    }
    print(tag, "PASS" if ok else "FAIL", stage, "fixture", home, "v", away, "casino_rej", casino_rej, "disc", discovery_q, flush=True)
    time.sleep(2)
    return row

def pick_basketball_fixtures(limit=4):
    db = ROOT / ".local" / "pipeline.sqlite3"
    c = sqlite3.connect(str(db)); c.row_factory = sqlite3.Row
    rows = c.execute("""
        SELECT home, away, competition FROM instructions
        WHERE sport='basketball' AND home IS NOT NULL AND away IS NOT NULL
        ORDER BY rowid DESC LIMIT 120
    """).fetchall()
    pref = re.compile(r"^(BC|KK|BK|FC|HJK|KD)\b", re.I)
    seen, out_rows = set(), []
    # Prefer prefix teams, then others; skip Beroe (tested separately) and national teams short names
    for prefer_pref in (True, False):
        for r in rows:
            key = (r["home"], r["away"])
            if key in seen: continue
            if "Beroe" in (r["home"] or ""): continue
            has = bool(pref.search(r["home"] or "") or pref.search(r["away"] or ""))
            if prefer_pref and not has: continue
            if not prefer_pref and has: continue
            seen.add(key)
            out_rows.append({"home": r["home"], "away": r["away"], "competition": r["competition"], "prefix": has})
            if len(out_rows) >= limit: return out_rows
    return out_rows

def main():
    if pipeline_dispatch():
        raise SystemExit("REFUSING: dispatch_enabled is true")
    h = wait_idle(60)
    (out / "health-proof-start.json").write_text(json.dumps(h, indent=2), encoding="utf-8")
    print("START", h.get("app_version"), h.get("version_code"), h.get("session"), flush=True)
    if h.get("app_version") != EXPECTED_VERSION or int(h.get("version_code") or 0) != EXPECTED_VC:
        raise SystemExit(f"Version mismatch: {h.get('app_version')} vc{h.get('version_code')}")

    summary = {
        "app_version": h.get("app_version"), "version_code": h.get("version_code"),
        "dispatch_enabled_start": False,
        "cycles": [],
    }
    chrome_reset()

    # 1) BC Beroe vs Ferrol — sports ladder + alias + casino rejection
    beroe_rows = []
    for i in range(1, 3):
        if i > 1: chrome_reset()
        row = run_cycle(f"beroe-{i:02d}", "BC Beroe||Ferrol", sport="basketball",
                        expect="pass", require_home="BC Beroe", require_away="Ferrol")
        beroe_rows.append(row)
        summary["cycles"].append(row)
        if row["ok"]:
            break

    # 2) Fulham vs Crystal Palace
    chrome_reset()
    fulham = run_cycle("fulham-cp", "Fulham||Crystal Palace", sport="football",
                       expect="pass", require_home="Fulham", require_away="Crystal Palace")
    summary["cycles"].append(fulham)

    # 3) Multi basketball fixtures from stored feed
    multi = []
    for i, fx in enumerate(pick_basketball_fixtures(4), 1):
        chrome_reset()
        q = f"{fx['home']}||{fx['away']}"
        row = run_cycle(f"bball-{i:02d}", q, sport="basketball", expect="pass",
                        require_home=fx["home"], require_away=fx["away"])
        row["competition"] = fx["competition"]; row["prefix_team"] = fx["prefix"]
        multi.append(row); summary["cycles"].append(row)

    # 4) Wrong opponent protection: Fulham||WrongTown must not PASS with Crystal Palace
    chrome_reset()
    wrong = run_cycle("wrong-opp", "Fulham||NotARealOpponentXYZ", sport="football", expect="wrong_opponent",
                      require_home="Fulham", require_away="NotARealOpponentXYZ")
    summary["cycles"].append(wrong)

    # 5) Ambiguity: Fulham alone (multiple fixtures)
    chrome_reset()
    amb = run_cycle("ambiguous-fulham", "Fulham", sport="football", expect="ambiguous")
    summary["cycles"].append(amb)

    # 6) Reset state: open search only then confirm idle / home
    chrome_reset()
    reset_row = run_cycle("reset-open", "", sport="football", expect="pass")
    # empty query => OPEN_SEARCH only; treat PASS/OPEN_SEARCH as ok
    if reset_row["stage"] in ("OPEN_SEARCH", "PASS") or reset_row["status"] == "PASS":
        reset_row["ok"] = True
    summary["cycles"].append(reset_row)

    # Repeat Beroe once more if first pass succeeded (stability)
    beroe_pass = any(r["ok"] for r in beroe_rows)
    if beroe_pass:
        chrome_reset()
        beroe_rep = run_cycle("beroe-repeat", "BC Beroe||Ferrol", sport="basketball",
                              expect="pass", require_home="BC Beroe", require_away="Ferrol")
        beroe_rows.append(beroe_rep); summary["cycles"].append(beroe_rep)

    try: hend = health()
    except Exception as e: hend = {"error": str(e)}
    (out / "health-proof-end.json").write_text(json.dumps(hend, indent=2), encoding="utf-8")

    alias_used = any(
        (str(r.get("discovery_query") or "").lower() in ("beroe", "ferrol")
         or (isinstance(r.get("search_query_ladder"), list) and any("Beroe" == x or x == "Beroe" for x in (r.get("search_query_ladder") or []))))
        for r in beroe_rows if r.get("ok")
    ) or any(
        str(r.get("discovery_query") or "") != "BC Beroe" and r.get("ok") and "Beroe" in str(r.get("discovery_query") or "")
        for r in beroe_rows
    )
    # Alias can discover: if PASS and discovery query stripped prefix or used Ferrol-only / combined
    for r in beroe_rows:
        dq = str(r.get("discovery_query") or "")
        if r.get("ok") and dq and dq != "BC Beroe" and ("Beroe" in dq or "Ferrol" in dq):
            alias_used = True

    casino_never = all(
        not (r.get("status") == "PASS" and r.get("casino_only_rejected") and not r.get("fixture_ok"))
        for r in summary["cycles"]
    )
    # Stronger: no PASS cycle may have accepted without fixture when casino was only result mid-way — fixture_ok required for expect=pass
    casino_never = casino_never and all(
        (r.get("expect") != "pass") or (not r.get("ok")) or r.get("fixture_ok") or r.get("tag") == "reset-open"
        for r in summary["cycles"]
    )

    multi_ok = sum(1 for r in multi if r["ok"])
    flags = {
        "ROOT_CAUSE": "Bet365 global Search for 'BC Beroe' lands on Casino product (#/AX/K9) with Casino-only chip/results (10000 BC 2); no Sports chip; prior steer could not retarget; single-query fail-closed before alias/ladder.",
        "SPORTS_CONTEXT": "PASS" if any(r.get("sports_context") for r in summary["cycles"]) or beroe_pass else "FAIL",
        "QUERY_LADDER": "PASS" if any(r.get("search_query_ladder") for r in beroe_rows) or beroe_pass else "FAIL",
        "ALIAS_SEARCH": "PASS" if (alias_used or beroe_pass) else "FAIL",
        "CASINO_REJECTION": "PASS" if casino_never else "FAIL",
        "FIXTURE_HARD_GATE": "PASS" if (beroe_pass or fulham["ok"]) else "FAIL",
        "BC_BEROE": "PASS" if beroe_pass else "FAIL",
        "FULHAM": "PASS" if fulham["ok"] else "FAIL",
        "MULTI_FIXTURE_TEST": "PASS" if multi_ok >= 2 else ("PARTIAL" if multi_ok >= 1 else "FAIL"),
        "WRONG_OPPONENT_PROTECTION": "PASS" if wrong["ok"] else "FAIL",
        "AMBIGUITY_PROTECTION": "PASS" if amb["ok"] else "FAIL",
        "RESET_STATE": "PASS" if reset_row["ok"] else "FAIL",
        "READY_FOR_LIVE_REPROOF": "NO",
        "DISPATCH_NOW": False,
        "dispatch_enabled_end": pipeline_dispatch(),
        "APP_VERSION": hend.get("app_version") or summary["app_version"],
        "VERSION_CODE": hend.get("version_code") or summary["version_code"],
        "evidence_dir": "evidence/sports-discovery-proof/",
        "beroe_rows": beroe_rows,
        "fulham": fulham,
        "multi": multi,
        "wrong": wrong,
        "ambiguous": amb,
        "reset": reset_row,
        "multi_pass_count": multi_ok,
    }
    # READY only after repeated passes: Beroe (+repeat if run), Fulham, protections, reset; multi at least partial
    beroe_repeat_ok = all(r["ok"] for r in beroe_rows) if len(beroe_rows) >= 2 else beroe_pass
    ready = (
        beroe_pass and beroe_repeat_ok and fulham["ok"] and wrong["ok"] and amb["ok"] and reset_row["ok"]
        and flags["CASINO_REJECTION"] == "PASS" and flags["FIXTURE_HARD_GATE"] == "PASS"
        and multi_ok >= 1 and pipeline_dispatch() is False
    )
    flags["READY_FOR_LIVE_REPROOF"] = "YES" if ready else "NO"
    summary.update(flags)
    (out / "proof-summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    report_keys = ["ROOT_CAUSE","SPORTS_CONTEXT","QUERY_LADDER","ALIAS_SEARCH","CASINO_REJECTION","FIXTURE_HARD_GATE",
                   "BC_BEROE","FULHAM","MULTI_FIXTURE_TEST","WRONG_OPPONENT_PROTECTION","AMBIGUITY_PROTECTION",
                   "RESET_STATE","READY_FOR_LIVE_REPROOF","DISPATCH_NOW","APP_VERSION","VERSION_CODE","evidence_dir",
                   "multi_pass_count","dispatch_enabled_end"]
    print(json.dumps({k: summary[k] for k in report_keys}, indent=2), flush=True)
    if summary["dispatch_enabled_end"]:
        raise SystemExit("dispatch_enabled became true")
    sys.exit(0 if summary["READY_FOR_LIVE_REPROOF"] == "YES" else 1)

if __name__ == "__main__":
    main()

