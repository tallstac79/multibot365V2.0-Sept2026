"""Read-only report of stored alert/live quotes and UTC/London eligibility differences.

No tolerance or timezone confirmation is written by this tool. Old forensic artifacts
are immutable inputs. Current instruction observations are frozen in the output.
"""
from collections import Counter
from datetime import datetime
from decimal import Decimal
import csv
import gzip
import json
from pathlib import Path
from core.alert_classifier import classify
from core.decision_support import upgrade
from core.rules_engine import time_assumptions, evaluate
from tools.strategy_forensics import ro, dump, ROOT

OUT = ROOT / 'evidence/execution-policy'


def write_csv(path, rows):
    if not rows: return
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def report():
    OUT.mkdir(parents=True, exist_ok=True)
    old = ROOT/'evidence/strategy-audit'
    baseline = json.loads(gzip.decompress((old/'baseline.json.gz').read_bytes()))
    rows = baseline['rows'] + json.loads((old/'postcutoff-baseline.json').read_text(encoding='utf-8'))['rows']
    rows += json.loads((old/'supplemental-baseline.json').read_text(encoding='utf-8'))
    config = upgrade(baseline['config'])
    config['global'].update(min_sharp_movement=None, feed_timezone_verified=False)
    # Explicit RESEARCH scenario to isolate timezone differences; never saved live.
    for sport in config['sports'].values():
        for rule in sport['markets'].values():
            rule.update(max_odds_deterioration=0, max_line_deterioration=0)
    seen, differences, decisions = set(), [], Counter()
    for r in rows:
        key = (r['chat_id'], r['message_id'], r.get('edit_key', ''))
        if key in seen: continue
        seen.add(key)
        v = classify(r['formatted_text'] or r['raw_text'], channel_id=str(r['chat_id']),
                     message_id=str(r['message_id']), source_timestamp=r['source_timestamp'])
        p = v.get('parsed') or {}
        now = datetime.fromisoformat(r['received_at'])
        timing = time_assumptions(p, config, now)
        if v['status'] == 'PARSED':
            decisions[evaluate(p, config, instruction_id='audit', received_at=r['received_at'], now=now)['decision']] += 1
        else: decisions[v['status']] += 1
        if timing['timezone_eligibility_uncertain']:
            item = dict(intake_id=r['id'], message_id=r['message_id'], fixture=p.get('fixture'),
                        received_at=r['received_at'], feed_wall_time=p.get('scheduled_at_local'),
                        sharp_side=p.get('target_side'), classification=v['status'])
            for zone in ('UTC','Europe/London'):
                item[zone+'_event_start'] = timing['event_time_assumptions'][zone]['event_start_utc']
                item[zone+'_not_started'] = timing['event_time_assumptions'][zone]['event_not_started']
                cfg = json.loads(json.dumps(config)); cfg['global'].update(event_timezone=zone, feed_timezone_verified=True)
                item[zone+'_otherwise_decision'] = evaluate(p, cfg, instruction_id='audit', received_at=r['received_at'], now=now)['decision'] if v['status']=='PARSED' else v['status']
            differences.append(item)
    write_csv(OUT/'timezone-sensitive-alerts.csv', differences)
    source_path = OUT/'stored-execution-observations.json'
    if not source_path.exists():
        with ro(ROOT/'.local/pipeline.sqlite3') as db:
            observations = [dict(r) for r in db.execute('SELECT instruction_id,fixture,market,selection,line,alert_price,raw_alert,result_payload,event_time,competition FROM instructions WHERE result_payload IS NOT NULL')]
        for r in observations:
            result = json.loads(r['result_payload'])
            r['result_payload'] = json.dumps({k: result[k] for k in ('selection', 'pretap', 'identity', 'competition') if k in result})
        dump(source_path, observations)
    observations = json.loads(source_path.read_text(encoding='utf-8'))
    quotes, clocks = [], []
    for r in observations:
        result = json.loads(r['result_payload'])
        observed = result.get('selection') or result.get('pretap') or result.get('ready_state') or {}
        if observed.get('price') and observed.get('line') and r['line'] and r['alert_price']:
            odds_loss = max(Decimal('0'), Decimal(r['alert_price'])-Decimal(observed['price']))
            delta = Decimal(r['line'])-Decimal(observed['line'])
            line_loss = max(Decimal('0'), -delta if r['selection']=='OVER' else delta)
            current = classify(r['raw_alert']).get('parsed') or {}
            quotes.append(dict(instruction_id=r['instruction_id'], fixture=r['fixture'], market=r['market'],
                               side=r['selection'], requested_line=r['line'], live_line=observed['line'],
                               requested_odds=r['alert_price'], live_odds=observed['price'],
                               odds_deterioration=str(odds_loss), line_deterioration=str(line_loss),
                               matches_corrected_sharp_side=current.get('target_side')==r['selection'],
                               source='selection' if result.get('selection') else 'pretap' if result.get('pretap') else 'ready_state'))
        identity = result.get('identity') or {}
        if identity.get('kickoff_known') and identity.get('kickoff_agrees'):
            clocks.append(dict(instruction_id=r['instruction_id'], fixture=r['fixture'], feed_wall_time=r['event_time'],
                               phone_header=result.get('competition'), identity=identity))
    write_csv(OUT/'alert-live-quotes.csv', quotes)
    dump(OUT/'timezone-phone-evidence.json', clocks)
    scenarios = []
    for market in ('ALL','SPREAD','TOTALS'):
        subset = [r for r in quotes if market=='ALL' or r['market']==market]
        for odds in ('0','0.01','0.02','0.05','0.10','0.32'):
            for line in ('0','0.5','1'):
                retained = sum(Decimal(r['odds_deterioration']) <= Decimal(odds) and Decimal(r['line_deterioration']) <= Decimal(line) for r in subset)
                scenarios.append(dict(market=market, max_odds_deterioration=odds, max_line_deterioration=line,
                                      observed=len(subset), retained=retained, rejected=len(subset)-retained))
    write_csv(OUT/'tolerance-scenarios.csv', scenarios)
    summary = dict(frozen_records=len(seen), frozen_alerts=len(seen)-decisions.get('IGNORED',0), decisions_with_unverified_timezone=dict(decisions),
                   research_execution_tolerances='zero deterioration; comparison scenario only, not saved configuration',
                   timezone_sensitive_start_checks=len(differences),
                   timezone_sensitive_overall_decisions=sum(r['UTC_otherwise_decision']!=r['Europe/London_otherwise_decision'] for r in differences),
                   stored_instruction_results=len(observations), complete_alert_live_quotes=len(quotes),
                   corrected_side_matches=sum(r['matches_corrected_sharp_side'] for r in quotes),
                   recommendation='Consider zero odds and zero line deterioration initially; no saved policy change. Sample too small to justify widening.',
                   limitations='Observed quote pairs are selected historical attempts under the previous strategy, not placements or independent opportunities; no full-corpus live prices exist.')
    dump(OUT/'summary.json', summary)
    print(json.dumps(summary, indent=2))


if __name__ == '__main__': report()
