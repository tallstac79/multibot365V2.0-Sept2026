"""Live COMPLETE_EXECUTION_READY acceptance ? prepare Place Bet gesture, do NOT dispatch."""
import argparse, json, time
from pathlib import Path
from coordinator_client import Client

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", default=".local/coordinator.json")
    p.add_argument("--output", default="evidence/live-bet365-complete-execution-ready")
    p.add_argument("--query", default="Arsenal")
    p.add_argument("--sport", default="football")
    p.add_argument("--market", default="MONEYLINE")
    p.add_argument("--side", default="HOME")
    p.add_argument("--minimum-price", default="1.01")
    p.add_argument("--stake", default="1.00")
    p.add_argument("--timeout-ms", type=int, default=120000)
    args = p.parse_args()
    c = Client(json.loads(Path(args.config).read_text(encoding="utf-8")))
    out = Path(args.output); out.mkdir(parents=True, exist_ok=True)
    health = c.health(); assert health.get("healthy"), health
    (out/"health-before.json").write_text(json.dumps(health, indent=2), encoding="utf-8")
    instruction = {
        "instruction_id": f"live-cer-{int(time.time())}",
        "action": "ADAPTER_WORKFLOW", "adapter": "live_bet365", "scenario": "live",
        "query": args.query, "market": args.market, "side": args.side, "sport": args.sport,
        "minimum_price": args.minimum_price, "stake": args.stake, "timeout_ms": args.timeout_ms,
        "execution_mode": "prepare", "confirmation_status": "APPROVED",
    }
    (out/"instruction.json").write_text(json.dumps(instruction, indent=2), encoding="utf-8")
    ack = c.submit(instruction); (out/"ack.json").write_text(json.dumps(ack, indent=2), encoding="utf-8")
    result = c.result(instruction["instruction_id"], seconds=max(90, args.timeout_ms//1000+30))
    (out/"result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    code, evidence = c.request("GET", "/instructions/"+instruction["instruction_id"]+"/evidence")
    (out/"evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if code == 200:
        for f in list(evidence.get("screenshots") or []):
            for name in (f, f.replace(".png", ".txt")):
                sc, data = c.request("GET", "/instructions/"+instruction["instruction_id"]+"/artifacts/"+name, raw=True)
                if sc == 200: (out/name).write_bytes(data)
    cer = result.get("complete_execution_ready") or (evidence.get("complete_execution_ready") if code==200 else None)
    dispatched = bool((evidence or {}).get("gesture_dispatched")) if code==200 else False
    wager = bool((evidence or {}).get("wager_submitted")) if code==200 else False
    ok = (result.get("stage")=="PASS" and result.get("detail")=="COMPLETE_EXECUTION_READY"
          and isinstance(cer, dict) and cer.get("state")=="COMPLETE_EXECUTION_READY"
          and cer.get("gesture_dispatched") is False and not dispatched and not wager
          and cer.get("final_control_bounds") and cer.get("prepared_gesture"))
    summary = {"status":"PASS" if ok else "FAIL","app_version":health.get("app_version"),"version_code":health.get("version_code"),
               "timestamp":time.strftime("%Y-%m-%dT%H:%M:%S%z"),"instruction":instruction,"result":result,
               "complete_execution_ready":cer,"gesture_dispatched":dispatched,"wager_submitted":wager,
               "detail":result.get("detail")}
    (out/"summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(summary["status"], result.get("detail"), "dispatched", dispatched, "wager", wager, flush=True)
    if not ok: raise SystemExit(1)
    print("COMPLETE_EXECUTION_READY ACCEPTANCE PASS", flush=True)

if __name__ == "__main__":
    main()
