"""Football (Feed 1) interpretation: real alerts from tests/fixtures/feed1_football plus explicitly marked mutations.

Every price row below is quoted from the stored feed (26-27 Sep 2026). Nothing here touches the network or the phone.
"""
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import unittest

from core.alert_classifier import classify
from core.execution_terms import compare
from core.football import (VERSION, PROFILE_1X2, PROFILE_TWO_SIDED, sharp_signal_1x2, sharp_signal_two_sided, in_play_link)
from core.market_interpretation import interpret
from core.rules_engine import evaluate
from tools.football_audit import football_config, load_rows, replay

ROOT = Path(__file__).resolve().parents[1]
ROWS = {r['intake_id']: r for r in load_rows()}
FEED1 = '1645770730'


def parsed(intake_id):
    r = ROWS[intake_id]
    return classify(r['text'], channel_id=FEED1, message_id=r['message_id'], source_timestamp=r['source_timestamp'])


def decide(intake_id, cfg=None, alert=None):
    # Evaluated as if received live: Feed 1 was subscribed on 27 Sep 2026 and its backlog arrived by catch-up, so the stored
    # receipt times lag the source timestamps by many minutes (the rules engine would call those STALE).
    r = ROWS[intake_id]
    source = datetime.fromisoformat(r['source_timestamp'])
    received = (source + timedelta(seconds=5)).isoformat()
    return evaluate(alert or parsed(intake_id)['parsed'], cfg or football_config(), instruction_id='fb-test',
                    received_at=received, now=source + timedelta(seconds=30))


class OneXTwo(unittest.TestCase):
    def test_real_home_shortener_universitario_de_vinto(self):
        c = parsed(2083)                      # 2.090 (2.310) - 3.490 - 2.880 (2.560); Opening 2.440 - 2.450; Bet365 **2.88** - 3.50 - 2.15
        p = c['parsed']
        self.assertEqual(c['status'], 'PARSED')
        self.assertEqual((p['market'], p['interpretation_version'], p['quote_mapping']['profile']), ('1X2', VERSION, PROFILE_1X2))
        self.assertEqual([q['side'] for q in p['pinnacle']['quotes']], ['HOME', 'DRAW', 'AWAY'])
        self.assertEqual([q['side'] for q in p['opening']['quotes']], ['HOME', 'AWAY'])
        self.assertEqual([q['side'] for q in p['comparison']['quotes']], ['HOME', 'DRAW', 'AWAY'])
        self.assertEqual((p['target_side'], p['alert_price'], p['reference']['odds']), ('HOME', '2.88', '2.090'))
        self.assertEqual((p['highlighted_side'], p['displayed_ev_percent'], p['bet_quality']), ('HOME', '127.07', 'CLEAR_VALUE_SIGNAL'))
        self.assertEqual(p['football']['verdict'], 'EXECUTABLE_HOME')
        self.assertFalse(p['football']['draw_opening_supplied'])
        self.assertEqual(p['selection_name'], 'Universitario de Vinto')

    def test_real_away_shortener_honda_yscc(self):
        p = parsed(2161)['parsed']            # 1.917 (1.900) - 3.700 - 3.330 (3.370); Opening 1.543 - 4.570; Bet365 1.65 - 3.80 - **4.10**
        self.assertEqual((p['target_side'], p['alert_price'], p['football']['verdict']), ('AWAY', '4.10', 'EXECUTABLE_AWAY'))
        self.assertEqual(p['sharp_signal']['opening_prices'], {'HOME': '1.543', 'AWAY': '4.570'})
        self.assertEqual(p['selection_name'], 'YSCC Yokohama')

    def test_every_real_1x2_highlight_sits_on_the_unique_shortener(self):
        for intake_id in (2083, 2114, 2115, 2150, 2157, 2161, 2163):
            p = parsed(intake_id)['parsed']
            with self.subTest(intake=intake_id):
                self.assertEqual(p['highlighted_side'], p['target_side'])
                self.assertTrue(p['sharp_signal']['highlight_agrees'])

    def test_draw_needs_a_three_price_opening_and_is_never_inferred(self):
        cur = [dict(position=i + 1, price=v) for i, v in enumerate(('2.50', '3.00', '3.10'))]
        # two-price opening: the draw is not a candidate even when the feed's draw price moved
        s = sharp_signal_1x2([dict(position=1, price='2.20'), dict(position=2, price='3.40')], cur)
        self.assertEqual((s['side'], s['draw_opening_supplied']), ('AWAY', False))
        # three-price opening with the draw as the unique shortener: DRAW is selectable
        s = sharp_signal_1x2([dict(position=i + 1, price=v) for i, v in enumerate(('2.40', '3.60', '3.00'))], cur)
        self.assertEqual((s['side'], s['draw_opening_supplied']), ('DRAW', True))
        text = ROWS[2083]['text']
        current = next(l for l in text.splitlines() if l.startswith('2.090'))
        text = text.replace('2.440 - 2.450', '2.440 - 3.900 - 2.450').replace(current, '2.500 - 3.200 - 2.950') \
            .replace('**2.88** - 3.50 - 2.15', '2.30 - **3.60** - 2.90')       # MUTATION: synthetic three-price opening, only the draw shortens, Bet365 bold on the draw
        r = interpret(text)
        p = r['parsed']
        self.assertEqual(r['status'], 'PARSED', r['reason'])
        self.assertEqual((p['target_side'], p['selection_name'], p['alert_price'], p['football']['verdict']), ('DRAW', 'Draw', '3.60', 'EXECUTABLE_DRAW'))

    def test_opposing_highlight_never_switches_or_lends_ev(self):
        text = ROWS[2083]['text'].replace('**2.88** - 3.50 - 2.15', '2.00 - 3.50 - **3.20**')   # MUTATION: bold moved to AWAY, HOME offer worse than Pinnacle
        p = interpret(text)['parsed']
        self.assertEqual((p['target_side'], p['highlighted_side']), ('HOME', 'AWAY'))
        self.assertEqual(p['comparison']['ev_status'], 'SUPPLIED_FOR_OTHER_SIDE')
        self.assertEqual((p['bet_quality'], p['football']['verdict']), ('UNFAVOURABLE', 'NO_BET'))

    def test_both_shortening_or_no_movement_is_ambiguous(self):
        text = ROWS[2083]['text'].replace('2.440 - 2.450', '2.300 - 3.100')   # MUTATION: both HOME and AWAY shortened from opening
        r = interpret(text)
        self.assertEqual(r['status'], 'AMBIGUOUS')
        self.assertIn('No unique net shortener', r['reason'])

    def test_malformed_1x2_is_invalid(self):
        text = ROWS[2083]['text'].replace('**2.88** - 3.50 - 2.15', '**2.88** - 3.50')     # MUTATION: two Bet365 prices for a three-way market
        self.assertEqual(interpret(text)['status'], 'INVALID')


class AsianHandicap(unittest.TestCase):
    def test_real_equal_line_price_shortener_home(self):
        p = parsed(2081)['parsed']            # Spread (-1) (alt. line) 1.330 (1.374) - 2.940 (2.750); Opening (-1) 1.787 - 1.934; Bet365 (Spread -1) **1.80** - 2.00
        self.assertEqual((p['market'], p['quote_mapping']['profile']), ('SPREAD', PROFILE_TWO_SIDED))
        self.assertEqual((p['target_side'], p['target_line'], p['alert_price'], p['reference']['odds']), ('HOME', '-1', '1.80', '1.330'))
        self.assertEqual((p['football']['signal_basis'], p['bet_quality'], p['football']['verdict']), ('price_same_line', 'CLEAR_VALUE_SIGNAL', 'EXECUTABLE_HOME'))
        self.assertEqual([q['line'] for q in p['comparison']['quotes']], ['-1', '+1'])
        self.assertEqual(p['selection_name'], 'Halcones Negros')

    def test_real_equal_line_price_shortener_away(self):
        p = parsed(2098)['parsed']
        self.assertEqual((p['target_side'], p['football']['verdict']), ('AWAY', 'EXECUTABLE_AWAY'))
        self.assertEqual(p['selection_line'], '+1.5')

    def test_real_unequal_bet365_line_is_no_bet(self):
        p = parsed(2082)['parsed']            # Spread (-1.75) ... Bet365 (Spread -1) 1.80 - 2.00, EV None (not equal lines)
        self.assertEqual((p['target_side'], p['target_line']), ('HOME', '-1'))
        self.assertEqual((p['bet_quality'], p['football']['verdict']), ('POTENTIAL_VALUE', 'NO_BET'))
        self.assertEqual(decide(2082)['decision'], 'REJECT')

    def test_real_alternate_line_with_moved_main_line_is_ambiguous(self):
        for intake_id in (2176, 2188, 2190):   # Vihiga Queens: Opening (0.25/0.5) before Spread (0) (alt. line)
            r = parsed(intake_id)
            with self.subTest(intake=intake_id):
                self.assertEqual(r['status'], 'AMBIGUOUS')
                self.assertIn('alternate line', r['reason'])

    def test_line_move_selects_home_or_away_unless_prices_contradict(self):
        op = [dict(position=1, price='1.90'), dict(position=2, price='1.95')]
        cur = [dict(position=1, price='1.85'), dict(position=2, price='2.00')]
        s = sharp_signal_two_sided('SPREAD', '-0.75', '-1', current_alt=False, opening_quotes=op, current_quotes=cur)
        self.assertEqual((s['side'], s['basis'], s['magnitude_units']), ('HOME', 'line_move', 'goals'))
        s = sharp_signal_two_sided('SPREAD', '-1', '-0.75', current_alt=False, opening_quotes=op, current_quotes=cur)
        self.assertIsNone(s['side'])            # line says AWAY, prices shortened HOME: contradictory
        self.assertIn('contradictory', s['reason'])
        s = sharp_signal_two_sided('SPREAD', '-1', '-0.75', current_alt=True, opening_quotes=op, current_quotes=cur)
        self.assertIn('alternate line', s['reason'])

    def test_in_play_alert_without_opening_row_is_not_invalid(self):
        # Real Feed 1 intake 2249 (27 Sep 2026 10:58Z): "Spread (0)" current row, no Opening row, Bet365 in-play link
        text = ('New odds update on Pinnacle\n\nFootball - Spain - Segunda Federacion\n'
                '[Las Palmas Atletico vs Badajoz](https://oddshub.io/football/spain-segunda-federacion-group-iv/72508382?market=Spread)\n'
                '27.09.2026 12:00\n\nSpread (0)\n1.671⬇️ (1.787) - 2.180⬆️ (2.050)\n\n'
                '[Bet365 (Spread 0)](https://www.bet365.com/#/IP/EV151391432692C1)\n**2.03** - 1.78\n\n🎯 EV: 116.09%')
        r = interpret(text)
        self.assertNotEqual(r['status'], 'INVALID')
        self.assertIsNone(r['parsed']['target_side'])
        self.assertEqual(r['parsed']['football']['verdict'], 'AMBIGUOUS' if r['status'] == 'AMBIGUOUS' else 'NO_BET')
        self.assertTrue(r['parsed']['football']['in_play_link'])

    def test_in_play_link_is_no_bet(self):
        p = parsed(2123)['parsed']
        self.assertTrue(in_play_link(p['comparison_url']))
        self.assertEqual((p['target_side'], p['football']['verdict']), (None, 'NO_BET'))
        self.assertEqual(parsed(2123)['status'], 'PARSED_PARTIAL')


class Totals(unittest.TestCase):
    def test_real_under_shortener_guaynabo(self):
        p = parsed(2087)['parsed']            # Totals (2.5) (alt. line) 1.769 (1.598) - 1.909 (2.060); Opening (2.5) 1.383 - 2.680; Bet365 (Totals 2.5) 1.50 - **2.50**
        self.assertEqual((p['target_side'], p['target_line'], p['alert_price'], p['reference']['odds']), ('UNDER', '2.5', '2.50', '1.909'))
        self.assertEqual((p['bet_quality'], p['football']['verdict'], p['selection_name']), ('CLEAR_VALUE_SIGNAL', 'EXECUTABLE_UNDER', 'Under'))

    def test_real_over_shortener_with_equal_line(self):
        for intake_id, side in ((2087, 'UNDER'),):
            self.assertEqual(parsed(intake_id)['parsed']['target_side'], side)
        overs = [r for r in replay(list(ROWS.values())) if r['market'] == 'TOTALS' and r['verdict'] == 'EXECUTABLE_OVER']
        self.assertTrue(overs)
        self.assertTrue(all(o['bet_quality'] == 'CLEAR_VALUE_SIGNAL' for o in overs))

    def test_real_different_bet365_goal_line_is_no_bet(self):
        p = parsed(2189)['parsed']            # JaPS v PPJ: Totals (4.25) 1.763 (1.854) - 1.961 (1.884); Opening (4.25) 1.884 - 1.826; Bet365 (Totals 2.5) 1.22 - 4.00, EV None
        self.assertEqual((p['target_side'], p['bet_quality'], p['football']['verdict']), ('OVER', 'POTENTIAL_VALUE', 'NO_BET'))
        self.assertEqual(decide(2189)['decision'], 'REJECT')
        # the Halcones totals alert with the same shape carries an in-play link: no target at all
        p = parsed(2085)['parsed']
        self.assertEqual((p['target_side'], p['football']['in_play_link'], p['football']['verdict']), (None, True, 'NO_BET'))

    def test_in_play_totals_link_is_no_bet(self):
        p = parsed(2084)['parsed']
        self.assertEqual((p['target_side'], p['football']['verdict']), (None, 'NO_BET'))

    def test_total_line_move_selects_over_or_under(self):
        op = [dict(position=1, price='1.90'), dict(position=2, price='1.95')]
        cur = [dict(position=1, price='1.85'), dict(position=2, price='2.00')]
        self.assertEqual(sharp_signal_two_sided('TOTALS', '2.5', '2.75', current_alt=False, opening_quotes=op, current_quotes=cur)['side'], 'OVER')
        cur = [dict(position=1, price='2.00'), dict(position=2, price='1.85')]
        self.assertEqual(sharp_signal_two_sided('TOTALS', '2.75', '2.5', current_alt=False, opening_quotes=op, current_quotes=cur)['side'], 'UNDER')


class RulesAndCorpus(unittest.TestCase):
    def test_live_configuration_rejects_football_until_terms_are_set(self):
        from core.decision_support import defaults
        cfg = defaults(); cfg['global'].update(feed_timezone_verified=True, event_timezone='Europe/London')
        d = decide(2083, cfg)
        self.assertEqual(d['decision'], 'REJECT')
        self.assertTrue(d['reason'].startswith('execution_tolerances'))

    def test_audit_terms_accept_real_executables_and_bind_the_same_side(self):
        for intake_id in (2083, 2081, 2087):
            with self.subTest(intake=intake_id):
                d = decide(intake_id)
                self.assertEqual(d['decision'], 'ACCEPT', d['reason'])
                self.assertTrue(next(c for c in d['checks'] if c['name'] == 'football_same_side_offer')['passed'])
                self.assertEqual(d['instruction']['market'], parsed(intake_id)['parsed']['market'])
        i = decide(2083)['instruction']
        self.assertEqual((i['side'], i['line'], i['alert_price'], i['minimum_price'], i['max_line_deterioration']), ('HOME', None, '2.88', '2.70', None))

    def test_tampered_target_or_price_fails_closed(self):
        p = parsed(2083)['parsed']
        for field, value in (('target_side', 'AWAY'), ('alert_price', '2.15'), ('interpretation_version', 'sharp-money-1')):
            alert = copy.deepcopy(p); alert[field] = value
            with self.subTest(field=field):
                self.assertEqual(decide(2083, alert=alert)['decision'], 'REJECT')

    def test_live_terms_use_net_payout_and_no_handicap_for_1x2(self):
        r = dict(market='1X2', side='HOME', line=None, price='2.88')
        self.assertTrue(compare(r, dict(r, price='2.70'), net_percent=10)['acceptable'])
        self.assertFalse(compare(r, dict(r, price='2.69'), net_percent=10)['acceptable'])
        self.assertFalse(compare(r, dict(r, line='-0.5', price='2.90'), net_percent=10)['acceptable'])

    def test_whole_corpus_counts(self):
        rows = replay(list(ROWS.values()))
        self.assertEqual(len(rows), 72)
        verdicts = {}
        for r in rows:
            verdicts[(r['market'], r['verdict'])] = verdicts.get((r['market'], r['verdict']), 0) + 1
        self.assertEqual(verdicts[('1X2', 'EXECUTABLE_HOME')], 5)
        self.assertEqual(verdicts[('1X2', 'EXECUTABLE_AWAY')], 2)
        self.assertNotIn(('1X2', 'EXECUTABLE_DRAW'), verdicts)
        self.assertEqual(sum(n for (m, v), n in verdicts.items() if v == 'INVALID'), 0)
        self.assertTrue(all(r['in_play_link'] for r in rows if r['verdict'] == 'NO_BET' and r['target_side'] is None))
        # every executable verdict has its Bet365 price at the target's own position and an EV owned by that side
        for r in rows:
            if str(r['verdict']).startswith('EXECUTABLE'):
                self.assertEqual(r['highlighted_side'], r['target_side'], r)
                self.assertIsNotNone(r['displayed_ev'])

    def test_basketball_paths_are_untouched(self):
        # Feed 2 basketball fixtures keep their existing interpretation (spot checks against the stored snapshot)
        from tests.pipeline_support import MELBOURNE, RYTAS
        m = interpret(MELBOURNE['raw_text'])['parsed']
        self.assertEqual((m['sport'], m['target_side'], m['interpretation_version']), ('basketball', 'OVER', 'sharp-money-1'))
        r = interpret(RYTAS['raw_text'])['parsed']
        self.assertEqual((r['sport'], r['target_side'], r['target_line']), ('basketball', 'HOME', '-18.5'))


if __name__ == '__main__':
    unittest.main()
