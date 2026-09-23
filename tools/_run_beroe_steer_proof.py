"""Focused Beroe Sports-steer + Fulham wrong-fixture protection. dispatch must stay false."""
import json, time, sys, http.client, re, subprocess
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
out = ROOT / "evidence" / "beroe-ocr-fixture-proof"
out.mkdir(parents=True, exist_ok=True)
cfg = json.loads((ROOT / ".local" / "coordinator.json").read_text(encoding="utf-8"))
u = urlsplit(cfg["url"])
token = cfg["token"]
ADB = Path(r"C:\Users\WINDOWS11\Desktop\platform-tools\adb.exe")

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

def result(iid, seconds=180):
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
        except Exception: pass
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
            for f in list(evidence.get("screenshots") or []):
                name = str(f)
                if any(k in name for k in ("query_results", "query_pre", "sports", "after", "focused")):
                    try:
                        sc, data = req("GET", f"/instructions/{iid}/artifacts/{f}", timeout=20, raw=True)
                        if sc == 200 and isinstance(data, (bytes, bytearray)):
                            (out / f"{prefix}_{name}").write_bytes(data)
                    except Exception: pass
        return evidence if isinstance(evidence, dict) else {}
    except Exception as e:
        print("pull_err", e, flush=True); return {}

def adb(*a):
    return subprocess.run([str(ADB), "-s", "R5CT61TE14Z"] + list(a), capture_output=True, text=True, timeout=60)

def team_pos(team, reqd):
    if not team or not reqd: return False
    t = re.sub(r"\s+", " ", str(team).strip()).lower()
    r = re.sub(r"\s+", " ", str(reqd).strip()).lower()
    return t == r or r in t or (r.endswith(" " + t) and len(t) >= 4)

def run_one(tag, query, sport):
    wait_idle(90)
    assert pipeline_dispatch() is False
    iid = f"steer-{tag}-{int(time.time())}"
    instruction = {
        "instruction_id": iid, "action": "OPEN_SEARCH", "adapter": "live_bet365",
        "scenario": "live", "sport": sport, "query": query, "timeout_ms": 120000,
    }
    (out / f"{tag}-instruction.json").write_text(json.dumps(instruction, indent=2), encoding="utf-8")
    print("SUBMIT", tag, iid, query, flush=True)
    try:
        ack = submit(instruction)
        (out / f"{tag}-ack.json").write_text(json.dumps(ack, indent=2), encoding="utf-8")
        res = result(iid, seconds=180)
    except Exception as e:
        res = {"status": "FAIL", "stage": "CLIENT_ERROR", "detail": f"{type(e).__name__}: {e}"}
    (out / f"{tag}-result.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    ev = pull(iid, tag)
    qe = {}
    try: qe = json.loads((out / f"{tag}-query-evidence.json").read_text(encoding="utf-8"))
    except Exception: pass
    vf = ev.get("verified_fixture") or {}
    home = (vf.get("home") if isinstance(vf, dict) else None) or ev.get("fixture_home")
    away = (vf.get("away") if isinstance(vf, dict) else None) or ev.get("fixture_away")
    typed = query.split("||")[0]
    exp_away = query.split("||")[1] if "||" in query else None
    fixture_ok = bool(home and away and (team_pos(home, typed) or team_pos(away, typed)))
    if exp_away:
        fixture_ok = fixture_ok and (team_pos(home, exp_away) or team_pos(away, exp_away))
    readback = str(ev.get("search_ocr_readback") or "")
    casino_only = ("Casino" in readback) and not any(x in readback for x in ("Football", "TEAMS", "Sports", "Basketball", " v ", " V "))
    steer = ev.get("search_results_steer")
    screens = [str(s) for s in (ev.get("screenshots") or [])]
    sports_shot = any("sports" in s for s in screens)
    row = {
        "tag": tag, "id": iid, "status": res.get("status"), "stage": res.get("stage"),
        "detail": res.get("detail") or res.get("verification_detail"),
        "exact_input_match": qe.get("exact_input_match"),
        "visual_text_match": qe.get("visual_text_match"),
        "ocr_soft_pass": bool(qe.get("ocr_soft_pass") or qe.get("ocr_gate") == "SOFT_SUPPORTING"),
        "visible_field_text": qe.get("visible_field_text"),
        "observed_text": qe.get("observed_text"),
        "search_results_steer": steer,
        "sports_shot": sports_shot,
        "casino_only": casino_only,
        "fixture_home": home, "fixture_away": away, "fixture_ok": fixture_ok,
        "search_result_fixtures": ev.get("search_result_fixtures"),
        "readback_snip": readback[:280],
    }
    print(tag, res.get("stage"), "exact", row["exact_input_match"], "soft", row["ocr_soft_pass"],
          "ocr", row["visible_field_text"], "steer", steer, "casino_only", casino_only,
          "fixture", home, "v", away, flush=True)
    time.sleep(2)
    return row

def main():
    if pipeline_dispatch():
        raise SystemExit("REFUSING: dispatch_enabled is true")
    h = wait_idle(60)
    (out / "health-steer-start.json").write_text(json.dumps(h, indent=2), encoding="utf-8")
    print("START", h.get("app_version"), h.get("version_code"), h.get("session"), flush=True)
    if h.get("app_version") != "0.6.26-ocr" or int(h.get("version_code") or 0) != 38:
        raise SystemExit(f"version mismatch {h.get('app_version')} vc{h.get('version_code')}")

    try:
        adb("shell", "am", "force-stop", "com.android.chrome"); time.sleep(1.5)
    except Exception: pass

    summary = {"app_version": h.get("app_version"), "version_code": h.get("version_code"), "dispatch_enabled_start": False}

    # 1) Beroe soft OCR + sports-steer + fixture hard gate
    beroe = run_one("beroe-steer-01", "BC Beroe||Ferrol", "basketball")
    summary["beroe"] = beroe

    # 2) Fulham without away => must AMBIGUOUS (wrong-fixture protection)
    try:
        adb("shell", "am", "force-stop", "com.android.chrome"); time.sleep(1.5)
    except Exception: pass
    fulham = run_one("fulham-ambiguous-01", "Fulham", "football")
    summary["fulham_protection"] = fulham

    # Optional: Fulham||Crystal Palace unique pairing if time - one shot
    try:
        adb("shell", "am", "force-stop", "com.android.chrome"); time.sleep(1.5)
    except Exception: pass
    fulham_pair = run_one("fulham-pair-01", "Fulham||Crystal Palace", "football")
    summary["fulham_pair"] = fulham_pair

    beroe_soft = bool(beroe.get("exact_input_match") and (beroe.get("ocr_soft_pass") or beroe.get("visual_text_match")))
    sports_steer = "PASS" if (beroe.get("search_results_steer") or beroe.get("sports_shot") or not beroe.get("casino_only")) else "FAIL"
    if beroe.get("casino_only") and not beroe.get("search_results_steer"):
        sports_steer = "FAIL_CASINO_ONLY_NO_CHIP"
    elif beroe.get("fixture_ok"):
        sports_steer = "PASS"
    elif beroe.get("search_results_steer"):
        sports_steer = "PASS_CHIP_TAPPED"
    elif beroe.get("casino_only"):
        sports_steer = "FAIL_CASINO_ONLY"

    fixture_gate = "PASS" if beroe.get("fixture_ok") else ("FAIL_CLOSED_CASINO_ONLY" if beroe.get("casino_only") else str(beroe.get("stage")))
    fulham_prot = "PASS" if str(fulham.get("stage")) == "AMBIGUOUS_FIXTURE" else "FAIL"
    fulham_pair_ok = "PASS" if fulham_pair.get("fixture_ok") and fulham_pair.get("status") == "PASS" else "FAIL"

    try: hend = health()
    except Exception as e: hend = {"error": str(e)}
    (out / "health-steer-end.json").write_text(json.dumps(hend, indent=2), encoding="utf-8")

    ready = (
        beroe_soft
        and fulham_prot == "PASS"
        and pipeline_dispatch() is False
        and (beroe.get("fixture_ok") or fulham_pair_ok == "PASS")
    )
    # CoS: READY only if Beroe fixture hard gate passes OR we must report Casino-only blocker (ready=NO)
    if beroe.get("casino_only") and not beroe.get("fixture_ok"):
        ready = False

    summary.update({
        "SPORTS_STEER": sports_steer,
        "BEROE_SOFT_OCR": "PASS" if beroe_soft else "FAIL",
        "BEROE_FIXTURE_HARD_GATE": fixture_gate,
        "FULHAM_WRONG_FIXTURE_PROTECTION": fulham_prot,
        "FULHAM_PAIR_UNIQUE": fulham_pair_ok,
        "READY_FOR_LIVE_REPROOF": "YES" if ready else "NO",
        "DISPATCH_NOW": False,
        "dispatch_enabled_end": pipeline_dispatch(),
        "APP_VERSION": hend.get("app_version") or "0.6.26-ocr",
        "VERSION_CODE": hend.get("version_code") or 38,
        "evidence_dir": "evidence/beroe-ocr-fixture-proof/",
        "CASINO_ONLY_BLOCKER": bool(beroe.get("casino_only") and not beroe.get("fixture_ok")),
    })
    (out / "proof-summary-steer.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in [
        "SPORTS_STEER", "BEROE_SOFT_OCR", "BEROE_FIXTURE_HARD_GATE",
        "FULHAM_WRONG_FIXTURE_PROTECTION", "FULHAM_PAIR_UNIQUE",
        "READY_FOR_LIVE_REPROOF", "DISPATCH_NOW", "CASINO_ONLY_BLOCKER",
        "APP_VERSION", "VERSION_CODE", "evidence_dir"
    ]}, indent=2), flush=True)
    sys.exit(0 if summary["READY_FOR_LIVE_REPROOF"] == "YES" else 1)

if __name__ == "__main__":
    main()
