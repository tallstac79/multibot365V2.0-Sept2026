"""Implied favourable-side target for unequal-line alerts (2026-09-25), proven on REAL stored OddsNotifier alerts.

When OddsNotifier highlights nothing, the lines alone decide: Pinnacle's current line is the sharp reference and the
one side for which Bet365 still offers a line >= 1.0 point better is the bet.
  totals  : Pinnacle 168.5, Bet365 165.5 -> OVER at 165.5 is 3.0 better        (lower total favours OVER)
            Pinnacle 159.5, Bet365 165.5 -> UNDER at 165.5 is 6.0 better       (higher total favours UNDER)
  spreads : Pinnacle home -5.5, Bet365 home -1.5 -> HOME -1.5 is 4.0 better    (higher signed handicap for that team)
            Pinnacle home -2.5, Bet365 home -5.5 -> AWAY +5.5 is 3.0 better than +2.5
No EV is calculated; prices are never compared across lines; everything that is not deterministic stays
PARSED_PARTIAL / AMBIGUOUS exactly as before. Pure parsing; nothing is dispatched.
"""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from core import alert_classifier
from core.market_interpretation import IMPLIED_SOURCE, IMPLIED_TARGET_MIN_ADVANTAGE, interpret
from core.rules_engine import evaluate, event_start
from core.status_notifier import format_instruction
from tests.pipeline_support import ROOT, MELBOURNE, T0, Clock, config, message, pipeline

CORPUS = json.loads((ROOT / 'tests/fixtures/unequal_line_corpus_20260925.json').read_text(encoding='utf-8'))
BY_ID = {m['id']: m for m in CORPUS['messages']}
FIXTURES = ROOT / 'tests/fixtures'


def alert(mid):
    return BY_ID[mid]['text']


def received(mid):
    return datetime.fromisoformat(BY_ID[mid]['received_at'].replace('Z', '+00:00'))


def decide(parsed, now, cfg=None):
    return evaluate(parsed, cfg or config(), instruction_id='implied', received_at=now.isoformat(), now=now)


def check(decision, name):
    return next(c for c in decision['checks'] if c['name'] == name)


class UsersExamples(unittest.TestCase):
    """The two shapes described by the operator, built from real alert texts with only the lines changed."""

    def test_pinnacle_over_168_5_bet365_still_165_5_is_over_plus_3(self):
        text = alert(25).replace('Totals (157.5 -> 158.5)', 'Totals (168.5)').replace('Bet365 (Totals 155.5)', 'Bet365 (Totals 165.5)')
        v = alert_classifier.classify(text)
        self.assertEqual(v['status'], 'PARSED', v['reason'])
        p = v['parsed']
        self.assertEqual((p['selection_side'], p['selection_line'], p['comparison']['line_advantage'], p['alert_price']), ('OVER', '165.5', '3.0', '1.83'))
        self.assertEqual((p['bet_quality'], p['target_price_source'], p['displayed_ev_percent'], p['comparison']['ev_status']),
                         ('FAVOURABLE_LINE_SIGNAL', IMPLIED_SOURCE, None, 'NOT_AVAILABLE_UNEQUAL_LINES'))
        self.assertIn('OVER 165.5 at Bet365 is 3.0 better than Pinnacle 168.5', v['reason'])
        decision = decide(p, T0)
        self.assertEqual(decision['decision'], 'ACCEPT', decision['reason'])
        self.assertEqual((decision['instruction']['side'], decision['instruction']['line'], decision['instruction']['line_advantage'],
                          decision['instruction']['target_source'], decision['instruction']['displayed_ev_percent']),
                         ('OVER', '165.5', '3.0', IMPLIED_SOURCE, None))
        self.assertIn('implied from the favourable Bet365 line', check(decision, 'explicit_target')['detail'])
        # the operator message says why
        row = dict(decision['instruction'], normalized_alert=json.dumps(p), state='QUEUED', instruction_id='x', fixture=p['fixture'],
                   selection=p['selection_side'], selection_name='Over', alert_price=p['alert_price'])
        text_out = format_instruction(row)
        self.assertIn('Signal: Bet365 line 3.0 pts better than Pinnacle (168.5 -> 165.5), no EV; target implied from the lines', text_out)

    def test_pinnacle_minus_5_5_bet365_still_minus_1_5_is_home_plus_4(self):
        text = alert(341).replace('Spread (-5 -> -4.5)', 'Spread (-5.5)')
        v = alert_classifier.classify(text)
        self.assertEqual(v['status'], 'PARSED', v['reason'])
        p = v['parsed']
        self.assertEqual((p['selection_side'], p['selection_name'], p['selection_line'], p['comparison']['line_advantage']),
                         ('HOME', 'CD Castro', '-1.5', '4.0'))
        self.assertEqual(p['bet_quality'], 'FAVOURABLE_LINE_SIGNAL')
        away = next(s for s in p['sides'] if s['side'] == 'AWAY')
        self.assertEqual((away['reference']['line'], away['comparison']['bet365_line'], away['line_quality'], away['comparison']['line_advantage']),
                         ('+5.5', '+1.5', 'UNFAVOURABLE', '-4.0'))
        decision = decide(p, received(341))
        self.assertEqual(decision['decision'], 'ACCEPT', decision['reason'])
        self.assertEqual(decision['instruction']['selection_name'], 'CD Castro')


class RealFeedAlerts(unittest.TestCase):
    """One stored alert per category; expectations were read off the alert text by hand."""
    CASES = {
        25: ('TOTALS', 'OVER', '155.5', '3.0', 'UP', True),       # Pinnacle 157.5 -> 158.5 (money on OVER), Bet365 still 155.5
        275: ('TOTALS', 'OVER', '127.5', '2.5', 'DOWN', False),   # Pinnacle 132 -> 130, Bet365 127.5 (still 2.5 below)
        67: ('TOTALS', 'UNDER', '165.5', '6.0', 'DOWN', True),    # Pinnacle 160.5 -> 159.5, Bet365 165.5
        37: ('TOTALS', 'UNDER', '168.5', '2.0', 'UP', False),     # Pinnacle 165.5 -> 166.5, Bet365 168.5
        341: ('SPREAD', 'HOME', '-1.5', '3.0', 'UP', False),      # Pinnacle home -5 -> -4.5, Bet365 home -1.5
        601: ('SPREAD', 'HOME', '-11.5', '12.5', 'UP', False),    # Pinnacle home -26 -> -24, Bet365 home -11.5
        21: ('SPREAD', 'AWAY', '+5.5', '3.0', 'UP', True),        # Pinnacle home -4 -> -2.5, Bet365 home -5.5: away +5.5 vs +2.5
        30: ('SPREAD', 'AWAY', '+4', '5', 'DOWN', False),         # Pinnacle home 2 -> 1, Bet365 home -4: away +4 vs -1
    }

    def test_each_category_gets_the_deterministic_side(self):
        for mid, (market, side, line, advantage, direction, agrees) in self.CASES.items():
            with self.subTest(message=mid):
                v = alert_classifier.classify(alert(mid))
                self.assertEqual(v['status'], 'PARSED', v['reason'])
                p = v['parsed']
                self.assertEqual((p['market'], p['selection_side'], p['selection_line'], p['comparison']['line_advantage']), (market, side, line, advantage))
                self.assertEqual((p['bet_quality'], p['target_price_source']), ('FAVOURABLE_LINE_SIGNAL', IMPLIED_SOURCE))
                self.assertIsNone(p['displayed_ev_percent'])
                self.assertEqual(p['comparison']['ev_status'], 'NOT_AVAILABLE_UNEQUAL_LINES')
                self.assertEqual((p['implied_target']['pinnacle_line_direction'], p['implied_target']['pinnacle_movement_agrees']), (direction, agrees))
                other = next(s for s in p['sides'] if s['side'] != side)
                self.assertEqual((other['line_quality'], other['bet_quality'], other['is_target']), ('UNFAVOURABLE', 'UNFAVOURABLE', False))
                self.assertGreaterEqual(Decimal(advantage), IMPLIED_TARGET_MIN_ADVANTAGE)
                # through the rules at the moment the alert was received: every rule passes except, possibly, timing
                decision = decide(p, received(mid))
                for name in ('verified_mapping', 'explicit_target', 'bet_quality', 'line_advantage', 'valid_price'):
                    self.assertTrue(check(decision, name)['passed'], (mid, name, check(decision, name)['detail']))
                if received(mid) < event_start(p, 'UTC'):
                    self.assertEqual(decision['decision'], 'ACCEPT', decision['reason'])
                else:
                    self.assertEqual((decision['decision'], decision['reason'].split(':')[0]), ('STALE', 'event_not_started'))

    def test_still_not_actionable(self):
        # 0.5 points is below the implied-target threshold: no side is chosen (PARSED_PARTIAL, both sides reported)
        half = alert(25).replace('Bet365 (Totals 155.5)', 'Bet365 (Totals 158)')
        v = alert_classifier.classify(half)
        self.assertEqual((v['status'], v['parsed']['selection_side'], v['parsed']['implied_target']), ('PARSED_PARTIAL', None, None))
        # equal lines reported as "not equal": the spread sign reference is ambiguous -> AMBIGUOUS, no side
        v = alert_classifier.classify(alert(10))
        self.assertEqual((v['status'], v['parsed']['selection_side']), ('AMBIGUOUS', None))
        # two highlighted prices: ambiguous, the implied rule never overrides a highlight
        both = alert(25).replace('1.83 - 1.83', '**1.83** - **1.83**')
        v = alert_classifier.classify(both)
        self.assertNotEqual(v['status'], 'PARSED')
        self.assertIsNone(v['parsed']['selection_side'])
        # a highlighted WORSE side is still the target (UNFAVOURABLE -> rejected); the lines do not override OddsNotifier
        worse = alert(25).replace('1.83 - 1.83', '1.83 - **1.83**')   # UNDER highlighted on an OVER-favourable line
        v = alert_classifier.classify(worse)
        self.assertEqual((v['parsed']['selection_side'], v['parsed']['bet_quality'], v['parsed']['target_price_source']), ('UNDER', 'UNFAVOURABLE', 'bold_bet365_quote'))
        self.assertTrue(decide(v['parsed'], T0)['reason'].startswith('bet_quality'))
        # an unverified quote mapping (football two-sided layout) never gets an implied side
        for name in ('oddsnotifier_spread.txt', 'oddsnotifier_football_total.txt'):
            v = alert_classifier.classify((FIXTURES / name).read_text(encoding='utf-8'))
            self.assertNotEqual(v['status'], 'PARSED', name)
            self.assertIsNone(v['parsed']['selection_side'], name)

    def test_spread_quoted_from_the_other_perspective_is_ambiguous(self):
        # Japan v Chinese Taipei: Pinnacle home -23, Bet365 "Spread 17.5" -> a 40.5-point "advantage" is the Bet365 line
        # quoted from the other side; likewise Seattle Storm +7.5 vs -9.5. No side is implied (AMBIGUOUS).
        for mid in (681, 364):
            v = alert_classifier.classify(alert(mid))
            self.assertEqual((v['status'], v['parsed']['selection_side']), ('AMBIGUOUS', None), mid)
            self.assertIn('favour different teams', v['reason'])
        # a favourite flip below 10 points is a genuine market move: Tartu v Kalev, Pinnacle +3 vs Bet365 -1.5 -> AWAY +1.5, +4.5
        v = alert_classifier.classify(alert(349))
        self.assertEqual((v['status'], v['parsed']['selection_side'], v['parsed']['selection_line'], v['parsed']['comparison']['line_advantage']),
                         ('PARSED', 'AWAY', '+1.5', '4.5'))

    def test_no_synthetic_ev_even_with_a_minimum_ev_rule(self):
        p = alert_classifier.classify(alert(67))['parsed']
        cfg = config()
        cfg['sports']['basketball']['markets']['TOTALS']['minimum_ev'] = 105
        decision = decide(p, received(67), cfg)
        self.assertIn('not applicable', check(decision, 'minimum_ev')['detail'])
        self.assertIsNone(decision['instruction']['displayed_ev_percent'])

    def test_materiality_still_belongs_to_the_rules(self):
        p = alert_classifier.classify(alert(37))['parsed']   # UNDER +2.0
        self.assertTrue(decide(p, received(37), config(min_line_advantage=2.5))['reason'].startswith('line_advantage'))

    def test_queued_once_through_the_pipeline_and_deduplicated(self):
        text = alert(25).replace('Totals (157.5 -> 158.5)', 'Totals (168.5)').replace('Bet365 (Totals 155.5)', 'Bet365 (Totals 165.5)')
        with tempfile.TemporaryDirectory() as tmp:
            p = pipeline(Path(tmp) / 'implied.sqlite3', Clock())
            first = p.ingest(message(MELBOURNE, message_id='920001', text=text))
            self.assertEqual((first['status'], first['state']), ('PARSED', 'QUEUED'))
            again = p.ingest(message(MELBOURNE, message_id='920002', text=text))
            self.assertEqual(again['status'], 'DUPLICATE')
            with p.store.connection() as db:
                rows = db.execute('SELECT selection, line, alert_price, displayed_ev FROM instructions').fetchall()
            self.assertEqual([tuple(r) for r in rows], [('OVER', '165.5', '1.83', None)])


if __name__ == '__main__':
    unittest.main()
