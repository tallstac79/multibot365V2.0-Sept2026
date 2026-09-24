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
    c,h=req("GET","/health"); assert c==200; return h

def adb(*a):
    return subprocess.run([str(ADB),"-s",DEVICE]+list(a), capture_output=True, text=True, timeout=60)

def dispatch():
    return bool(json.loads((ROOT/".local"/"pipeline.json").read_text(encoding="utf-8-sig"))["pipeline"]["dispatch_enabled"])

assert dispatch() is False
adb("shell","input","keyevent","KEYCODE_WAKEUP"); time.sleep(1); adb("shell","input","keyevent","82")
for _ in range(40):
    h=health()
    if h.get("state")=="IDLE" and not h.get("current_instruction"): break
    time.sleep(2)

iid=f"st-inact2-{int(time.time())}"[:64]
ins={"instruction_id":iid,"action":"ADAPTER_WORKFLOW","adapter":"live_bet365","scenario":"live",
     "query":"Fulham||Crystal Palace","sport":"football","market":"SPREAD","side":"HOME","line":"-0.5",
     "minimum_price":"1.80","stake":"0.10","timeout_ms":300000,"execution_mode":"ready"}
print("SUBMIT", iid, flush=True)
code,ack=req("POST","/instructions",ins)
assert code in (200,202), ack

# Wait until ENTER_QUERY (stage entered), then disable accessibility to freeze OCR/gestures.
saw=None; t0=time.time()
while time.time()-t0 < 90:
    c,res=req("GET",f"/instructions/{iid}")
    if c==202 and isinstance(res,dict):
        st=res.get("device_stage") or (res.get("progress") or {}).get("stage")
        if st in ("ENTER_QUERY","QUERY_VERIFY","RESULTS_WAIT","OPEN_SEARCH","SPORTS_CONTEXT"):
            saw=st
            if st in ("ENTER_QUERY","QUERY_VERIFY","RESULTS_WAIT"):
                break
    if c==200: break
    time.sleep(1)
print("saw", saw, "-> disable accessibility + airplane", flush=True)
# Disable our accessibility service (freeze screenshots/gestures). Save current value first.
cur = adb("shell","settings","get","secure","enabled_accessibility_services")
(OUT/"inactivity2-a11y-before.txt").write_text(cur.stdout or "", encoding="utf-8")
adb("shell","settings","put","secure","enabled_accessibility_services","")
adb("shell","settings","put","global","airplane_mode_on","1")
adb("shell","am","broadcast","-a","android.intent.action.AIRPLANE_MODE","--ez","state","true")

deadline=time.time()+100
last=None; progress=[]
while time.time()<deadline:
    try:
        c,res=req("GET",f"/instructions/{iid}")
    except Exception as e:
        print("poll err", e, flush=True); time.sleep(2); continue
    last=res
    if c==202 and isinstance(res,dict):
        st=res.get("device_stage") or (res.get("progress") or {}).get("stage")
        if st and (not progress or progress[-1]!=st):
            progress.append(st); print("prog", st, flush=True)
    if c==200 and isinstance(res,dict) and res.get("status") in ("PASS","FAIL"):
        break
    time.sleep(1.5)

# Restore network + a11y
adb("shell","settings","put","global","airplane_mode_on","0")
adb("shell","am","broadcast","-a","android.intent.action.AIRPLANE_MODE","--ez","state","false")
prev=(cur.stdout or "").strip()
if prev and prev != "null":
    adb("shell","settings","put","secure","enabled_accessibility_services", prev)
else:
    # fallback package/service name used by Bet365Agent
    adb("shell","settings","put","secure","enabled_accessibility_services","com.bet365agent/com.bet365agent.Bet365AccessibilityService")

(OUT/"inactivity2-result.json").write_text(json.dumps(last,indent=2,default=str),encoding="utf-8")
detail=str((last or {}).get("detail") or "")
ok=(last or {}).get("stage")=="TIMEOUT" and ("inactivity" in detail.lower() or "Stage inactivity" in detail or "Absolute deadline" in detail)
print("RESULT", (last or {}).get("status"), (last or {}).get("stage"), detail[:350], "OK", ok, flush=True)

# Wake/reset/session
adb("shell","input","keyevent","KEYCODE_WAKEUP"); time.sleep(1); adb("shell","input","keyevent","82")
time.sleep(2)
for _ in range(50):
    try:
        h=health()
        if h.get("state")=="IDLE" and not h.get("current_instruction"): break
    except Exception:
        pass
    time.sleep(2)
sid=f"st-inact2-sess-{int(time.time())}"[:64]
try:
    req("POST","/instructions",{"instruction_id":sid,"action":"SESSION_CHECK","adapter":"live_bet365","scenario":"live","sport":"football","timeout_ms":90000})
    for _ in range(60):
        c,res=req("GET",f"/instructions/{sid}")
        if c==200 and isinstance(res,dict) and res.get("status") in ("PASS","FAIL"): break
        time.sleep(2)
except Exception as e:
    print("session_check err", e, flush=True)
h=health(); sess=(h.get("session") or {}).get("state")
row={"ok_timeout":ok,"ok_reset":h.get("state")=="IDLE" and sess in ("AUTHENTICATED","UNKNOWN","LOGGED_OUT"),
     "detail":detail,"session_after_reset":sess,"progress":progress,"result_stage":(last or {}).get("stage"),
     "dispatch_enabled":dispatch(),"method":"disable_a11y_after_ENTER_QUERY"}
(OUT/"inactivity2-summary.json").write_text(json.dumps(row,indent=2),encoding="utf-8")
print(json.dumps(row,indent=2), flush=True)
assert dispatch() is False
raise SystemExit(0 if ok else 2)
