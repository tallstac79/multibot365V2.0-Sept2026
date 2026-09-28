"""Desktop Chrome worker, offline: page parsing on real captured Bet365 desktop pages (28 Sep 2026), the decision bridge
(the phone's own Java decisions), the at-most-once ledger and the coordinator admission contract. No browser, no network.
The bridge tests need a JDK (the same one the Android build uses) and are skipped without it."""
import json
import tempfile
import unittest
from pathlib import Path

from desktop_worker import bet365_page as bp
from desktop_worker.ledger import Ledger

FIX = Path(__file__).parent / 'fixtures' / 'desktop'


def words(name):
    return json.loads((FIX / f'{name}.json').read_text(encoding='utf-8'))['words']


def bridge():
    try:
        from desktop_worker.decisions import Decisions
        return Decisions()
    except Exception as e:                          # no JDK / Android SDK on this machine
        raise unittest.SkipTest(f'decision bridge unavailable: {e}')


class Header(unittest.TestCase):
    def test_football_header_is_the_phones_shape(self):
        self.assertEqual(bp.header(words('football_nir_hun_popular')), ['UEFA Nations League B • 28 Sep 19:45', 'Northern Ireland v Hungary'])

    def test_basketball_competition_and_date_rows_are_joined(self):
        self.assertEqual(bp.header(words('basketball_dubai_barcelona_popular')), ['Euroleague • 29 Sep 17:00', 'BC Dubai vs Barcelona'])

    def test_logged_out_is_seen(self):
        self.assertIs(bp.logged_in(words('football_nir_hun_popular')), False)

    def test_groups_start_below_the_tab_strip(self):
        titles = [g[0] for g in bp.groups(words('football_nir_hun_popular'))]
        self.assertEqual(titles[0], 'Full Time Result')
        self.assertNotIn('Northern Ireland v Hungary', titles)


class Markets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = bridge()

    @classmethod
    def tearDownClass(cls):
        cls.d.close()

    def quotes(self, name):
        return bp.football_quotes(words(name), 'Northern Ireland', 'Hungary', self.d.norm_line)

    def test_popular_full_time_result_and_totals(self):
        q = {(x['market'], x['side'], x['line']): x['raw_price'] for x in self.quotes('football_nir_hun_popular')}
        self.assertEqual(q[('MONEYLINE', 'HOME', '')], '9/5')
        self.assertEqual(q[('MONEYLINE', 'DRAW', '')], '2/1')
        self.assertEqual(q[('MONEYLINE', 'AWAY', '')], '17/10')
        self.assertEqual(q[('TOTAL', 'OVER', '2.5')], '6/4')
        self.assertEqual(q[('TOTAL', 'UNDER', '4.5')], '1/20')

    def test_asian_lines_read_as_the_phone_names_them(self):
        q = self.quotes('football_nir_hun_asian_lines')
        self.assertEqual([(x['market'], x['side'], x['line'], x['price']) for x in q],
                         [('SPREAD', 'HOME', '0.0', '1.950'), ('SPREAD', 'AWAY', '0.0', '1.850'),
                          ('TOTAL', 'OVER', '2.0', '1.900'), ('TOTAL', 'UNDER', '2.0', '1.900')])
        self.assertTrue(all(x['q'] is not None for x in q))     # every quote carries its click tag
        self.assertEqual([t for t, _ in bp.collapsed(words('football_nir_hun_asian_lines'), bp.FOOTBALL_AH + bp.FOOTBALL_TOTALS)],
                         ['Alternative Asian Handicap', 'Alternative Goal Line'])

    def test_fractional_prices_are_never_a_decimal_price(self):
        self.assertTrue(all(x['price'] is None for x in self.quotes('football_nir_hun_popular')))

    def test_basketball_game_lines(self):
        q = bp.basketball_quotes(words('basketball_dubai_barcelona_popular'), 'BC Dubai', 'Barcelona')
        self.assertEqual(sorted((x['market'], x['side'], x['line'], x['raw_price']) for x in q),
                         sorted([('SPREAD', 'HOME', '-5.5', '19/25'), ('SPREAD', 'AWAY', '+5.5', '10/11'), ('TOTAL', 'OVER', '169.5', '5/6'),
                                 ('TOTAL', 'UNDER', '169.5', '5/6'), ('MONEYLINE', 'HOME', '', '1/3'), ('MONEYLINE', 'AWAY', '', '41/20')]))
        self.assertEqual(bp.basketball_quotes(words('basketball_dubai_barcelona_popular'), 'Barcelona', 'BC Dubai'), [])   # rows not in order

    def test_the_phones_decisions_come_through_the_bridge(self):
        r = self.d.decide(bp.header(words('football_nir_hun_popular')), 'football', 'Northern Ireland', 'Hungary', '2026-09-28T18:45',
                          'UEFA Nations League B', None, True, False)
        self.assertEqual((r['verdict'], r['accepted'], r['competition_key']), ('EXACT', True, 'uefa nations league b'))
        wrong = self.d.decide(bp.header(words('football_nir_hun_popular')), 'football', 'Northern Ireland', 'Hungary', '2026-09-28T20:45',
                              'UEFA Nations League B', None, True, False)
        self.assertFalse(wrong['accepted'])                      # kick-off two hours out
        other = self.d.decide(bp.header(words('football_nir_hun_popular')), 'football', 'Wales', 'Hungary', '2026-09-28T18:45',
                              'UEFA Nations League B', None, True, False)
        self.assertFalse(other['accepted'])
        # the Wenzhou class (28 Sep 2026): a far line is never the quote for a 4.5 alert
        seen = [dict(market='TOTAL', side='OVER', line='2.5', price='1.20')]
        self.assertEqual(self.d.nearest(seen, 'TOTAL', 'OVER', '4.5', '0.25'), -1)
        self.assertIn('no line within 0.25', self.d.refusal(seen, 'TOTAL', 'OVER', '4.5', '0.25'))
        self.assertTrue(self.d.line_ok('basketball', 'TOTAL', 'OVER', '190.5', '185.5', '1'))       # basketball unchanged
        self.assertFalse(self.d.price_ok('1.76', '1.77'))


class LedgerAndAdmission(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'l.sqlite3'

    def worker(self):
        from desktop_worker.server import Worker
        return Worker(dict(port=0, token='t', worker_id='dw-test', account_fingerprint=None), ledger_path=self.path, start_executor=False)

    def hold(self, iid='on-1'):
        return dict(instruction_id=iid, action='ADAPTER_WORKFLOW', adapter='live_bet365', scenario='live', query='A||B', sport='football',
                    market='SPREAD', side='HOME', line='0.0', minimum_price='1.86', stake='0.10', timeout_ms=120000, execution_mode='hold')

    def test_ids_are_at_most_once_and_busy_does_not_consume(self):
        w = self.worker()
        self.assertEqual(w.submit(self.hold('on-1'))[0], 202)
        code, reply = w.submit(self.hold('on-2'))
        self.assertEqual((code, reply['stage']), (409, 'INTERNAL_ERROR'))
        self.assertIn('ID not consumed', reply['detail'])
        self.assertIsNone(w.ledger.get('on-2'))
        self.assertEqual(w.submit(self.hold('on-1'))[1]['stage'], 'DUPLICATE')

    def test_a_restart_never_replays_uncertain_work(self):
        w = self.worker()
        w.submit(self.hold('on-1'))
        w.submit(dict(instruction_id='x-place', action='PLACE_HELD', timeout_ms=1000))      # BUSY: not consumed
        closed = self.worker().closed_at_start                   # a new process over the same ledger
        self.assertEqual(closed, ['on-1'])
        again = self.worker()
        code, result = again.result('on-1')
        self.assertEqual((code, result['stage']), (200, 'INTERNAL_ERROR'))
        self.assertEqual(again.submit(self.hold('on-1'))[1]['stage'], 'DUPLICATE')

    def test_validation_and_health(self):
        w = self.worker()
        self.assertEqual(w.submit(dict(self.hold(), instruction_id='bad id!'))[0], 400)
        self.assertEqual(w.submit(dict(self.hold(), execution_mode='dispatch'))[0], 400)
        self.assertEqual(w.submit(dict(self.hold(), minimum_price='1.8'))[0], 400)
        h = w.health()
        self.assertIs(h['phone_final_action_armed'], False)     # the automatic policy can never approve for this worker
        self.assertIs(h['local_execution']['enabled'], False)
        self.assertEqual((h['worker_id'], h['kind']), ('dw-test', 'desktop_chrome'))

    def test_the_account_fingerprint_is_the_phones(self):
        from desktop_worker.server import fingerprint
        import hashlib
        self.assertEqual(fingerprint('  SomeUser '), hashlib.sha256(b'someuser').hexdigest()[:12])
        self.assertIsNone(fingerprint(''))

    def test_ledger_directly(self):
        led = Ledger(self.path)
        self.assertEqual(led.admit('a', 'SESSION_CHECK', {})[0], 'NEW')
        self.assertEqual(led.admit('a', 'SESSION_CHECK', {'changed': 1})[0], 'DUPLICATE')
        led.complete('a', dict(status='PASS'))
        led.complete('a', dict(status='FAIL'))                  # a terminal result is never replaced
        self.assertEqual(json.loads(led.get('a')['result'])['status'], 'PASS')


if __name__ == '__main__':
    unittest.main()
