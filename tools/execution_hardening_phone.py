"""Bounded, disarmed hold/prepare and reboot proofs. Never dispatches Place Bet.

The fixture is a dated diagnostic, not a production signal. Run from repo root:
python -m tools.execution_hardening_phone [reboot]
"""
import json
from pathlib import Path
import subprocess
import sys
import time
from tools.coordinator_client import Client
from tools.strategy_phone_audit import ROOT, safety

ADB = r'C:\Users\WINDOWS11\Desktop\platform-tools\adb.exe'
BASE = dict(action='ADAPTER_WORKFLOW', sport='basketball', query='Kirchheim||SBB Baskets Wolmirstedt',
            market='MONEYLINE', side='HOME', line='', minimum_price='1.01', stake='0.10', execution_mode='hold',
            event_url='https://www.bet365.com/#/AC/B18/C21170155/D19/E26748183/F19/I0/',
            kickoff_utc='2026-09-26T16:00', competition='Germany Pro A', period='FULL_GAME', max_line_deterioration='0')


def main():
    safety()
    prefix='hardening-'+str(int(time.time()))
    reboot='reboot' in sys.argv[1:]
    out=ROOT/'evidence/execution-hardening'/('reboot-' if reboot else 'phone-')/prefix
    out.mkdir(parents=True,exist_ok=True)
    c=Client(json.loads((ROOT/'.local/coordinator.json').read_text(encoding='utf-8-sig')))
    checks=[]
    def save(tag,item):
        (out/(tag+'.json')).write_text(json.dumps(item,indent=2),encoding='utf-8')
        checks.append(dict(tag=tag,ok=item['ok']))
        print(tag,item['ok'],item.get('result',{}).get('detail',''),flush=True)
    def run(tag,payload,expected='PASS',iid=None):
        safety()
        assert payload.get('execution_mode') != 'dispatch' and not payload.get('place_bet')
        p=dict(payload,instruction_id=iid or prefix+'-'+tag,adapter='live_bet365',scenario='live',timeout_ms=120000)
        start=time.monotonic()
        try:
            ack=c.submit(p)
            deadline=time.monotonic()+145
            poll_errors=[]
            while True:
                try:
                    r=c.result(p['instruction_id'],seconds=10);break
                except (ValueError,TimeoutError) as exc:
                    poll_errors.append(str(exc))
                    if time.monotonic()>deadline:raise
                    time.sleep(1)  # Read-only retry of the same ID; never resubmit.
            ok=r.get('status')=='PASS' if expected=='PASS' else r.get('status')=='FAIL' and r.get('stage')==expected
            save(tag,dict(ok=ok,payload=p,ack=ack,result=r,expected=expected,poll_errors=poll_errors,wall_seconds=round(time.monotonic()-start,3)))
            return r,p
        except Exception as exc:
            save(tag,dict(ok=False,payload=p,error=str(exc),wall_seconds=round(time.monotonic()-start,3)))
            return {},p
    def reject(tag,p,fragment):
        safety();assert p['execution_mode']=='prepare'
        code,r=c.request('POST','/instructions',p)
        save(tag,dict(ok=code==400 and fragment in r.get('detail',''),code=code,result=r,payload=p))
    def adb(*args):
        return subprocess.run([ADB,'-s','R5CT61TE14Z',*args],capture_output=True,text=True,timeout=15).stdout.strip()

    h=c.health()
    assert h.get('phone_final_action_armed') is False
    (out/'health-start.json').write_text(json.dumps(h,indent=2),encoding='utf-8')
    if reboot:
        assert not h.get('current_instruction')
        before=adb('shell','cat','/proc/sys/kernel/random/boot_id')
        adb('reboot');print('Reboot requested',flush=True)
        until=time.monotonic()+180
        while time.monotonic()<until:
            if adb('shell','getprop','sys.boot_completed')=='1':break
            time.sleep(2)
        else:raise RuntimeError('Boot timeout')
        after=adb('shell','cat','/proc/sys/kernel/random/boot_id')
        adb('shell','input','keyevent','224');adb('shell','wm','dismiss-keyguard')
        until=time.monotonic()+180
        while time.monotonic()<until:
            try:
                h=c.health()
                if h.get('healthy') and not h.get('current_instruction'):break
            except (OSError,RuntimeError):pass
            time.sleep(2)
        else:raise RuntimeError('Coordinator recovery timeout')
        save('reboot',dict(ok=bool(after) and before!=after and h.get('phone_final_action_armed') is False,
                           boot_before=before,boot_after=after,health=h))
        prior=sorted((ROOT/'evidence/execution-hardening/phone-').glob('*/hold.json'))[-1]
        original=json.loads(prior.read_text(encoding='utf-8'))['payload']
        code,r=c.request('POST','/instructions',original)
        save('duplicate-after-reboot',dict(ok=code==409 and r.get('stage')=='DUPLICATE',code=code,result=r))
    code,lease=c.request('POST','/diagnostics',{'seconds':1800})
    assert code==200 and lease['diagnostics_active']
    session,_=run('session',dict(action='SESSION_CHECK',sport='basketball'))
    if session.get('status')=='PASS':
        if reboot:
            search=dict(BASE);search.pop('event_url')
            run('search-hold',search)
        else:
            r,p=run('hold',BASE)
            code,d=c.request('POST','/instructions',p)
            save('duplicate',dict(ok=code==409 and d.get('stage')=='DUPLICATE',code=code,result=d))
            if r.get('status')=='PASS':
                sel=r['selection'];ctx=r['event_context']
                held=dict(action='PLACE_HELD',sport='basketball',market=sel['market'],side=sel['side'],
                          line=sel.get('line') or '',selection_name=sel['selection_name'],price=sel['price'],
                          minimum_price=BASE['minimum_price'],stake=BASE['stake'],execution_mode='prepare',
                          confirmation_status='APPROVED',held_instruction_id=p['instruction_id'],
                          **{k:ctx[k] for k in ('home','away','competition','kickoff_utc','period')})
                prepared=dict(held,instruction_id=p['instruction_id']+'-place',adapter='live_bet365',scenario='live',timeout_ms=120000)
                reject('wrong-held-event',dict(prepared,away='Wrong Opponent'),'Held event changed')
                reject('changed-held-price',dict(prepared,price='999.00'),'Held selection changed')
                run('pretap-prepare',held,iid=p['instruction_id']+'-place')
            run('reset',dict(action='RESET_BETSLIP'))
            run('wrong-link',dict(BASE,query='Kyoto Hannaryz||Shiga Lake Stars'),'WRONG_EVENT')
            run('worse-line',dict(BASE,market='SPREAD',line='+999.5'),'TARGET_NOT_FOUND')
        run('cleanup',dict(action='RESET_BETSLIP'))
    safety()
    h=c.health()
    assert h.get('phone_final_action_armed') is False
    (out/'health-end.json').write_text(json.dumps(h,indent=2),encoding='utf-8')
    (out/'summary.json').write_text(json.dumps(dict(checks=checks,passed=sum(x['ok'] for x in checks),total=len(checks),
                            final_action_dispatched=False),indent=2),encoding='utf-8')
    return 0 if all(x['ok'] for x in checks) else 1


if __name__=='__main__':
    raise SystemExit(main())
