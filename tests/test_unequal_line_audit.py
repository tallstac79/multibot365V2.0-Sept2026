"""Unequal-line execution logic audit (2026-09-25) on REAL OddsNotifier alerts from the stored feed.

Properties asserted against the production code path (alert_classifier -> market_interpretation -> rules_engine):
  * equal lines: price / supplied-EV comparison (CLEAR_VALUE_SIGNAL)
  * unequal lines: compared by line quality for the selected side; OVER lower is better, UNDER higher is better,
    selected-team spread higher signed handicap is better
  * a favourable unequal line qualifies (FAVOURABLE_LINE_SIGNAL -> ACCEPT) with EV unavailable, no synthetic EV
  * an unfavourable unequal line never qualifies; an ambiguous target fails closed
  * FACT of the live feed: unequal-line alerts carry no highlighted Bet365 price, so no side is chosen and no
    instruction is created (PARSED_PARTIAL) - the signal path is only reachable with a highlighted target.
Pure parsing; no device, no bookmaker, nothing dispatched.
"""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from core import alert_classifier
from core.market_interpretation import compare_side, bet_quality, interpret, FAVOURABLE, UNFAVOURABLE, EQUAL, NOT_COMPARABLE
from core.rules_engine import evaluate
from tests.pipeline_support import ROOT, MELBOURNE, T0, Clock, config, message, pipeline

CORPUS = json.loads((ROOT / 'tests/fixtures/unequal_line_corpus_20260925.json').read_text(encoding='utf-8'))
ALERTS = {m['id']: m['text'] for m in CORPUS['messages']}
ANYANG_TOTALS = ALERTS[1160]      # Totals: Pinnacle 165, Bet365 160.5 -> OVER +4.5 favourable, UNDER -4.5
ANYANG_SPREAD = ALERTS[1157]      # Spread: Pinnacle home +1, Bet365 home +4.5 -> HOME +3.5 favourable, AWAY -3.5
WNBA_AMBIGUOUS = ALERTS[993]      # Bet365 spread equals Pinnacle as displayed but "not equal lines" reported


def highlight(text, position):
    """Bold the Bet365 price at position 0/1, as OddsNotifier does on equal-line alerts."""
    import re
    m = re.search(r'(\[?Bet365[^\n]*\n)([0-9.]+)( - )([0-9.]+)', text)
    first, second = m[2], m[4]
    if position == 0:
        first = f'**{first}**'
    else:
        second = f'**{second}**'
    return text[:m.start()] + m[1] + first + m[3] + second + text[m.end():]


def side(parsed, name):
    return next(s for s in parsed['sides'] if s['side'] == name)


def decide(parsed, cfg=None, now=T0):
    return evaluate(parsed, cfg or config(), instruction_id='audit', received_at=now.isoformat(), now=now)


class LineComparisonMatrix(unittest.TestCase):
    def test_equal_lines_use_price_and_supplied_ev(self):
        p = interpret(MELBOURNE['raw_text'])['parsed']
        self.assertEqual((p['comparison']['equal_line'], p['price_quality'], p['bet_quality']), (True, FAVOURABLE, 'CLEAR_VALUE_SIGNAL'))
        self.assertEqual(p['comparison']['ev_status'], 'SUPPLIED_EQUAL_LINE')
        self.assertEqual(decide(p)['decision'], 'ACCEPT')

    def test_over_lower_total_is_better(self):
        better = compare_side('TOTALS', 'OVER', '165', '1.81', '160.5', '1.83')
        worse = compare_side('TOTALS', 'OVER', '165', '1.81', '169.5', '1.83')
        self.assertEqual((better['line_quality'], better['line_advantage'], better['price_quality']), (FAVOURABLE, '4.5', NOT_COMPARABLE))
        self.assertEqual((worse['line_quality'], worse['line_advantage']), (UNFAVOURABLE, '-4.5'))

    def test_under_higher_total_is_better(self):
        better = compare_side('TOTALS', 'UNDER', '165', '1.93', '169.5', '1.83')
        worse = compare_side('TOTALS', 'UNDER', '165', '1.93', '160.5', '1.83')
        self.assertEqual((better['line_quality'], better['line_advantage']), (FAVOURABLE, '4.5'))
        self.assertEqual((worse['line_quality'], worse['line_advantage']), (UNFAVOURABLE, '-4.5'))

    def test_selected_team_spread_higher_signed_handicap_is_better(self):
        # home +1 at Pinnacle, +4.5 at Bet365: HOME gains 3.5 points; the AWAY side (-1 vs -4.5) loses 3.5
        home = compare_side('SPREAD', 'HOME', '+1', '1.77', '+4.5', '1.83')
        away = compare_side('SPREAD', 'AWAY', '-1', '1.98', '-4.5', '1.83')
        self.assertEqual((home['line_quality'], home['line_advantage']), (FAVOURABLE, '3.5'))
        self.assertEqual((away['line_quality'], away['line_advantage']), (UNFAVOURABLE, '-3.5'))
        # favourite side: -3 at Pinnacle vs -1.5 at Bet365 is +1.5 for that team
        self.assertEqual(compare_side('SPREAD', 'HOME', '-3', '1.9', '-1.5', '1.9')['line_advantage'], '1.5')

    def test_prices_are_never_compared_across_unequal_lines(self):
        c = compare_side('TOTALS', 'OVER', '165', '1.50', '160.5', '2.50')
        self.assertEqual(c['price_quality'], NOT_COMPARABLE)
        self.assertIsNone(c['price_difference'])

    def test_bet_quality_needs_a_target_and_no_ev_is_invented(self):
        c = compare_side('TOTALS', 'OVER', '165', '1.81', '160.5', '1.83')
        kw = dict(verified=True, bet365_present=True, ev_status='NOT_AVAILABLE_UNEQUAL_LINES', supplied_ev=None)
        self.assertEqual(bet_quality(c, is_target=True, **kw), 'FAVOURABLE_LINE_SIGNAL')
        self.assertEqual(bet_quality(c, is_target=False, **kw), 'POTENTIAL_VALUE')
        worse = compare_side('TOTALS', 'OVER', '165', '1.81', '169.5', '1.83')
        self.assertEqual(bet_quality(worse, is_target=True, **kw), 'UNFAVOURABLE')
        # an unequal line can never be a CLEAR_VALUE_SIGNAL, whatever EV text arrives
        self.assertNotEqual(bet_quality(c, is_target=True, verified=True, bet365_present=True, ev_status='SUPPLIED_EQUAL_LINE', supplied_ev='120'), 'CLEAR_VALUE_SIGNAL')


class RealFeedUnequalLineAlerts(unittest.TestCase):
    def test_feed_fact_no_unequal_line_alert_carries_a_highlighted_target(self):
        self.assertGreaterEqual(len(ALERTS), 6)
        for mid, text in ALERTS.items():
            with self.subTest(message=mid):
                self.assertIn('EV: None (not equal lines)', text)
                self.assertNotIn('**', text)

    def test_real_alerts_get_an_implied_target_only_when_the_lines_single_out_a_side(self):
        # 2026-09-25: the implied favourable-side rule. Every stored alert whose lines single out one side by >= 1.0
        # is PARSED with that side as the target; the spread whose sign reference is ambiguous stays AMBIGUOUS.
        parsed_ids = []
        for mid, text in ALERTS.items():
            v = alert_classifier.classify(text)
            with self.subTest(message=mid, status=v['status']):
                p = v['parsed']
                self.assertIsNone(p['displayed_ev_percent'])                       # no synthetic EV, ever
                self.assertEqual(p['comparison']['ev_status'], 'NOT_AVAILABLE_UNEQUAL_LINES')
                if v['status'] == 'AMBIGUOUS':
                    self.assertIsNone(p['selection_side'])
                    continue
                self.assertEqual(v['status'], 'PARSED', v['reason'])
                fav = [s for s in p['sides'] if s['line_quality'] == FAVOURABLE]
                unf = [s for s in p['sides'] if s['line_quality'] == UNFAVOURABLE]
                self.assertEqual((len(fav), len(unf)), (1, 1))                       # exactly one side benefits
                self.assertEqual((p['selection_side'], p['target_price_source']), (fav[0]['side'], 'implied_favourable_line'))
                self.assertEqual((fav[0]['bet_quality'], unf[0]['bet_quality']), ('FAVOURABLE_LINE_SIGNAL', 'UNFAVOURABLE'))
                self.assertGreaterEqual(float(fav[0]['comparison']['line_advantage']), 1.0)
                self.assertIn('target implied from the favourable Bet365 line', v['reason'])
                parsed_ids.append(mid)
        self.assertGreaterEqual(len(parsed_ids), 6)
        with tempfile.TemporaryDirectory() as tmp:
            p = pipeline(Path(tmp) / 'audit.sqlite3', Clock())
            created = 0
            for n, (mid, text) in enumerate(ALERTS.items()):
                result = p.ingest(message(MELBOURNE, message_id=str(910000 + n), text=text))
                if mid in parsed_ids:
                    self.assertIn(result['status'], ('PARSED', 'DUPLICATE'), mid)   # same selection twice = duplicate
                    created += result['status'] == 'PARSED'
                else:
                    self.assertIsNone(result['instruction_id'], mid)
            with p.store.connection() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM instructions').fetchone()[0], created)
            self.assertGreaterEqual(created, 4)

    def test_anyang_totals_direction(self):
        p = alert_classifier.classify(ANYANG_TOTALS)['parsed']
        over, under = side(p, 'OVER'), side(p, 'UNDER')
        self.assertEqual((over['line_quality'], over['comparison']['line_advantage']), (FAVOURABLE, '4.5'))
        self.assertEqual((under['line_quality'], under['comparison']['line_advantage']), (UNFAVOURABLE, '-4.5'))

    def test_anyang_spread_direction_uses_the_selected_team_handicap(self):
        p = alert_classifier.classify(ANYANG_SPREAD)['parsed']
        home, away = side(p, 'HOME'), side(p, 'AWAY')
        self.assertEqual((home['reference']['line'], home['comparison']['bet365_line'], home['line_quality'], home['comparison']['line_advantage']),
                         ('1', '4.5', FAVOURABLE, '3.5'))
        self.assertEqual((away['reference']['line'], away['comparison']['bet365_line'], away['line_quality'], away['comparison']['line_advantage']),
                         ('-1', '-4.5', UNFAVOURABLE, '-3.5'))

    def test_counterfactual_highlighted_favourable_side_qualifies_without_ev(self):
        for text, pos, want in ((ANYANG_TOTALS, 0, ('OVER', '160.5', '4.5', '1.83')), (ANYANG_SPREAD, 0, ('HOME', '4.5', '3.5', '1.83'))):
            with self.subTest(side=want[0]):
                v = alert_classifier.classify(highlight(text, pos))
                self.assertEqual(v['status'], 'PARSED')
                p = v['parsed']
                self.assertEqual((p['selection_side'], p['selection_line'], p['comparison']['line_advantage'], p['alert_price']), want)
                self.assertEqual((p['bet_quality'], p['comparison']['ev_status'], p['displayed_ev_percent']),
                                 ('FAVOURABLE_LINE_SIGNAL', 'NOT_AVAILABLE_UNEQUAL_LINES', None))
                received = datetime(2026, 9, 25, 5, 0, tzinfo=timezone.utc)   # before the 07:30 tip-off
                decision = decide(p, now=received)
                self.assertEqual(decision['decision'], 'ACCEPT', decision['reason'])
                self.assertIsNone(decision['instruction']['displayed_ev_percent'])
                self.assertEqual(decision['instruction']['ev_status'], 'NOT_AVAILABLE_UNEQUAL_LINES')
                # even with a minimum EV configured for the market, a line signal is not judged on an EV it does not have
                cfg = config()
                cfg['sports']['basketball']['markets'][p['market']]['minimum_ev'] = 105
                with_ev_rule = decide(p, cfg=cfg, now=received)
                self.assertEqual(with_ev_rule['decision'], 'ACCEPT', with_ev_rule['reason'])
                self.assertIn('not applicable', next(c['detail'] for c in with_ev_rule['checks'] if c['name'] == 'minimum_ev'))

    def test_counterfactual_highlighted_unfavourable_side_never_qualifies(self):
        for text, pos in ((ANYANG_TOTALS, 1), (ANYANG_SPREAD, 1)):
            v = alert_classifier.classify(highlight(text, pos))
            self.assertEqual(v['status'], 'PARSED')
            self.assertEqual(v['parsed']['bet_quality'], 'UNFAVOURABLE')
            self.assertTrue(decide(v['parsed'])['reason'].startswith('bet_quality'))

    def test_immaterial_advantage_is_rejected_by_the_rules_not_the_parser(self):
        half = ANYANG_TOTALS.replace('Bet365 (Totals 160.5)', 'Bet365 (Totals 164.5)')   # OVER +0.5
        p = alert_classifier.classify(highlight(half, 0))['parsed']
        self.assertEqual((p['bet_quality'], p['comparison']['line_advantage']), ('FAVOURABLE_LINE_SIGNAL', '0.5'))
        self.assertTrue(decide(p)['reason'].startswith('line_advantage'))

    def test_ambiguous_target_fails_closed(self):
        both = ANYANG_TOTALS.replace('1.83 - 1.83', '**1.83** - **1.83**')
        v = alert_classifier.classify(both)
        self.assertNotEqual(v['status'], 'PARSED')
        self.assertIsNone(v['parsed']['selection_side'])
        # spread whose sign reference cannot be normalised stays AMBIGUOUS even with a highlight
        for pos in (0, 1):
            v = alert_classifier.classify(highlight(WNBA_AMBIGUOUS, pos))
            self.assertEqual(v['status'], 'AMBIGUOUS')
            self.assertTrue(decide(v['parsed'])['decision'] != 'ACCEPT')


if __name__ == '__main__':
    unittest.main()
