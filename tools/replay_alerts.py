"""Replay stored live alerts through the complete production interpretation path (read-only).

    PYTHONPATH=. python tools/replay_alerts.py [--since 2026-09-24T00:00] [--db .local/pipeline.sqlite3] [--out file]

Every stored intake message since --since (all sports, equal and unequal lines) goes through core.alert_classifier
and, when it parses with a target, the rules engine with the live rules config at the alert's own receipt time.
Prints the totals (ACCEPT / REJECT / STALE / AMBIGUOUS / PARSED_PARTIAL / INVALID), examples of HOME / AWAY / OVER
/ UNDER implied selections, and a list of selections worth a manual look (very large advantages, alternate lines,
Pinnacle moving hard the other way, Bet365 far from its opening line). Nothing is written or dispatched.
"""
import argparse
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
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


def dec(v):
    try:
        return Decimal(str(v))
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='.local/pipeline.sqlite3')
    ap.add_argument('--rules', default='.local/dashboard.sqlite3')
    ap.add_argument('--since', default='2026-09-24T00:00')
    ap.add_argument('--out', default=None)
    a = ap.parse_args()
    cfg = live_config(a.rules)
    db = sqlite3.connect(f'file:{a.db}?mode=ro', uri=True); db.row_factory = sqlite3.Row
    rows = db.execute("SELECT id, chat_id, message_id, received_at, source_timestamp, status, formatted_text, raw_text FROM intake_messages "
                      "WHERE received_at >= ? AND status != 'DUPLICATE' ORDER BY id", (a.since,)).fetchall()
    lines = []; out = lines.append
    outcome = Counter(); by_source = Counter(); examples = defaultdict(list); questionable = []; reasons = Counter()
    for r in rows:
        text = r['formatted_text'] or r['raw_text']
        v = alert_classifier.classify(text, channel_id=str(r['chat_id']), message_id=str(r['message_id']), source_timestamp=r['source_timestamp'])
        p = v['parsed'] or {}
        if v['status'] != 'PARSED':
            outcome[v['status']] += 1
            reasons[(v['status'], (v['reason'] or '')[:70])] += 1
            continue
        received = datetime.fromisoformat(r['received_at'].replace('Z', '+00:00'))
        d = evaluate(p, cfg, instruction_id=f"replay-{r['id']}", received_at=r['received_at'], now=received)
        key = d['decision'] if d['decision'] != 'REJECT' else 'REJECT (' + d['reason'].split(':')[0] + ')'
        outcome[key] += 1
        cmp = p.get('comparison') or {}; imp = p.get('implied_target') or {}; mv = p.get('market_movement') or {}
        source = 'implied' if imp else 'highlighted'
        by_source[(source, d['decision'])] += 1
        desc = (f"#{r['id']} {r['received_at'][11:16]} {p['sport']} {p['market']} {p['fixture'][:38]} | Pinnacle {p.get('displayed_line')} "
                f"(opening {(p.get('opening') or {}).get('line')}, moved {mv.get('line_direction') or 'no'}), Bet365 {cmp.get('bet365_line_displayed')} "
                f"-> {p['selection_side']} {p['selection_line']} @ {p['alert_price']} (+{cmp.get('line_advantage')}) {key}")
        if imp and len(examples[p['selection_side']]) < 3 and d['decision'] == 'ACCEPT':
            examples[p['selection_side']].append(desc)
        adv = dec(cmp.get('line_advantage')) or Decimal(0)
        flags = []
        if imp:   # only implied selections can be "questionable" on the lines; highlighted ones are OddsNotifier's own call
            if adv >= 6:
                flags.append(f'advantage {adv} is unusually large: Bet365 may be quoting a different line/market or a stale one')
            pin, b365 = dec(p.get('displayed_line')), dec(cmp.get('bet365_line_displayed'))
            if p['market'] == 'SPREAD' and pin is not None and b365 is not None and (pin < 0) != (b365 < 0) and abs(pin - b365) >= 4:
                flags.append(f'Pinnacle ({pin}) and Bet365 ({b365}) favour different teams')
            change = dec(mv.get('line_change'))
            if imp.get('pinnacle_movement_agrees') is False and change is not None and abs(change) >= 3:
                flags.append(f"Pinnacle just moved {change} against the implied side")
        if flags and d['decision'] == 'ACCEPT':
            questionable.append(desc + '  ?? ' + '; '.join(flags))
    total = len(rows)
    out(f"alerts evaluated since {a.since}: {total} (duplicate deliveries excluded); rules min_line_advantage={cfg['global'].get('min_line_advantage')}")
    out(f"outcome: {dict(outcome)}")
    out(f"by target source (highlighted = OddsNotifier bold, implied = lines) x decision: {dict(by_source)}")
    out('')
    for side in ('HOME', 'AWAY', 'OVER', 'UNDER'):
        out(f"implied {side} examples:")
        for e in examples[side]: out('  ' + e)
    out('')
    out(f"questionable ACCEPTs for manual review ({len(questionable)}):")
    for q in questionable[:40]: out('  ' + q)
    if reasons:
        out('')
        out(f"non-parsed reasons: {dict(reasons.most_common(10))}")
    text = '\n'.join(lines)
    print(text)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text, encoding='utf-8')


main()
