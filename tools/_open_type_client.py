import json, time, urllib.request, ssl
from pathlib import Path

cfg = json.loads(Path(".local/coordinator.json").read_text(encoding="utf-8"))
base = cfg["url"].rstrip("/")
token = cfg["token"]

def req(method, path, body=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    r = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw}
        return e.code, payload

# health
print("HEALTH", req("GET", "/health")[0])
code, health = req("GET", "/health")
print("endpoint", health.get("endpoint"), "session", health.get("session"))

ts = int(time.time())
iid = f"ar2-{ts}"
body = {
    "instruction_id": iid,
    "action": "OPEN_AND_TYPE",
    "target_text": "Search",
    "input_text": "Fulham",
    "timeout_ms": 60000,
}
print("POST", body)
code, ack = req("POST", "/instructions", body)
print("ACK", code, ack)
Path("evidence/app-restart-reprove/ack-python.json").write_text(json.dumps(ack, indent=2), encoding="utf-8")

result = None
for i in range(30):
    code, res = req("GET", f"/instructions/{iid}")
    if code == 200:
        result = res
        print("RESULT", res.get("status"), res.get("stage"), res.get("detail"))
        Path("evidence/app-restart-reprove/result-python.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
        break
    time.sleep(3)
code, dup = req("POST", "/instructions", body)
print("DUP", code, dup)
Path("evidence/app-restart-reprove/duplicate-python.json").write_text(json.dumps({"http": code, "body": dup}, indent=2), encoding="utf-8")

summary = {
    "APP_RESTART_REPROVE": "PASS" if result and result.get("status") == "PASS" else f"FAIL/{(result or {}).get('stage')}",
    "instruction_id": iid,
    "result": result,
    "wifi_on": 0,
    "endpoint": health.get("endpoint"),
}
Path("evidence/app-restart-reprove/summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(summary["APP_RESTART_REPROVE"])
