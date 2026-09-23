import json, time, http.client
from pathlib import Path
from urllib.parse import urlsplit
ROOT=Path('.').resolve(); OUT=ROOT/'evidence'/'stage-timeout-gunma-proof'
cfg=json.loads((ROOT/'.local'/'coordinator.json').read_text(encoding='utf-8-sig'))
u=urlsplit(cfg['url']); token=cfg['token']

def req(method,path,body=None,timeout=30):
    conn=http.client.HTTPConnection(u.hostname,u.port,timeout=timeout)
    payload=None if body is None else json.dumps(body).encode()
    try:
        conn.request(method,path,payload,{'Authorization':'Bearer '+token,'Content-Type':'application/json'})
        r=conn.getresponse(); data=r.read()
        try: return r.status, json.loads(data.decode() or 'null')
        except Exception: return r.status, {'raw': data.decode('utf-8','replace')}
    finally: conn.close()

def health():
    c,h=req('GET','/health'); assert c==200; return h

def dispatch():
    return bool(json.loads((ROOT/'.local'/'pipeline.json').read_text(encoding='utf-8-sig'))['pipeline']['dispatch_enabled'])

assert dispatch() is False
for _ in range(40):
    h=health()
    if h.get('state')=='IDLE' and not h.get('current_instruction'): break
    time.sleep(1)

iid=f'st-stall-{int(time.time())}'[:64]
ins={'instruction_id':iid,'action':'ADAPTER_WORKFLOW','adapter':'live_bet365','scenario':'live',
     'query':'__STALL__','sport':'football','market':'SPREAD','side':'HOME','line':'-0.5',
     'minimum_price':'1.80','stake':'0.10','timeout_ms':300000,'execution_mode':'ready'}
(OUT/'stall-instruction.json').write_text(json.dumps(ins,indent=2),encoding='utf-8')
print('SUBMIT',iid,flush=True)
code,ack=req('POST','/instructions',ins)
print('ack',code,ack,flush=True)
assert code in (200,202)
t0=time.time(); last=None; progress=[]
while time.time()-t0 < 100:
    c,res=req('GET',f'/instructions/{iid}')
    last=res
    if c==202 and isinstance(res,dict):
        st=res.get('device_stage') or (res.get('progress') or {}).get('stage')
        if st and (not progress or progress[-1]!=st):
            progress.append(st); print('prog',st,'t',round(time.time()-t0,1),flush=True)
    if c==200 and isinstance(res,dict) and res.get('status') in ('PASS','FAIL'):
        break
    time.sleep(1)
(OUT/'stall-result.json').write_text(json.dumps(last,indent=2,default=str),encoding='utf-8')
detail=str((last or {}).get('detail') or '')
ok=(last or {}).get('stage')=='TIMEOUT' and ('inactivity' in detail.lower() or 'Stage inactivity' in detail)
print('RESULT', (last or {}).get('status'), (last or {}).get('stage'), detail[:400], 'OK', ok, 'elapsed', round(time.time()-t0,1), flush=True)
# reset / idle
for _ in range(30):
    h=health()
    if h.get('state')=='IDLE': break
    time.sleep(1)
# session check
sid=f'st-stall-sess-{int(time.time())}'[:64]
req('POST','/instructions',{'instruction_id':sid,'action':'SESSION_CHECK','adapter':'live_bet365','scenario':'live','sport':'football','timeout_ms':90000})
for _ in range(60):
    c,res=req('GET',f'/instructions/{sid}')
    if c==200 and isinstance(res,dict) and res.get('status') in ('PASS','FAIL'): break
    time.sleep(2)
h=health(); sess=(h.get('session') or {}).get('state')
row={'ok_timeout':ok,'ok_reset':h.get('state')=='IDLE' and sess=='AUTHENTICATED','detail':detail,
     'session_after_reset':sess,'progress':progress,'elapsed_s':round(time.time()-t0,1),
     'dispatch_enabled':dispatch(),'method':'__STALL__ harness'}
(OUT/'stall-summary.json').write_text(json.dumps(row,indent=2),encoding='utf-8')
# merge into proof-summary
ps=json.loads((OUT/'proof-summary.json').read_text(encoding='utf-8'))
ps['RESET_AFTER_TIMEOUT']=row
ps['STAGE_TIMEOUTS']['stuck_proof']=row
ps['STAGE_TIMEOUTS']['inactivity_proven']=ok
if ok and row['ok_reset']:
    ps['residual_blockers']=[b for b in (ps.get('residual_blockers') or []) if 'Stuck-stage' not in b]
    if not ps['residual_blockers']:
        ps['READY_FOR_LIVE_REPROOF']='YES'
(OUT/'proof-summary.json').write_text(json.dumps(ps,indent=2,default=str),encoding='utf-8')
print(json.dumps(row,indent=2), flush=True)
print('READY', ps.get('READY_FOR_LIVE_REPROOF'), 'blockers', ps.get('residual_blockers'), flush=True)
assert dispatch() is False
raise SystemExit(0 if ok and row['ok_reset'] else 1)
