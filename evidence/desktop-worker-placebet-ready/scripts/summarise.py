"""Per-run table + pass rate for a batch label (reads runs/<label>-*/result.json)."""
import json, sys
from pathlib import Path
RUNS = Path(__file__).resolve().parents[1] / 'runs'
rows = []
for d in sorted(RUNS.glob(sys.argv[1] + '-*')):
    r = json.loads((d / 'result.json').read_text(encoding='utf-8'))
    add = r.get('addbet') or {}
    cer = r.get('complete_execution_ready') or {}
    bs = r.get('betslip') or {}
    rows.append(dict(run=d.name, status=r['status'], stage=r['stage'], detail=r['detail'][:160], secs=round(r['duration_ms'] / 1000, 1),
                     fixture=r.get('fixture_name'), group=r.get('selection_group'),
                     addbet=None if not add else dict(cs=add.get('cs'), sr=add.get('sr'), accepted=add.get('accepted'), bets=len(add.get('bets') or [])),
                     betsweb_calls=[a['url'].rsplit('/', 1)[-1] for a in r.get('betslip_api') or []],
                     removed_before=(r.get('betslip_clear') or {}).get('removed'),
                     screen=dict(title=bs.get('title'), line=bs.get('handicap'), price=bs.get('price'), market=bs.get('market'),
                                 fixture=bs.get('fixture'), stake=bs.get('stake'), to_return=bs.get('to_return'),
                                 place_bet_enabled=(bs.get('place_bet') or {}).get('enabled'), notices=bs.get('notices')) if bs else None,
                     ready=dict(market=cer.get('market'), side=cer.get('selection_role'), line=cer.get('line'), price=cer.get('price'),
                                stake=cer.get('stake'), to_return=cer.get('to_return')) if cer else None,
                     rereads=len(r.get('readback_rereads') or []), wager_submitted=r.get('wager_submitted'),
                     place_bet_clicked=False))
n, ok = len(rows), sum(r['status'] == 'PASS' for r in rows)
out = dict(label=sys.argv[1], runs=n, passed=ok, pass_rate=f'{ok}/{n}', rows=rows)
(RUNS.parent / f'{sys.argv[1]}_summary.json').write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding='utf-8')
for r in rows:
    print(r['run'], r['status'], r['stage'], r['addbet'], r['betsweb_calls'], r['removed_before'], (r['ready'] or {}).get('price'), (r['screen'] or {}).get('to_return'), r['rereads'], r['group'])
print(out['pass_rate'])
