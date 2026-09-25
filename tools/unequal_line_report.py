"""Unequal-line audit over the REAL stored OddsNotifier feed (read-only).

    PYTHONPATH=. python tools/unequal_line_report.py [--since 2026-09-24] [--db .local/pipeline.sqlite3] [--out file]

For every stored alert that says "EV: None (not equal lines)" it re-runs the production classifier
(core.alert_classifier) and the rules engine with the live rules config and prints, per alert:
  * what the backend did with it (status / reason / instruction created or not)
  * the per-side line comparison (favourable side, advantage in points, both Bet365 prices)
  * the counterfactual: the same message with the favourable side's Bet365 price highlighted, through the
    same classifier + rules (what FAVOURABLE_LINE_SIGNAL would have decided), and why it would be rejected
Nothing is written to the database and nothing is dispatched.
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from core import alert_classifier
from core.rules_engine import evaluate

sys.stdout.reconfigure(encoding='utf-8')
NUMBER = r'[0-9]+(?:\.[0-9]+)?'


def live_config(path):
    try:
        from core.decision_support import Store as ConfigStore
        return ConfigStore(path).get()['config']
    except Exception:
        from core.decision_support import defaults
        return defaults()


def highlight(text, position):
    """Bold the Bet365 price at `position` (0 = first side, 1 = second side), exactly as OddsNotifier does
    on equal-line alerts. Returns None if the Bet365 price row cannot be found."""
    m = re.search(rf'(\[?Bet365[^\n]*\n)({NUMBER})( - )({NUMBER})', text)
    if not m:
        return None
    first, second = m[2], m[4]
    if position == 0:
        first = f'**{first}**'
    else:
        second = f'**{second}**'
    return text[:m.start()] + m[1] + first + m[3] + second + text[m.end():]


def favourable_side(parsed):
    sides = parsed.get('sides') or []
    fav = [s for s in sides if s.get('line_quality') == 'FAVOURABLE']
    return fav[0] if len(fav) == 1 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='.local/pipeline.sqlite3')
    ap.add_argument('--rules', default='.local/dashboard.sqlite3')
    ap.add_argument('--since', default=None)
    ap.add_argument('--out', default=None)
    ap.add_argument('--limit', type=int, default=2000)
    a = ap.parse_args()
    cfg = live_config(a.rules)
    db = sqlite3.connect(f'file:{a.db}?mode=ro', uri=True); db.row_factory = sqlite3.Row
    q = "SELECT id, chat_id, message_id, received_at, source_timestamp, status, reason, instruction_id, formatted_text, raw_text FROM intake_messages WHERE (formatted_text LIKE '%not equal lines%' OR raw_text LIKE '%not equal lines%')"
    args = []
    if a.since:
        q += ' AND received_at >= ?'; args.append(a.since)
    q += ' ORDER BY id DESC LIMIT ?'; args.append(a.limit)
    rows = db.execute(q, args).fetchall()
    lines = []
    out = lines.append
    out(f"unequal-line alerts in store: {len(rows)}  (since {a.since or 'beginning'})  rules: min_line_advantage={cfg['global'].get('min_line_advantage')}")
    stored = Counter(); now_status = Counter(); markets = Counter(); counterfactual = Counter(); reasons = Counter()
    bolded = 0
    for r in rows:
        text = r['formatted_text'] or r['raw_text']
        if '**' in text:
            bolded += 1
        stored[(r['status'], 'instruction' if r['instruction_id'] else 'no instruction')] += 1
        verdict = alert_classifier.classify(text, channel_id=str(r['chat_id']), message_id=str(r['message_id']), source_timestamp=r['source_timestamp'])
        p = verdict['parsed'] or {}
        now_status[verdict['status']] += 1
        markets[p.get('market')] += 1
        fav = favourable_side(p) if verdict['status'] in ('PARSED', 'PARSED_PARTIAL') else None
        received = datetime.fromisoformat(r['received_at'].replace('Z', '+00:00'))
        line = f"#{r['id']:<5} {r['received_at'][:16]} {p.get('sport') or '?':10s} {str(p.get('market')):6s} {str(p.get('fixture'))[:38]:38s} pin={str(p.get('displayed_line')):6s} b365={str((p.get('comparison') or {}).get('bet365_line_displayed')):6s} stored={r['status']}/{'ins' if r['instruction_id'] else 'none'}"
        if verdict['status'] not in ('PARSED', 'PARSED_PARTIAL'):
            line += f"  now={verdict['status']}: {(verdict['reason'] or '')[:70]}"
            counterfactual['not parseable / ambiguous'] += 1
            reasons[(verdict['reason'] or '')[:80]] += 1
        elif fav is None:
            line += '  no single favourable side'
            counterfactual['no favourable side'] += 1
        else:
            adv = fav['comparison'].get('line_advantage'); price = fav['comparison'].get('bet365_price')
            line += f"  fav={fav['side']} +{adv} @ {price} ({fav['bet_quality']}, target={p.get('target_side')})"
            pos = [s['side'] for s in p['sides']].index(fav['side'])
            cf_text = highlight(text, pos)
            if cf_text is None:
                counterfactual['bet365 row not found'] += 1
            else:
                cf = alert_classifier.classify(cf_text, channel_id=str(r['chat_id']), message_id=str(r['message_id']), source_timestamp=r['source_timestamp'])
                cp = cf['parsed'] or {}
                if cf['status'] != 'PARSED':
                    line += f"  | if highlighted: {cf['status']} ({(cf['reason'] or '')[:50]})"
                    counterfactual[f"if highlighted: {cf['status']}"] += 1
                else:
                    decision = evaluate(cp, cfg, instruction_id=f"cf-{r['id']}", received_at=r['received_at'], now=received)
                    line += f"  | if highlighted: {cp.get('bet_quality')} -> {decision['decision']} ({decision['reason'][:60]})"
                    key = f"if highlighted: {cp.get('bet_quality')} -> {decision['decision']}"
                    if decision['decision'] != 'ACCEPT':
                        key += ' (' + decision['reason'].split(':')[0] + ')'
                    counterfactual[key] += 1
        out(line)
    out('')
    out(f'stored outcome (status, instruction?): {dict(stored)}')
    out(f'classifier today: {dict(now_status)}   markets: {dict(markets)}   with a highlighted Bet365 price: {bolded}/{len(rows)}')
    out(f'counterfactual (favourable side highlighted, same classifier + live rules): {dict(counterfactual)}')
    if reasons:
        out(f'non-parseable reasons: {dict(reasons.most_common(6))}')
    text = '\n'.join(lines)
    print(text)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text, encoding='utf-8')


main()
