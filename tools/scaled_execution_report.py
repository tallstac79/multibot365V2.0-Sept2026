"""Freeze current quote evidence and compare the approved execution policy, read-only.

Re-running uses the frozen input. Totals candidates are research scenarios, never
saved execution settings. The report does not submit any phone instructions.
"""
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
from core.execution_terms import compare

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'evidence/execution-policy-v2'


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + '\n', encoding='utf-8')


def snapshot():
    with sqlite3.connect((ROOT/'.local/pipeline.sqlite3').resolve().as_uri()+'?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        results = [dict(r) for r in db.execute('SELECT instruction_id,fixture,market,selection,line,alert_price,result_payload FROM instructions WHERE result_payload IS NOT NULL ORDER BY instruction_id')]
        totals = []
        for row in db.execute('SELECT id,normalized FROM intake_messages WHERE normalized IS NOT NULL ORDER BY id'):
            p = json.loads(row['normalized'])
            if p.get('sport') == 'basketball' and p.get('market') == 'TOTALS':
                totals.append(dict(intake_id=row['id'], fixture=p.get('fixture'), target_line=p.get('target_line'),
                                   comparison_line=(p.get('comparison') or {}).get('line')))
    for r in results:
        result = json.loads(r.pop('result_payload'))
        r['quotes'] = {key: result[key] for key in ('selection','pretap','execution_observations') if key in result}
    return dict(captured_at=datetime.now(timezone.utc).isoformat(), results=results, totals_feed_rows=totals)


def report():
    OUT.mkdir(parents=True, exist_ok=True)
    source = OUT/'observations.json'
    if not source.exists(): dump(source, snapshot())
    data = json.loads(source.read_text(encoding='utf-8'))
    quotes, scenarios = [], []
    for r in data['results']:
        stages = r['quotes']
        stage = 'pretap' if stages.get('pretap') else 'selection'
        live = stages.get(stage) or {}
        if not all(live.get(k) is not None for k in ('line','price')) or r['line'] is None or r['alert_price'] is None:
            continue
        request = dict(market=r['market'], side=r['selection'], line=r['line'], price=r['alert_price'])
        live = dict(market=live.get('market',r['market']), side=live.get('side',r['selection']), line=live['line'], price=live['price'])
        base = dict(instruction_id=r['instruction_id'], fixture=r['fixture'], stage=stage, requested=request, observed=live)
        if r['market'] == 'SPREAD':
            base.update(compare(request,live,net_percent=10,line_tolerance=1,line_percent=10), policy='configured basketball spread')
        else:
            base['policy'] = 'totals allowance not configured; scenario comparisons only'
            base['candidates'] = {str(cap):compare(request,live,net_percent=10,line_tolerance=cap) for cap in (0,.5,1)}
        quotes.append(base)
    for cap in (0,.5,1):
        subset=[q for q in quotes if q['requested']['market']=='TOTALS']
        keep=sum(q['candidates'][str(cap)]['acceptable'] for q in subset)
        scenarios.append(dict(market='TOTALS', net_payout_percent=10, absolute_line_cap=cap, retained=keep,rejected=len(subset)-keep))
    spread=[q for q in quotes if q['requested']['market']=='SPREAD']
    keep=sum(q['acceptable'] for q in spread)
    valid_lines=[Decimal(r['target_line']) for r in data['totals_feed_rows'] if r['target_line'] is not None]
    # Alert rows/edits are not independent events and do not establish bookmaker ladder steps.
    endings=Counter(str(x%1) for x in valid_lines)
    summary=dict(captured_at=data['captured_at'], source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                 stored_result_rows=len(data['results']), comparable_quotes=len(quotes),
                 stages=dict(Counter(q['stage'] for q in quotes)), spread=dict(retained=keep,rejected=len(spread)-keep),
                 totals_scenarios=scenarios, totals_feed_rows=len(data['totals_feed_rows']),
                 totals_rows_with_target_line=len(valid_lines), totals_line_fraction_counts=dict(endings),
                 totals_line_range=[str(min(valid_lines)),str(max(valid_lines))] if valid_lines else [],
                 totals_proposal=dict(absolute_points=.5,configured=False,reason='Half-point increments occur in alert quotes; provisional operational choice, not an estimated optimum.'),
                 limitations='Six selected historical attempts, not independent opportunities or placements. Five selection-stage quotes and one pre-tap quote. No observed line deterioration, so retention cannot distinguish candidate totals caps or quantify full-feed effect.')
    dump(OUT/'quote-comparisons.json',quotes);dump(OUT/'summary.json',summary)
    rows=['# Scaled execution tolerance comparison', '',
          'Frozen at '+data['captured_at']+'. Each row compares the original alert with the latest available stored quote; selection-stage observations are not pre-action guarantees.', '',
          '| Fixture | Side | Alert → observed line | Alert → observed odds | Stage | Result |',
          '|---|---|---|---|---|---|']
    for q in quotes:
        r,l=q['requested'],q['observed']
        verdict=('Retain' if q['acceptable'] else 'Reject: net payout loss '+str(round(Decimal(q['net_payout_deterioration_percent']),2))+'%') if r['market']=='SPREAD' else 'Retain at 0, 0.5 or 1 point (scenarios only)'
        rows.append(f"| {q['fixture']} | {r['market']} {r['side']} | {r['line']} → {l['line']} | {r['price']} → {l['price']} | {q['stage']} | {verdict} |")
    rows += ['', 'Basketball spreads: **3 retained / 1 rejected**. Boras/Nassjo needs at least 2.04 under the 10% net-payout rule; the observed 1.83 rejects.', '',
             'Totals: **2 retained / 0 rejected** for each candidate allowance of 0, 0.5 and 1 point, with 10% net-payout tolerance. Both observed totals were unchanged. These are scenario results; configured totals line tolerance remains null and fails closed.', '',
             '**Proposal for operator choice: 0.5 point absolute deterioration for basketball totals.** OVER can rise by 0.5; UNDER can fall by 0.5. Improvements always pass. The stored alerts contain whole- and half-point values; that supports a half-point unit, but does not prove every live ladder advances in half-point steps or that this limit is optimal.', '',
             f"The snapshot has {len(data['totals_feed_rows'])} totals feed rows, including {len(valid_lines)} with a resolved target line, spanning {summary['totals_line_range']}. Fraction counts: {dict(endings)}. Rows include repeated alerts/edits and are not independent opportunities.", '',
             summary['limitations'], '',
             'Compared with the earlier zero-deterioration scenario, this small set gains no retained observations: 3/4 spreads and 2/2 totals under each candidate totals policy. This is a lack of informative moving-quote data, not evidence that zero tolerance is preferable.', '',
             'Synthetic spread examples (separate from historical counts): -25.5→-26.5, -15.5→-16.5 and -10.5→-11.5 pass; -5.5→-6.5 and -1.5→-2.5 fail. The same signed arithmetic applies to either selected team.']
    (OUT/'REPORT.md').write_text('\n'.join(rows)+'\n',encoding='utf-8')
    print(json.dumps(summary,indent=2))


if __name__ == '__main__': report()
