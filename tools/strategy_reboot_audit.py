"""One requested phone reboot proof. No betting action; preserves backend disarm."""
import json
from pathlib import Path
import subprocess
import time
from tools.strategy_phone_audit import safety, ROOT
from tools.coordinator_client import Client

def main():
    safety()
    out=ROOT/'evidence/strategy-audit/reboot'/('run-'+str(int(time.time())));out.mkdir(parents=True,exist_ok=True)
    c=Client(json.loads((ROOT/'.local/coordinator.json').read_text(encoding='utf-8-sig')))
    before=c.health()
    if before.get('current_instruction'):raise RuntimeError('Phone busy; reboot withheld')
    def adb(*args):
        return subprocess.run(['adb',*args],capture_output=True,text=True,timeout=12).stdout.strip()
    boot_before=adb('shell','cat','/proc/sys/kernel/random/boot_id')
    start=time.monotonic();adb('reboot');print('Reboot requested',flush=True)
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        if adb('shell','getprop','sys.boot_completed')=='1':break
        time.sleep(2)
    else:raise RuntimeError('Boot did not finish within 180s')
    boot_after=adb('shell','cat','/proc/sys/kernel/random/boot_id')
    adb('shell','input','keyevent','224');adb('shell','wm','dismiss-keyguard')
    print('Boot complete; non-secure keyguard dismissed',flush=True)
    deadline=time.monotonic()+150
    while time.monotonic()<deadline:
        try:
            after=c.health()
            if after.get('healthy') and not after.get('current_instruction'):break
        except (OSError,RuntimeError):pass
        time.sleep(2)
    else:raise RuntimeError('Coordinator did not recover within 150s')
    iid='forensic-reboot-session-'+str(int(time.time()))
    (out/'checkpoint.json').write_text(json.dumps(dict(boot_before=boot_before,boot_after=boot_after,health=after,instruction_id=iid),indent=2))
    safety()
    ack=c.submit(dict(instruction_id=iid,action='SESSION_CHECK',adapter='live_bet365',scenario='live',sport='basketball',timeout_ms=120000))
    poll_errors=[];deadline=time.monotonic()+145
    while time.monotonic()<deadline:
        try:
            session=c.result(iid,seconds=10);break
        except (ValueError,TimeoutError) as exc:
            poll_errors.append(str(exc));time.sleep(1)
    else:session=dict(status='UNRESOLVED',detail='Bounded result polling expired; no replacement instruction submitted')
    latest=sorted((ROOT/'evidence/strategy-audit/phone').glob('run-*'))[-1]
    prior=json.loads((latest/'hold.json').read_text(encoding='utf-8'))
    assert prior['payload']['execution_mode']=='hold'
    code,duplicate=c.request('POST','/instructions',prior['payload'])
    safety()
    result=dict(boot_id_changed=boot_before!=boot_after and bool(boot_after),boot_before=boot_before,boot_after=boot_after,
                coordinator_recovered=after.get('healthy'),session=session,duplicate_code=code,duplicate=duplicate,
                wall_seconds=round(time.monotonic()-start,3),health=c.health(),ack=ack,poll_errors=poll_errors,final_action_dispatched=False)
    (out/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('REBOOT',result['boot_id_changed'],'SESSION',session.get('status'),session.get('detail'),
          'DUPLICATE',code,duplicate.get('stage'),'SECONDS',result['wall_seconds'],flush=True)

if __name__=='__main__':main()
