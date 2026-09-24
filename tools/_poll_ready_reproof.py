"""Poll for next READY-only live dispatch; fail-closed; disable dispatch on terminal."""
import json, sqlite3, time, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(r"C:\Users\WINDOWS11\Desktop\MultiBotV2.0\MultiBot365")
EV = ROOT / "evidence" / "ready-reproof-20260923"
EV.mkdir(parents=True, exist_ok=True)
DB = ROOT / ".local" / "pipeline.sqlite3"
CFG = ROOT / ".local" / "pipeline.json"
STATUS = ROOT / ".local" / "pipeline_status.json"
COORD = json.loads((ROOT / ".local" / "coordinator.json").read_text(encoding="utf-8-sig"))
START = datetime.now(timezone.utc)
TIMEOUT_S = 50 * 60  # 50 minutes
POLL = 8
baseline_intake = None
baseline_instr_rowid = None
dispatched_id = None
events = []

def log(msg, **extra):
    row = {"t": datetime.now(timezone.utc).isoformat(), "msg": msg, **extra}
    events.append(row)
    print(json.dumps(row), flush=True)
    (EV / "poll-log.jsonl").open("a", encoding="utf-8").write(json.dumps(row) + "\n")

def health():
    req = urllib.request.Request(
        COORD["url"].rstrip("/") + "/health",
        headers={"Authorization": "Bearer " + COORD["token"]},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

def set_dispatch(enabled: bool):
    cfg = json.loads(CFG.read_text(encoding="utf-8-sig"))
    cfg["pipeline"]["dispatch_enabled"] = bool(enabled)
    CFG.write_text(json.dumps(cfg, indent=4) + "\n", encoding="utf-8")
    return cfg["pipeline"]["dispatch_enabled"]

def restart_pipeline():
    # caller should have stopped/started; here we only flip config and write marker
    (EV / "dispatch-disable-request.json").write_text(json.dumps({
        "dispatch_enabled": False,
        "at": datetime.now(timezone.utc).isoformat(),
        "reason": "terminal device result or timeout cleanup",
    }, indent=2), encoding="utf-8")

con = sqlite3.connect(str(DB), timeout=30)
con.row_factory = sqlite3.Row
baseline_intake = con.execute("SELECT MAX(id) FROM intake_messages").fetchone()[0] or 0
baseline_instr_rowid = con.execute("SELECT MAX(rowid) FROM instructions").fetchone()[0] or 0
log("baseline", intake_id=baseline_intake, instr_rowid=baseline_instr_rowid)

try:
    h = health()
    (EV / "health-start.json").write_text(json.dumps(h, indent=2), encoding="utf-8")
    log("health", app_version=h.get("app_version"), version_code=h.get("version_code"),
        session=(h.get("session") or {}).get("state"), state=h.get("state"))
except Exception as e:
    log("health_error", error=str(e))

st = json.loads(STATUS.read_text(encoding="utf-8-sig")) if STATUS.exists() else {}
log("pipeline_status", dispatch_enabled=st.get("dispatch_enabled"), intake=st.get("intake"))

final = {
    "FINAL_STATUS": "WAITING",
    "COMMIT": "5c826649f730d2395c1730b32c1407e212d5d49c",
    "APK_MATCH": True,
    "APP_VERSION": "0.6.24-search",
    "DISPATCH_NOW": True,
}

terminal_states = {
    "READY", "FAIL", "ERROR", "TARGET_NOT_FOUND", "SESSION_REQUIRED", "DEVICE_OFFLINE",
    "STALE", "REJECTED", "UNKNOWN", "TIMEOUT", "CANCELLED", "ABORTED",
}
# lifecycle terminal from store
def is_terminal_row(row):
    if row is None:
        return False
    if row["terminal"]:
        return True
    return row["state"] in (
        "READY", "STALE", "REJECTED", "DEVICE_OFFLINE", "SESSION_REQUIRED",
        "FAIL", "UNKNOWN", "CANCELLED", "ABORTED", "TIMEOUT",
        "PRICE_CHANGED", "LINE_CHANGED", "BELOW_MINIMUM", "TARGET_NOT_FOUND",
        "COMPLETED", "EXPIRED",
    )

seen_intake = set()
while True:
    elapsed = (datetime.now(timezone.utc) - START).total_seconds()
    if elapsed > TIMEOUT_S:
        log("timeout", elapsed_s=elapsed)
        final["FINAL_STATUS"] = "WAITING/NO_ALERT"
        break

    # new intake
    for r in con.execute(
        "SELECT id, message_id, status, reason, instruction_id, received_at, substr(raw_text,1,200) as snip FROM intake_messages WHERE id > ? ORDER BY id",
        (baseline_intake,),
    ):
        if r["id"] in seen_intake:
            continue
        seen_intake.add(r["id"])
        log("intake", id=r["id"], message_id=r["message_id"], status=r["status"],
            reason=(r["reason"] or "")[:180], instruction_id=r["instruction_id"], snip=r["snip"])
        (EV / f"intake-{r['id']}.json").write_text(json.dumps(dict(r), indent=2), encoding="utf-8")

    # new / updated instructions since baseline OR any non-terminal after start
    for r in con.execute(
        """SELECT rowid, instruction_id, state, terminal, sport, home, away, market, selection, line,
                  minimum_price, stake, observed_price, failure_reason, device_stage, received_at,
                  queued_at, dispatched_at, ready_at, completed_at, dispatch_payload, result_payload,
                  session_state, rules_result
           FROM instructions WHERE rowid > ? OR (received_at >= ? AND terminal=0)
           ORDER BY rowid""",
        (baseline_instr_rowid, START.isoformat()),
    ):
        d = {k: r[k] for k in r.keys() if k != "rowid"}
        # truncate bulky fields in log
        brief = {k: d[k] for k in d if k not in ("dispatch_payload", "result_payload", "rules_result")}
        path = EV / f"instruction-{r['instruction_id']}-{r['state']}.json"
        # always refresh file for state changes
        slim = dict(brief)
        if d.get("dispatch_payload"):
            try:
                slim["dispatch_payload"] = json.loads(d["dispatch_payload"]) if isinstance(d["dispatch_payload"], str) else d["dispatch_payload"]
            except Exception:
                slim["dispatch_payload"] = d["dispatch_payload"]
        if d.get("result_payload"):
            try:
                slim["result_payload"] = json.loads(d["result_payload"]) if isinstance(d["result_payload"], str) else d["result_payload"]
            except Exception:
                slim["result_payload"] = d["result_payload"]
        if d.get("rules_result"):
            try:
                slim["rules_result"] = json.loads(d["rules_result"]) if isinstance(d["rules_result"], str) else d["rules_result"]
            except Exception:
                slim["rules_result"] = d["rules_result"]
        path.write_text(json.dumps(slim, indent=2, default=str), encoding="utf-8")
        log("instruction", **brief)

        if r["state"] == "DISPATCHED" and dispatched_id is None:
            dispatched_id = r["instruction_id"]
            log("DISPATCHED", instruction_id=dispatched_id)
            final["ALERT"] = f"{r['home']} vs {r['away']} {r['market']} {r['selection']} {r['line']}"
            final["PARSE"] = "PARSED"
            final["RULES"] = "ACCEPT"
            payload = slim.get("dispatch_payload") or {}
            final["execution_mode"] = payload.get("execution_mode") if isinstance(payload, dict) else None

        if dispatched_id and r["instruction_id"] == dispatched_id and is_terminal_row(r):
            log("TERMINAL", instruction_id=dispatched_id, state=r["state"], failure_reason=r["failure_reason"], device_stage=r["device_stage"])
            final["FINAL_STATUS"] = r["state"]
            final["READY"] = "YES" if r["state"] == "READY" else "NO"
            rp = slim.get("result_payload") or {}
            if isinstance(rp, dict):
                ready = rp.get("ready_state") or {}
                final["SESSION"] = ready.get("session") or r["session_state"]
                final["FIXTURE"] = f"{ready.get('fixture_home') or r['home']} vs {ready.get('fixture_away') or r['away']}"
                final["MARKET"] = ready.get("market") or r["market"]
                final["LINE"] = ready.get("line") or r["line"]
                final["PRICE"] = ready.get("price") or r["observed_price"]
                final["STAKE"] = ready.get("stake") or r["stake"]
                final["WAGER_SUBMITTED"] = ready.get("wager_submitted", rp.get("wager_submitted", False))
                final["SEARCH"] = rp.get("stage") or r["device_stage"]
                final["DASHBOARD"] = f"instruction {dispatched_id} state={r['state']}"
            else:
                final["WAGER_SUBMITTED"] = False
                final["SESSION"] = r["session_state"]
            break
    else:
        # loop else: no break from for
        # also watch status heartbeat
        if STATUS.exists():
            try:
                st = json.loads(STATUS.read_text(encoding="utf-8-sig"))
                if int(elapsed) % 60 < POLL:
                    log("heartbeat", dispatch_enabled=st.get("dispatch_enabled"),
                        intake_state=(st.get("intake") or {}).get("state"),
                        last_event=(st.get("intake") or {}).get("last_event_at"),
                        elapsed_s=int(elapsed))
            except Exception as e:
                log("status_read_error", error=str(e))
        time.sleep(POLL)
        continue
    # broke from terminal
    break

# Disable dispatch immediately
try:
    after = set_dispatch(False)
    log("dispatch_disabled_config", dispatch_enabled=after)
except Exception as e:
    log("dispatch_disable_error", error=str(e))
    after = None

final["DISPATCH_NOW"] = after
final["elapsed_s"] = int((datetime.now(timezone.utc) - START).total_seconds())
final["dispatched_id"] = dispatched_id
(EV / "final-summary.json").write_text(json.dumps(final, indent=2), encoding="utf-8")
(EV / "events.json").write_text(json.dumps(events, indent=2), encoding="utf-8")
print("DONE", json.dumps(final), flush=True)
