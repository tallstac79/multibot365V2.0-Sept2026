"""Per-stage execution evidence (analysis only, 28 Sep 2026): the route actually used, the first live quote, the pre-tap
quote and the final/receipt terms survive the final phone result, which replaces instructions.result_payload.
Fake coordinator only: no phone, no bookmaker, no money."""
import tempfile
import unittest
from pathlib import Path

from core.pipeline_store import Store
from tests.pipeline_support import MELBOURNE, Clock, FakeGateway, fail_result, message, pipeline, ready_result
from tests.test_final_action import placement_result

FIRST = dict(market='TOTAL', side='OVER', line='190.5', price='2.25', selection_name='Over')      # read on the grid
HELD = dict(market='TOTALS', side='OVER', line='190.5', price='2.20', selection_name='Over')      # on the slip
PRETAP = dict(ok=True, market='TOTALS', side='OVER', selection='Over', line='190.5', price='2.20', stake='1.00')


class ExecutionStages(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'p.sqlite3'
        self.clock = Clock()
        self.gateway = FakeGateway(self.clock)
        self.p = pipeline(self.path, self.clock, instant_verification=False, final_action_enabled=True, approval_mode='automatic')

    def stages(self, iid):
        return {s['stage']: s for s in Store(self.path).execution_stages(iid)}    # a fresh Store: durable, not in memory

    def hold_result(self, iid, route='event_link'):
        return dict(ready_result(iid), route=route, event_url='https://www.bet365.com/#/AC/B18/C1/D19/E1/F19/I0/' if route == 'event_link' else None,
                    selection=HELD, execution_observations=[dict(stage='grid', observed=FIRST, observed_at_ms=1, identity_verified=False),
                                                            dict(stage='selection', observed=HELD, observed_at_ms=2, identity_verified=True)])

    def test_every_stage_survives_the_final_result(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.p.tick(self.gateway)
        self.gateway.results[iid] = self.hold_result(iid)
        self.p.tick(self.gateway)
        self.gateway.results[iid + '-place'] = dict(placement_result(iid, actual_terms=dict(line='190.5', odds='2.20', stake='1.00')),
                                                    pretap=PRETAP)
        self.p.tick(self.gateway); self.p.tick(self.gateway)
        with self.p.store.connection() as db:
            row = db.execute('SELECT state, result_payload, dispatch_payload FROM instructions WHERE instruction_id=?', (iid,)).fetchone()
        self.assertEqual(row['state'], 'COMPLETED')
        self.assertNotIn('route', row['result_payload'])            # the final result replaced the hold result...
        s = self.stages(iid)                                          # ...but every stage is kept
        self.assertEqual(set(s), {'hold_request', 'first_quote', 'hold_result', 'hold_timings', 'place_request', 'place_timings', 'pretap', 'receipt'})
        self.assertEqual((s['hold_request']['route'], s['hold_request']['device_instruction_id']), ('event_link', iid))
        # requested (alert) and minimum acceptable prices are separate; `price` is never the floor
        with self.p.store.connection() as db:
            alert, minimum = db.execute('SELECT alert_price, minimum_price FROM instructions WHERE instruction_id=?', (iid,)).fetchone()
        self.assertEqual((s['hold_request']['requested_price'], s['hold_request']['minimum_price'], s['hold_request']['price']),
                         (alert, minimum, None))
        self.assertEqual((s['place_request']['requested_price'], s['place_request']['minimum_price'], s['place_request']['price']),
                         (alert, minimum, '2.20'))
        self.assertEqual((s['first_quote']['route'], s['first_quote']['side'], s['first_quote']['line'], s['first_quote']['price']),
                         ('event_link', 'OVER', '190.5', '2.25'))    # the FIRST quote (grid), not the later slip quote
        self.assertEqual(s['hold_result']['price'], '2.20')
        self.assertEqual(s['place_request']['device_instruction_id'], iid + '-place')
        self.assertEqual((s['pretap']['line'], s['pretap']['price'], s['pretap']['stake']), ('190.5', '2.20', '1.00'))
        self.assertEqual((s['receipt']['bet_reference'], s['receipt']['line'], s['receipt']['price']), ('JL1234567890', '190.5', '2.20'))
        self.assertTrue(s['receipt']['outcome'].startswith('PLACED'))
        # the phone's own stage timings and marks are kept per job (latency analysis; nothing here affects execution)
        import json as _json
        self.assertIn('stage_timings', _json.loads(s['hold_timings']['detail']))
        self.assertIn('marks', _json.loads(s['place_timings']['detail']))

    def test_search_route_and_a_failed_hold(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.p.tick(self.gateway)
        self.gateway.results[iid] = dict(fail_result(iid, 'BELOW_MINIMUM', 'Visible price 1.95 is below minimum 2.08'), route='search',
                                         execution_observations=[dict(stage='grid', observed=dict(FIRST, price='1.95'))])
        self.p.tick(self.gateway)
        s = self.stages(iid)
        self.assertEqual((s['first_quote']['route'], s['first_quote']['price']), ('search', '1.95'))
        self.assertTrue(s['hold_result']['outcome'].startswith('PRICE_CHANGED'))
        self.assertNotIn('pretap', s)
        self.assertNotIn('receipt', s)

    def test_old_request_rows_are_relabelled(self):
        """Rows recorded before the fix held the minimum in `price` (on-f4d9aa2d: 'requested @1.77' was the floor)."""
        import json, sqlite3
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        with self.p.store.connection() as db:
            alert, minimum = db.execute('SELECT alert_price, minimum_price FROM instructions WHERE instruction_id=?', (iid,)).fetchone()
        raw = sqlite3.connect(self.path)
        raw.execute("INSERT INTO execution_stages(instruction_id, stage, recorded_at, price, source, detail) VALUES (?,?,?,?,?,?)",
                    (iid, 'hold_request', '2026-09-28T06:30:00', minimum, 'dispatcher', json.dumps(dict(minimum_price=minimum))))
        raw.commit(); raw.close()
        s = self.stages(iid)['hold_request']                         # a fresh Store runs the migration
        self.assertEqual((s['requested_price'], s['minimum_price'], s['price']), (alert, minimum, None))

    def test_a_stage_is_written_once(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        with self.p.store.tx() as db:
            self.assertTrue(self.p.store.record_stage(db, iid, 'pretap', source='test', price='2.20'))
            self.assertFalse(self.p.store.record_stage(db, iid, 'pretap', source='test', price='9.99'))
        self.assertEqual(self.stages(iid)['pretap']['price'], '2.20')
        with self.assertRaises(ValueError):
            with self.p.store.tx() as db:
                self.p.store.record_stage(db, iid, 'pretap', source='test', unknown_field=1)


if __name__ == '__main__':
    unittest.main()
