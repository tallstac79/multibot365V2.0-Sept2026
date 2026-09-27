"""The three live failure modes of 27 Sep 2026 16:10-16:22Z, replayed from the stored production rows
(tests/fixtures/live_failures_20260927.json):

  on-741157b9 / on-ce279264  TIMEOUT after 360 s: the phone answered "BUSY ... ID not consumed" (it was running the
                             RESET_BETSLIP the same tick had just sent), the dispatcher logged SUBMIT_UNCERTAIN and waited
                             for a result that could never exist.
  on-728c2c3d                AUTO_APPROVAL_REFUSED verified_market_mapping: the approval gate still required
                             sport == 'basketball' although the rules engine accepted the production-verified football
                             mapping and the phone had held Santa Cruz RJ v Cardoso Moreira AWAY 0.0 @2.050.
  on-ee666445                (phone side, FootballLineCheckTest) the Asian Handicap was read at 0.0, outside the +0.5
                             alert's 0.25 allowance, but reported as "No live football market quotes parsed".
"""
import json
import tempfile
import unittest
from pathlib import Path

from core.final_action import VERIFIED_PROFILES, mapping_verified
from core.lifecycle import busy_not_admitted
from tests.pipeline_support import MELBOURNE, Clock, FakeGateway, message, pipeline

LIVE = json.loads((Path(__file__).parent / 'fixtures/live_failures_20260927.json').read_text(encoding='utf-8'))
BUSY = ValueError({'instruction_id': 'x', 'status': 'FAIL', 'stage': 'INTERNAL_ERROR',
                   'detail': 'BUSY: one instruction at a time; ID not consumed', 'duration_ms': 0})


class VerifiedMappingIsOneDecision(unittest.TestCase):
    def test_santa_cruz_mapping_is_verified_by_the_rules_and_the_approval_gate(self):
        row = LIVE['on-728c2c3d06a66870420086fa']
        mapping = row['normalized_alert']['quote_mapping']
        rules_check = [c for c in row['rules_result']['checks'] if c['name'] == 'verified_mapping'][0]
        self.assertTrue(rules_check['passed'])                              # the rules engine accepted it live
        self.assertTrue(mapping_verified(row['sport'], mapping))            # and now the approval gate agrees
        refused = [a for a in row['audit'] if a['kind'] == 'AUTO_APPROVAL_REFUSED'][0]['detail']['checks']
        others = [c for c in refused if c['check'] != 'verified_mapping' and c['check'] != 'verified_market_mapping']
        self.assertTrue(all(c['ok'] for c in others), others)               # it was the only failing check

    def test_every_parser_profile_is_verified_for_its_own_sport_only(self):
        for sport, profiles in VERIFIED_PROFILES.items():
            for profile in profiles:
                self.assertTrue(mapping_verified(sport, dict(profile=profile, production_verified=True)))
                self.assertFalse(mapping_verified(sport, dict(profile=profile, production_verified=False)))
                other = 'football' if sport == 'basketball' else 'basketball'
                self.assertFalse(mapping_verified(other, dict(profile=profile, production_verified=True)))
        self.assertFalse(mapping_verified('football', {}))
        self.assertFalse(mapping_verified('tennis', dict(profile='oddsnotifier_football_1x2_v1', production_verified=True)))


class BusyIsNotAdmission(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.clock = Clock()
        self.gateway = FakeGateway(self.clock)
        self.p = pipeline(Path(tmp.name) / 'p.sqlite3', self.clock)

    def state(self, iid):
        with self.p.store.connection() as db:
            return db.execute('SELECT state FROM instructions WHERE instruction_id=?', (iid,)).fetchone()[0]

    def audit(self, kind):
        with self.p.store.connection() as db:
            return db.execute('SELECT COUNT(*) FROM audit_events WHERE kind=?', (kind,)).fetchone()[0]

    def test_the_live_replies_are_busy_non_admissions(self):
        for iid in ('on-741157b9f9da5fd391efa61c', 'on-ce2792642d0cfd6458094971'):
            error = [a for a in LIVE[iid]['audit'] if a['kind'] == 'SUBMIT_UNCERTAIN'][0]['detail']['error']
            self.assertTrue(busy_not_admitted(ValueError(error)), error)
        self.assertFalse(busy_not_admitted(OSError('timed out')))
        self.assertFalse(busy_not_admitted(ValueError({'stage': 'INTERNAL_ERROR', 'detail': 'something else'})))

    def test_busy_returns_the_instruction_to_the_queue_and_it_is_resent_not_timed_out(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.gateway.submit_error = BUSY
        self.p.tick(self.gateway)
        self.assertEqual(self.state(iid), 'QUEUED')                         # not DISPATCHED waiting 360 s
        self.assertEqual(self.audit('SUBMIT_NOT_ADMITTED_BUSY'), 1)
        self.assertEqual(self.audit('SUBMIT_UNCERTAIN'), 0)
        self.gateway.submit_error = None
        self.clock.advance(2)
        self.p.tick(self.gateway)
        self.assertIn(self.state(iid), ('DEVICE_ACTIVE', 'DISPATCHED', 'READY'))
        sent = [x['instruction_id'] for x in self.gateway.submitted]
        self.assertEqual(sent, [iid, iid])                                  # the same ID, resent once the phone was free


    def test_a_released_hold_ends_the_tick_before_anything_else_is_sent(self):
        """16:10:14.971 on-da34929e refused -> RESET_BETSLIP sent -> 16:10:15.516 next instruction sent in the SAME tick."""
        from core.lifecycle import State
        from core.pipeline import HELD_KEY
        refused = self.p.ingest(message(MELBOURNE, message_id='940001'))['instruction_id']
        with self.p.store.tx() as db:
            self.p.store.transition(db, refused, State.REJECTED, actor='automatic-policy', reason='AUTO_APPROVAL_REFUSED: test')
        self.p.store.set_control(HELD_KEY, dict(instruction_id=refused), by='test')
        waiting = self.p.ingest(message(MELBOURNE, message_id='940002', text=None))['instruction_id']
        self.p.tick(self.gateway)
        self.assertEqual([x['action'] for x in self.gateway.submitted], ['RESET_BETSLIP'])   # nothing else this tick
        self.clock.advance(2)
        self.p.tick(self.gateway)
        self.assertIn('ADAPTER_WORKFLOW', [x['action'] for x in self.gateway.submitted])
        self.assertNotEqual(self.state(waiting), 'TIMEOUT')

    def test_a_busy_my_bets_check_is_not_an_attempt(self):
        """13:32Z Pantery check 1 was refused BUSY, then waited 3 minutes and counted as a failed attempt."""
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        with self.p.store.tx() as db:
            self.p.store.upsert_bet(db, iid, status='PLACED_UNVERIFIED', stake='0.10', odds='2.20', placed_at='2020-01-01T00:00:00+00:00',
                                    source='device')
        health = self.gateway.health()
        self.gateway.submit_error = BUSY
        self.assertTrue(self.p.final.schedule(self.gateway, health, True))
        with self.p.store.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reconciliations').fetchone()[0], 0)
        self.assertEqual(self.audit('RECONCILE_NOT_ADMITTED_BUSY'), 1)
        self.gateway.submit_error = None
        self.assertTrue(self.p.final.schedule(self.gateway, health, True))
        with self.p.store.connection() as db:
            self.assertEqual(db.execute('SELECT attempt FROM reconciliations').fetchall()[0][0], 1)   # still attempt 1


if __name__ == '__main__':
    unittest.main()
