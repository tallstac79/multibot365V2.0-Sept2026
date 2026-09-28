"""Codex daily audit 28 Sep 2026, backend side of 'fresh slip proof' (Al Kharaitiyat v Al Wakrah, on-5438c5ae): the phone
held an acceptable slip, but the approval judged the last recorded observation - an identity-unverified pre-selection
grid read - and refused terms_within_tolerance. A verified hold is now judged on its fresh final slip observation;
a final observation that is itself unverified or unacceptable still refuses. Fake coordinator only."""
import tempfile
import unittest
from pathlib import Path

from tests.pipeline_support import MELBOURNE, Clock, FakeGateway, message, pipeline, ready_result

SEL = dict(market='TOTALS', side='OVER', line='190.5', selection_name='Over', availability='OPEN')


def obs(stage, identity, price='2.20'):
    return dict(stage=stage, observed=dict(SEL, price=price), identity_verified=identity, observed_at_ms=1)


class FreshFinalProof(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.clock = Clock()
        self.gateway = FakeGateway(self.clock)
        self.p = pipeline(Path(tmp.name) / 'p.sqlite3', self.clock, instant_verification=False, final_action_enabled=True,
                          approval_mode='automatic')

    def run_hold(self, observations):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.p.tick(self.gateway)
        self.gateway.results[iid] = dict(ready_result(iid), execution_observations=observations)
        self.p.tick(self.gateway)
        with self.p.store.connection() as db:
            row = db.execute('SELECT state, failure_reason FROM instructions WHERE instruction_id=?', (iid,)).fetchone()
        placed = iid + '-place' in [x['instruction_id'] for x in self.gateway.submitted]
        return row['state'], row['failure_reason'] or '', placed

    def test_the_fresh_final_observation_decides_not_an_earlier_grid_read(self):
        state, reason, placed = self.run_hold([obs('grid', False), obs('selection', True), obs('selection_preflight', False), obs('final', True)])
        self.assertNotIn('terms_within_tolerance', reason)
        self.assertTrue(placed, (state, reason))                       # auto-approved: PLACE_HELD sent

    def test_a_later_unverified_grid_read_does_not_override_the_fresh_final_proof(self):
        state, reason, placed = self.run_hold([obs('selection', True), obs('final', True), obs('selection_preflight', False)])
        self.assertNotIn('terms_within_tolerance', reason)
        self.assertTrue(placed, (state, reason))

    def test_the_days_sequence_without_a_final_observation_still_refuses(self):
        state, reason, placed = self.run_hold([obs('grid', False), obs('selection', True), obs('selection_preflight', False)])
        self.assertFalse(placed)
        self.assertIn('terms_within_tolerance', reason)                # no earlier success is reused

    def test_an_unverified_or_unacceptable_final_observation_refuses(self):
        state, reason, placed = self.run_hold([obs('selection', True), obs('final', False)])
        self.assertFalse(placed)
        self.assertIn('terms_within_tolerance', reason)

    def test_an_unacceptable_final_price_refuses(self):
        state, reason, placed = self.run_hold([obs('selection', True), obs('final', True, price='1.50')])
        self.assertFalse(placed)


if __name__ == '__main__':
    unittest.main()
