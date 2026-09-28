"""Wenzhou Yincai v Qingdao Red Lions U20 (28 Sep 2026), backend side.

  on-cebe474a Over 4.25 and on-44457a9c / on-11883180 / on-eae84dcd Over 4.5: the phone evaluated the Popular tab's main
  Over 2.5 (@1.20 / 1.14 / 1.12). The backend comparison counted 2.5 as an improvement of 4.25/4.5 (one-sided rule).
  Football AH and Totals now use a +/- allowance band (operator, 28 Sep 2026); basketball is unchanged.

  Those four attempts were hold refusals (never approved, no bet): they must not lock the Totals market of the game, and a
  later Totals alert for the game still reaches the phone. Fake coordinator only."""
import tempfile
import unittest
from pathlib import Path

from core.execution_terms import compare
from core.final_action import market_already_bet
from tests.pipeline_support import MELBOURNE, Clock, FakeGateway, fail_result, message, pipeline, ready_result

TOL = dict(net_percent=10, line_tolerance='0.25')


def request(line, price, sport='football', market='TOTALS', side='OVER'):
    return dict(market=market, side=side, line=line, price=price, sport=sport)


def live(line, price, market='TOTAL', side='OVER'):
    return dict(market=market, side=side, line=line, price=price)


class FootballBand(unittest.TestCase):
    def test_the_wenzhou_quotes_are_another_line_not_an_improvement(self):
        for line, alert, seen in (('4.25', '1.93', '1.20'), ('4.5', '1.85', '1.14'), ('4.5', '1.85', '1.12')):
            out = compare(request(line, alert), live('2.5', seen), **TOL)
            self.assertFalse(out['acceptable'])
            self.assertFalse(out['line_acceptable'], out)            # refused on the line, whatever the price
        # a far line is refused even at a price above the minimum
        self.assertFalse(compare(request('4.5', '1.85'), live('2.5', '2.10'), **TOL)['line_acceptable'])

    def test_inside_the_band_both_directions(self):
        for seen in ('4.25', '4.5', '4.75'):
            self.assertTrue(compare(request('4.5', '1.85'), live(seen, '1.85'), **TOL)['acceptable'], seen)
        for seen in ('4.0', '5.0'):
            self.assertFalse(compare(request('4.5', '1.85'), live(seen, '1.85'), **TOL)['acceptable'], seen)
        self.assertTrue(compare(request('-2', '1.95', market='SPREAD', side='AWAY'), live('-1.75', '1.95', 'SPREAD', 'AWAY'), **TOL)['acceptable'])
        self.assertFalse(compare(request('-2', '1.95', market='SPREAD', side='AWAY'), live('0.5', '1.95', 'SPREAD', 'AWAY'), **TOL)['acceptable'])

    def test_prices_are_unchanged(self):
        self.assertFalse(compare(request('4.5', '1.85'), live('4.5', '1.70'), **TOL)['acceptable'])   # below the 10 % net floor
        self.assertTrue(compare(request('4.5', '1.85'), live('4.5', '2.10'), **TOL)['acceptable'])    # better price

    def test_basketball_is_unchanged(self):
        self.assertTrue(compare(request('190.5', '1.90', sport='basketball'), live('185.5', '1.90'), line_tolerance='1', net_percent=10)['acceptable'])
        self.assertTrue(compare(request('190.5', '1.90', sport=None), live('185.5', '1.90'), line_tolerance='1', net_percent=10)['acceptable'])
        self.assertFalse(compare(request('190.5', '1.90', sport='basketball'), live('192.5', '1.90'), line_tolerance='1', net_percent=10)['acceptable'])


class RefusedAttemptsDoNotLockTheMarket(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.clock = Clock()
        self.gateway = FakeGateway(self.clock)
        self.p = pipeline(Path(tmp.name) / 'p.sqlite3', self.clock, instant_verification=False, final_action_enabled=True,
                          approval_mode='automatic')

    def row(self, iid):
        with self.p.store.connection() as db:
            return dict(db.execute('SELECT * FROM instructions WHERE instruction_id=?', (iid,)).fetchone())

    def test_a_later_alert_after_hold_refusals_still_reaches_the_phone(self):
        refused = []
        for n, (line, ev) in enumerate((('190.5', '113.52%'), ('191.5', '113.60%'), ('191.5', '113.70%'))):
            text = MELBOURNE['raw_text'].replace('Totals (190.5)', f'Totals ({line})').replace('Bet365 (Totals 190.5)', f'Bet365 (Totals {line})') \
                .replace('EV: 113.52%', f'EV: {ev}')
            iid = self.p.ingest(message(MELBOURNE, message_id=str(970000 + n), text=text))['instruction_id']
            self.assertIsNotNone(iid)
            self.p.tick(self.gateway)
            if refused:
                self.assertEqual(self.gateway.submitted[-1]['instruction_id'], iid)     # dispatched, not locked out
            self.gateway.results[iid] = fail_result(iid, 'BELOW_MINIMUM', 'Visible price 1.20 is below minimum 1.84')
            self.p.tick(self.gateway)
            self.assertEqual(self.row(iid)['state'], 'PRICE_CHANGED')
            with self.p.store.connection() as db:
                self.assertIsNone(market_already_bet(db, self.row(iid)))
            refused.append(iid)
            self.clock.advance(30)


if __name__ == '__main__':
    unittest.main()
