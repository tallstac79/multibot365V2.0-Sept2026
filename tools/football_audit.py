"""Replay the stored Feed 1 football corpus through the football interpreter and the rules engine.

Read-only: reads tests/fixtures/feed1_football/*.jsonl (and, with --live, the intake rows of the OddsNotifier Feed 1 chat
from .local/pipeline.sqlite3). Never creates Pipeline objects, never dispatches, never touches the live queue.

    python -m tools.football_audit            # fixture corpus
    python -m tools.football_audit --live     # fixture corpus + every stored Feed 1 intake row

Writes evidence/football/replay-<utc>.json and prints the report the operator asked for: total alerts, supported by
market type, executable / rejected / ambiguous / invalid, with examples for HOME / DRAW / AWAY / OVER / UNDER.
"""
from collections import Counter
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
import sys

from core.alert_classifier import classify
from core.decision_support import defaults
from core.rules_engine import evaluate

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / 'tests/fixtures/feed1_football'
OUT = ROOT / 'evidence/football'
FEED1_CHAT = '1645770730'


def football_config(*, enable=True):
    """The live defaults plus the football execution terms this audit assumes (NOT the live configuration: the live
    football tolerances are unset, which makes every football alert REJECT at execution_tolerances)."""
    cfg = defaults()
    # the live global defaults: fixed £0.10 stake, verified Europe/London feed time, no extra movement floor
    cfg['global'].update(feed_timezone_verified=True, event_timezone='Europe/London', min_sharp_movement=None, default_stake=0.1)
    for market, rule in cfg['sports']['football']['markets'].items():
        rule.update(enabled=enable, max_odds_deterioration=None, max_net_payout_deterioration_percent=10,
                    max_line_deterioration=None if market == '1X2' else 0.25, max_line_deterioration_percent=None)
    return cfg


def load_rows(live=False):
    rows = []
    for path in sorted(CORPUS.glob('*.jsonl')):
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.strip():
                r = json.loads(line)
                rows.append(dict(source=path.name, intake_id=r['intake_id'], message_id=str(r['message_id']),
                                 source_timestamp=r['source_timestamp'], received_at=r['received_at'], text=r['text']))
    if live:
        seen = {r['intake_id'] for r in rows}
        with sqlite3.connect((ROOT / '.local/pipeline.sqlite3').resolve().as_uri() + '?mode=ro', uri=True) as db:
            db.row_factory = sqlite3.Row
            for r in db.execute("SELECT id, message_id, source_timestamp, received_at, formatted_text FROM intake_messages "
                                "WHERE chat_id=? AND status<>'DUPLICATE' ORDER BY id", (FEED1_CHAT,)):
                if r['id'] not in seen:
                    rows.append(dict(source='live', intake_id=r['id'], message_id=str(r['message_id']), source_timestamp=r['source_timestamp'],
                                     received_at=r['received_at'], text=r['formatted_text'] or ''))
    return rows


def replay(rows, config=None):
    config = config or football_config()
    out = []
    for r in rows:
        c = classify(r['text'], channel_id=FEED1_CHAT, message_id=r['message_id'], source_timestamp=r['source_timestamp'])
        p = c.get('parsed') or {}
        football = p.get('football') or {}
        verdict = football.get('verdict') or ('INVALID' if c['status'] == 'INVALID' else 'AMBIGUOUS' if c['status'] == 'AMBIGUOUS' else 'IGNORED')
        decision = None
        if c['status'] == 'PARSED':
            # As if received live (source timestamp + 5 s, decided 30 s after the source): Feed 1 was subscribed on 27 Sep 2026
            # and its backlog arrived by catch-up, so the stored receipt times lag the source by many minutes.
            source = datetime.fromisoformat(r['source_timestamp'])
            d = evaluate(copy.deepcopy(p), config, instruction_id=f"audit-{r['intake_id']}", received_at=(source + timedelta(seconds=5)).isoformat(),
                         now=source + timedelta(seconds=30))
            decision = dict(decision=d['decision'], reason=d['reason'])
        out.append(dict(intake_id=r['intake_id'], message_id=r['message_id'], source_timestamp=r['source_timestamp'], status=c['status'],
                        reason=c.get('reason'), sport=p.get('sport') or c.get('sport'), market=p.get('market') or c.get('market'),
                        fixture=p.get('fixture'), competition=p.get('competition_full') or p.get('competition'),
                        in_play_link=football.get('in_play_link'), signal_basis=football.get('signal_basis'),
                        target_side=p.get('target_side'), target_line=p.get('target_line'), alert_price=p.get('alert_price'),
                        reference_odds=(p.get('reference') or {}).get('odds'), bet_quality=p.get('bet_quality'),
                        highlighted_side=p.get('highlighted_side'), displayed_ev=p.get('displayed_ev_percent'),
                        verdict=verdict, verdict_reason=football.get('verdict_reason'), rules=decision))
    return out


def report(results):
    by_market = Counter(r['market'] for r in results)
    verdicts = Counter(r['verdict'] for r in results)
    by_market_verdict = Counter((r['market'], r['verdict']) for r in results)
    executable = [r for r in results if str(r['verdict']).startswith('EXECUTABLE_')]
    rejected = [r for r in results if r['verdict'] == 'NO_BET']
    ambiguous = [r for r in results if r['verdict'] == 'AMBIGUOUS']
    invalid = [r for r in results if r['verdict'] == 'INVALID']
    lines = [f"FOOTBALL FEED 1 REPLAY: {len(results)} alerts", 'supported by market type: ' + ', '.join(f'{m} {n}' for m, n in sorted(by_market.items())),
             f'executable {len(executable)} | rejected (NO BET) {len(rejected)} | ambiguous {len(ambiguous)} | invalid {len(invalid)}',
             'verdicts: ' + ', '.join(f'{v} {n}' for v, n in sorted(verdicts.items())),
             'by market and verdict: ' + ', '.join(f'{m}/{v} {n}' for (m, v), n in sorted(by_market_verdict.items()))]
    reasons = Counter((r['market'], (r['verdict_reason'] or r['reason'] or '')[:70]) for r in results if r['verdict'] in ('NO_BET', 'AMBIGUOUS'))
    lines.append('NO BET / AMBIGUOUS reasons:')
    lines += [f'  {n:3d}  {m:7s} {why}' for (m, why), n in reasons.most_common()]
    rules = Counter((r['rules'] or {}).get('decision') for r in results if r['rules'])
    lines.append(f'rules engine at historical receipt time with the audit football terms (10% net payout, 0.25 goal line, min_line_advantage 1.0): {dict(rules)}')
    rule_reasons = Counter(((r['rules'] or {}).get('reason') or '')[:80] for r in results if r['rules'] and r['rules']['decision'] != 'ACCEPT')
    lines += [f'  {n:3d}  {why}' for why, n in rule_reasons.most_common(8)]
    lines.append('examples:')
    for side in ('HOME', 'DRAW', 'AWAY', 'OVER', 'UNDER'):
        ex = [r for r in executable if r['target_side'] == side][:2]
        if not ex:
            lines.append(f'  {side}: none in corpus' + (' (draw opening price is never supplied by the feed; DRAW requires a three-price opening row)' if side == 'DRAW' else ''))
        for r in ex:
            lines.append(f"  {side}: intake {r['intake_id']} {r['fixture']} | {r['market']} {r['target_line'] or ''} | Bet365 {r['alert_price']} vs Pinnacle {r['reference_odds']} | "
                         f"{r['bet_quality']} | EV {r['displayed_ev']} | rules {(r['rules'] or {}).get('decision')}")
    return '\n'.join(lines)


def main(argv):
    live = '--live' in argv
    rows = load_rows(live=live)
    results = replay(rows)
    text = report(results)
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    (OUT / f'replay-{stamp}.json').write_text(json.dumps(dict(generated_at=stamp, live=live, config=football_config(), rows=results), indent=1, ensure_ascii=False), encoding='utf-8')
    (OUT / f'replay-{stamp}.txt').write_text(text + '\n', encoding='utf-8')
    print(text)
    print('written', OUT / f'replay-{stamp}.json')


if __name__ == '__main__':
    main(sys.argv[1:])
