"""Phone regression (Milestones A/B/C). NEVER taps Place Bet (hold / prepare / MY_BETS / RESET only). From the repo root:

    PYTHONPATH=. python tools/phone_regression.py "$(cat evidence/milestone-c/cases.json)" evidence/<out-dir>


Case fields: tag, query, market, side, line, [event_url, kickoff_utc], expect ("PASS" or a stage), and for
hold PASS cases a PLACE_HELD *prepare* pre-tap check follows, then RESET_BETSLIP. "mybets": true runs a MY_BETS
OPEN read and checks the phone returned HOME. "no_search": true asserts the run never entered ENTER_QUERY.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

from tools.coordinator_client import Client

sys.stdout.reconfigure(encoding='utf-8')
c = Client(json.loads(Path('.local/coordinator.json').read_text(encoding='utf-8-sig')))
OUT = Path(sys.argv[2]); OUT.mkdir(parents=True, exist_ok=True)
ADB = r'C:\Users\WINDOWS11\Desktop\platform-tools\adb.exe'
verdicts = []


def run(payload, seconds):
    assert payload.get('execution_mode') != 'dispatch', 'harness never dispatches a tap'
    for _ in range(60):
        try:
            c.submit(payload); break
        except ValueError as error:
            if 'BUSY' not in str(error): raise
            time.sleep(1.5)
    t0 = time.time()
    r = None
    for _ in range(60):
        try:
            r = c.result(payload['instruction_id'], seconds=seconds); break
        except ValueError:
            time.sleep(1)
    wall = time.time() - t0
    rec = {}
    try:
        raw = subprocess.run([ADB, 'shell', 'run-as', 'com.bet365agent', 'cat', f"files/workflow/{(r or {}).get('run_id')}/result.json"],
                             capture_output=True, timeout=30).stdout
        rec = json.loads(raw.decode('utf-8'))
    except Exception:
        pass
    (OUT / f"{payload['instruction_id']}.json").write_text(json.dumps(dict(payload=payload, result=r, run=rec, wall=wall), indent=1, ensure_ascii=False), encoding='utf-8')
    return r or {}, rec, wall


def stage_names(rec):
    return [x['stage'] for x in (rec.get('stage_timings') or [])]


def verdict(tag, ok, note):
    verdicts.append((tag, ok))
    print(f"   => {'OK ' if ok else 'FAIL'} {tag}: {note}", flush=True)


for case in json.loads(sys.argv[1]):
    tag = case['tag'] + time.strftime('-%H%M%S')
    if case.get('mybets'):
        r, rec, wall = run(dict(instruction_id=tag, action='MY_BETS', adapter='live_bet365', scenario='live', view='OPEN', timeout_ms=120000), 150)
        print(f"[{tag}] MY_BETS {r.get('status')} {r.get('detail')} | home_verified={r.get('home_verified')} | {wall:.1f}s", flush=True)
        verdict(case['tag'], r.get('status') == 'PASS' and r.get('home_verified') is True, 'read + returned HOME (verified)')
        continue
    hold = dict(instruction_id=tag, action='ADAPTER_WORKFLOW', adapter='live_bet365', scenario='live', query=case['query'],
                sport='basketball', market=case['market'], side=case['side'], line=case['line'],
                minimum_price=case.get('minimum_price', '1.50'), stake='0.10', timeout_ms=240000, execution_mode='hold')
    if case.get('event_url'):
        hold['event_url'] = case['event_url']
    if case.get('kickoff_utc'):
        hold['kickoff_utc'] = case['kickoff_utc']
    if case.get('aliases'):
        hold['aliases'] = json.dumps(case['aliases'])
    r, rec, wall = run(hold, 280)
    sel = r.get('selection') or {}
    stages = stage_names(rec)
    searched = 'ENTER_QUERY' in stages
    print(f"[{tag}] HOLD {r.get('status')} {r.get('stage')} | {(r.get('detail') or '')[:110]} | route={r.get('route')} | "
          f"{r.get('fixture_name')} | {sel.get('side')} {sel.get('line')} @ {sel.get('price')} | searched={searched} | verdict={r.get('identity_verdict')} cand={json.dumps(r.get('alias_candidate'))[:90]} | "
          f"field={r.get('stake_field_state')} clear={json.dumps(r.get('stake_clear'))} | {wall:.1f}s", flush=True)
    expect = case.get('expect', 'PASS')
    if expect == 'PASS':
        ok = r.get('status') == 'PASS'
        if case.get('route'):
            ok = ok and r.get('route') == case['route']
        verdict(case['tag'], ok, f"expected PASS via {case.get('route', 'any route')}")
    else:
        ok = r.get('status') == 'FAIL' and r.get('stage') == expect
        if case.get('no_search'):
            ok = ok and not searched
        verdict(case['tag'], ok, f"expected {expect}{' without Search' if case.get('no_search') else ''}")
    if r.get('status') != 'PASS':
        run(dict(instruction_id='rs' + tag, action='RESET_BETSLIP', adapter='live_bet365', scenario='live', timeout_ms=60000), 90)
        continue
    base = dict(action='PLACE_HELD', adapter='live_bet365', scenario='live', sport='basketball', market=case['market'],
                side=case['side'], line=sel.get('line') or '', selection_name=sel.get('selection_name'), price=sel.get('price'),
                minimum_price=case.get('minimum_price', '1.50'), stake='0.10', execution_mode='prepare',
                confirmation_status='APPROVED', timeout_ms=60000)
    r3, rec3, wall3 = run(dict(base, instruction_id='pt' + tag), 90)
    pretap = (rec3.get('t_pretap_done_ms', 0) - rec3.get('t_start_ms', 0)) / 1000 if rec3.get('t_pretap_done_ms') else None
    print(f"   PRETAP {r3.get('status')} {r3.get('detail')} | phone check {pretap}s | {json.dumps(rec3.get('stake_check_pretap'))[:100]}", flush=True)
    verdict(case['tag'] + '/pretap', r3.get('status') == 'PASS', 'held slip pre-tap check (no tap)')
    r4, rec4, wall4 = run(dict(instruction_id='rs' + tag, action='RESET_BETSLIP', adapter='live_bet365', scenario='live', timeout_ms=60000), 90)
    print(f"   RESET {r4.get('status')} {json.dumps(rec4.get('betslip_reset'))[:120]}", flush=True)
print('SUMMARY', json.dumps(verdicts), flush=True)
print('ALL_OK' if all(ok for _, ok in verdicts) else 'SOME_FAILED', flush=True)
