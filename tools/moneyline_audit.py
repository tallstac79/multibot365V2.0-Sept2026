"""Replay the frozen real feed, preserving raw rows and comparing all non-ML decisions.

Read-only to the operational databases. Does not create Pipeline objects, send
messages, arm execution or replay historical alerts into the live queue.
"""
from collections import Counter
import copy
from datetime import datetime
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sqlite3
import sys
import tempfile
import io
import zipfile
from core.alert_classifier import classify
from core.rules_engine import evaluate

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/moneyline-audit'
BASELINE_COMMIT='8b39fed'


def dump(path,value):
    path.write_text(json.dumps(value,indent=2,ensure_ascii=True)+'\n',encoding='utf-8')


def snapshot_tail():
    """Freeze arrivals during this audit against the committed pre-ML classifier."""
    dest = OUT/'postcutoff-baseline.json'
    if dest.exists():
        raise SystemExit('Tail snapshot already exists; refusing to overwrite evidence')
    baseline = json.loads(gzip.decompress((OUT/'baseline.json.gz').read_bytes()))
    seen = {r['id'] for r in baseline['rows']}
    with sqlite3.connect((ROOT/'.local/pipeline.sqlite3').resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = [dict(r) for r in db.execute('SELECT * FROM intake_messages ORDER BY id') if r['id'] not in seen]
    archive = subprocess.check_output(['git','archive','--format=zip',BASELINE_COMMIT,'core'],cwd=ROOT)
    with tempfile.TemporaryDirectory(prefix='ml-old-core-') as tmp:
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            assert all(n.startswith('core/') and '..' not in Path(n).parts for n in z.namelist())
            z.extractall(tmp)
        program = ('import sys,json; sys.path.insert(0,sys.argv[1]); '
                   'from core.alert_classifier import classify; rows=json.load(sys.stdin); '
                   'json.dump([classify(r["formatted_text"] or r["raw_text"], '
                   'channel_id=str(r["chat_id"]),message_id=str(r["message_id"]), '
                   'source_timestamp=r["source_timestamp"]) for r in rows],sys.stdout)')
        proc = subprocess.run([sys.executable,'-c',program,tmp],cwd=ROOT,
                              input=json.dumps(rows),capture_output=True,text=True,encoding='utf-8',check=True)
    for r, old in zip(rows,json.loads(proc.stdout)):
        r['baseline_classification'] = old
    from datetime import timezone
    dump(dest,dict(captured_at=datetime.now(timezone.utc).isoformat(),baseline_commit=BASELINE_COMMIT,rows=rows))
    print('Frozen additional records:',len(rows))


def report():
    source=OUT/'baseline.json.gz'
    data=json.loads(gzip.decompress(source.read_bytes()))
    tail_source=OUT/'postcutoff-baseline.json'
    tail=json.loads(tail_source.read_text(encoding='utf-8')) if tail_source.exists() else None
    if tail:
        data['rows'].extend(tail['rows'])
    # Load the pre-ML pure rules evaluator for exact non-ML comparison. Its line
    # dependencies are unchanged; the frozen old classification is the input.
    code=subprocess.run(['git','show',BASELINE_COMMIT+':core/rules_engine.py'],cwd=ROOT,check=True,capture_output=True).stdout.decode('utf-8')
    old_scope={'__name__':'moneyline_audit_baseline_rules'}
    exec(compile(code,'baseline_rules_engine.py','exec'),old_scope)
    rows,ml=[],[];classification_changes=[];rules_changes=[];counts=Counter();rules_counts=Counter()
    for r in data['rows']:
        v=classify(r['formatted_text'] or r['raw_text'],channel_id=str(r['chat_id']),message_id=str(r['message_id']),source_timestamp=r['source_timestamp'])
        p=v.get('parsed') or {};market=v.get('market') or p.get('market')
        d=evaluate(p,data['config'],instruction_id=f"audit-{r['id']}",received_at=r['received_at'],now=datetime.fromisoformat(r['received_at'])) if v['status']=='PARSED' else None
        counts[v['status']]+=1
        if d:rules_counts[d['decision']]+=1
        item=dict(intake_id=r['id'],message_id=r['message_id'],market=market,classification=v['status'],classification_reason=v['reason'],
                  target=p.get('target_side'),decision=d['decision'] if d else None,decision_reason=d['reason'] if d else None)
        rows.append(item)
        if market=='MONEYLINE':
            item=copy.deepcopy(item)
            item.update(fixture=p.get('fixture'),opening=(p.get('opening') or {}).get('quotes'),current=(p.get('pinnacle') or {}).get('quotes'),
                        bet365=(p.get('comparison') or {}).get('quotes'),sharp_signal=p.get('sharp_signal'),highlight=p.get('highlighted_side'),
                        feed_ev=p.get('feed_displayed_ev_percent'),selected_ev=p.get('displayed_ev_percent'),quality=p.get('bet_quality'),
                        alert_price=p.get('alert_price'),minimum_live_price=(d.get('instruction') or {}).get('minimum_price') if d else None)
            ml.append(item)
        else:
            old=copy.deepcopy(r['baseline_classification']);new=copy.deepcopy(v)
            old.pop('parser_version',None);new.pop('parser_version',None)
            if old!=new:classification_changes.append(r['id'])
            if d:
                old_d=old_scope['evaluate'](old['parsed'],data['config'],instruction_id=f"audit-{r['id']}",received_at=r['received_at'],now=datetime.fromisoformat(r['received_at']))
                new_d=copy.deepcopy(d);old_d.pop('engine',None);new_d.pop('engine',None)
                if old_d!=new_d:rules_changes.append(r['id'])
    summary=dict(captured_at=data['captured_at'],snapshot_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),baseline_commit=BASELINE_COMMIT,
                 final_cutoff=tail['captured_at'] if tail else data['captured_at'],
                 additional_rows=len(tail['rows']) if tail else 0,
                 additional_snapshot_sha256=hashlib.sha256(tail_source.read_bytes()).hexdigest() if tail else None,
                 total_rows=len(rows),classifications=dict(counts),rules_at_historical_receipt=dict(rules_counts),
                 moneyline_rows=len(ml),moneyline_fixtures=len({r['fixture'] for r in ml}),
                 moneyline_classifications=dict(Counter(r['classification'] for r in ml)),
                 moneyline_rules=dict(Counter(r['decision'] or r['classification'] for r in ml)),
                 moneyline_directions=dict(Counter(r['target'] or 'UNRESOLVED' for r in ml)),
                 opposing_highlights=sum(bool(r['target'] and r['highlight'] and r['target']!=r['highlight']) for r in ml),
                 same_side_value_signals=sum(r['quality']=='CLEAR_VALUE_SIGNAL' for r in ml),
                 non_ml_classification_changes=classification_changes,non_ml_rules_changes=rules_changes,
                 source_documents=['https://oddsnotifier.io/en/blog/oddsnotifier-setup-guide'],
                 limits='Rows include repeated alerts and edits; historical eligibility is not execution, profit or retention of fresh live quotes. No equal/no-movement full pair occurs in the frozen ML sample; that boundary is tested by explicit mutations of a real row.')
    dump(OUT/'corpus-replay.json',rows);dump(OUT/'moneyline-results.json',ml);dump(OUT/'summary.json',summary)
    assert not classification_changes and not rules_changes,'Spread/Totals or other non-ML behavior changed'
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    if '--snapshot-tail' in sys.argv:snapshot_tail()
    report()
