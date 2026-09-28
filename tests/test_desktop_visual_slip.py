"""Desktop worker's visual betslip, offline: real screenshots of Bet365's desktop slip captured by the worker (28 Sep 2026),
read with Tesseract exactly as the live flow reads them; Bet365's addbet answers; and the slip checks (one selection,
fixture / market / selection / line on the screen AND in addbet, price judged by the phone's tolerances, Accept Change
never pressed). No browser, no network. OCR tests need Tesseract; the check tests need the decision bridge (JDK)."""
import json
import unittest
from pathlib import Path

from desktop_worker import visual_slip as vs

FIX = Path(__file__).parent / 'fixtures' / 'desktop' / 'slip'
ACCEPTED = json.dumps({"bg": "x", "at": 0, "cs": 1, "bs": [], "pc": "x", "cc": "x", "bt": [{"bt": 1, "fd": "Northern Ireland v Hungary", "od": "39/40",
                       "sa": "x", "pt": [{"bd": "Northern Ireland", "hd": "0.0", "md": "Asian Handicap"}], "cs": 0, "sr": 0}], "sr": 0})
REFUSED = '{"cs":2,"sr":-1}'


def shot(name):
    if not vs.TESSERACT.exists():
        raise unittest.SkipTest('Tesseract not installed')
    from PIL import Image
    return vs.read_slip(Image.open(FIX / f'{name}.png').convert('RGB'))


class ScreenReading(unittest.TestCase):
    def test_empty_slip_is_seen_as_empty(self):
        self.assertFalse(shot('empty')['present'])

    def test_selection_before_stake(self):
        s = shot('ah_home_selected')
        self.assertEqual((s['items'], s['title'], s['handicap'], s['price'], s['market'], s['fixture']),
                         (1, 'Northern Ireland', '0.0', '2.000', 'Asian Handicap', 'Northern Ireland v Hungary'))
        self.assertEqual(s['stake_control']['kind'], 'set_stake')
        self.assertFalse(s['place_bet']['enabled'])                 # grey until a stake is entered

    def test_footer_the_whole_panel_pass_missed_is_read_from_its_own_band(self):
        s = shot('set_stake_footer_hard')                           # live run proof-09 (Sweden 0.0): footer missed before
        self.assertEqual((s['title'], s['handicap'], s['price'], s['stake_control']['kind']), ('Sweden', '0.0', '1.450', 'set_stake'))
        self.assertFalse(s['place_bet']['enabled'])

    def test_staked_slips_asian_handicap_total_and_result(self):
        for name, want in (('ah_home_staked', ('Northern Ireland', '0.0', '2.000', 'Asian Handicap', '0.10', '0.20')),
                           ('total_over_staked', ('Over', '2.0', '1.900', 'Goal Line', '0.10', '0.19')),
                           ('ml_away_staked', ('France', None, '1.83', 'Full Time Result', '0.10', '0.18'))):
            s = shot(name)
            self.assertEqual((s['title'], s['handicap'], s['price'], s['market'], s['stake'], s['to_return']), want, name)
            self.assertTrue(s['place_bet']['enabled'], name)
            self.assertEqual(s['notices'], [], name)

    def test_a_frame_with_the_caret_over_the_stake_is_not_read_as_a_stake(self):
        self.assertIsNone(shot('ah_home_caret_frame')['stake'])     # '£0.1|' is never taken for 0.10 or 0.1


class Network(unittest.TestCase):
    def test_addbet_terms(self):
        a = vs.addbet_terms(ACCEPTED)
        self.assertTrue(a['accepted'])
        self.assertEqual(a['bets'][0]['selection'], 'Northern Ireland')
        self.assertAlmostEqual(a['bets'][0]['decimal'], 1.975)
        self.assertFalse(vs.addbet_terms(REFUSED)['accepted'])
        self.assertEqual(vs.fraction_decimal('1/1'), 2.0)
        self.assertAlmostEqual(vs.fraction_decimal('5/6'), 1.8333, places=3)

    def test_evidence_is_redacted(self):
        r = json.dumps(vs.redacted(ACCEPTED))
        self.assertNotIn('"x"', r)
        self.assertIn('Northern Ireland', r)


class SlipChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from desktop_worker.decisions import Decisions
            cls.d = Decisions()
        except Exception as e:
            raise unittest.SkipTest(f'decision bridge unavailable: {e}')
        from desktop_worker.workflow import DesktopBet365
        cls.site = DesktopBet365(None, cls.d)

    @classmethod
    def tearDownClass(cls):
        cls.d.close()

    class _Run:
        def __init__(self):
            self.record = {}
        def put(self, k, v):
            self.record[k] = v
        def observe(self, *a):
            pass

    def check(self, state, net=None, minimum='1.86'):
        expected = dict(market='SPREAD', side='HOME', line='0.0', price='1.975', raw_price='1.975', name='Northern Ireland', bounds=[0, 0, 0, 0])
        base = dict(present=True, items=1, title='Northern Ireland', handicap='0.0', price='1.975', market='Asian Handicap',
                    fixture='Northern Ireland v Hungary', notices=[])
        base.update(state)
        return self.site._check_slip(self._Run(), base, vs.addbet_terms(net or ACCEPTED), 'football', expected,
                                     ('Northern Ireland', 'Hungary'), '0.0', '0.25', minimum)

    def stage(self, **kw):
        from desktop_worker.workflow import Failure
        with self.assertRaises(Failure) as c:
            self.check(**kw)
        return c.exception.stage

    def test_matching_slip_passes(self):
        self.assertEqual(self.check({})['price'], '1.975')

    def test_total_goals_label_only_for_the_goals_over_under_group(self):
        net = ACCEPTED.replace('Asian Handicap', 'Total Goals').replace('"Northern Ireland", "hd": "0.0"', '"Over", "hd": "2.5"')
        expected = dict(market='TOTAL', side='OVER', line='2.5', price='1.975', raw_price='1.975', name='Over', bounds=[0, 0, 0, 0])
        state = dict(present=True, items=1, title='Over', handicap='2.5', price='1.975', market='Total Goals',
                     fixture='Northern Ireland v Hungary', notices=[])
        args = (vs.addbet_terms(net), 'football')
        ok = self.site._check_slip(self._Run(), state, *args, dict(expected, group='Goals Over/Under'), ('Northern Ireland', 'Hungary'), '2.5', '0.25', '1.50')
        self.assertEqual(ok['line'], '2.5')
        from desktop_worker.workflow import Failure
        with self.assertRaises(Failure) as c:
            self.site._check_slip(self._Run(), state, *args, dict(expected, group='Goal Line'), ('Northern Ireland', 'Hungary'), '2.5', '0.25', '1.50')
        self.assertEqual(c.exception.stage, 'WRONG_EVENT')

    def test_refusals(self):
        self.assertEqual(self.stage(state=dict(notices=['Accept Changes'])), 'PRICE_CHANGED')     # never pressed
        self.assertEqual(self.stage(state=dict(items=2)), 'BETSLIP_NOT_SINGLE')
        self.assertEqual(self.stage(state=dict(fixture='Wales v Hungary')), 'WRONG_EVENT')
        self.assertEqual(self.stage(state=dict(market='Goal Line')), 'WRONG_EVENT')
        self.assertEqual(self.stage(state=dict(title='Hungary')), 'SELECTION_CHANGED')
        self.assertEqual(self.stage(state=dict(handicap='+0.5')), 'LINE_CHANGED')             # screen and addbet disagree
        self.assertEqual(self.stage(state=dict(price='1.80')), 'PRICE_CHANGED')              # screen and addbet disagree
        low = ACCEPTED.replace('39/40', '4/5')                                               # both show 1.80 < minimum 1.86
        self.assertIn(self.stage(state=dict(price='1.80'), net=low), ('BELOW_MINIMUM', 'PRICE_CHANGED'))


if __name__ == '__main__':
    unittest.main()
