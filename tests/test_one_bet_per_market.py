"""One bet per market per game (operator, 27 Sep 2026): once a bet is taken on a market of a game, later alerts for the
SAME market of that game are ignored; other markets of the game stay allowed; an attempt proven not placed does not
count. Read from the durable store, so it holds across restarts. Fake coordinator only."""
import tempfile
import unittest
from pathlib import Path

from core.final_action import market_already_bet
from core.status_notifier import AUTOMATIC_STATES, Notifier
from tests.pipeline_support import MELBOURNE, Clock, FakeGateway, message, pipeline, ready_result
from tests.test_final_action import placement_result

# A later alert on the same game and market at a DIFFERENT line (the same selection is already refused as DUPLICATE).
LATER = MELBOURNE['raw_text'].replace('Totals (190.5)', 'Totals (191.5)').replace('Bet365 (Totals 190.5)', 'Bet365 (Totals 191.5)')


class OneBetPerMarket(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'p.sqlite3'
        self.clock = Clock()
        self.gateway = FakeGateway(self.clock)
        self.p = self.make()

    def make(self):
        return pipeline(self.path, self.clock, instant_verification=False, final_action_enabled=True, approval_mode='automatic')

    def row(self, iid):
        with self.p.store.connection() as db:
            return dict(db.execute('SELECT * FROM instructions WHERE instruction_id=?', (iid,)).fetchone())

    def place_first(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.p.tick(self.gateway)
        self.gateway.results[iid] = ready_result(iid)
        self.p.tick(self.gateway)
        self.gateway.results[iid + '-place'] = placement_result(iid)
        self.p.tick(self.gateway); self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'COMPLETED')
        return iid

    def clone(self, iid, new_id, **changes):
        with self.p.store.tx() as db:
            row = dict(db.execute('SELECT * FROM instructions WHERE instruction_id=?', (iid,)).fetchone())
            row.update(instruction_id=new_id, selection_key=(row.get('selection_key') or '') + new_id, state='QUEUED', terminal=0,
                       approved_at=None, **changes)
            db.execute(f"INSERT INTO instructions({','.join(row)}) VALUES ({','.join('?' * len(row))})", tuple(row.values()))
            return dict(db.execute('SELECT * FROM instructions WHERE instruction_id=?', (new_id,)).fetchone())

    def test_a_later_alert_for_the_same_market_is_ignored_before_it_qualifies(self):
        first = self.place_first()
        notifier = Notifier(self.p.store, sender=None, states=AUTOMATIC_STATES, clock=self.clock, outcome_only=True)
        notifier.enqueue()
        self.clock.advance(5)
        later = self.p.ingest(message(MELBOURNE, message_id='980001', text=LATER))
        row = self.row(later['instruction_id'])
        self.assertEqual(row['state'], 'REJECTED')
        self.assertTrue(row['failure_reason'].startswith('ALREADY_BET: TOTALS'), row['failure_reason'])
        self.assertIn(first[:12], row['failure_reason'])
        self.p.tick(self.gateway)
        self.assertNotIn(later['instruction_id'], [x['instruction_id'].replace('-place', '') for x in self.gateway.submitted])
        notifier.enqueue()
        with self.p.store.connection() as db:       # ignored: no operator message for it
            self.assertEqual(db.execute('SELECT COUNT(*) FROM notifications WHERE instruction_id=?', (later['instruction_id'],)).fetchone()[0], 0)

    def test_other_markets_of_the_game_stay_allowed(self):
        first = self.place_first()
        with self.p.store.connection() as db:
            self.assertIsNone(market_already_bet(db, self.clone(first, 'on-spread', market='SPREAD')))
            self.assertIsNone(market_already_bet(db, self.clone(first, 'on-ml', market='MONEYLINE')))
            self.assertIsNotNone(market_already_bet(db, self.clone(first, 'on-totals', market='TOTALS', selection='UNDER')))
            # another game (different kick-off) is never blocked
            self.assertIsNone(market_already_bet(db, self.clone(first, 'on-other', event_time='2026-10-01T09:30', normalized_alert='{}')))

    def test_ml_and_1x2_are_one_market(self):
        first = self.place_first()
        with self.p.store.tx() as db:
            db.execute("UPDATE instructions SET market='1X2' WHERE instruction_id=?", (first,))
        with self.p.store.connection() as db:
            self.assertIsNotNone(market_already_bet(db, self.clone(first, 'on-ml2', market='MONEYLINE')))

    def test_an_attempt_proven_not_placed_does_not_block(self):
        first = self.place_first()
        for status, blocks in (('NOT_PLACED', False), ('NOT_PLACED_CLAIMED', False), ('UNKNOWN', True), ('PLACED_UNVERIFIED', True),
                               ('OPEN', True), ('WON', True), ('DISCREPANCY', True)):
            with self.p.store.tx() as db:
                db.execute('UPDATE bets SET status=? WHERE instruction_id=?', (status, first))
            with self.p.store.connection() as db:
                got = market_already_bet(db, self.clone(first, 'on-x-' + status.lower()))
            self.assertEqual(got is not None, blocks, (status, got))

    def test_a_tap_in_flight_blocks(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.p.tick(self.gateway)
        self.gateway.results[iid] = ready_result(iid)
        self.p.tick(self.gateway)                   # auto-approved, PLACE_HELD sent, no result yet
        self.assertIn(self.row(iid)['state'], ('DISPATCHED', 'DEVICE_ACTIVE'))
        with self.p.store.connection() as db:
            self.assertIsNotNone(market_already_bet(db, self.clone(iid, 'on-race')))

    def test_durable_across_restart(self):
        self.place_first()
        self.p = self.make()                        # a new process over the same database
        self.p.recover()
        later = self.p.ingest(message(MELBOURNE, message_id='980002', text=LATER))
        self.assertTrue(self.row(later['instruction_id'])['failure_reason'].startswith('ALREADY_BET'))


if __name__ == '__main__':
    unittest.main()
