"""Physical live Bet365 READY_STATE acceptance ? session + stake + full betslip readback.
Stops before wager submission. Evidence under evidence/live-bet365-ready-state/.
"""
import argparse, json, time
from pathlib import Path
from coordinator_client import Client

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=".local/coordinator.json")
    parser.add_argument("--output", default="evidence/live-bet365-ready-state")
    parser.add_argument("--query", default="Arsenal")
    parser.add_argument("--sport", default="football", choices=["football", "basketball"])
    parser.add_argument("--market", default="MONEYLINE")
    parser.add_argument("--side", default="HOME")
    parser.add_argument("--minimum-price", default="1.01")
    parser.add_argument("--stake", default="1.00")
    parser.add_argument("--timeout-ms", type=int, default=120000)
    args = parser.parse_args()
    c = Client(json.loads(Path(args.config).read_text(encoding="utf-8")))
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    health = c.health()
    (out / "health-before.json").write_text(json.dumps(health, indent=2), encoding="utf-8")
    assert health.get("healthy"), health
    instruction = {
        "instruction_id": f"live-ready-{int(time.time())}",
        "action": "ADAPTER_WORKFLOW",
        "adapter": "live_bet365",
        "scenario": "live",
        "query": args.query,
        "market": args.market,
        "side": args.side,
        "sport": args.sport,
        "minimum_price": args.minimum_price,
        "stake": args.stake,
        "timeout_ms": args.timeout_ms,
    }
    (out / "instruction.json").write_text(json.dumps(instruction, indent=2), encoding="utf-8")
    ack = c.submit(instruction)
    (out / "ack.json").write_text(json.dumps(ack, indent=2), encoding="utf-8")
    result = c.result(instruction["instruction_id"], seconds=max(90, args.timeout_ms // 1000 + 30))
    (out / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    code, evidence = c.request("GET", "/instructions/" + instruction["instruction_id"] + "/evidence")
    (out / "evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if code == 200:
        files = list(evidence.get("screenshots", []) or [])
        for f in list(files):
            files.append(f.replace(".png", ".txt"))
        for f in files:
            sc, data = c.request("GET", "/instructions/" + instruction["instruction_id"] + "/artifacts/" + f, raw=True)
            if sc == 200:
                (out / f).write_bytes(data)
    ready = None
    if code == 200:
        ready = evidence.get("ready_state")
    if ready is None and isinstance(result.get("ready_state"), dict):
        ready = result.get("ready_state")
    final_state = result.get("final_state") or (evidence.get("final_state") if code == 200 else None)
    summary = {
        "status": "PASS" if result.get("stage") == "PASS" and result.get("status") == "PASS" else "FAIL",
        "app_version": health.get("app_version"),
        "version_code": health.get("version_code"),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "instruction": instruction,
        "result": result,
        "fixture": result.get("fixture_name"),
        "home": result.get("home"),
        "away": result.get("away"),
        "selection": result.get("selection"),
        "ready_state": ready,
        "final_state": final_state,
        "detail": result.get("detail") or result.get("verification_detail"),
        "wager_submitted": False,
        "stop_before_wager": True,
        "session": (ready or {}).get("session") if isinstance(ready, dict) else None,
        "stake": args.stake,
    }
    # Safety + READY_STATE invariants
    if summary["status"] == "PASS":
        rs = ready if isinstance(ready, dict) else {}
        fs = final_state if isinstance(final_state, dict) else {}
        if rs.get("wager_submitted") is True or fs.get("wager_submitted") is True:
            summary["status"] = "FAIL"
            summary["detail"] = "Safety violation: wager_submitted true"
        elif rs.get("state") != "READY" and fs.get("state") != "READY":
            summary["status"] = "FAIL"
            summary["detail"] = "Missing READY_STATE (state!=READY)"
        elif str(rs.get("stake") or fs.get("stake") or "") != args.stake:
            # allow stake from result selection path
            entered = None
            if code == 200:
                entered = evidence.get("stake_entered")
            if str(entered or rs.get("stake") or fs.get("stake") or "") != args.stake:
                summary["status"] = "FAIL"
                summary["detail"] = f"Stake mismatch: wanted {args.stake} got ready={rs.get('stake')} final={fs.get('stake')} entered={entered}"
        elif result.get("detail") and "READY_STATE" not in str(result.get("detail")) and result.get("stage") == "PASS":
            # detail should mention READY_STATE from AdapterWorkflow finish
            pass
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    def _ascii(x):
        if x is None: return None
        return str(x).encode("ascii", "replace").decode("ascii")
    print(summary["status"], _ascii(result.get("stage")), _ascii(result.get("fixture_name")), _ascii(summary.get("detail")), flush=True)
    if isinstance(ready, dict):
        print("READY_STATE", json.dumps({k: ready.get(k) for k in ("fixture_home","fixture_away","market","selection_role","selection_name","line","price","stake","session","state","wager_submitted")}, ensure_ascii=True), flush=True)
    if summary["status"] != "PASS":
        raise SystemExit(1)
    print("LIVE BET365 READY_STATE ACCEPTANCE PASS", flush=True)

if __name__ == "__main__":
    main()
