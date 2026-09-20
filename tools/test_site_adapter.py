"""Physical local-simulator acceptance, using authenticated LAN HTTP only."""
import argparse,json,socket,time,hashlib
from pathlib import Path
from coordinator_client import Client

CASES=[('moneyline','normal','MONEYLINE','HOME','PASS'),('spread','normal','SPREAD','AWAY','PASS'),('spread_home','normal','SPREAD','HOME','PASS'),('total','normal','TOTAL','OVER','PASS'),('empty','empty','SPREAD','HOME','NO_FIXTURE_FOUND'),('query_empty','normal','SPREAD','HOME','NO_FIXTURE_FOUND'),('query_unverified','normal','SPREAD','HOME','TEXT_NOT_VERIFIED'),('ambiguous','ambiguous','SPREAD','HOME','AMBIGUOUS_FIXTURE'),('wrong_event','wrong_event','SPREAD','HOME','WRONG_EVENT'),('click_ignored','click_ignored','SPREAD','HOME','CLICK_FAILED'),('suspended','suspended','SPREAD','HOME','SUSPENDED'),('unavailable','unavailable','SPREAD','HOME','UNAVAILABLE'),('changing','changing','SPREAD','HOME','PRICE_CHANGED'),('wrong_line','wrong_line','SPREAD','HOME','LINE_CHANGED'),('wrong_side','wrong_side','SPREAD','HOME','SELECTION_CHANGED'),('timeout','normal','SPREAD','HOME','TIMEOUT')]

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',default='.local/coordinator.json');parser.add_argument('--output',default='evidence/fixture');parser.add_argument('--case');parser.add_argument('--resume',action='store_true');args=parser.parse_args()
    c=Client(json.loads(Path(args.config).read_text()));out=Path(args.output);out.mkdir(parents=True,exist_ok=True);prefix='adapter-'+str(int(time.time()));summary={'status':'RUNNING','tests':[]}
    if args.resume:
        build=json.loads((out/'build.json').read_text());assert build['apk_sha256']==hashlib.sha256(Path('android/Bet365Agent/app/build/outputs/apk/debug/app-debug.apk').read_bytes()).hexdigest(),'Resume requires the same APK'
        summary=json.loads((out/'results.json').read_text());summary['status']='RUNNING';summary.pop('failure',None)
    completed={t['case'] for t in summary['tests'] if t.get('assertions_passed')}
    def save(path,value):
        p=out/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value,indent=2),encoding='utf-8')
    def no_adb():
        with socket.socket() as s:s.settimeout(.5);assert s.connect_ex(('127.0.0.1',5037))!=0,'Stop the ADB server first'
        return True
    def instruction(name,scenario='normal',market='SPREAD',side='HOME'):
        return dict(instruction_id=prefix+'-'+name,action='ADAPTER_WORKFLOW',adapter='local_simulator',scenario=scenario,query=('unreadable screen text '*4) if name=='query_unverified' else 'zebra' if name=='query_empty' else 'football',market=market,side=side,timeout_ms=200 if name=='timeout' else 60000)
    def collect(name,i):
        r=c.result(i['instruction_id']);save(name+'/instruction.json',i);save(name+'/result.json',r)
        code,e=c.request('GET','/instructions/'+i['instruction_id']+'/evidence');save(name+'/evidence.json',e)
        if code==200:
            files=list(e.get('screenshots',[]))
            for f in list(files):files.append(f.replace('.png','.txt'))
            if e.get('query_evidence'):files+=['before.png','focused.png','after.png','field_after.png','before.txt','focused.txt','after.txt']
            for f in files:
                code,data=c.request('GET','/instructions/'+i['instruction_id']+'/artifacts/'+f,raw=True)
                assert code==200,(f,code)
                (out/name/f).write_bytes(data)
        return r,e
    def check(name,i,expected):
        r,e=collect(name,i);assert r['stage']==expected,r
        if expected=='PASS':
            assert r['status']=='PASS' and r['execution_count']==1
            assert e['query_evidence']['exact_input_match'] and e['query_evidence']['visual_text_match'] and e['query_evidence']['input_attempts']==1
            assert len(e['discovered_fixtures'])==3 and len(e['markets'])==6
            assert e['fixture']==e['discovered_fixtures'][0]
            assert e['discovered_fixtures'][0]['home'].split()[0]==e['discovered_fixtures'][1]['home'].split()[0]
            assert r['home']==e['final_state']['home'] and r['away']==e['final_state']['away']
            for key in ['market','side','line','price']:assert e['selection'][key]==e['final_state'][key]
            assert e['final_state']['state']=='REVIEWONLY' and e['gesture_attempts']==5
            phases={v['phase'] for v in e['events'] if 'phase' in v}
            assert {'OPEN_HOME','OPEN_SEARCH','ENTER_QUERY','DISCOVER_FIXTURE','SELECT_FIXTURE','VERIFY_EVENT','DISCOVER_MARKETS','READ_SELECTION','READ_LINE','READ_PRICE','OPEN_SELECTION','VERIFY_FINAL_STATE'}<=phases
            code,d=c.request('POST','/instructions',i);assert code==409 and d['stage']=='DUPLICATE' and d['execution_count']==1;save(name+'/duplicate.json',d)
            assert c.result(i['instruction_id'])==r
            assert c.request('GET','/instructions/'+i['instruction_id']+'/evidence')[1]['gesture_attempts']==5
        if expected=='TEXT_NOT_VERIFIED':assert e['query_evidence']['input_attempts']==1 and not e['query_evidence']['visual_text_match']
        if expected in ['NO_FIXTURE_FOUND','AMBIGUOUS_FIXTURE']:assert e['gesture_attempts']==2
        if expected in ['SUSPENDED','UNAVAILABLE']:assert e['gesture_attempts']==4
        summary['tests'].append(dict(case=name,expected=expected,result=r,assertions_passed=True));save('results.json',summary);print(name,expected,r.get('fixture_name',''),flush=True)
        return r,e
    try:
        save('resumed-environment.json' if args.resume else 'environment.json',dict(health=c.health(),adb_server_absent=no_adb(),transport='private LAN HTTP; no ADB calls or forwarding'))
        bad=instruction('unknown');bad['adapter']='missing_adapter';code,r=c.request('POST','/instructions',bad);assert code==400 and r['stage']=='INVALID_INSTRUCTION';save('invalid-adapter.json',r)
        for name,scenario,market,side,expected in CASES:
            if (args.case and args.case!=name) or (args.resume and name in completed):continue
            i=instruction(name,scenario,market,side);save(name+'/ack.json',c.submit(i));check(name,i,expected)
        if not args.case:
            i=instruction('restart');old=c.health()['pid'];save('restart/ack.json',c.submit(i));end=time.monotonic()+60
            while time.monotonic()<end:
                code,e=c.request('GET','/instructions/'+i['instruction_id']+'/evidence')
                if code==200 and e.get('gesture_attempts')==5 and e.get('status')=='RUNNING':break
                time.sleep(.08)
            else:raise AssertionError('Could not intercept final review tap')
            save('restart/before-kill.json',e);save('restart/restart-ack.json',c.request('POST','/test/restart',{})[1]);time.sleep(.6);end=time.monotonic()+60
            while time.monotonic()<end:
                try:
                    health=c.health()
                    if health['pid']!=old:break
                except OSError:pass
                time.sleep(.5)
            else:raise AssertionError('Service did not rebind')
            save('restart/health-after.json',health);r,e=check('restart',i,'INTERNAL_ERROR');assert e['gesture_attempts']==5
            code,d=c.request('POST','/instructions',i);assert code==409 and d['stage']=='DUPLICATE';save('restart/duplicate.json',d)
            assert c.request('GET','/instructions/'+i['instruction_id']+'/evidence')[1]['gesture_attempts']==5
            i=instruction('after_restart',market='TOTAL',side='UNDER');save('after_restart/ack.json',c.submit(i));check('after_restart',i,'PASS')
            i=instruction('lost_response',market='MONEYLINE');body=json.dumps(i).encode()
            with socket.create_connection((c.url.hostname,c.url.port),5) as connection:
                headers=f'POST /instructions HTTP/1.1\r\nHost: {c.url.hostname}\r\nAuthorization: Bearer {c.config["token"]}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n'
                connection.sendall(headers.encode()+body)
            time.sleep(.3);retry=c.submit(i);assert retry.get('stage')=='DUPLICATE';save('lost_response/retry.json',retry);check('lost_response',i,'PASS')
            codes={t['result']['fixture_name'] for t in summary['tests'] if t['result']['stage']=='PASS'};assert len(codes)>1,'Fixtures must vary between runs'
        summary['adb_server_absent_at_end']=no_adb();summary['final_health']=c.health();summary['status']='PASS'
    except Exception as error:
        summary['status']='FAIL';summary['failure']=str(error);raise
    finally:save('results.json',summary)
    print('ADAPTER ACCEPTANCE PASS',flush=True)

if __name__=='__main__':main()
