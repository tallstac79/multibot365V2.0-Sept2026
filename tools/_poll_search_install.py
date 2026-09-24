import json, time, sys
from pathlib import Path
sys.path.insert(0, ".")
from tools.coordinator_client import Client

c = Client(json.loads(Path(".local/coordinator.json").read_text(encoding="utf-8")))
deadline = time.time() + 25 * 60
target_ver, target_code = "0.6.23-search", 35
while time.time() < deadline:
    try:
        h = c.health()
    except Exception as e:
        print("HEALTH_ERR", e, flush=True)
        time.sleep(5)
        continue
    ver = h.get("app_version") or h.get("version_name") or "?"
    code = h.get("version_code") or h.get("versionCode") or "?"
    sess = (h.get("session") or {}).get("state")
    print(f"POLL ver={ver} code={code} session={sess} state={h.get('state')}", flush=True)
    if ver == target_ver and int(code) == target_code:
        Path("evidence/search-ui-fix").mkdir(parents=True, exist_ok=True)
        Path("evidence/search-ui-fix/health-after-install.json").write_text(json.dumps(h, indent=2), encoding="utf-8")
        print("INSTALLED", flush=True)
        sys.exit(0)
    time.sleep(8)
print("TIMEOUT_WAITING_INSTALL", flush=True)
sys.exit(2)
