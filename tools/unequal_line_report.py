"""Unequal-line alerts through the EXACT production path (read-only): every stored alert that says
"EV: None (not equal lines)" is re-run through core.alert_classifier and, when it parses with a target, the rules
engine with the live rules config at the moment it was received. Nothing is written, nothing is dispatched.

    PYTHONPATH=. python tools/unequal_line_report.py [--since 2026-09-24] [--db .local/pipeline.sqlite3] [--out file]

Prints one line per alert (what the target is, why, Pinnacle's own movement) and the totals the operator asked
for: ACCEPT / REJECT / STALE / AMBIGUOUS / PARSED_PARTIAL remaining / INVALID.
"""
import argparse
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from core import alert_classifier
from core.rules_engine import evaluate

sys.stdout.reconfigure(encoding='utf-8')


def live_config(path):
    try:
        from core.decision_support import Store as ConfigStore
        return ConfigStore(path).get()['config']
    except Exception:
        from core.decision_support import defaults
        return defaults()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='.local/pipeline.sqlite3')
    ap.add_argument('--rules', default='.local/dashboard.sqlite3')
    ap.add_argument('--since', default=None)
    ap.add_argument('--out', default=None)
    ap.add_argument('--limit', type=int, default=5000)
    a = ap.parse_args()
    cfg = live_config(a.rules)
    db = sqlite3.connect(f'file:{a.db}?mode=ro', uri=True); db.row_factory = sqlite3.Row
    q = ("SELECT id, chat_id, message_id, received_at, source_timestamp, status, reason, instruction_id, formatted_text, raw_text "
         "FROM intake_messages WHERE (formatted_text LIKE '%not equal lines%' OR raw_text LIKE '%not equal lines%')")
    args = []
    if a.since:
        q += ' AND received_at >= ?'; args.append(a.since)
    q += ' ORDER BY id DESC LIMIT ?'; args.append(a.limit)
    rows = db.execute(q, args).fetchall()
    lines, outcome, stored, reasons, sides, movement = [], Counter(), Counter(), Counter(), Counter(), Counter()
    out = lines.append
    out(f"unequal-line alerts in store: {len(rows)} (since {a.since or 'beginning'}); rules min_line_advantage={cfg['global'].get('min_line_advantage')}, "
        f"stale_alert_seconds={cfg['global'].get('stale_alert_seconds')}; evaluated at each alert's own receipt time")
    for r in rows:
        text = r['formatted_text'] or r['raw_text']
        stored[(r['status'], 'instruction' if r['instruction_id'] else 'no instruction')] += 1
        verdict = alert_classifier.classify(text, channel_id=str(r['chat_id']), message_id=str(r['message_id']), source_timestamp=r['source_timestamp'])
        p = verdict['parsed'] or {}
        cmp = p.get('comparison') or {}
        line = (f"#{r['id']:<5} {r['received_at'][:16]} {str(p.get('market')):6s} {str(p.get('fixture'))[:40]:40s} "
                f"pin={str(p.get('displayed_line')):6s} b365={str(cmp.get('bet365_line_displayed')):6s}")
        if verdict['status'] == 'PARSED':
            imp = p.get('implied_target') or {}
            received = datetime.fromisoformat(r['received_at'].replace('Z', '+00:00'))
            decision = evaluate(p, cfg, instruction_id=f"audit-{r['id']}", received_at=r['received_at'], now=received)
            key = decision['decision'] if decision['decision'] != 'REJECT' else 'REJECT (' + decision['reason'].split(':')[0] + ')'
            outcome[key] += 1
            sides[(p['market'], p['selection_side'])] += 1
            movement[(p['market'], p['selection_side'], imp.get('pinnacle_line_direction'), imp.get('pinnacle_movement_agrees'))] += 1
            line += (f"  -> {p['selection_side']} {p['selection_line']} @ {p['alert_price']} (+{cmp.get('line_advantage')} vs Pinnacle, "
                     f"{p['target_price_source']}, Pinnacle line {imp.get('pinnacle_line_direction') or 'no move'})  {key}")
            if decision['decision'] != 'ACCEPT':
                line += f": {decision['reason'][:70]}"
        else:
            outcome[verdict['status']] += 1
            reasons[(verdict['status'], (verdict['reason'] or '')[:90])] += 1
            line += f"  -> {verdict['status']}: {(verdict['reason'] or '')[:80]}"
        out(line)
    out('')
    out(f"OUTCOME through the production path today: {dict(outcome)}")
    out(f"targets by market/side: {dict(sides)}")
    out(f"Pinnacle's own line movement vs the implied side (market, side, direction, agrees): {dict(movement)}")
    out(f"what the store recorded at the time: {dict(stored)}")
    if reasons:
        out(f"non-actionable reasons: {dict(reasons.most_common(8))}")
    text = '\n'.join(lines)
    print(text)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text, encoding='utf-8')


main()
