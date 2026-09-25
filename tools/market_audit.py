"""Market-interpretation audit of the questionable cases (read-only).

    PYTHONPATH=. python tools/market_audit.py [--since 2026-09-24T00:00] [--out evidence/market-audit/market-review-20260925.csv]

Every stored alert since --since goes through the production classifier + rules at its receipt time. Cases are
flagged when: an implied advantage is >= 6 points; the favourite changed between Pinnacle and Bet365 on a spread;
the alert is AMBIGUOUS for a spread sign/perspective reason; or it is INVALID because EV was supplied on unequal
lines. For each flagged case the CSV reconstructs the requested fields plus per-fixture history evidence
(Bet365 line ever moved? Pinnacle range? same Bet365 event id?) and, where the phone actually opened that fixture,
what the Game Lines grid really showed. A category is assigned from that evidence, never from the size of a number.
"""
import argparse
import csv
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from core import alert_classifier
from core.rules_engine import evaluate

sys.stdout.reconfigure(encoding='utf-8')
EVENT_ID = re.compile(r'/E(\d+)/')


def dec(v):
    try:
        return Decimal(str(v))
    except Exception:
        return None


def live_config(path):
    try:
        from core.decision_support import Store as ConfigStore
        return ConfigStore(path).get()['config']
    except Exception:
        from core.decision_support import defaults
        return defaults()


def phone_observations(db):
    """(fixture, market) -> list of Bet365 grid cells the phone actually read (verified events only)."""
    seen = defaultdict(list)
    for r in db.execute("SELECT fixture, market, result_payload, dispatch_payload FROM instructions WHERE result_payload IS NOT NULL"):
        try:
            rp = json.loads(r['result_payload'] or '{}')
        except ValueError:
            continue
        cells = ((rp.get('game_lines') or {}).get('agreed')) or []
        if cells and rp.get('identity_verdict') in ('EXACT', 'CANONICAL_MATCH', 'ALIAS_MATCH', 'HIGH_CONFIDENCE_EVENT_MATCH'):
            seen[(r['fixture'], r['market'])].append(cells)
    return seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='.local/pipeline.sqlite3')
    ap.add_argument('--rules', default='.local/dashboard.sqlite3')
    ap.add_argument('--since', default='2026-09-24T00:00')
    ap.add_argument('--out', default='evidence/market-audit/market-review-20260925.csv')
    a = ap.parse_args()
    cfg = live_config(a.rules)
    db = sqlite3.connect(f'file:{a.db}?mode=ro', uri=True); db.row_factory = sqlite3.Row
    rows = db.execute("SELECT id, chat_id, message_id, received_at, source_timestamp, status, reason, formatted_text, raw_text FROM intake_messages "
                      "WHERE received_at >= ? AND status != 'DUPLICATE' ORDER BY id", (a.since,)).fetchall()
    phone = phone_observations(db)
    parsed = []
    for r in rows:
        text = r['formatted_text'] or r['raw_text']
        v = alert_classifier.classify(text, channel_id=str(r['chat_id']), message_id=str(r['message_id']), source_timestamp=r['source_timestamp'])
        p = v['parsed'] or {}
        decision = None
        if v['status'] == 'PARSED':
            received = datetime.fromisoformat(r['received_at'].replace('Z', '+00:00'))
            decision = evaluate(p, cfg, instruction_id=f"audit-{r['id']}", received_at=r['received_at'], now=received)
        parsed.append((r, text, v, p, decision))
    # per (fixture, market) history from every alert in the window (including non-flagged ones)
    history = defaultdict(list)
    for r, text, v, p, d in parsed:
        if p.get('fixture') and p.get('market'):
            cmp = p.get('comparison') or {}
            history[(p['fixture'], p['market'])].append(dict(t=r['received_at'], pin=dec(p.get('displayed_line')), b365=dec(cmp.get('bet365_line_displayed')),
                                                             url=p.get('comparison_url'), status=v['status']))
    out_rows = []
    categories = Counter(); questions = defaultdict(Counter)
    for r, text, v, p, d in parsed:
        cmp = p.get('comparison') or {}; imp = p.get('implied_target') or {}; mv = p.get('market_movement') or {}
        market = p.get('market'); adv = dec(cmp.get('line_advantage'))
        pin, b365 = dec(p.get('displayed_line')), dec(cmp.get('bet365_line_displayed'))
        flags = []
        if v['status'] == 'PARSED' and imp and adv is not None and adv >= 6: flags.append('advantage>=6')
        if v['status'] == 'PARSED' and imp and market == 'SPREAD' and pin is not None and b365 is not None and (pin < 0) != (b365 < 0): flags.append('favourite_flip')
        if v['status'] == 'AMBIGUOUS' and 'favour different teams' in (v['reason'] or ''): flags.append('perspective_ambiguous')
        if v['status'] == 'AMBIGUOUS' and 'equals Pinnacle as displayed' in (v['reason'] or ''): flags.append('sign_reference_ambiguous')
        if v['status'] == 'INVALID' and 'EV supplied' in (v['reason'] or ''): flags.append('ev_supplied_unequal')
        if not flags:
            continue
        # --- history evidence
        key = (p.get('fixture'), market)
        hist = history.get(key, [])
        b_lines = sorted({h['b365'] for h in hist if h['b365'] is not None}); p_lines = [h['pin'] for h in hist if h['pin'] is not None]
        span_min = 0
        if len(hist) >= 2:
            ts = [datetime.fromisoformat(h['t'].replace('Z', '+00:00')) for h in hist]
            span_min = int((max(ts) - min(ts)).total_seconds() / 60)
        pin_range = (max(p_lines) - min(p_lines)) if p_lines else None
        event_ids = {EVENT_ID.search(h['url']).group(1) for h in hist if h.get('url') and EVENT_ID.search(h['url'])}
        # did Bet365's line trend the same way as Pinnacle's over the fixture (first -> last observation)?
        trend = ''
        if len(hist) >= 2 and hist[0]['pin'] is not None and hist[-1]['pin'] is not None and hist[0]['b365'] is not None and hist[-1]['b365'] is not None:
            dp, db_ = hist[-1]['pin'] - hist[0]['pin'], hist[-1]['b365'] - hist[0]['b365']
            trend = 'Bet365 unchanged' if db_ == 0 else ('same direction as Pinnacle' if (dp > 0) == (db_ > 0) and dp != 0 else 'opposite/uncertain')
        observed = phone.get(key) or []
        observed_lines = sorted({c.split('/')[2].split('@')[0] for cells in observed for c in cells if c.startswith(market.replace('TOTALS', 'TOTAL') + '/')}) if market else []
        # --- proofs
        orientation = 'production-verified quote mapping (basketball two-sided)' if (p.get('quote_mapping') or {}).get('production_verified') else 'NOT proven'
        alt = p.get('alternate_line') or {}
        market_identity = 'label + fixture URL market agree' + ('; Bet365 row marked (alt. line)' if alt.get('comparison') else '') + ('; Pinnacle row marked (alt. line)' if alt.get('current') else '')
        url_agrees = 'no Bet365 link' if not p.get('comparison_url') else ('one event id across %d alerts' % len(hist) if len(event_ids) == 1 else 'MULTIPLE event ids %s' % sorted(event_ids))
        phone_check = ('phone read Bet365 %s lines %s' % (market, observed_lines)) if observed else 'fixture never opened on the phone'
        # --- category from evidence
        if 'perspective_ambiguous' in flags:
            category = 'perspective issue (Bet365 spread quoted from the other side; now AMBIGUOUS)'
        elif 'sign_reference_ambiguous' in flags:
            category = 'sign reference ambiguous (equal as displayed, reported unequal; AMBIGUOUS)'
        elif 'ev_supplied_unequal' in flags:
            category = 'contradictory alert (EV supplied on unequal lines; INVALID)'
        elif alt.get('comparison'):
            category = 'alternate market (Bet365 row is an alt. line)'
        elif len(b_lines) == 1 and len(hist) >= 3 and span_min >= 30 and pin_range is not None and pin_range >= 3:
            category = 'stale Bet365 market (line unchanged while Pinnacle moved)'
        elif len(b_lines) >= 2 and trend == 'same direction as Pinnacle':
            category = 'genuine lag/value (Bet365 line updating in the same direction as Pinnacle)'
        elif len(b_lines) >= 2:
            category = 'live Bet365 market, direction unclear (line updating)'
        elif 'favourite_flip' in flags and adv is not None and adv < 6:
            category = 'favourite flip, single observation: unresolved'
        else:
            category = 'unresolved (single observation)'
        categories[category] += 1
        for f in flags: questions[f][category] += 1
        fav_changed = ''
        if market == 'SPREAD' and pin is not None and b365 is not None:
            fav_changed = 'yes' if (pin < 0) != (b365 < 0) else 'no'
        out_rows.append(dict(
            intake_id=r['id'], flags='|'.join(flags), sport=p.get('sport'), competition=p.get('competition_full') or p.get('competition'),
            fixture=p.get('fixture'), event_time_local=p.get('scheduled_at_local'), received_at=r['received_at'], market=market,
            pinnacle_previous=mv.get('previous_line'), pinnacle_current=p.get('displayed_line'), pinnacle_opening=(p.get('opening') or {}).get('line'),
            bet365_line=cmp.get('bet365_line_displayed'), inferred_target=(f"{p.get('selection_side')} {p.get('selection_line')} @ {p.get('alert_price')}" if p.get('selection_side') else ''),
            target_source=p.get('target_price_source') or '', line_advantage=cmp.get('line_advantage'), pinnacle_direction=mv.get('line_direction') or '',
            pinnacle_movement_agrees=imp.get('pinnacle_movement_agrees', ''), favourite_changed=fav_changed, orientation_proven=orientation,
            market_identity=market_identity, bet365_event_url=url_agrees, phone_observation=phone_check,
            status=v['status'], decision=(d or {}).get('decision') or '', reason=((d or {}).get('reason') if d else v['reason'])[:120],
            fixture_alerts=len(hist), fixture_span_min=span_min, bet365_lines_seen=' '.join(str(x) for x in b_lines), pinnacle_range=str(pin_range) if pin_range is not None else '',
            bet365_trend=trend, category=category))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=list(out_rows[0].keys()))
        w.writeheader(); w.writerows(out_rows)
    print(f'flagged cases: {len(out_rows)} of {len(parsed)} alerts since {a.since} -> {a.out}')
    print('categories:', json.dumps(categories, indent=1))
    for f, c in questions.items():
        print(f'  by flag {f}:', dict(c))


main()
