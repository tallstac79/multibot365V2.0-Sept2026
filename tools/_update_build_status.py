from pathlib import Path
p = Path("BUILD_STATUS.md")
old = p.read_text(encoding="utf-8")
marker = "# MultiBot365 Search UI re-home 5/5 OPEN_SEARCH PASS (0.6.24-search vc36)"
if marker in old:
    print("section already present; skip rewrite")
else:
    section = """# MultiBot365 Search UI re-home 5/5 OPEN_SEARCH PASS (0.6.24-search vc36) — READY_FOR_LIVE_REPROOF YES

Verified 2026-09-23 ~17:00 Europe/London. App **0.6.24-search (36)** on Samsung R5CT61TE14Z / galaxy-a13-5g. Coordinator Tailscale `http://100.114.45.68:8767` / MagicDNS `galaxy-a13-5g.taila8257e.ts.net:8767`. Session **AUTHENTICATED**.

- **Prior FAIL fixed:** live ready-only dispatch hit `TARGET_NOT_FOUND` ("Live Bet365 search UI not visible after Search tap") on 0.6.22-login (34). Root cause: home chrome / wrong tab after prior reset; Search control not reliably visible. Fix: Search re-home + session re-probe in Bet365LiveAdapter / SearchOpenWorkflow (and SessionCheck/SessionProbe workflows).
- **Proof (evidence/search-ui-fix/proof-summary.json):**
  - **5/5 OPEN_SEARCH PASS** consecutive: `open-search-1790178324-1` … `open-search-1790179344-5` (all status PASS, detail OPEN_SEARCH).
  - **Fulham OPEN_SEARCH_QUERY PASS:** `search-fulham-1790179552` — query 'Fulham' entered and results verified; reset afterward.
  - Flags: `SEARCH_OPEN=PASS`, `5X_REPEAT=PASS`, `SEARCH_TEXT_ENTRY=PASS`, `RESET_STATE=PASS`, **`READY_FOR_LIVE_REPROOF=YES`**.
- **APK match:** installed package versionName `0.6.24-search` versionCode `36`; `/health` same; sha256 of installed base.apk equals Desktop `Bet365Agent-0.6.24-search.apk` and `app/build/outputs/apk/debug/app-debug.apk` (`965FCF78466569E9EA8DB3D97288CC6B8120B67DE55A735C38B9B70A5856F2B7`).
- **gradle.kts:** versionCode 36 / versionName 0.6.24-search.
- **Safety unchanged:** ready-only path; `wager_submitted=false`; Place Bet / final action not engaged in these proofs.
- **Next:** enable READY-only `dispatch_enabled` for one live OddsNotifier PARSED→QUEUED→DISPATCHED cycle, then disable immediately after first terminal READY or FAIL.

---
"""
    p.write_text(section + old, encoding="utf-8")
    print("BUILD_STATUS.md updated; new length", p.stat().st_size)
