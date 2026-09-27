"""Dashboard operator actions for the final action: approve, reject, kill switch, bets."""
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from dashboard.app import create_app
from dashboard.services import Health
from tests.pipeline_support import MELBOURNE, RYTAS, Clock, FakeGateway, config, fail_result, message, pipeline
from tests.test_final_action import placement_result


class DashboardFinalActionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / '.local').mkdir()
        (self.root / '.local/pipeline.json').write_text(json.dumps({'pipeline': {'final_action_enabled': True,
                                                                                  'dispatch_enabled': True}}))
        self.client = TestClient(create_app(self.root, health=Health(self.root, network=lambda: {})))
        # The dashboard's own rules store uses defaults (no timezone); give the operator pipeline the test rules.
        from core.decision_support import Store
        Store(self.root / '.local/dashboard.sqlite3').save(config())
        self.p = pipeline(self.root / '.local/pipeline.sqlite3', Clock(), final_action_enabled=True)
        self.gateway = FakeGateway(self.p.clock)

    def waiting(self, sample=MELBOURNE):
        iid = self.p.ingest(message(sample))['instruction_id']
        self.p.tick(self.gateway)
        return iid

    def state(self, iid):
        with self.p.store.connection() as db:
            return db.execute('SELECT state, approved_by FROM instructions WHERE instruction_id=?', (iid,)).fetchone()

    def test_approve_and_reject(self):
        iid = self.waiting()
        summary = self.client.get('/api/pipeline').json()
        self.assertEqual(summary['awaiting_approval'][0]['instruction_id'], iid)
        # The operator pipeline uses real wall-clock time: widen the window for the fixed test clock.
        with self.p.store.tx() as db:
            db.execute("UPDATE instructions SET approval_requested_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')")
        response = self.client.post(f'/api/instructions/{iid}/approve')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(tuple(self.state(iid)), ('APPROVED', 'dashboard'))
        self.p.tick(self.gateway)                                   # first approved bet goes to the phone
        self.gateway.results[iid + "-place"] = fail_result(iid, 'SUSPENDED')   # ...and is refused before any tap
        second = self.waiting(RYTAS)                                # this tick releases the refused bet's slip (RESET_BETSLIP)
        self.p.tick(self.gateway)                                   # the next tick sends the second hold (never the same tick:
                                                                    # 27 Sep 2026 BUSY race) -> verified -> awaiting
        self.assertEqual(self.client.post(f'/api/instructions/{second}/reject').status_code, 200)
        self.assertEqual(self.state(second)[0], 'REJECTED')
        self.assertEqual(self.client.post(f'/api/instructions/{second}/approve').status_code, 409)
        self.assertEqual(self.client.post('/api/instructions/nothing/approve').status_code, 404)

    def test_kill_switch_and_cross_origin_protection(self):
        iid = self.waiting()
        refused = self.client.post('/api/controls/pause', json={'paused': True}, headers={'Origin': 'http://evil.example'})
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(self.client.post('/api/controls/pause', json={'paused': 'yes'}).status_code, 422)
        self.assertEqual(self.client.post('/api/controls/pause', json={'paused': True}).json(), {'paused': True})
        self.assertEqual(self.state(iid)[0], 'REJECTED')
        self.assertTrue(self.client.get('/api/pipeline').json()['paused'])
        self.client.post('/api/controls/pause', json={'paused': False})
        self.assertFalse(self.client.get('/api/pipeline').json()['paused'])

    def test_bets_listing(self):
        self.assertEqual(self.client.get('/api/bets').json()['items'], [])
        iid = self.waiting()
        self.p.final.approve(iid, 'operator')
        self.p.tick(self.gateway)
        self.gateway.results[iid + "-place"] = placement_result(iid)
        self.p.tick(self.gateway)
        items = self.client.get('/api/bets').json()['items']
        self.assertEqual((items[0]['status'], items[0]['bet_reference'], items[0]['approved_by']),
                         ('PLACED_UNVERIFIED', 'JL1234567890', 'operator'))


if __name__ == '__main__':
    unittest.main()
