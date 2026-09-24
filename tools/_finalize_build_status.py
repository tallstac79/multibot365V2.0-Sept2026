from pathlib import Path
import subprocess, json, re

hdr = """---
# MultiBot365 stage timeouts + session keepalive 0.6.28-stage vc40 - READY_FOR_LIVE_REPROOF YES

Verified 2026-09-23 ~23:50 Europe/London. App **0.6.28-stage (40)** on Samsung R5CT61TE14Z / galaxy-a13-5g. Coordinator Tailscale `http://100.114.45.68:8767`. Session **AUTHENTICATED**. `dispatch_enabled=false` throughout (never flipped true).

- **HOTFIX_COMMIT:** `bdcd4bb` fix(pipeline): sqlite3.Row away access for home||away query.
- **ROOT_CAUSE:** Prior Gunma tip on-ee808246 spent ~120s DEVICE_ACTIVE with `device_stage=null`; CoordinatorAgent single hard deadline (`timeout_ms=120000`) killed as 'Coordinator hard deadline expired' before Search; mid-job `refreshSession` forced session UNKNOWN (SESSION_REQUIRED race). No progress heartbeats.
- **Fix:** stage timings + progress heartbeats on /health and 202 ack; stage inactivity 45s fail-closed; absolute backstop 300s (schema max 600s); pre-job session refresh + job-active AUTHENTICATED keepalive (no UNKNOWN flip); `session_max_age` remains **120s**.
- **Proof (`evidence/stage-timeout-gunma-proof/`):**
  - **GUNMA:** Search start **20363ms**; sports_context `open_home_url`; progress ladder visible; terminal WRONG_EVENT fail-closed (fixture not on board); session AUTHENTICATED; no unexplained 120s stall.
  - **BASKETBALL x3:** Search ~23-33s each; sports_context set; progress heartbeats; fail-closed (board/target).
  - **FULHAM:** sports_context `already_sports_or_home`; Search **24418ms**; reached MARKET_NAV; fail-closed TARGET_NOT_FOUND on SPREAD line.
  - **RESET_AFTER_TIMEOUT:** `__STALL__` harness -> TIMEOUT Stage inactivity 46218ms @ SPORTS_HOME; reset + SESSION_CHECK AUTHENTICATED.
- **READY_FOR_LIVE_REPROOF=YES**. **DISPATCH_NOW=false**.
- **Safety:** no wager; Place Bet not engaged; dispatch left **false**.

---

"""
p = Path('BUILD_STATUS.md')
cur = p.read_text(encoding='utf-8')
cur = re.sub(r'(?s)^---\r?\n# MultiBot365 stage timeouts.*?---\r?\n\r?\n', '', cur)
p.write_text(hdr + cur, encoding='utf-8')
print('BUILD_STATUS updated')
