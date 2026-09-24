import json, time, sys
from pathlib import Path
sys.path.insert(0, str(Path(".").resolve()))
from tools.coordinator_client import Client

out = Path("evidence/search-ui-fix")
out.mkdir(parents=True, exist_ok=True)
c = Client(json.loads(Path(".local/coordinator.json").read_text(encoding="utf-8")))
health = c.health()
(out / "health-before.json").write_text(json.dumps(health, indent=2), encoding="utf-8")
print("HEALTH", health.get("app_version"), health.get("session"))
iid = f"search-repro-{int(time.time())}"
instruction = {
    "instruction_id": iid,
    "action": "ADAPTER_WORKFLOW",
    "adapter": "live_bet365",
    "scenario": "live",
    "query": "Fulham",
    "market": "MONEYLINE",
    "side": "HOME",
    "sport": "football",
    "minimum_price": "1.01",
    "stake": "1.00",
    "timeout_ms": 90000,
    "execution_mode": "ready",
}
(out / "repro-instruction.json").write_text(json.dumps(instruction, indent=2), encoding="utf-8")
ack = c.submit(instruction)
(out / "repro-ack.json").write_text(json.dumps(ack, indent=2), encoding="utf-8")
print("ACK", ack)
result = c.result(iid, seconds=120)
(out / "repro-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print("RESULT", result.get("status"), result.get("stage"), result.get("detail"))
code, evidence = c.request("GET", "/instructions/" + iid + "/evidence")
(out / "repro-evidence.json").write_text(json.dumps(evidence if not isinstance(evidence, (bytes, bytearray)) else evidence.decode("utf-8", "replace"), indent=2, default=str), encoding="utf-8")
print("EVIDENCE_CODE", code)
if code == 200 and isinstance(evidence, dict):
    files = list(evidence.get("screenshots") or [])
    for f in list(files):
        files.append(f.replace(".png", ".txt"))
    for f in files:
        sc, data = c.request("GET", "/instructions/" + iid + "/artifacts/" + f, raw=True)
        if sc == 200:
            (out / ("repro_" + f)).write_bytes(data)
            print("saved", f, len(data))
print("DONE", iid)
