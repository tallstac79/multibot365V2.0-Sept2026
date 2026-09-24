"""Market interpretation matrix: totals/spread/moneyline direction, unequal lines, movement,
bet quality, genuine production formats (Feed 2 live corpus, HJK Helsinki vs Brann, Kipina)
and fail-closed safety cases. Pure parsing; no network, device or bookmaker access."""
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from core import alert_classifier
from core.market_interpretation import (compare_side, bet_quality, interpret, FAVOURABLE, EQUAL, UNFAVOURABLE,
                                        UNKNOWN, NOT_COMPARABLE)
from core.oddsnotifier_parser import parse_oddsnotifier
from core.pipeline_store import Store
from core.rules_engine import evaluate
from tests.pipeline_support import ROOT, SNAPSHOT, MELBOURNE, RYTAS, T0, Clock, config, message, pipeline

FIXTURES = ROOT / 'tests/fixtures'
HJK = (FIXTURES / 'oddsnotifier_football_hjk_brann_real.txt').read_text(encoding='utf-8')
KIPINA = (FIXTURES / 'oddsnotifier_basketball_kipina_unequal_real.txt').read_text(encoding='utf-8')
CORPUS = {m['message_id']: m['text'] for m in json.loads(
    (FIXTURES / 'oddsnotifier_feed2_live_corpus.json').read_text(encoding='utf-8'))['messages']}


def parse(text):
    return interpret(text)


def side(parsed, name):
    return next(s for s in parsed['sides'] if s['side'] == name)


class TotalsTests(unittest.TestCase):
    def test_equal_lines_compare_price_and_keep_supplied_ev(self):
        r = parse(MELBOURNE['raw_text'])
        self.assertEqual(r['status'], 'PARSED')
        p = r['parsed']
        self.assertEqual((p['selection_side'], p['selection_line'], p['comparison']['equal_line']), ('OVER', '190.5', True))
        self.assertEqual((p['line_quality'], p['price_quality'], p['bet_quality']), (EQUAL, FAVOURABLE, 'CLEAR_VALUE_SIGNAL'))
        self.assertEqual((p['comparison']['ev_status'], p['comparison']['supplied_ev']), ('SUPPLIED_EQUAL_LINE', '113.52'))
        self.assertEqual((p['reference']['odds'], p['comparison']['bet365_odds']), ('1.840', '2.20'))
        under = side(p, 'UNDER')
        self.assertEqual((under['price_quality'], under['bet_quality']), (UNFAVOURABLE, 'UNFAVOURABLE'))

    def test_direction_matrix(self):
        cases = [('OVER', '168.5', '165.5', FAVOURABLE, '3.0'), ('OVER', '168.5', '171.5', UNFAVOURABLE, '-3.0'),
                 ('UNDER', '168.5', '171.5', FAVOURABLE, '3.0'), ('UNDER', '168.5', '165.5', UNFAVOURABLE, '-3.0'),
                 ('OVER', '168.5', '168.5', EQUAL, '0.0')]
        for name, ref, b365, quality, advantage in cases:
            with self.subTest(side=name, bet365=b365):
                c = compare_side('TOTALS', name, ref, '1.90', b365, '1.90')
                self.assertEqual((c['line_quality'], c['line_advantage']), (quality, advantage))
                self.assertEqual(c['price_quality'], EQUAL if quality == EQUAL else NOT_COMPARABLE)

    def test_kipina_unequal_lines_and_ev_none_is_partial_with_both_sides(self):
        r = parse(KIPINA)
        self.assertEqual(r['status'], 'PARSED_PARTIAL')
        p = r['parsed']
        self.assertIsNone(p['selection_side'])
        self.assertEqual((p['comparison']['ev_status'], p['comparison']['equal_line'], p['comparison']['line_difference']),
                         ('NOT_AVAILABLE_UNEQUAL_LINES', False, '2.0'))
        over, under = side(p, 'OVER'), side(p, 'UNDER')
        self.assertEqual((over['comparison']['reference_line'], over['reference']['odds'],
                          over['comparison']['bet365_line'], over['comparison']['bet365_price']), ('166.5', '1.751', '168.5', '1.83'))
        self.assertEqual((under['reference']['odds'], under['comparison']['bet365_price']), ('1.917', '1.83'))
        self.assertEqual((over['line_quality'], over['comparison']['line_advantage'], over['price_quality'],
                          over['bet_quality']), (UNFAVOURABLE, '-2.0', NOT_COMPARABLE, 'UNFAVOURABLE'))
        self.assertEqual((under['line_quality'], under['comparison']['line_advantage'], under['price_quality'],
                          under['bet_quality']), (FAVOURABLE, '2.0', NOT_COMPARABLE, 'POTENTIAL_VALUE'))
        self.assertNotEqual(r['status'], 'INVALID')

    def test_line_movement_up_and_down_separate_from_price(self):
        up = parse(KIPINA)['parsed']['market_movement']
        self.assertEqual((up['previous_line'], up['current_line'], up['line_change'], up['line_direction']),
                         ('165.5', '166.5', '1.0', 'UP'))
        self.assertEqual((up['opening_line'], up['opening_line_change']), ('170.5', '-4.0'))
        down = parse(CORPUS['68020'])['parsed']
        self.assertEqual((down['market_movement']['line_change'], down['market_movement']['line_direction']), ('-1.0', 'DOWN'))
        over = side(parse(KIPINA)['parsed'], 'OVER')['movement']
        self.assertEqual((over['price_direction'], over['opening_price'], over['current_price'],
                          over['previous_price_displayed']), ('SHORTENED', '1.806', '1.751', '1.769'))
        self.assertEqual(side(parse(KIPINA)['parsed'], 'UNDER')['movement']['price_direction'], 'DRIFTED')

    def test_live_unequal_totals_without_transition(self):
        p = parse(CORPUS['68017'])['parsed']            # Pinnacle 160.5, Bet365 165.5
        self.assertEqual((side(p, 'OVER')['line_quality'], side(p, 'UNDER')['line_quality']), (UNFAVOURABLE, FAVOURABLE))
        self.assertEqual(side(p, 'UNDER')['comparison']['line_advantage'], '5.0')
        self.assertIsNone(p['market_movement']['line_change'])


class SpreadTests(unittest.TestCase):
    def test_selected_team_perspective_matrix(self):
        cases = [('-8.5', '-6.5', FAVOURABLE, '2.0'), ('-8.5', '-10.5', UNFAVOURABLE, '-2.0'),
                 ('+6.5', '+8.5', FAVOURABLE, '2.0'), ('+6.5', '+4.5', UNFAVOURABLE, '-2.0'), ('-3', '-3', EQUAL, '0')]
        for ref, b365, quality, advantage in cases:
            for name in ('HOME', 'AWAY'):
                with self.subTest(ref=ref, bet365=b365, side=name):
                    c = compare_side('SPREAD', name, ref, '1.90', b365, '1.95')
                    self.assertEqual((c['line_quality'], c['line_advantage']), (quality, advantage))

    def test_home_selection_equal_line(self):
        p = parse(RYTAS['raw_text'])['parsed']
        self.assertEqual((p['selection_side'], p['selection_name'], p['selection_line']), ('HOME', 'Rytas Vilnius', '-18.5'))
        self.assertEqual((p['line_quality'], p['price_quality'], p['bet_quality']), (EQUAL, FAVOURABLE, 'CLEAR_VALUE_SIGNAL'))
        self.assertEqual(p['alternate_line'], {'current': True, 'opening': False, 'comparison': False})
        self.assertEqual(side(p, 'AWAY')['comparison']['reference_line'], '+18.5')

    def test_away_selection_inverts_displayed_home_line(self):
        r = parse(CORPUS['68000'])                     # Spread (12), bold second price
        p = r['parsed']
        self.assertEqual(r['status'], 'PARSED')
        self.assertEqual((p['selection_side'], p['selection_name'], p['selection_line']),
                         ('AWAY', 'NBA G League United', '-12'))
        self.assertEqual((p['reference']['line'], p['reference']['odds'], p['comparison']['bet365_odds']), ('-12', '1.558', '1.83'))
        self.assertEqual(p['bet_quality'], 'CLEAR_VALUE_SIGNAL')

    def test_inverse_sign_normalisation_for_unequal_lines(self):
        p = parse(CORPUS['68014'])['parsed']           # Spread (9.5 -> 10), Bet365 4.5
        home, away = side(p, 'HOME'), side(p, 'AWAY')
        self.assertEqual((home['comparison']['reference_line'], home['comparison']['bet365_line']), ('10', '4.5'))
        self.assertEqual((away['comparison']['reference_line'], away['comparison']['bet365_line']), ('-10', '-4.5'))
        self.assertEqual((home['line_quality'], home['comparison']['line_advantage']), (UNFAVOURABLE, '-5.5'))
        self.assertEqual((away['line_quality'], away['comparison']['line_advantage']), (FAVOURABLE, '5.5'))
        self.assertEqual(away['movement']['previous_line'], '-9.5')

    def test_spread_equal_as_displayed_but_reported_unequal_is_ambiguous(self):
        r = parse(CORPUS['68027'])                     # WNBA: Spread (-2) vs Bet365 (Spread -2), EV None
        self.assertEqual(r['status'], 'AMBIGUOUS')
        self.assertIn('cannot be normalised safely', r['reason'])

    def test_alt_line_and_unlinked_fixture(self):
        r = parse(CORPUS['68079'])                     # unlinked fixture row, bold second price
        self.assertEqual(r['status'], 'PARSED')
        self.assertEqual((r['parsed']['fixture_url'], r['parsed']['selection_side'], r['parsed']['selection_line']),
                         (None, 'AWAY', '-22.5'))


class MoneylineTests(unittest.TestCase):
    def test_same_outcome_price_only(self):
        for market, name in (('MONEYLINE', 'HOME'), ('1X2', 'DRAW'), ('1X2', 'AWAY')):
            with self.subTest(market=market, side=name):
                higher = compare_side(market, name, None, '2.10', None, '2.25')
                self.assertEqual((higher['line_applicable'], higher['line_quality'], higher['price_quality']),
                                 (False, EQUAL, FAVOURABLE))
                self.assertEqual(compare_side(market, name, None, '2.10', None, '2.00')['price_quality'], UNFAVOURABLE)
                self.assertEqual(compare_side(market, name, None, '2.10', None, '2.10')['price_quality'], EQUAL)
                self.assertEqual(compare_side(market, name, None, '2.10', None, None)['price_quality'], UNKNOWN)

    def test_live_moneyline_ordering_stays_ambiguous(self):
        for message_id in ('68001', '68005'):
            verdict = alert_classifier.classify(CORPUS[message_id])
            self.assertEqual(verdict['status'], 'AMBIGUOUS')
            self.assertIn('UNSUPPORTED_MAPPING: basketball MONEYLINE', verdict['reason'])


class FootballProductionTests(unittest.TestCase):
    def test_hjk_brann_expected_interpretation(self):
        r = parse(HJK)
        self.assertEqual(r['status'], 'PARSED_PARTIAL')
        p = r['parsed']
        expected = dict(sport='football', competition_full='UEFA - Europa Cup Women', country='UEFA',
                        competition='Europa Cup Women', home='HJK Helsinki', away='Brann', market='SPREAD',
                        selection_side='AWAY', selection_name='Brann', selection_line='-1.5',
                        scheduled_at_local='2026-09-23T15:30')
        for key, value in expected.items():
            self.assertEqual(p[key], value, key)
        m = p['movement']
        self.assertEqual((m['opening_price'], m['current_price'], m['price_direction'], m['price_change_percent']),
                         ('2.030', '1.724', 'SHORTENED', -11.7))
        self.assertEqual(m['price_change_basis'], 'SUPPLIED_BY_ODDSNOTIFIER_BASE_UNSPECIFIED')
        self.assertEqual(m['opening_to_current_price_change_percent'], -15.07)
        self.assertEqual((p['reference']['bookmaker'], p['reference']['odds'], p['reference']['fair_odds']),
                         ('Pinnacle', '1.724', '1.850'))
        self.assertEqual(p['limit'], dict(previous='200', current='400', currency='EUR', changed_at_text='just now'))
        self.assertFalse(p['comparison']['bet365_present'])
        self.assertEqual((p['comparison']['bet365_odds'], p['comparison']['ev_status']), (None, 'MISSING'))
        self.assertEqual((p['line_quality'], p['price_quality'], p['bet_quality']),
                         (UNKNOWN, UNKNOWN, 'INSUFFICIENT_INFORMATION'))
        self.assertIsNone(p['target_side'])

    def test_missing_bet365_stays_partial_in_pipeline_without_instruction(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pipeline(Path(tmp) / 'p.sqlite3', Clock())
            result = p.ingest(message(MELBOURNE, message_id='900001', text=HJK))
            self.assertEqual((result['status'], result['instruction_id']), ('PARSED_PARTIAL', None))
            with p.store.connection() as db:
                row = db.execute('SELECT status, normalized FROM intake_messages').fetchone()
            self.assertEqual(json.loads(row['normalized'])['selection_name'], 'Brann')

    def test_unverified_football_two_sided_keeps_market_data_without_sides(self):
        r = parse((FIXTURES / 'oddsnotifier_spread.txt').read_text(encoding='utf-8'))
        self.assertEqual(r['status'], 'AMBIGUOUS')
        self.assertIn('UNSUPPORTED_MAPPING: football SPREAD', r['reason'])
        self.assertEqual(r['parsed']['sides'], [])
        self.assertEqual((r['parsed']['comparison']['equal_line'], r['parsed']['comparison']['ev_status']),
                         (True, 'SUPPLIED_EQUAL_LINE'))


class BetQualityTests(unittest.TestCase):
    def quality(self, line, price, **kw):
        values = dict(verified=True, bet365_present=True, is_target=True, ev_status='SUPPLIED_EQUAL_LINE', supplied_ev='108')
        values.update(kw)
        advantage = values.pop('advantage', None)
        return bet_quality(dict(line_quality=line, price_quality=price, line_advantage=advantage), **values)

    def test_line_quality_is_not_bet_quality(self):
        unequal = dict(ev_status='NOT_AVAILABLE_UNEQUAL_LINES', supplied_ev=None)
        self.assertEqual(self.quality(FAVOURABLE, NOT_COMPARABLE, advantage='3.0', **unequal), 'FAVOURABLE_LINE_SIGNAL')
        self.assertEqual(self.quality(FAVOURABLE, NOT_COMPARABLE, advantage='3.0', is_target=False, **unequal),
                         'POTENTIAL_VALUE')                                   # no target side
        self.assertEqual(self.quality(FAVOURABLE, UNKNOWN, advantage='3.0', **unequal), 'POTENTIAL_VALUE')  # price missing
        self.assertEqual(self.quality(FAVOURABLE, NOT_COMPARABLE, advantage=None, **unequal), 'POTENTIAL_VALUE')
        self.assertEqual(self.quality(FAVOURABLE, NOT_COMPARABLE, advantage='3.0', verified=False, **unequal),
                         'INSUFFICIENT_INFORMATION')                          # ordering unverified
        self.assertEqual(self.quality(EQUAL, FAVOURABLE), 'CLEAR_VALUE_SIGNAL')
        self.assertEqual(self.quality(EQUAL, FAVOURABLE, is_target=False), 'POTENTIAL_VALUE')
        self.assertEqual(self.quality(EQUAL, FAVOURABLE, supplied_ev='99.5'), 'POTENTIAL_VALUE')
        self.assertEqual(self.quality(EQUAL, EQUAL), 'NO_ADVANTAGE')
        self.assertEqual(self.quality(EQUAL, UNFAVOURABLE), 'UNFAVOURABLE')
        self.assertEqual(self.quality(UNFAVOURABLE, NOT_COMPARABLE), 'UNFAVOURABLE')
        self.assertEqual(self.quality(EQUAL, FAVOURABLE, verified=False), 'INSUFFICIENT_INFORMATION')
        self.assertEqual(self.quality(UNKNOWN, UNKNOWN), 'INSUFFICIENT_INFORMATION')

    def test_rules_engine_requires_clear_value_signal(self):
        p = parse(MELBOURNE['raw_text'])['parsed']
        self.assertEqual(evaluate(p, config(), instruction_id='x', received_at=T0.isoformat(), now=T0)['decision'], 'ACCEPT')
        for quality in ('POTENTIAL_VALUE', 'NO_ADVANTAGE', None):
            decision = evaluate(dict(p, bet_quality=quality), config(), instruction_id='x', received_at=T0.isoformat(), now=T0)
            self.assertEqual(decision['decision'], 'REJECT')
            self.assertTrue(decision['reason'].startswith('bet_quality'), decision['reason'])


def unequal_totals(pinnacle, bet365, bold):
    """Genuine Kipina layout with the lines and highlighted Bet365 position changed."""
    prices = '**1.83** - 1.90' if bold == 'OVER' else '1.90 - **1.83**' if bold == 'UNDER' else '1.83 - 1.90'
    return (KIPINA.replace('Totals (165.5 -> 166.5)', f'Totals ({pinnacle})')
            .replace('Bet365 (Totals 168.5)', f'Bet365 (Totals {bet365})').replace('1.83 - 1.83', prices))


class FavourableLineSignalTests(unittest.TestCase):
    def evaluate(self, parsed, cfg=None):
        return evaluate(parsed, cfg or config(), instruction_id='x', received_at=T0.isoformat(), now=T0)

    def test_user_examples_over_and_under(self):
        for pinnacle, bet365, target, advantage in (('168.5', '165.5', 'OVER', '3.0'), ('168.5', '171.5', 'UNDER', '3.0')):
            with self.subTest(target=target):
                r = parse(unequal_totals(pinnacle, bet365, target))
                p = r['parsed']
                self.assertEqual(r['status'], 'PARSED')
                self.assertIn('unequal lines evaluated directionally', r['reason'])
                self.assertEqual((p['selection_side'], p['selection_line'], p['line_quality'], p['price_quality']),
                                 (target, bet365, FAVOURABLE, NOT_COMPARABLE))
                self.assertEqual((p['bet_quality'], p['comparison']['line_advantage'], p['comparison']['ev_status'],
                                  p['displayed_ev_percent']),
                                 ('FAVOURABLE_LINE_SIGNAL', advantage, 'NOT_AVAILABLE_UNEQUAL_LINES', None))
                decision = self.evaluate(p)
                self.assertEqual(decision['decision'], 'ACCEPT', decision['reason'])
                self.assertEqual((decision['instruction']['signal_reason'], decision['instruction']['line_advantage'],
                                  decision['instruction']['side'], decision['instruction']['line']),
                                 ('FAVOURABLE_LINE_SIGNAL', advantage, target, bet365))

    def test_highlighted_side_with_worse_line_is_unfavourable(self):
        p = parse(unequal_totals('168.5', '171.5', 'OVER'))['parsed']
        self.assertEqual((p['bet_quality'], p['comparison']['line_advantage']), ('UNFAVOURABLE', '-3.0'))
        self.assertTrue(self.evaluate(p)['reason'].startswith('bet_quality'))

    def test_kipina_without_highlight_never_picks_under(self):
        r = parse(KIPINA)
        self.assertEqual(r['status'], 'PARSED_PARTIAL')
        self.assertIsNone(r['parsed']['selection_side'])
        self.assertEqual(side(r['parsed'], 'UNDER')['bet_quality'], 'POTENTIAL_VALUE')
        self.assertTrue(self.evaluate(r['parsed'])['reason'].startswith('explicit_target'))
        with tempfile.TemporaryDirectory() as tmp:
            result = pipeline(Path(tmp) / 'p.sqlite3', Clock()).ingest(message(MELBOURNE, message_id='900002', text=KIPINA))
            self.assertEqual((result['status'], result['instruction_id']), ('PARSED_PARTIAL', None))

    def test_line_signal_still_subject_to_price_and_materiality_rules(self):
        p = parse(unequal_totals('168.5', '171.5', 'UNDER'))['parsed']     # UNDER @ 1.83, +3.0
        self.assertTrue(self.evaluate(p, config(min_line_advantage=3.5))['reason'].startswith('line_advantage'))
        for bound, value in (('min_price', 1.9), ('max_price', 1.5)):
            cfg = config()
            cfg['sports']['basketball']['markets']['TOTALS'][bound] = value
            self.assertTrue(self.evaluate(p, cfg)['reason'].startswith(bound), bound)
        cfg = config(allowed_slippage=0.03)
        cfg['sports']['basketball']['markets']['TOTALS']['minimum_ev'] = 105
        decision = self.evaluate(p, cfg)
        self.assertEqual(decision['decision'], 'ACCEPT')
        self.assertEqual(decision['instruction']['minimum_price'], '1.80')
        self.assertIn('not applicable', next(c['detail'] for c in decision['checks'] if c['name'] == 'minimum_ev'))

    def test_default_minimum_line_advantage_is_one_point(self):
        from core.decision_support import defaults, validate
        self.assertEqual(defaults()['global']['min_line_advantage'], 1.0)
        half = parse(unequal_totals('168.5', '169', 'UNDER'))['parsed']        # +0.5
        self.assertEqual((half['bet_quality'], half['comparison']['line_advantage']), ('FAVOURABLE_LINE_SIGNAL', '0.5'))
        self.assertTrue(self.evaluate(half, config())['reason'].startswith('line_advantage'))
        one = parse(unequal_totals('168.5', '169.5', 'UNDER'))['parsed']       # +1.0
        self.assertEqual(self.evaluate(one, config())['decision'], 'ACCEPT')
        self.assertEqual(self.evaluate(half, config(min_line_advantage=0.5))['decision'], 'ACCEPT')  # still configurable
        legacy = defaults()
        del legacy['global']['min_line_advantage']
        self.assertEqual(validate(legacy)['global']['min_line_advantage'], 1.0)
        for bad in (0.4, 51):
            with self.assertRaises(ValueError):
                validate(config(min_line_advantage=bad))

    def test_equal_line_minimum_ev_still_enforced(self):
        cfg = config()
        cfg['sports']['basketball']['markets']['TOTALS']['minimum_ev'] = 120
        self.assertTrue(self.evaluate(parse(MELBOURNE['raw_text'])['parsed'], cfg)['reason'].startswith('minimum_ev'))

    def test_line_signal_reaches_queue_in_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pipeline(Path(tmp) / 'p.sqlite3', Clock())
            result = p.ingest(message(MELBOURNE, message_id='900003', text=unequal_totals('168.5', '171.5', 'UNDER')))
            self.assertEqual((result['status'], result['state']), ('PARSED', 'QUEUED'))
            with p.store.connection() as db:
                row = db.execute('SELECT selection, line, alert_price FROM instructions').fetchone()
            self.assertEqual(tuple(row), ('UNDER', '171.5', '1.83'))

    def test_spread_line_signal_uses_selected_team_line(self):
        text = CORPUS['68014'].replace('1.83 - 1.83', '1.83 - **1.83**')   # AWAY: -10 -> -4.5 (+5.5)
        p = parse(text)['parsed']
        self.assertEqual((p['selection_side'], p['selection_line'], p['bet_quality'], p['comparison']['line_advantage']),
                         ('AWAY', '-4.5', 'FAVOURABLE_LINE_SIGNAL', '5.5'))


class SafetyTests(unittest.TestCase):
    def test_unknown_ordering(self):
        for name in ('oddsnotifier_spread.txt', 'oddsnotifier_football_total.txt'):
            verdict = alert_classifier.classify((FIXTURES / name).read_text(encoding='utf-8'))
            self.assertEqual(verdict['status'], 'AMBIGUOUS', name)
            self.assertIsNone(verdict['parsed']['selection_side'])

    def test_ambiguous_highlighted_price(self):
        text = MELBOURNE['raw_text'].replace('- 1.65', '- **1.65**')
        self.assertEqual(parse(text)['status'], 'AMBIGUOUS')
        text = KIPINA.replace('1.751⬇️', '**1.751**⬇️')
        self.assertIn('Highlighted price in Pinnacle row', parse(text)['reason'])

    def test_missing_side(self):
        r = parse(HJK.replace('Spread (-1.5): Away 1.724', 'Spread (-1.5): 1.724'))
        self.assertEqual(r['status'], 'AMBIGUOUS')
        self.assertIn('not labelled', r['reason'])

    def test_contradictory_lines(self):
        cases = {
            'EV supplied although': KIPINA.replace('EV: None (not equal lines)', 'EV: 112.00%'),
            'Equal total lines': KIPINA.replace('Bet365 (Totals 168.5)', 'Bet365 (Totals 166.5)'),
            'Bet365 market conflicts': KIPINA.replace('Bet365 (Totals 168.5)', 'Bet365 (Spread 168.5)'),
            'Opening side conflicts': HJK.replace('Opening: Away', 'Opening: Home'),
            'impossible for SPREAD': HJK.replace('Away 1.724', 'Over 1.724'),
            'cannot be negative': KIPINA.replace('Totals (165.5 -> 166.5)', 'Totals (165.5 -> -166.5)'),
            'arrow conflicts': HJK.replace('[-11.7%]', '[+11.7%]'),
            'market conflicts with market label': CORPUS['67998'].replace('?market=Totals', '?market=Spread'),
        }
        for expected, text in cases.items():
            with self.subTest(expected):
                r = parse(text)
                self.assertEqual(r['status'], 'INVALID', r)
                self.assertIn(expected, r['reason'])

    def test_malformed(self):
        cases = [KIPINA.replace('1.83 - 1.83', '1.83 - 1.83 - 1.90'), KIPINA.replace('1.806 - 1.793', '0.95 - 1.793'),
                 KIPINA.replace('Kipina Basket vs Kauhajoki Karhu Basket', 'Kipina vs Kipina'),
                 KIPINA.replace('23.09.2026', '31.02.2026'), KIPINA + '\nUnexpected trailer row']
        for text in cases:
            with self.subTest(text=text[-60:]):
                self.assertEqual(alert_classifier.classify(text)['status'], 'INVALID')


class ProductionRegressionTests(unittest.TestCase):
    def test_snapshot_messages_match_verified_parser(self):
        keys = ('sport', 'country', 'competition', 'fixture', 'home', 'away', 'scheduled_at_local', 'market',
                'target_side', 'target_line', 'alert_price', 'displayed_ev_percent', 'alternate_line', 'fixture_url',
                'comparison_url')
        for sample in SNAPSHOT:
            new = parse(sample['raw_text'])['parsed']
            old = parse_oddsnotifier(sample['raw_text'], ordering_profile='oddsnotifier_basketball_v1')
            for key in keys:
                self.assertEqual(new[key], old[key], (sample['message_id'], key))
            for group in ('pinnacle', 'opening', 'comparison'):
                self.assertEqual([(q['side'], q['price'], q['line']) for q in new[group]['quotes']],
                                 [(q['side'], q['price'], q['line']) for q in old[group]['quotes']])

    def test_live_corpus_nothing_valid_is_invalid(self):
        statuses = {}
        for message_id, text in CORPUS.items():
            statuses[message_id] = alert_classifier.classify(text)['status']
        self.assertNotIn('INVALID', statuses.values(), {k: v for k, v in statuses.items() if v == 'INVALID'})
        self.assertEqual(statuses['67962'], 'PARSED')          # early heavily-bolded Telegram render
        self.assertEqual(statuses['67961'], 'AMBIGUOUS')       # no market label and no fixture link
        self.assertEqual(statuses['67998'], 'PARSED_PARTIAL')  # linked Kipina, EV None
        counts = {s: list(statuses.values()).count(s) for s in set(statuses.values())}
        self.assertGreaterEqual(counts['PARSED_PARTIAL'], 80)
        self.assertGreaterEqual(counts['PARSED'], 26)

    def test_every_live_parsed_alert_has_consistent_interpretation(self):
        for message_id, text in CORPUS.items():
            verdict = alert_classifier.classify(text)
            p = verdict['parsed']
            if verdict['status'] == 'PARSED':
                self.assertIsNotNone(p['selection_side'], message_id)
                if p['comparison']['equal_line']:
                    self.assertEqual(p['comparison']['ev_status'], 'SUPPLIED_EQUAL_LINE', message_id)
                    self.assertIn(p['bet_quality'], ('CLEAR_VALUE_SIGNAL', 'NO_ADVANTAGE', 'UNFAVOURABLE', 'POTENTIAL_VALUE'))
                else:
                    self.assertIn(p['bet_quality'], ('FAVOURABLE_LINE_SIGNAL', 'UNFAVOURABLE'), message_id)
            if verdict['status'] == 'PARSED_PARTIAL' and p['comparison']['ev_status'] == 'NOT_AVAILABLE_UNEQUAL_LINES':
                qualities = {s['side']: s['line_quality'] for s in p['sides']}
                self.assertEqual(sorted(qualities.values()), [FAVOURABLE, UNFAVOURABLE], message_id)
                advantages = [Decimal(s['comparison']['line_advantage']) for s in p['sides']]
                self.assertEqual(sum(advantages), 0, message_id)


class MigrationTests(unittest.TestCase):
    def test_v1_store_migrates_to_accept_parsed_partial(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'v1.sqlite3'
            from core import pipeline_store
            v1 = pipeline_store.SCHEMA.replace("'PARSED','PARSED_PARTIAL',", "'PARSED',")
            db = sqlite3.connect(path)
            db.executescript(v1)
            db.execute("INSERT INTO intake_messages(origin,source,chat_id,message_id,delivery,received_at,processed_at,status)"
                       " VALUES ('production','telegram','1','1','event','t','t','PARSED')")
            db.execute("INSERT INTO instructions(instruction_id,origin,intake_id,chat_id,message_id,selection_key,state,"
                       "updated_at) VALUES ('on-x','production',1,'1','1','k','QUEUED','t')")
            db.commit()
            db.close()
            store = Store(path)
            with store.tx() as db:
                db.execute("INSERT INTO intake_messages(origin,source,chat_id,message_id,delivery,received_at,processed_at,"
                           "status) VALUES ('production','telegram','1','2','event','t','t','PARSED_PARTIAL')")
            with store.connection() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM intake_messages').fetchone()[0], 2)
                self.assertEqual(db.execute('SELECT intake_id FROM instructions').fetchone()[0], 1)
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
                self.assertEqual(db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], '3')
            Store(path)  # idempotent re-open


if __name__ == '__main__':
    unittest.main()
