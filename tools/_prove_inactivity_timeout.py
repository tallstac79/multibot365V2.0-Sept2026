# Re-prove stage inactivity timeout + reset. dispatch stays false.
import json, time, http.client, subprocess
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence" / "stage-timeout-gunma-proof"
cfg = json.loads((ROOT / ".local" / "coordinator.json").read_text(encoding="utf-8-sig"))
u = urlsplit(cfg["url"]); token = cfg["token"]
ADB = Path(r"C:\Users\WINDOWS11\Desktop\platform-tools\adb.exe"); DEVICE = "R5CT61TE14Z"

def req(method, path, body=None, timeout=30):
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=timeout)
    payload = None if body is None else json.dumps(body).encode()
    try:
        conn.request(method, path, payload, {"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        r = conn.getresponse(); data = r.read()
        try: return r.status, json.loads(data.decode() or "null")
        except Exception: return r.status, {"raw": data.decode("utf-8","replace")}
    finally: conn.close()

def health():
    c,h = req("GET","/health"); assert c==200; return h

def adb(*a):
    return subprocess.run([str(ADB),"-s",DEVICE]+list(a), capture_output=True, text=True, timeout=60)

def dispatch():
    return bool(json.loads((ROOT/".local"/"pipeline.json").read_text(encoding="utf-8-sig"))["pipeline"]["dispatch_enabled"])

assert dispatch() is False
adb("shell","input","keyevent","KEYCODE_WAKEUP"); time.sleep(1); adb("shell","input","keyevent","82"); time.sleep(1)
# wait idle
for _ in range(60):
    h=health()
    if h.get("state")=="IDLE" and not h.get("current_instruction"): break
    time.sleep(2)

iid=f"st-inact-{int(time.time())}"[:64]
ins={
  "instruction_id":iid,"action":"ADAPTER_WORKFLOW","adapter":"live_bet365","scenario":"live",
  "query":"Fulham||Crystal Palace","sport":"football","market":"SPREAD","side":"HOME","line":"-0.5",
  "minimum_price":"1.80","stake":"0.10","timeout_ms":300000,"execution_mode":"ready"
}
(OUT/"inactivity-instruction.json").write_text(json.dumps(ins,indent=2),encoding="utf-8")
print("SUBMIT", iid, flush=True)
code, ack = req("POST","/instructions", ins)
print("ack", code, ack, flush=True)
assert code in (200,202)

# Wait until SEARCH or SESSION_CHECK, then turn screen OFF to stall OCR without instant fail-closed assert.
saw=None
t0=time.time()
while time.time()-t0 < 50:
    c,res=req("GET",f"/instructions/{iid}")
    if c==202 and isinstance(res,dict):
        st=res.get("device_stage") or (res.get("progress") or {}).get("stage")
        if st in ("SESSION_CHECK","SPORTS_CONTEXT","OPEN_SEARCH","ENTER_QUERY","SPORTS_HOME","OPEN_HOME") and st not in (None,"STARTED"):
            # Prefer after SESSION_CHECK started captures
            if st in ("SESSION_CHECK","SPORTS_CONTEXT","OPEN_SEARCH","ENTER_QUERY"):
                saw=st; break
    time.sleep(1)
print("saw", saw, "-> screen OFF", flush=True)
adb("shell","input","keyevent","26")  # power/sleep

# Poll for TIMEOUT inactivity
deadline=time.time()+90
last=None
progress=[]
while time.time()<deadline:
    c,res=req("GET",f"/instructions/{iid}")
    last=res
    if c==202 and isinstance(res,dict):
        st=res.get("device_stage") or (res.get("progress") or {}).get("stage")
        if st and (not progress or progress[-1]!=st):
            progress.append(st); print("prog", st, flush=True)
    if c==200 and isinstance(res,dict) and res.get("status") in ("PASS","FAIL"):
        break
    time.sleep(1.5)

(OUT/"inactivity-result.json").write_text(json.dumps(last,indent=2,default=str),encoding="utf-8")
detail=str((last or {}).get("detail") or "")
ok = (last or {}).get("stage")=="TIMEOUT" and ("inactivity" in detail.lower() or "Stage inactivity" in detail)
print("RESULT", (last or {}).get("status"), (last or {}).get("stage"), detail[:300], "OK", ok, flush=True)

# Reset: wake + chrome + session check
adb("shell","input","keyevent","KEYCODE_WAKEUP"); time.sleep(1); adb("shell","input","keyevent","82"); time.sleep(1)
adb("shell","am","start","-a","android.intent.action.VIEW","-d","https://www.bet365.com/#/HO/","com.android.chrome")
time.sleep(3)
for _ in range(40):
    h=health()
    if h.get("state")=="IDLE" and not h.get("current_instruction"): break
    time.sleep(2)
# session check
sid=f"st-inact-sess-{int(time.time())}"[:64]
req("POST","/instructions",{"instruction_id":sid,"action":"SESSION_CHECK","adapter":"live_bet365","scenario":"live","sport":"football","timeout_ms":90000})
for _ in range(60):
    c,res=req("GET",f"/instructions/{sid}")
    if c==200 and isinstance(res,dict) and res.get("status") in ("PASS","FAIL"): break
    time.sleep(2)
h=health(); sess=(h.get("session") or {}).get("state")
reset_ok = h.get("state")=="IDLE" and sess=="AUTHENTICATED"
row={"ok_timeout":ok,"ok_reset":reset_ok,"detail":detail,"session_after_reset":sess,"progress":progress,"result_stage":(last or {}).get("stage"),"dispatch_enabled":dispatch()}
(OUT/"inactivity-summary.json").write_text(json.dumps(row,indent=2),encoding="utf-8")
print(json.dumps(row,indent=2), flush=True)
assert dispatch() is False
raise SystemExit(0 if ok and reset_ok else 1)
