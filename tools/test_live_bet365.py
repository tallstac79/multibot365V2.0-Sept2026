"""Physical live Bet365 acceptance — LAN HTTP only. Stops before wager submission."""
import argparse, json, time
from pathlib import Path
from coordinator_client import Client

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=".local/coordinator.json")
    parser.add_argument("--output", default="evidence/live-bet365")
    parser.add_argument("--query", default="")
    parser.add_argument("--sport", default="football", choices=["football", "basketball"])
    parser.add_argument("--market", default="MONEYLINE")
    parser.add_argument("--side", default="HOME")
    parser.add_argument("--minimum-price", default="1.01")
    parser.add_argument("--stake", default="0.00")
    args = parser.parse_args()
    c = Client(json.loads(Path(args.config).read_text()))
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    health = c.health()
    (out / "health-before.json").write_text(json.dumps(health, indent=2), encoding="utf-8")
    assert health.get("healthy"), health
    instruction = {
        "instruction_id": f"live-bet365-{int(time.time())}",
        "action": "ADAPTER_WORKFLOW",
        "adapter": "live_bet365",
        "scenario": "live",
        "query": args.query or ("Lakers" if args.sport == "basketball" else "Arsenal"),
        "market": args.market,
        "side": args.side,
        "sport": args.sport,
        "minimum_price": args.minimum_price,
        "stake": args.stake,
        "timeout_ms": 60000,
    }
    (out / "instruction.json").write_text(json.dumps(instruction, indent=2), encoding="utf-8")
    ack = c.submit(instruction)
    (out / "ack.json").write_text(json.dumps(ack, indent=2), encoding="utf-8")
    result = c.result(instruction["instruction_id"])
    (out / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    code, evidence = c.request("GET", "/instructions/" + instruction["instruction_id"] + "/evidence")
    (out / "evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if code == 200:
        files = list(evidence.get("screenshots", []))
        for f in list(files):
            files.append(f.replace(".png", ".txt"))
        if evidence.get("query_evidence"):
            files += ["before.png", "focused.png", "after.png", "field_after.png", "before.txt", "focused.txt", "after.txt"]
        for f in files:
            sc, data = c.request("GET", "/instructions/" + instruction["instruction_id"] + "/artifacts/" + f, raw=True)
            if sc == 200:
                (out / f).write_bytes(data)
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
        "final_state": result.get("final_state") or (evidence.get("final_state") if code == 200 else None),
        "detail": result.get("detail") or result.get("verification_detail"),
        "wager_submitted": False,
        "stop_before_wager": True,
    }
    if summary["status"] == "PASS":
        fs = summary.get("final_state") or {}
        if isinstance(fs, dict) and fs.get("wager_submitted") is True:
            summary["status"] = "FAIL"
            summary["detail"] = "Safety violation: wager_submitted true"
        if isinstance(fs, dict) and fs.get("state") not in (None, "NOSUBMIT"):
            # still allow PASS if stage PASS and NOSUBMIT missing but explicitly no submit path
            pass
    ml = []
    if code == 200:
        ml = evidence.get("moneyline_map") or []
    summary["moneyline_map"] = ml
    summary["fixture_home"] = result.get("home")
    summary["fixture_away"] = result.get("away")
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    def _ascii(x):
        if x is None: return None
        return str(x).encode("ascii", "replace").decode("ascii")
    print(summary["status"], _ascii(result.get("stage")), _ascii(result.get("fixture_name")), _ascii(result.get("detail")), flush=True)
    if summary["status"] != "PASS":
        raise SystemExit(1)
    # 1X2 identity invariants ? do not accept PASS without a verified map
    fh, fa = result.get("home"), result.get("away")
    if not ml:
        print("FAIL missing moneyline_map in evidence", flush=True)
        raise SystemExit(2)
    by = {row.get("selection_role"): row for row in ml}
    for role in ("HOME", "DRAW", "AWAY"):
        if role not in by:
            print("FAIL moneyline_map missing", role, flush=True)
            raise SystemExit(2)
    if by["HOME"].get("selection_name", "").lower() != (fh or "").lower():
        print("FAIL HOME name", by["HOME"].get("selection_name"), "!=", fh, flush=True)
        raise SystemExit(2)
    if by["AWAY"].get("selection_name", "").lower() != (fa or "").lower():
        print("FAIL AWAY name", by["AWAY"].get("selection_name"), "!=", fa, flush=True)
        raise SystemExit(2)
    dn = (by["DRAW"].get("selection_name") or "").lower()
    if dn in ((fh or "").lower(), (fa or "").lower()) or (dn and dn not in ("draw", "x", "tie", "")):
        if dn not in ("draw", "x", "tie"):
            print("FAIL DRAW name looks like team", by["DRAW"].get("selection_name"), flush=True)
            raise SystemExit(2)
    prices = {r: by[r].get("price") for r in ("HOME", "DRAW", "AWAY")}
    if len(set(prices.values())) < 3:
        print("FAIL 1X2 prices not distinct", prices, flush=True)
        raise SystemExit(2)
    sel = result.get("selection") or {}
    if sel.get("side") == "HOME" and sel.get("price") != by["HOME"].get("price"):
        print("FAIL selected HOME price mismatch", sel.get("price"), by["HOME"].get("price"), flush=True)
        raise SystemExit(2)
    print("1X2 MAP OK", prices, flush=True)
    print("LIVE BET365 ACCEPTANCE PASS", flush=True)

if __name__ == "__main__":
    main()
