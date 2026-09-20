"""Physical Samsung acceptance using HTTP only; requires ADB server stopped."""
import json, socket, time, argparse
from pathlib import Path
from coordinator_client import Client

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',default='.local/coordinator.json');parser.add_argument('--output',default='evidence/coordinator');args=parser.parse_args()
    c=Client(json.loads(Path(args.config).read_text()));out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    prefix='lan-'+str(int(time.time())); results=[]
    def save(path,data):
        p=out/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(data,indent=2),encoding='utf-8')
    def no_adb():
        s=socket.socket();s.settimeout(.5);code=s.connect_ex(('127.0.0.1',5037));s.close();assert code!=0,'Stop ADB before this suite';return True
    def instruction(name,text='Fulham',target='Search',timeout=15000):
        return dict(instruction_id=prefix+'-'+name,action='OPEN_AND_TYPE',target_text=target,input_text=text,timeout_ms=timeout)
    def collect(name,i):
        r=c.result(i['instruction_id']);save(name+'/instruction.json',i);save(name+'/result.json',r)
        code,e=c.request('GET','/instructions/'+i['instruction_id']+'/evidence')
        save(name+'/evidence.json',e)
        if code==200:
            for f in ['before.png','focused.png','after.png','field_after.png','before.txt','focused.txt','after.txt']:
                status,data=c.request('GET','/instructions/'+i['instruction_id']+'/artifacts/'+f,raw=True)
                if status==200:(out/name/f).write_bytes(data)
        return r,e
    def run(name,expected='PASS',**kwargs):
        i=instruction(name,**kwargs);save(name+'/ack.json',c.submit(i));r,e=collect(name,i);assert r['stage']==expected,r
        if expected=='PASS':assert e['input_attempts']==1 and e['exact_input_match'] and e['visual_text_match'],e
        results.append(dict(case=name,expected=expected,result=r,assertions_passed=True));print(name,r['stage'],flush=True);return i,r,e
    save('environment.json',dict(adb_server_absent=no_adb(),health=c.health(),transport='private LAN HTTP; no forwarding; suite contains no ADB calls'))
    i,r,e=run('normal')
    code,duplicate=c.request('POST','/instructions',i);save('duplicate.json',duplicate);assert code==409 and duplicate['stage']=='DUPLICATE' and duplicate['execution_count']==1
    assert c.result(i['instruction_id'])==r
    assert c.request('GET','/instructions/'+i['instruction_id']+'/evidence')[1]['input_attempts']==1
    results.append(dict(case='duplicate',assertions_passed=True))
    for name,text in [('spaces','clear blue sky'),('mixed','MiXeD Case'),('numbers','907314')]:run(name,text=text)
    bad=[]
    for body in ['{', '{}', json.dumps(dict(i,timeout_ms='15000')),json.dumps(dict(i,unknown=True)),json.dumps(i)[:-1]+',"action":"OPEN_AND_TYPE"}']:
        code,r=c.request('POST','/instructions',body);assert code==400 and r['stage']=='INVALID_INSTRUCTION';bad.append(dict(body=body,http=code,result=r))
    save('malformed.json',bad);results.append(dict(case='malformed',count=len(bad),assertions_passed=True))
    other=Client(dict(c.config,token='invalid'));code,r=other.request('GET','/health');assert code==401;save('unauthorized.json',r)
    run('missing',expected='TARGET_NOT_FOUND',target='Nonexistent')
    run('timeout',expected='TIMEOUT',timeout=200)
    lost=instruction('lost-response',text='Lost response 42');body=json.dumps(lost).encode();s=socket.create_connection((c.url.hostname,c.url.port),5)
    headers=f'POST /instructions HTTP/1.1\r\nHost: {c.url.hostname}\r\nAuthorization: Bearer {c.config["token"]}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n'
    s.sendall(headers.encode()+body);s.close();time.sleep(.3)
    retry=c.submit(lost);save('lost-response/retry.json',retry);assert retry.get('stage')=='DUPLICATE',retry
    r,e=collect('lost-response',lost);assert r['stage']=='PASS' and r['execution_count']==1 and e['input_attempts']==1,r
    results.append(dict(case='lost-response',result=r,assertions_passed=True));print('lost-response PASS',flush=True)
    pending=instruction('restart',text='Restart proof 42');oldpid=c.health()['pid'];save('restart/ack.json',c.submit(pending))
    busy=instruction('busy');code,b=c.request('POST','/instructions',busy);save('busy.json',b);assert code==409 and 'BUSY' in b['detail']
    end=time.monotonic()+14
    while time.monotonic()<end:
        code,e=c.request('GET','/instructions/'+pending['instruction_id']+'/evidence')
        if code==200 and e.get('input_attempts')==1 and e['status']=='RUNNING':break
        time.sleep(.06)
    else:raise AssertionError('Did not observe durable input before restart')
    save('restart/before-kill.json',e);save('restart/restart-ack.json',c.request('POST','/test/restart',{})[1])
    time.sleep(.6);end=time.monotonic()+60
    while time.monotonic()<end:
        try:
            health=c.health()
            if health['pid']!=oldpid:break
        except OSError:pass
        time.sleep(.5)
    else:raise AssertionError('Service did not rebind')
    save('restart/health-after.json',health);r,e=collect('restart',pending)
    assert r['stage']=='INTERNAL_ERROR' and r['execution_count']==1 and e['input_attempts']==1,r
    code,dup=c.request('POST','/instructions',pending);assert code==409 and dup['stage']=='DUPLICATE';save('restart/duplicate.json',dup)
    results.append(dict(case='restart-no-replay',old_pid=oldpid,new_pid=health['pid'],result=r,assertions_passed=True));print('restart PASS',flush=True)
    run('after-restart',text='Recovered 42')
    save('results.json',dict(status='PASS',tests=results,adb_server_absent_at_end=no_adb(),final_health=c.health()))
    print('ACCEPTANCE PASS',flush=True)

if __name__=='__main__':main()
