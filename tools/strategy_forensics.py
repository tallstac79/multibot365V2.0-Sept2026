"""Read-only, reproducible strategy audit. Never creates a Pipeline or contacts a phone.

snapshot freezes ALL intake deliveries and the old classification/rules results before
production edits. report compares that immutable snapshot with the current pure code.
An independent raw-field extractor supplies the movement hypothesis, including records
the production parser rejects. Neither arrows nor Bet365 offers select its candidate.
"""
import argparse
from collections import Counter
import csv
import copy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import gzip
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import io
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'evidence/strategy-audit'
NUM = r'[+-]?\d+(?:\.\d+)?'


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')


def ro(path):
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    return db


def classify_record(r, config):
    from core.alert_classifier import classify
    from core.rules_engine import evaluate
    v = classify(r['formatted_text'] or r['raw_text'], channel_id=str(r['chat_id']),
                 message_id=str(r['message_id']), source_timestamp=r['source_timestamp'])
    d = None
    if v['status'] == 'PARSED':
        d = evaluate(v['parsed'], config, instruction_id=f"audit-{r['id']}",
                     received_at=r['received_at'], now=datetime.fromisoformat(r['received_at']))
    return dict(classification=v, rules=d)


def extract(text):
    """Independent two-sided raw grammar. Missing fields remain null; no line repair."""
    plain = (text or '').replace('**', '').replace('\ufe0f', '')
    sport = re.search(r'(Basketball|Football) - ([^\n]+)', plain)
    fixture = re.search(r'(?:\[)?([^\n\[\]]+ vs [^\n\[\]]+)(?:\]|\n)', plain)
    market = re.search(r'^\s*(Spread|Totals?) \((' + NUM + r')(?:\s*(?:->|→)\s*(' + NUM + r'))?\)', plain, re.M)
    opening = re.search(r'Opening \((' + NUM + r')\)', plain)
    opening_anchor = re.search(r'Opening\b(?:\s*\([^)]*\))?', plain)
    event_date = re.search(r'\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}', plain)
    book = re.search(r'Bet365 \((Spread|Totals?) (' + NUM + r')\)', plain)
    ev = re.search(r'EV:\s*([^\n]+)', plain)
    def quotes(start, raw=False):
        part = (text if raw else plain)[start:]
        match = re.search(r'(?m)^\s*(\*\*)?(\d+\.\d+)(\*\*)?([⬇⬆↓↑]️?)?(?:\s*\((\d+\.\d+)\))?\s+-\s+(\*\*)?(\d+\.\d+)(\*\*)?([⬇⬆↓↑]️?)?(?:\s*\((\d+\.\d+)\))?', part)
        if not match:
            return []
        return [dict(price=match[2], arrow=match[4], parenthetical=match[5], highlighted=bool(match[1])),
                dict(price=match[7], arrow=match[9], parenthetical=match[10], highlighted=bool(match[6]))]
    raw_book = re.search(r'Bet365', text or '')
    result = dict(sport=sport[1].lower() if sport else None, competition=sport[2] if sport else None,
                  fixture=fixture[1].strip() if fixture else None,
                  market=('SPREAD' if market[1] == 'Spread' else 'TOTALS') if market else
                  ('MONEYLINE' if sport and sport[1]=='Basketball' else '1X2') if 'market=ML' in plain else None,
                  opening_line=opening[1] if opening else None,
                  previous_line=market[2] if market and market[3] else None,
                  current_line=(market[3] or market[2]) if market else None,
                  book_line=book[2] if book else None,
                  pinnacle_quotes=quotes(market.end()) if market else quotes(event_date.end()) if event_date else [],
                  opening_quotes=quotes(opening_anchor.end()) if opening_anchor else [],
                  book_quotes=quotes(raw_book.end(), True) if raw_book else [],
                  ev=ev[1].strip() if ev else None)
    sides = ('HOME', 'AWAY') if result['market'] == 'SPREAD' and result['sport']=='basketball' else \
            ('OVER', 'UNDER') if result['market']=='TOTALS' and result['sport']=='basketball' else \
            ('UNVERIFIED_POSITION_1','UNVERIFIED_POSITION_2')
    highlights = [sides[i] for i, q in enumerate(result['book_quotes']) if q['highlighted']]
    result['highlight'] = highlights[0] if len(highlights) == 1 else None
    result['highlight_count'] = len(highlights)
    return result


def hypothesis(f):
    o, c, b = f['opening_line'], f['current_line'], f['book_line']
    out = dict(sharp_side=None, movement=None, magnitude=None, direction=None,
               signal='insufficient_data', offer='insufficient_data', ambiguity=None,
               sharp_line=None, sharp_price=None, opposite_line=None, opposite_price=None,
               advantage=None, equal=None, highlighted_agrees=None, recent_reversal=False)
    if f['sport'] != 'basketball' or f['market'] not in ('SPREAD', 'TOTALS') or o is None or c is None:
        out['ambiguity'] = 'Missing opening/current line or unverified market/quote mapping'
        return out
    delta = Decimal(c) - Decimal(o)
    out.update(movement=str(delta), magnitude=str(abs(delta)), direction='UP' if delta > 0 else 'DOWN' if delta < 0 else 'UNCHANGED')
    if delta == 0:
        out.update(signal='no_movement', ambiguity='Unchanged opening/current line; price-only strategy not established')
        return out
    side = ('HOME' if delta < 0 else 'AWAY') if f['market'] == 'SPREAD' else ('OVER' if delta > 0 else 'UNDER')
    out.update(sharp_side=side, signal='clear_sharp_side_signal')
    if f['previous_line'] is not None:
        out['recent_reversal'] = (Decimal(c)-Decimal(f['previous_line'])) * delta < 0
    if f['highlight']:
        out['highlighted_agrees'] = f['highlight'] == side
    if b is None or len(f['book_quotes']) != 2 or len(f['pinnacle_quotes']) != 2:
        out['ambiguity'] = 'Bet365 or Pinnacle quotes incomplete'
        return out
    idx = 0 if side in ('HOME', 'OVER') else 1
    spread = f['market'] == 'SPREAD'
    bl = Decimal(b) * (-1 if spread and idx else 1)
    pl = Decimal(c) * (-1 if spread and idx else 1)
    adv = bl-pl if spread or side == 'UNDER' else pl-bl
    out.update(sharp_line=str(bl), sharp_price=f['book_quotes'][idx]['price'],
               opposite_line=str(-bl) if spread else str(bl), opposite_price=f['book_quotes'][1-idx]['price'],
               advantage=str(adv), equal=adv == 0)
    if spread and Decimal(b)*Decimal(c)<0:
        out.update(offer='ambiguous', ambiguity='Cross-book favourite disagreement; Bet365 orientation needs verification')
    elif adv < 0:
        out['offer'] = 'moved_too_far'
    elif adv > 0:
        out['offer'] = 'favourable_line_unpriced'
    elif out['highlighted_agrees'] is True and f['ev'] and re.fullmatch(NUM+'%', f['ev']) and Decimal(f['ev'][:-1])>100 and Decimal(out['sharp_price'])>Decimal(f['pinnacle_quotes'][idx]['price']):
        out['offer'] = 'equal_line_supplied_edge'
    else:
        out.update(offer='no_proven_same_side_value', ambiguity='No supplied equal-line EV bound to the sharp side')
    return out


def snapshot():
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / 'baseline.json'
    if dest.exists() or dest.with_suffix('.json.gz').exists():
        raise SystemExit('Snapshot exists; refusing to overwrite old production evidence')
    with ro(ROOT / '.local/dashboard.sqlite3') as db:
        config = json.loads(db.execute('SELECT payload FROM config').fetchone()[0])
    with ro(ROOT / '.local/pipeline.sqlite3') as db:
        db.execute('BEGIN')
        rows = [dict(r) for r in db.execute('SELECT * FROM intake_messages ORDER BY id')]
        instructions = {r['intake_id']:dict(r) for r in db.execute('SELECT intake_id,instruction_id,state,selection,line,rules_result FROM instructions')}
        safety = [dict(r) for r in db.execute("SELECT * FROM controls WHERE key IN ('paused','final_action_one_shot','held_slip')")]
    for r in rows:
        r['old'] = classify_record(r, config)
        r['stored_instruction'] = instructions.get(r['id'])
    data = dict(captured_at=datetime.now(timezone.utc).isoformat(),
                git_head=subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip(),
                config=config, safety=safety, rows=rows)
    dump(dest, data)
    print('Frozen',len(rows),'deliveries at',data['captured_at'])


def snapshot_tail():
    """Freeze later arrivals with the OLD committed core, not the edited working tree."""
    dest = OUT/'postcutoff-baseline.json'
    if dest.exists():
        raise SystemExit('Tail snapshot exists; refusing to overwrite')
    data = json.loads(gzip.decompress((OUT/'baseline.json.gz').read_bytes()))
    seen = {r['id'] for r in data['rows']}
    with ro(ROOT/'.local/pipeline.sqlite3') as db:
        db.execute('BEGIN')
        rows = [dict(r) for r in db.execute('SELECT * FROM intake_messages ORDER BY id') if r['id'] not in seen]
        instructions = {r['intake_id']:dict(r) for r in db.execute('SELECT intake_id,instruction_id,state,selection,line,rules_result FROM instructions')}
    archive = subprocess.check_output(['git','archive','--format=zip',data['git_head'],'core'],cwd=ROOT)
    with tempfile.TemporaryDirectory(prefix='strategy-old-core-') as tmp:
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            for name in z.namelist():
                if not name.startswith('core/') or '..' in Path(name).parts:
                    raise ValueError('Unexpected archive path')
            z.extractall(tmp)
        program = ('import sys,json; sys.path.insert(0,sys.argv[1]); '
                   'from tools.strategy_forensics import classify_record; '
                   'd=json.load(sys.stdin); '
                   'json.dump([classify_record(r,d["config"]) for r in d["rows"]],sys.stdout)')
        proc = subprocess.run([sys.executable,'-c',program,tmp],cwd=ROOT,
                              input=json.dumps(dict(config=data['config'],rows=rows)),
                              capture_output=True,text=True,encoding='utf-8',check=True)
        old = json.loads(proc.stdout)
    for r,result in zip(rows,old):
        r['old']=result;r['stored_instruction']=instructions.get(r['id'])
    dump(dest,dict(captured_at=datetime.now(timezone.utc).isoformat(),git_head=data['git_head'],rows=rows))
    print('Frozen',len(rows),'later arrivals using archived old core',data['git_head'])


def report():
    baseline = OUT/'baseline.json'
    raw = baseline.read_bytes() if baseline.exists() else gzip.decompress(baseline.with_suffix('.json.gz').read_bytes())
    data = json.loads(raw)
    records, counts, oldcounts, newcounts, changed = [], Counter(), Counter(), Counter(), []
    diagnostic_counts, strategy_counts = Counter(), Counter()
    diagnostic_config = copy.deepcopy(data['config'])
    diagnostic_config['global']['min_sharp_movement'] = 0 # RESEARCH scenario only; never saved to live config
    supplemental = json.loads((OUT/'supplemental-baseline.json').read_text(encoding='utf-8')) if (OUT/'supplemental-baseline.json').exists() else []
    tail = json.loads((OUT/'postcutoff-baseline.json').read_text(encoding='utf-8')) if (OUT/'postcutoff-baseline.json').exists() else {}
    for r in data['rows'] + tail.get('rows',[]) + supplemental:
        old = r['old']; new = classify_record(r,data['config'])
        diagnostic = classify_record(r,diagnostic_config)
        f = extract(r['formatted_text'] or r['raw_text']); h = hypothesis(f)
        op = old['classification'].get('parsed') or {}; np = new['classification'].get('parsed') or {}
        od = (old.get('rules') or {}).get('decision', old['classification']['status'])
        nd = (new.get('rules') or {}).get('decision', new['classification']['status'])
        dd = (diagnostic.get('rules') or {}).get('decision', diagnostic['classification']['status'])
        # Content-suppressed alerts have DISTINCT source message IDs and can carry
        # different movement evidence. Include them in a full-corpus strategy audit.
        eligible = old['classification']['status'] != 'IGNORED'
        strategy_decision = 'NO BET' if nd == 'REJECT' and (new.get('rules') or {}).get('reason','').startswith('bet_quality:') else nd
        same = op.get('target_side') == h['sharp_side'] if h['sharp_side'] and op.get('target_side') else None
        row = dict(alert_id=r['id'], channel_id=r['chat_id'], message_id=r['message_id'], received_at=r['received_at'],
                   source_timestamp=r['source_timestamp'], stored_status=r['status'], duplicate_of=r['duplicate_of'], in_analysis=eligible,
                   sport=f['sport'],competition=f['competition'],fixture=f['fixture'],market=f['market'],
                   pinnacle_opening_line=f['opening_line'],pinnacle_current_line=f['current_line'],pinnacle_previous_line=f['previous_line'],
                   pinnacle_opening_prices=json.dumps(f['opening_quotes']),pinnacle_current_prices=json.dumps(f['pinnacle_quotes']),
                   movement_magnitude=h['magnitude'],movement_direction=h['direction'],inferred_sharp_side=h['sharp_side'],
                   bet365_sharp_line=h['sharp_line'],bet365_sharp_price=h['sharp_price'],
                   bet365_opposite_line=h['opposite_line'],bet365_opposite_price=h['opposite_price'],
                   oddsnotifier_highlighted_side=f['highlight'],supplied_ev=f['ev'],equal_line=h['equal'],line_advantage=h['advantage'],
                   current_production_interpretation=op.get('target_side'),current_production_decision=od,
                   stored_production_decision=(r.get('stored_instruction') or {}).get('state'),
                   agrees_with_sharp_strategy=same,confidence='HIGH_DIRECTION_ONLY' if h['sharp_side'] else 'INSUFFICIENT',
                   ambiguity_reason=h['ambiguity'],signal=h['signal'],offer_assessment=h['offer'],recent_reversal=h['recent_reversal'],
                   new_side=np.get('target_side'),new_decision=nd,new_reason=(new.get('rules') or new['classification']).get('reason'),
                   new_strategy_decision=strategy_decision,diagnostic_min_movement_zero_decision=dd,
                   diagnostic_reason=(diagnostic.get('rules') or diagnostic['classification']).get('reason'),
                   raw_sha256=hashlib.sha256((r['formatted_text'] or r['raw_text'] or '').encode()).hexdigest())
        records.append(row)
        if not eligible:continue
        counts[h['signal']]+=1;counts['offer_'+h['offer']]+=1
        if h['equal'] is not None:counts['equal_line' if h['equal'] else 'unequal_line']+=1
        if same is False:counts['old_side_contradicts_opening_movement']+=1
        if h['highlighted_agrees'] is False:counts['highlight_contradicts_opening_movement']+=1
        if h['recent_reversal']:counts['recent_reversal']+=1
        oldcounts[od]+=1;newcounts[nd]+=1
        diagnostic_counts[dd]+=1;strategy_counts[strategy_decision]+=1
        if op.get('target_side') != np.get('target_side'):changed.append(row)
    for filename,rows in [('strategy-forensics.csv',records),('changed-sides.csv',changed)]:
        with (OUT/filename).open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(records[0]));writer.writeheader();writer.writerows(rows)
    summary=dict(captured_at=data['captured_at'],baseline_commit=data['git_head'],deliveries=len(records),
                 analyzed=sum(r['in_analysis'] for r in records),duplicates=sum(r['stored_status']=='DUPLICATE' for r in records),
                 counts=dict(counts),old=dict(oldcounts),new=dict(newcounts),selected_side_changed=len(changed))
    summary.update(strategy_outcomes=dict(strategy_counts),diagnostic_min_movement_zero=dict(diagnostic_counts),
                   final_capture_at=tail.get('captured_at',data['captured_at']),later_arrivals=len(tail.get('rows',[])),
                   diagnostic_warning='Counterfactual, unapproved policy: any nonzero net move, inherited 1-point advantage, no price bounds. No live configuration changed.',
                   duplicates_note=f"{summary['duplicates']} stored content-suppressed alerts are included because they have distinct Telegram message IDs.")
    dump(OUT/'summary.json',summary)
    print(json.dumps(summary,indent=2))


if __name__ == '__main__':
    ap=argparse.ArgumentParser();ap.add_argument('command',choices=['snapshot','snapshot_tail','report']);args=ap.parse_args()
    {'snapshot':snapshot,'snapshot_tail':snapshot_tail,'report':report}[args.command]()
