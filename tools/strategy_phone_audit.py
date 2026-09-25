"""Bounded audit proofs: session, held slip/prepare, negative identity/line, duplicate.

Never dispatches a final action. Requires the backend to remain fully disarmed.
Explicit CLI command needed; importing this module has no side effects.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time
from tools.coordinator_client import Client

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/strategy-audit/phone'

def safety():
    cfg=json.loads((ROOT/'.local/pipeline.json').read_text(encoding='utf-8-sig'))['pipeline']
    assert all(cfg.get(k) is False for k in ('dispatch_enabled','final_action_enabled','final_action_one_shot'))
    with sqlite3.connect((ROOT/'.local/pipeline.sqlite3').resolve().as_uri()+'?mode=ro',uri=True) as db:
        assert json.loads(db.execute("SELECT value FROM controls WHERE key='paused'").fetchone()[0]) is True

def main():
    global OUT
    OUT=OUT/('run-'+str(int(time.time())))
    safety();OUT.mkdir(parents=True,exist_ok=True)
    c=Client(json.loads((ROOT/'.local/coordinator.json').read_text(encoding='utf-8-sig')))
    prefix='forensic-'+str(int(time.time()));results=[]
    def run(tag,payload,expected):
        safety()
        assert payload.get('execution_mode') != 'dispatch' and payload.get('place_bet') not in ('true',True)
        assert payload['action'] in ('SESSION_CHECK','ADAPTER_WORKFLOW','PLACE_HELD','RESET_BETSLIP','MY_BETS')
        payload=dict(payload,instruction_id=prefix+'-'+tag,adapter='live_bet365',scenario='live',timeout_ms=120000)
        start=time.monotonic()
        try:
            until=time.monotonic()+180
            while True:
                try:
                    ack=c.submit(payload);break
                except ValueError as exc:
                    if 'BUSY' not in str(exc) or time.monotonic()>until:raise
                    time.sleep(1)
            r=c.result(payload['instruction_id'],seconds=145)
            ok=(r.get('status')=='PASS') if expected=='PASS' else r.get('stage')==expected and r.get('status')=='FAIL'
            item=dict(tag=tag,expected=expected,ok=ok,payload=payload,ack=ack,result=r,wall_seconds=round(time.monotonic()-start,3))
        except Exception as exc:
            item=dict(tag=tag,expected=expected,ok=False,payload=payload,error=str(exc),wall_seconds=round(time.monotonic()-start,3));r={}
        (OUT/(tag+'.json')).write_text(json.dumps(item,indent=2),encoding='utf-8');results.append(item)
        print(tag,item['ok'],r.get('status'),r.get('stage'),r.get('detail'),item['wall_seconds'],flush=True)
        return r,payload
    h=c.health();(OUT/'health-start.json').write_text(json.dumps(h,indent=2),encoding='utf-8')
    # Reconciliation may run even with betting paused; the submit loop waits its turn.
    run('session',dict(action='SESSION_CHECK',sport='basketball'),'PASS')
    # Exact bookmaker names read in the first audit attempt; no automatic alias promotion.
    base=dict(action='ADAPTER_WORKFLOW',sport='basketball',query='Kirchheim||SBB Baskets Wolmirstedt',
              market='MONEYLINE',side='HOME',line='',minimum_price='1.01',stake='0.10',execution_mode='hold',
              event_url='https://www.bet365.com/#/AC/B18/C21170155/D19/E26748183/F19/I0/',kickoff_utc='2026-09-26T16:00')
    r,payload=run('hold',base,'PASS')
    code,duplicate=c.request('POST','/instructions',payload)
    dup=dict(tag='duplicate',ok=code==409 and duplicate.get('stage')=='DUPLICATE',code=code,response=duplicate)
    results.append(dup);(OUT/'duplicate.json').write_text(json.dumps(dup,indent=2),encoding='utf-8')
    if r.get('status')=='PASS':
        sel=r['selection']
        held=dict(action='PLACE_HELD',sport='basketball',market=sel['market'],side=sel['side'],line=sel.get('line') or '',
                  selection_name=sel['selection_name'],price=sel['price'],minimum_price='1.01',stake='0.10',execution_mode='prepare',confirmation_status='APPROVED')
        run('pretap-prepare',held,'PASS')
        run('changed-price-prepare',dict(held,price='999.00'),'PRICE_CHANGED')
    run('reset',dict(action='RESET_BETSLIP'),'PASS')
    run('wrong-link',dict(base,query='Kyoto Hannaryz||Shiga Lake Stars'),'WRONG_EVENT')
    run('moved-line',dict(base,market='SPREAD',line='-999.5'),'TARGET_NOT_FOUND')
    run('cleanup',dict(action='RESET_BETSLIP'),'PASS')
    run('mybets',dict(action='MY_BETS',view='OPEN'),'PASS')
    safety()
    (OUT/'health-end.json').write_text(json.dumps(c.health(),indent=2),encoding='utf-8')
    (OUT/'summary.json').write_text(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(),checks=[dict(tag=x['tag'],ok=x['ok']) for x in results],passed=sum(x['ok'] for x in results),total=len(results),final_action_dispatched=False),indent=2),encoding='utf-8')

if __name__=='__main__':main()
