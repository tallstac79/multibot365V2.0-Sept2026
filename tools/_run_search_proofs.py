import json, time, sys, http.client
from pathlib import Path
from urllib.parse import urlsplit

out = Path("evidence/search-ui-fix")
out.mkdir(parents=True, exist_ok=True)
cfg = json.loads(Path(".local/coordinator.json").read_text(encoding="utf-8"))
u = urlsplit(cfg["url"])
token = cfg["token"]

def req(method, path, body=None, timeout=30, raw=False):
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=timeout)
    payload = None if body is None else json.dumps(body).encode()
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    try:
        conn.request(method, path, payload, headers)
        r = conn.getresponse()
        data = r.read()
        if raw:
            return r.status, data
        try:
            return r.status, json.loads(data.decode() or "null")
        except Exception:
            return r.status, {"raw": data.decode("utf-8", "replace")}
    finally:
        conn.close()

def health():
    code, h = req("GET", "/health", timeout=20)
    if code != 200:
        raise RuntimeError(h)
    return h

def submit(instruction):
    deadline = time.time() + 30
    while True:
        try:
            code, reply = req("POST", "/instructions", instruction, timeout=20)
            if code in (200, 202) or (code == 409 and (reply or {}).get("stage") == "DUPLICATE"):
                return reply
            raise ValueError(reply)
        except (OSError, http.client.HTTPException, TimeoutError) as e:
            if time.time() >= deadline:
                raise
            time.sleep(1)

def result(iid, seconds=120):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            code, value = req("GET", f"/instructions/{iid}", timeout=20)
            if code == 200:
                return value
            if code not in (202, 204):
                raise ValueError(value)
        except (OSError, http.client.HTTPException, TimeoutError):
            pass
        time.sleep(2)
    raise TimeoutError(iid)

def wait_idle(seconds=60):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            h = health()
            cur = h.get("current_instruction")
            if h.get("state") in ("IDLE", "idle", None) and not cur:
                return h
        except Exception:
            pass
        time.sleep(2)
    return health()

def pull_evidence(iid, prefix):
    try:
        code, evidence = req("GET", f"/instructions/{iid}/evidence", timeout=30)
        (out / f"{prefix}-evidence.json").write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
        if code == 200 and isinstance(evidence, dict):
            files = list(evidence.get("screenshots") or [])
            for f in list(files):
                files.append(f.replace(".png", ".txt"))
            for f in files:
                sc, data = req("GET", f"/instructions/{iid}/artifacts/{f}", timeout=30, raw=True)
                if sc == 200 and isinstance(data, (bytes, bytearray)):
                    (out / f"{prefix}_{f}").write_bytes(data)
    except Exception as e:
        print("evidence_err", prefix, e, flush=True)

h = wait_idle(45)
(out / "health-proof-start.json").write_text(json.dumps(h, indent=2), encoding="utf-8")
print("START", h.get("app_version"), h.get("version_code"), h.get("session"), flush=True)
assert h.get("app_version") == "0.6.24-search" and int(h.get("version_code") or 0) == 36

results = {"open_search": [], "text_entry": None, "app_version": h.get("app_version"), "version_code": h.get("version_code")}

for i in range(1, 6):
    wait_idle(45)
    iid = f"open-search-{int(time.time())}-{i}"
    instruction = {
        "instruction_id": iid,
        "action": "OPEN_SEARCH",
        "adapter": "live_bet365",
        "scenario": "live",
        "sport": "football",
        "timeout_ms": 90000,
    }
    (out / f"open-search-{i}-instruction.json").write_text(json.dumps(instruction, indent=2), encoding="utf-8")
    print(f"OPEN_SEARCH {i} submit {iid}", flush=True)
    try:
        ack = submit(instruction)
        (out / f"open-search-{i}-ack.json").write_text(json.dumps(ack, indent=2), encoding="utf-8")
        res = result(iid, seconds=130)
    except Exception as e:
        res = {"status": "FAIL", "stage": "CLIENT_ERROR", "detail": f"{type(e).__name__}: {e}"}
    (out / f"open-search-{i}-result.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    pull_evidence(iid, f"open-search-{i}")
    ok = (res.get("status") == "PASS") or (res.get("stage") in ("PASS", "OPEN_SEARCH"))
    results["open_search"].append({"i": i, "id": iid, "ok": bool(ok), "status": res.get("status"), "stage": res.get("stage"), "detail": res.get("detail") or res.get("verification_detail")})
    print(f"OPEN_SEARCH {i}", "PASS" if ok else "FAIL", res.get("stage"), res.get("detail"), flush=True)
    time.sleep(2)

wait_idle(45)
iid = f"search-fulham-{int(time.time())}"
instruction = {
    "instruction_id": iid,
    "action": "OPEN_SEARCH",
    "adapter": "live_bet365",
    "scenario": "live",
    "sport": "football",
    "query": "Fulham",
    "timeout_ms": 120000,
}
(out / "fulham-instruction.json").write_text(json.dumps(instruction, indent=2), encoding="utf-8")
print("FULHAM submit", iid, flush=True)
try:
    ack = submit(instruction)
    (out / "fulham-ack.json").write_text(json.dumps(ack, indent=2), encoding="utf-8")
    res = result(iid, seconds=160)
except Exception as e:
    res = {"status": "FAIL", "stage": "CLIENT_ERROR", "detail": f"{type(e).__name__}: {e}"}
(out / "fulham-result.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
pull_evidence(iid, "fulham")
ok = (res.get("status") == "PASS") or (res.get("stage") in ("PASS", "OPEN_SEARCH_QUERY", "OPEN_SEARCH"))
results["text_entry"] = {"id": iid, "ok": bool(ok), "status": res.get("status"), "stage": res.get("stage"), "detail": res.get("detail") or res.get("verification_detail")}
print("FULHAM", "PASS" if ok else "FAIL", res.get("stage"), res.get("detail"), flush=True)

try:
    hend = health()
except Exception as e:
    hend = {"error": str(e)}
(out / "health-proof-end.json").write_text(json.dumps(hend, indent=2), encoding="utf-8")
results["health_end"] = hend

open_pass = all(r["ok"] for r in results["open_search"]) and len(results["open_search"]) == 5
text_pass = bool(results["text_entry"] and results["text_entry"]["ok"])
results["SEARCH_OPEN"] = "PASS" if any(r["ok"] for r in results["open_search"]) else "FAIL"
results["5X_REPEAT"] = "PASS" if open_pass else "FAIL"
results["SEARCH_TEXT_ENTRY"] = "PASS" if text_pass else "FAIL"
results["RESET_STATE"] = "PASS" if open_pass else "FAIL"
results["READY_FOR_LIVE_REPROOF"] = "YES" if open_pass and text_pass else "NO"
(out / "proof-summary.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
print(json.dumps({k: results[k] for k in ["SEARCH_OPEN","5X_REPEAT","SEARCH_TEXT_ENTRY","RESET_STATE","READY_FOR_LIVE_REPROOF", "open_search", "text_entry"]}, indent=2), flush=True)
sys.exit(0 if open_pass and text_pass else 1)
