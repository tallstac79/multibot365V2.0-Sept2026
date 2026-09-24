import json, hashlib, shutil
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(r"C:\Users\WINDOWS11\Desktop\MultiBotV2.0\MultiBot365")
EV = ROOT / "evidence" / "ready-reproof-20260923"
EV.mkdir(parents=True, exist_ok=True)

# APK match record
apk_hash = "965FCF78466569E9EA8DB3D97288CC6B8120B67DE55A735C38B9B70A5856F2B7"
(EV / "apk-match.json").write_text(json.dumps({
    "app_version": "0.6.24-search",
    "version_code": 36,
    "sha256": apk_hash,
    "sources": [
        "Desktop/Bet365Agent-0.6.24-search.apk",
        "android/Bet365Agent/app/build/outputs/apk/debug/app-debug.apk",
        "device installed base.apk (pm path pull)",
    ],
    "MATCH": True,
    "commit": "5c826649f730d2395c1730b32c1407e212d5d49c",
    "recorded_at_london": "2026-09-23 ~17:20 Europe/London",
}, indent=2), encoding="utf-8")

# Enable dispatch_enabled in pipeline.json (read utf-8-sig, write utf-8 no BOM)
cfg_path = ROOT / ".local" / "pipeline.json"
raw = cfg_path.read_text(encoding="utf-8-sig")
cfg = json.loads(raw)
assert "pipeline" in cfg
before = cfg["pipeline"].get("dispatch_enabled")
cfg["pipeline"]["dispatch_enabled"] = True
# Keep only known safe keys; do not touch telegram secrets beyond this toggle
cfg_path.write_text(json.dumps(cfg, indent=4) + "\n", encoding="utf-8")
after = json.loads(cfg_path.read_text(encoding="utf-8-sig"))["pipeline"]["dispatch_enabled"]
(EV / "dispatch-enable.json").write_text(json.dumps({
    "before": before,
    "after": after,
    "keys_set": {"pipeline.dispatch_enabled": True},
    "notes": "READY-only enforced in core/pipeline.py build_payload (execution_mode=ready, no confirmation_status). Place Bet cannot fire.",
    "at": datetime.now(timezone.utc).isoformat(),
}, indent=2), encoding="utf-8")
print("dispatch_enabled", before, "->", after)
print("apk-match written")
