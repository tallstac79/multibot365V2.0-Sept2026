"""Real-phone session proofs (no betting; dispatch/final action stay disabled on the backend). From the repo root:
    PYTHONPATH=. python tools/session_proofs.py <command> ...

    python proofs.py health
    python proofs.py check <tag>          SESSION_CHECK, prints the machine path
    python proofs.py probe <tag>          SESSION_PROBE (screen-only classification)
    python proofs.py restart              POST /test/restart, wait for the agent, wait for the idle probe
    python proofs.py logout               clear Chrome data (dedicated test phone) and open Bet365 home
    python proofs.py wait_selfheal <sec>  watch /health until the agent's own SESSION_CHECK has run
    python proofs.py hold <tag>           hold run on the Besancon event link (no tap) then RESET_BETSLIP
Evidence: evidence/session-machine/<tag>.json
"""
import json
import subprocess
import sys
import time
from pathlib import Path

from tools.coordinator_client import Client

sys.stdout.reconfigure(encoding='utf-8')
ADB = r'C:\Users\WINDOWS11\Desktop\platform-tools\adb.exe'
OUT = Path('evidence/session-machine'); OUT.mkdir(parents=True, exist_ok=True)
c = Client(json.loads(Path('.local/coordinator.json').read_text(encoding='utf-8-sig')))
KEYS = ('status', 'stage', 'detail', 'session_machine', 'session_recovered', 'session_path', 'home_verified', 'login_submitted', 'chrome_first_run_dismissed', 'duration_ms', 'route')


def health(retries=30):
    for _ in range(retries):
        try:
            return c.health()
        except Exception:
            time.sleep(2)
    return None


def show_health(h, label='health'):
    print(label, {k: h.get(k) for k in ('app_version', 'state', 'credentials_configured', 'credential_store')}, 'session', h.get('session'), 'recovery', h.get('session_recovery'), flush=True)


def submit(payload, seconds):
    for _ in range(60):
        try:
            c.submit(payload); break
        except ValueError as e:
            if 'BUSY' not in str(e): raise
            time.sleep(2)
    for _ in range(60):
        try:
            return c.result(payload['instruction_id'], seconds=seconds)
        except ValueError:
            time.sleep(1)
    return {}


def save(tag, obj):
    (OUT / f'{tag}.json').write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding='utf-8')


def check(tag):
    iid = f'{tag}-{int(time.time())}'
    r = submit(dict(instruction_id=iid, action='SESSION_CHECK', adapter='live_bet365', scenario='live', sport='basketball', timeout_ms=150000), 170)
    print('SESSION_CHECK', {k: r.get(k) for k in KEYS}, flush=True)
    save(iid, r); return r


def probe(tag):
    iid = f'{tag}-{int(time.time())}'
    r = submit(dict(instruction_id=iid, action='SESSION_PROBE', adapter='live_bet365', timeout_ms=30000), 40)
    print('SESSION_PROBE', {k: r.get(k) for k in ('status', 'stage', 'detail', 'session')}, flush=True)
    save(iid, r); return r


def restart():
    import urllib.request
    cfg = json.loads(Path('.local/coordinator.json').read_text(encoding='utf-8-sig'))
    req = urllib.request.Request(cfg['url'].rstrip('/') + '/test/restart', method='POST', data=b'{}',
                                 headers={'Authorization': 'Bearer ' + cfg['token'], 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print('restart ->', resp.status, flush=True)
    except Exception as e:
        print('restart request:', e, flush=True)
    t0 = time.time(); time.sleep(6)
    h = health(45)
    print(f'agent back after {time.time() - t0:.1f}s pid={h and h.get("pid")}', flush=True)
    for _ in range(40):
        h = health()
        s = (h or {}).get('session') or {}
        if s.get('state') in ('AUTHENTICATED', 'LOGGED_OUT', 'EXPIRED', 'RESTRICTED') and 'idle probe' in str(s.get('detail')):
            break
        time.sleep(3)
    show_health(h, 'after restart'); save(f'restart-{int(time.time())}', h); return h


def logout():
    for cmd in (['shell', 'am', 'force-stop', 'com.android.chrome'], ['shell', 'pm', 'clear', 'com.android.chrome'],
                ['shell', 'am', 'start', '-a', 'android.intent.action.VIEW', '-d', 'https://www.bet365.com/#/HO/', 'com.android.chrome']):
        out = subprocess.run([ADB] + cmd, capture_output=True, timeout=60)
        print(' '.join(cmd[:3]), '->', out.stdout.decode().strip()[:80], out.stderr.decode().strip()[:80], flush=True)
    time.sleep(8)


def wait_selfheal(seconds):
    t0 = time.time(); seen = set()
    while time.time() - t0 < seconds:
        h = health()
        s = (h or {}).get('session') or {}; rec = (h or {}).get('session_recovery') or {}
        key = (s.get('state'), s.get('detail'), rec.get('last_outcome'), (h or {}).get('state'))
        if key not in seen:
            seen.add(key); print(f'{time.time() - t0:6.1f}s session={s.get("state")} ({s.get("detail")}) agent={h.get("state")} recovery={rec}', flush=True)
        if rec.get('last_outcome', '').startswith('self-session') and h.get('state') == 'IDLE' and s.get('state') == 'AUTHENTICATED' and 'workflow' in str(s.get('detail')):
            break
        time.sleep(3)
    h = health(); show_health(h, 'final'); last = h.get('last_result') or {}
    print('last_result', {k: last.get(k) for k in KEYS}, flush=True); save(f'selfheal-{int(time.time())}', dict(health=h)); return h


def hold(tag):
    iid = f'{tag}-{int(time.time())}'
    r = submit(dict(instruction_id=iid, action='ADAPTER_WORKFLOW', adapter='live_bet365', scenario='live', query='Besancon||Val De Seine', sport='basketball',
                    market='SPREAD', side='AWAY', line='+1.5', minimum_price='1.50', stake='0.10', timeout_ms=240000, execution_mode='hold',
                    event_url='https://www.bet365.com/#/AC/B18/C21168177/D19/E26747385/F19/I0/', kickoff_utc='2026-09-25T18:00'), 280)
    print('HOLD', {k: r.get(k) for k in KEYS}, '| fixture', r.get('fixture_name'), '| stage_timings', [(x['stage'], round(x['duration_ms'] / 1000, 1)) for x in (r.get('stage_timings') or [])], flush=True)
    save(iid, r)
    r2 = submit(dict(instruction_id='rs' + iid, action='RESET_BETSLIP', adapter='live_bet365', scenario='live', timeout_ms=60000), 90)
    print('RESET', r2.get('status'), flush=True)
    return r


if __name__ == '__main__':
    what = sys.argv[1]
    if what == 'health': show_health(health())
    elif what == 'check': check(sys.argv[2])
    elif what == 'probe': probe(sys.argv[2])
    elif what == 'restart': restart()
    elif what == 'logout': logout()
    elif what == 'wait_selfheal': wait_selfheal(int(sys.argv[2]))
    elif what == 'hold': hold(sys.argv[2])
