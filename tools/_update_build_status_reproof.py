from pathlib import Path
p = Path("BUILD_STATUS.md")
text = p.read_text(encoding="utf-8")
marker = "# MultiBot365 live ready-only reproof on 0.6.24-search - FAIL (FOCUS_FAILED); dispatch re-disabled"
if marker in text:
    print("already present")
else:
    section = """# MultiBot365 live ready-only reproof on 0.6.24-search - FAIL (FOCUS_FAILED); dispatch re-disabled

Verified 2026-09-23 ~18:22 Europe/London. App **0.6.24-search (36)** (commit `5c82664`). Coordinator Tailscale `http://100.114.45.68:8767`. Session kept **AUTHENTICATED** via session keepalive (120s max-age). David override: Place Bet not force-disabled; pipeline still sends `execution_mode=ready` (no confirmation_status).

- **Dispatch:** `.local/pipeline.json` `pipeline.dispatch_enabled=true` then false after watch. Keys set: only `pipeline.dispatch_enabled`. No Place Bet lock keys.
- **Near-misses before dispatch:** several CLEAR_VALUE PARSED alerts went `SESSION_REQUIRED` (stale/UNKNOWN session before keepalive) or `STALE` (`event_not_started` ? rules require pre-match tip-off).
- **Live instruction (ONE):** `on-85a1398083a603180851685a` msg path OddsNotifier ? PARSED ? rules ACCEPT (CLEAR_VALUE_SIGNAL) ? QUEUED ? **DISPATCHED** 17:12:54Z ? DEVICE_ACTIVE ? terminal **UNKNOWN**/FAIL `FOCUS_FAILED: No fresh input session for the visually tapped field` (completed 17:13:39Z).
- **Alert:** basketball SPREAD Atletico Boca Juniors vs NBA G League United HOME line **15.5** min 1.83 stake 1.00.
- **READY not reached.** `wager_submitted=false`. `execution_mode=ready`. Place Bet never engaged.
- **Post:** `dispatch_enabled=false` verified; intake LISTENING; session AUTHENTICATED.
- Evidence: `evidence/ready-reproof-20260923/` (instruction full/transitions/audit, final-summary, apk-match, session keepalive, poll logs).

---
"""
    # insert after search PASS section (before market interpretation) or at top
    anchor = "# MultiBot365 Search UI re-home 5/5 OPEN_SEARCH PASS"
    idx = text.find(anchor)
    if idx >= 0:
        # find end of that section's ---
        end = text.find("\n---\n", idx)
        if end >= 0:
            end = end + len("\n---\n")
            text = text[:end] + section + text[end:]
        else:
            text = section + text
    else:
        text = section + text
    p.write_text(text, encoding="utf-8")
    print("BUILD_STATUS updated")
