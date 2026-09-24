"""Run non-betting live Bet365 session authentication check through Coordinator."""
import argparse, json, time
from pathlib import Path
from coordinator_client import Client

p=argparse.ArgumentParser(description=__doc__)
p.add_argument("--config", default=".local/coordinator.json")
p.add_argument("--evidence-dir", default="evidence/session-login")
p.add_argument("--id", default=None)
a=p.parse_args()
config=json.loads(Path(a.config).read_text(encoding="utf-8"))
c=Client(config)
iid=a.id or "session-check-"+str(int(time.time()))
body={"instruction_id":iid,"action":"SESSION_CHECK","adapter":"live_bet365","scenario":"live","sport":"football","timeout_ms":60000}
out=Path(a.evidence_dir); out.mkdir(parents=True,exist_ok=True)
(out/(iid+"-instruction.json")).write_text(json.dumps(body,indent=2),encoding="utf-8")
ack=c.submit(body,seconds=20)
result=c.result(iid,seconds=75)
health=c.health()
(out/(iid+"-ack.json")).write_text(json.dumps(ack,indent=2),encoding="utf-8")
(out/(iid+"-result.json")).write_text(json.dumps(result,indent=2),encoding="utf-8")
(out/(iid+"-health.json")).write_text(json.dumps(health,indent=2),encoding="utf-8")
print(json.dumps({"instruction_id":iid,"result":result,"session":health.get("session")},indent=2))
