"""OCR benchmark harness (Milestone C1/C4). Runs OCR_BENCH on the phone over a labelled corpus of REAL stored
frames and scores the parsers' output against the truth. No screen interaction, no taps. From the repo root:

    PYTHONPATH=. python tools/ocr_bench.py <engine> <out.json> [max_per_class]      engine = legacy | fast | hybrid
"""
import base64
import hashlib
import json
import re
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

from core import bet_matching
from tools.coordinator_client import Client


# Hand-labelled full grids from screenshots inspected during the proofs (fixture key -> expected cells).
GRIDS = {
    'Hapoel Tel Aviv|Bayern Munich': ['SPREAD/HOME/-8.0@1.83', 'SPREAD/AWAY/+8.0@1.83', 'TOTAL/OVER/173.5@1.83', 'TOTAL/UNDER/173.5@1.83', 'MONEYLINE/HOME/NONE@1.23', 'MONEYLINE/AWAY/NONE@3.75'],
    'Crvena Zvezda|Zalgiris': ['SPREAD/HOME/-2.5@1.86', 'SPREAD/AWAY/+2.5@1.79', 'TOTAL/OVER/168.5@1.83', 'TOTAL/UNDER/168.5@1.83', 'MONEYLINE/HOME/NONE@1.68', 'MONEYLINE/AWAY/NONE@2.05'],
    'Hapoel Jerusalem|Bnei Herzliya': ['SPREAD/HOME/-9.5@1.83', 'SPREAD/AWAY/+9.5@1.83', 'TOTAL/OVER/177.5@1.83', 'TOTAL/UNDER/177.5@1.83', 'MONEYLINE/HOME/NONE@1.20', 'MONEYLINE/AWAY/NONE@4.20'],
    'Kyoto Hannaryz|Shiga Lakes': ['SPREAD/HOME/-4.5@1.83', 'SPREAD/AWAY/+4.5@1.83', 'TOTAL/OVER/167.5@1.83', 'TOTAL/UNDER/167.5@1.83', 'MONEYLINE/HOME/NONE@1.47', 'MONEYLINE/AWAY/NONE@2.55'],
    'Berck/Rang du Fliers|Pays Salonais Basket 13': ['SPREAD/HOME/-3.5@1.83', 'SPREAD/AWAY/+3.5@1.83', 'TOTAL/OVER/156.5@1.83', 'TOTAL/UNDER/156.5@1.83'],
    'Saga Ballooners|Hiroshima Dragonflies': ['SPREAD/HOME/-2.5@1.83', 'SPREAD/AWAY/+2.5@1.83', 'TOTAL/OVER/164.5@1.83', 'TOTAL/UNDER/164.5@1.83', 'MONEYLINE/HOME/NONE@1.64', 'MONEYLINE/AWAY/NONE@2.12'],
    'Sopron KC|DEAC Debreceni': ['SPREAD/HOME/-1.5@1.83', 'SPREAD/AWAY/+1.5@1.83', 'TOTAL/OVER/162.5@1.83', 'TOTAL/UNDER/162.5@1.83', 'MONEYLINE/HOME/NONE@1.74', 'MONEYLINE/AWAY/NONE@1.95'],
}
# Truth read off the stored receipt frames by eye. The second receipt shows "YT6334352221W"; the legacy engine's
# full-page read (and so the Telegram receipt message for on-d875519f) had reported it as "W6334352221W".
RECEIPTS = {'c_VcSepTjgrzTEUlRLkSa30vA7OcbYKXfEmicyRH7KlGg': ('HT5515901931W', '0.10', '0.18'),
            'c_rQ0--hlgGOHakkcsYLk4GKy0IkFyO1duB8b7mgQhmnw': ('YT6334352221W', '0.10', '0.18')}
SOURCES = ('milestone-a', 'milestone-b', 'fast-070', 'live-', 'prepare-0641', 'betslip-proof-0631', 'search-kyoto')
# Frames inspected by eye: event page not rendered yet (only the bet365 chrome) -> the parser must return nothing.
BLANK_HEADERS = {'c_E2NGT17c3hdDd8QpbiaDijERLlq4RMiZfaQk4pS2Z84/s013_event.png',
                 'c_ownIw8aeWslzGT1SMJWwqsQkBClYS5B06CsMZYK1hy4/s001_event_direct.png',
                 'c_cW8IG-Vgm6WdmLHKeYin8C8w161xPvDdxXZA2aqzRzo/s001_event_direct.png'}
# Place Bet spinner still showing (receipt not rendered yet) -> classifier must NOT say PLACED.
PENDING_RECEIPTS = {'c_rQ0--hlgGOHakkcsYLk4GKy0IkFyO1duB8b7mgQhmnw/s002_place_bet_after.png',
                    'c_VcSepTjgrzTEUlRLkSa30vA7OcbYKXfEmicyRH7KlGg/s029_place_bet_after.png'}
ADB = r'C:\Users\WINDOWS11\Desktop\platform-tools\adb.exe'


def phone_frames():
    """Every stored frame on the phone (files/visual/<run>/<name>.png), so the corpus only lists frames that exist."""
    import subprocess
    out = subprocess.run([ADB, 'shell', 'run-as', 'com.bet365agent', 'find', 'files/visual', '-name', '*.png'],
                         capture_output=True, timeout=120).stdout.decode('utf-8', 'replace')
    return {line.strip().replace('files/visual/', '') for line in out.splitlines() if line.strip()}


def run_id(device_id):
    return 'c_' + base64.urlsafe_b64encode(hashlib.sha256(device_id.encode()).digest()).decode().rstrip('=')


def corpus():
    frames = []
    seen = set()
    for f in sorted(Path('evidence').rglob('*.json')):
        src = f.as_posix().split('evidence/')[-1]
        if not src.startswith(SOURCES) or 'runs_manifest' in src:
            continue
        try:
            d = json.load(open(f, encoding='utf-8'))
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        run = d.get('run') if isinstance(d.get('run'), dict) else (d if 'screenshots' in d else None)
        res = d.get('result') if isinstance(d.get('result'), dict) else {}
        if not run or not run.get('run_id') or run['run_id'] in seen:
            continue
        seen.add(run['run_id'])
        rid = run['run_id']
        vf = run.get('verified_fixture') or {}
        home, away = vf.get('home') or res.get('home'), vf.get('away') or res.get('away')
        sel = res.get('selection') or run.get('selection') or {}
        for name in run.get('screenshots', []):
            spec = None
            if re.search(r'markets|selection_preflight', name) and home and away:
                spec = dict(c='grid', home=home, away=away, key=f'{home}|{away}', target=(f"{sel['market']}/{sel['side']}/{sel['line']}@{sel['price']}" if sel.get('price') and sel.get('market') else None))
            elif re.search(r'event_direct|_event\.png', name) and (home or run.get('direct_event_closed')):
                spec = dict(c='header', home=home, away=away, kickoff=run.get('kickoff_verified'), closed=bool(run.get('direct_event_closed')),
                            blank=f'{rid}/{name}' in BLANK_HEADERS)
            elif re.search(r'_final\.png|pretap\.png|betslip_stake|complete_execution_pre|place_bet_pre_dispatch', name) and sel.get('price'):
                spec = dict(c='slip', stake='0.10', price=sel['price'], market=sel['market'], side=sel['side'], name=sel.get('selection_name', ''), line=sel.get('line', ''))
            elif re.search(r'stake_ui\.png', name):
                spec = dict(c='keypad', field='EMPTY')
            elif re.search(r'stake_typed\.png', name) and sel.get('price'):
                # keypad digits are greyed out once a stake is typed; the live check here is the strict readback
                spec = dict(c='keypad', field='FILLED', stake='0.10', price=sel['price'])
            elif 'place_bet_after' in name and rid in RECEIPTS:
                spec = dict(c='receipt', ref=RECEIPTS[rid][0], stake=RECEIPTS[rid][1], ret=RECEIPTS[rid][2], pending=f'{rid}/{name}' in PENDING_RECEIPTS)
            if spec:
                spec['p'] = f'{rid}/{name}'
                frames.append(spec)
    # My Bets frames from the live reconciliation runs (truth = the bet each verified); scored per run, the way the
    # live matcher sees them (all scrolled frames together), and only runs whose frames are still on the phone.
    db = sqlite3.connect('.local/pipeline.sqlite3'); db.row_factory = sqlite3.Row
    runs = 0
    for r in db.execute("SELECT r.device_instruction_id, b.*, i.home, i.away FROM reconciliations r JOIN bets b USING(instruction_id) "
                        "JOIN instructions i USING(instruction_id) WHERE r.outcome='FOUND' ORDER BY r.completed_at DESC"):
        rid = run_id(r['device_instruction_id'])
        names = sorted(p.split('/')[1] for p in PHONE_FRAMES if p.startswith(rid + '/') and re.search(r'my_bets_\d\.png$', p))
        if not names or runs >= 4:
            continue
        runs += 1
        for n, name in enumerate(names):
            frames.append(dict(c='mybets', p=f'{rid}/{name}', group=rid, n=n,
                               bet=dict(home=r['home'], away=r['away'], market=r['market'], selection=r['selection'], line=r['line'], stake=r['stake'], odds=r['odds'])))
    per = defaultdict(int); picked = []
    for fr in frames:
        if fr['p'] not in PHONE_FRAMES:
            continue
        if fr['c'] == 'mybets' or per[fr['c']] < MAX:
            per[fr['c']] += 1; picked.append(fr)
    return picked


def score(fr, out):
    """(ok, critical_errors list, note)"""
    if out.get('error'):
        return False, ['no_read:' + out['error']], out['error']
    p = out.get('parsed') or {}
    cls = fr['c']; errs = []
    if cls == 'grid':
        cells = set(p.get('cells') or [])
        truth = set(GRIDS.get(fr['key'], []))
        if fr.get('target') and fr['target'] not in cells: errs.append('target_cell_missing')
        by_side = {c.rsplit('@', 1)[0].rsplit('/', 1)[0]: c for c in cells}
        for t in truth:
            key = t.rsplit('@', 1)[0].rsplit('/', 1)[0]
            got = by_side.get(key)
            if got is None: errs.append('labelled_cell_missing')
            if got and got != t:
                tl, tp = t.rsplit('@', 1)[0].rsplit('/', 1)[1], t.rsplit('@', 1)[1]
                gl, gp = got.rsplit('@', 1)[0].rsplit('/', 1)[1], got.rsplit('@', 1)[1]
                if tl != gl: errs.append('wrong_sign' if tl.lstrip('+-') == gl.lstrip('+-') else 'wrong_line')
                if tp != gp: errs.append('wrong_price')
        if len(by_side) != len(cells): errs.append('conflicting_cells_for_side')
        over = [c for c in cells if c.startswith('TOTAL/OVER')]; under = [c for c in cells if c.startswith('TOTAL/UNDER')]
        if over and under and over[0].split('/')[2].split('@')[0] != under[0].split('/')[2].split('@')[0]: errs.append('over_under_inconsistent')
        ok = not errs and (fr.get('target') is None or fr['target'] in cells)
        return ok, errs, f"{len(cells)} cells {p.get('notes')}"
    if cls == 'slip':
        if not p.get('stake_ok'): errs.append('stake_or_return_unread')
        if not p.get('line_shown'): errs.append('line_not_shown')
        if not p.get('price_shown'): errs.append('price_not_shown')
        return not errs, errs, p.get('stake_detail', '')
    if cls == 'keypad':
        if fr.get('stake'):
            if not p.get('stake_ok'): errs.append('stake_readback_failed')
        elif not p.get('keypad'): errs.append('keypad_not_located')
        if p.get('field_state') != fr['field']: errs.append(f"field_state_{p.get('field_state')}")
        return not errs, errs, p.get('stake_detail', '')
    if cls == 'receipt':
        if fr.get('pending'):
            return p.get('outcome') != 'PLACED', [] if p.get('outcome') != 'PLACED' else ['false_placed_on_spinner'], f"pending -> {p.get('outcome')}"
        if p.get('outcome') != 'PLACED': errs.append('receipt_not_recognised')
        if p.get('bet_reference') != fr['ref']: errs.append('wrong_bet_reference')
        if p.get('stake') != fr['stake']: errs.append('wrong_stake')
        if p.get('return') != fr['ret']: errs.append('wrong_to_return')
        return not errs, errs, f"{p.get('bet_reference')} {p.get('stake')} {p.get('return')}"
    if cls == 'header':
        if fr.get('blank'):
            ok = p.get('home') is None and p.get('away') is None
            return ok, [] if ok else ['phantom_team_on_blank_page'], f"blank -> {p.get('home')} v {p.get('away')}"
        if fr.get('closed'):
            return bool(p.get('closed')), [] if p.get('closed') else ['closed_page_not_recognised'], ''
        from core import bet_matching as _bm  # noqa
        norm = lambda x: re.sub(r'[^a-z0-9]', '', (x or '').lower())
        if norm(p.get('home')) != norm(fr['home']): errs.append('wrong_home')
        if norm(p.get('away')) != norm(fr['away']): errs.append('wrong_away')
        if fr.get('kickoff') and re.match(r'\d+ \w+ \d\d:\d\d', str(fr['kickoff'])) and p.get('kickoff') != fr['kickoff']: errs.append('wrong_kickoff')
        return not errs, errs, f"{p.get('home')} v {p.get('away')} {p.get('kickoff')}"
    if cls == 'mybets':
        lines = p.get('lines') or []
        return bool(lines), [] if lines else ['no_lines'], f'{len(lines)} lines'
    return True, [], ''


def score_mybets_runs(frames, results):
    """Per-run My Bets verdict: all scrolled frames of a run together, exactly as the live matcher sees them."""
    rows = []
    by_group = defaultdict(list)
    for fr, res in zip(frames, results):
        if fr['c'] == 'mybets': by_group[fr['group']].append((fr, res))
    for group, items in by_group.items():
        lines = []
        for fr, res in sorted(items, key=lambda x: x[0]['n']):
            for l in ((res.get('parsed') or {}).get('lines') or []): lines.append(dict(l, frame=fr['n']))
        lat = [res['latency_ms'] for _, res in items if res.get('latency_ms') is not None]
        try:
            m = bet_matching.match(dict(items[0][0]['bet']), {'view': 'OPEN', 'lines': lines})
            ok, errs, note = bool(m['found']), [] if m['found'] else ['bet_not_found'], m['confidence']
        except ValueError as e:
            ok, errs, note = False, ['view_unconfirmed'], str(e)
        rows.append(dict(frame=group, cls='mybets_run', ok=ok, errors=errs, latency_ms=sum(lat) if lat else None, words=None, note=note, parsed=None, text=None))
    return rows


def align_batch(frames, response):
    """Preserve every requested frame; a failed/truncated batch cannot shrink the denominator."""
    response = response or {}
    outputs = (response.get('bench') or {}).get('frames') or []
    if response.get('status') != 'PASS':
        return [dict(error='batch_failed:' + str(response.get('detail', response.get('status')))) for _ in frames]
    expected = {fr['p'] for fr in frames}
    if len(outputs) != len(frames) or {out.get('p') for out in outputs} != expected:
        return [dict(error='batch_frame_set_mismatch') for _ in frames]
    by_path = {out['p']: out for out in outputs}
    return [by_path[fr['p']] if by_path[fr['p']].get('c') == fr['c']
            else dict(error='batch_frame_class_mismatch') for fr in frames]


def main():
    global ENGINE, OUT, MAX, c, PHONE_FRAMES
    sys.stdout.reconfigure(encoding='utf-8')
    ENGINE, OUT = sys.argv[1], Path(sys.argv[2])
    MAX = int(sys.argv[3]) if len(sys.argv) > 3 else 14
    c = Client(json.loads(Path('.local/coordinator.json').read_text(encoding='utf-8-sig')))
    PHONE_FRAMES = phone_frames()
    frames = corpus()
    print(f'corpus: {len(frames)} frames', dict((k, sum(1 for f in frames if f["c"] == k)) for k in ('grid', 'header', 'slip', 'keypad', 'receipt', 'mybets')), flush=True)
    results = []
    batch, batches = [], []
    for fr in frames:
        batch.append(fr)
        if len(json.dumps(batch)) > 2600 or len(batch) >= 10:
            batches.append(batch); batch = []
    if batch: batches.append(batch)
    for n, b in enumerate(batches, 1):
        iid = f'bench-{ENGINE}-{int(time.time())}-{n}'
        spec = [{k: v for k, v in fr.items() if k not in ('key', 'target', 'field', 'ref', 'ret', 'bet', 'closed', 'kickoff', 'blank', 'pending', 'group', 'n')} for fr in b]
        payload = dict(instruction_id=iid, action='OCR_BENCH', adapter='live_bet365', scenario='live', frames=json.dumps(spec), engine=ENGINE, timeout_ms=240000)
        for _ in range(60):
            try:
                c.submit(payload); break
            except ValueError as e:
                if 'BUSY' not in str(e): raise
                time.sleep(1.5)
        r = None
        for _ in range(60):
            try:
                r = c.result(iid, seconds=260); break
            except ValueError:
                time.sleep(1)
        outs = align_batch(b, r)
        for fr, out in zip(b, outs):
            ok, errs, note = score(fr, out)
            results.append(dict(frame=fr['p'], cls=fr['c'], ok=ok, errors=errs, latency_ms=out.get('latency_ms'), words=out.get('word_count'), note=note, parsed=out.get('parsed'), text=out.get('text')))
        print(f'batch {n}/{len(batches)} done ({sum(1 for x in results if x["ok"])}/{len(results)} ok)', flush=True)
    results += score_mybets_runs(frames, results)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(dict(engine=ENGINE, results=results), indent=1, ensure_ascii=False), encoding='utf-8')
    print(f'\nENGINE {ENGINE}')
    print(f"{'class':10s} {'n':>3s} {'ok':>4s} {'acc':>6s} {'lat_mean':>9s} {'lat_med':>8s}  critical errors")
    crit = defaultdict(lambda: defaultdict(int))
    for cls in ('grid', 'header', 'slip', 'keypad', 'receipt', 'mybets', 'mybets_run'):
        rows = [x for x in results if x['cls'] == cls]
        if not rows: continue
        lat = [x['latency_ms'] for x in rows if x['latency_ms'] is not None]
        for x in rows:
            for e in x['errors']: crit[cls][e] += 1
        print(f"{cls:10s} {len(rows):3d} {sum(1 for x in rows if x['ok']):4d} {100 * sum(1 for x in rows if x['ok']) / len(rows):5.0f}% {mean(lat) if lat else 0:8.0f}ms {median(lat) if lat else 0:7.0f}ms  {dict(crit[cls])}")
    print('BENCH DONE', flush=True)
    return 0 if frames and len(results) >= len(frames) and all(row['ok'] for row in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
