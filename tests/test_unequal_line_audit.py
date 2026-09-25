"""Unequal-line execution logic audit (2026-09-25) on REAL OddsNotifier alerts from the stored feed.

Properties asserted against the production code path (alert_classifier -> market_interpretation -> rules_engine):
  * equal lines: price / supplied-EV comparison (CLEAR_VALUE_SIGNAL)
  * unequal lines: compared by line quality for the selected side; OVER lower is better, UNDER higher is better,
    selected-team spread higher signed handicap is better
  * a favourable unequal line qualifies (FAVOURABLE_LINE_SIGNAL -> ACCEPT) with EV unavailable, no synthetic EV
  * an unfavourable unequal line never qualifies; an ambiguous target fails closed
  * Missing highlighting does not prevent a verified net Pinnacle movement from selecting the candidate.
    Bet365 value is assessed only after that candidate is established.
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
# the unequal-line ("EV: None") alerts of the shared corpus; the same fixture also holds a few contradictory / equal-line
# alerts used by tests/test_market_audit.py, which these feed-fact tests do not cover
ALERTS = {m['id']: m['text'] for m in CORPUS['messages'] if 'EV: None (not equal lines)' in m['text']}
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

    def test_real_alerts_select_from_pinnacle_opening_not_book_advantage(self):
        from decimal import Decimal
        parsed_count = 0
        for mid, text in ALERTS.items():
            with self.subTest(message=mid):
                v = alert_classifier.classify(text); p = v['parsed']
                self.assertIsNone(p['displayed_ev_percent'])
                if v['status'] == 'AMBIGUOUS':
                    self.assertIsNone(p['target_side']); continue
                delta = Decimal(p['pinnacle']['line']) - Decimal(p['opening']['line'])
                expected = ('HOME' if delta < 0 else 'AWAY') if p['market'] == 'SPREAD' else ('OVER' if delta > 0 else 'UNDER')
                self.assertEqual((p['target_side'], p['target_price_source']), (expected, 'pinnacle_opening_to_current'))
                parsed_count += 1
        self.assertGreater(parsed_count, 0)

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

    def test_counterfactual_highlight_preserves_sharp_candidate(self):
        for text in (ANYANG_TOTALS, ANYANG_SPREAD):
            original = alert_classifier.classify(text)['parsed']
            for prices in ('**1.83** - 1.83', '1.83 - **1.83**'):
                p = alert_classifier.classify(text.replace('1.83 - 1.83', prices))['parsed']
                self.assertEqual(p['target_side'], original['target_side'])
                self.assertIsNone(p['displayed_ev_percent'])

    def test_counterfactual_highlight_does_not_reverse_a_known_target(self):
        for text in (ANYANG_TOTALS, ANYANG_SPREAD):
            p = alert_classifier.classify(text)['parsed']
            changed = alert_classifier.classify(text.replace('1.83 - 1.83', '1.83 - **1.83**'))['parsed']
            self.assertEqual(changed['target_side'], p['target_side'])

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
