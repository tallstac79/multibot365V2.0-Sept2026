"""One safe Search fallback hold after reboot; never dispatch a final action."""
import json
import time
from tools.strategy_phone_audit import ROOT, safety
from tools.coordinator_client import Client

def main():
    safety()
    out=ROOT/'evidence/strategy-audit/search'/('run-'+str(int(time.time())));out.mkdir(parents=True,exist_ok=True)
    c=Client(json.loads((ROOT/'.local/coordinator.json').read_text(encoding='utf-8-sig')))
    items=[]
    for tag,body in [
        ('session',dict(action='SESSION_CHECK',sport='basketball')),
        ('search-hold',dict(action='ADAPTER_WORKFLOW',sport='basketball',query='Kirchheim||SBB Baskets Wolmirstedt',
             market='MONEYLINE',side='HOME',line='',minimum_price='1.01',stake='0.10',execution_mode='hold',kickoff_utc='2026-09-26T16:00')),
        ('reset',dict(action='RESET_BETSLIP'))]:
        safety();start=time.monotonic()
        body.update(instruction_id='forensic-search-'+tag+'-'+str(int(time.time())),adapter='live_bet365',scenario='live',timeout_ms=120000)
        assert body.get('execution_mode') != 'dispatch'
        errors=[];deadline=time.monotonic()+150
        while True:
            try:ack=c.submit(body);break
            except ValueError as exc:
                if 'BUSY' not in str(exc) or time.monotonic()>deadline:raise
                time.sleep(1)
        while time.monotonic()<deadline:
            try:r=c.result(body['instruction_id'],seconds=10);break
            except (TimeoutError,ValueError) as exc:errors.append(str(exc));time.sleep(1)
        else:r=dict(status='UNRESOLVED',detail='Result poll expired; no replacement ID')
        item=dict(tag=tag,payload=body,ack=ack,result=r,wall_seconds=round(time.monotonic()-start,3),poll_errors=errors)
        items.append(item);(out/(tag+'.json')).write_text(json.dumps(item,indent=2))
        print(tag,r.get('status'),r.get('stage'),r.get('detail'),item['wall_seconds'],flush=True)
        if r.get('status')=='UNRESOLVED':break
    safety();(out/'summary.json').write_text(json.dumps(dict(checks=items,health=c.health(),final_action_dispatched=False),indent=2))

if __name__=='__main__':main()
