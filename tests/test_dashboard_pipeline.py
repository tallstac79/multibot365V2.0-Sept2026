"""Dashboard wiring over the authoritative pipeline store: read-only, REAL/SAMPLE separated."""
import shutil
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from core.observation_store import record_alert
from dashboard.app import create_app
from dashboard.services import Health
from tests.pipeline_support import ROOT, MELBOURNE, RYTAS, Clock, FakeGateway, message, pipeline, ready_result


class DashboardPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / '.local/pipeline.sqlite3'
        self.client = TestClient(create_app(self.root, health=Health(self.root, network=lambda: {})))

    def populate(self):
        clock = Clock()
        p = pipeline(self.db, clock)
        gateway = FakeGateway(clock)
        ready = p.ingest(message(MELBOURNE))['instruction_id']
        p.ingest(message(MELBOURNE))                                   # duplicate delivery
        p.ingest(message(RYTAS, origin='sample'))                      # replayed sample
        p.tick(gateway)
        gateway.results[ready] = ready_result(ready)
        p.tick(gateway)
        return ready

    def test_missing_store_is_empty_and_not_created(self):
        self.assertEqual(self.client.get('/api/alerts').json()['items'], [])
        self.assertFalse(self.db.exists())
        self.assertFalse(self.client.get('/api/pipeline').json()['available'])

    def test_real_alerts_show_lifecycle_rules_and_notification(self):
        ready = self.populate()
        before = self.db.read_bytes()
        rows = self.client.get('/api/alerts?mode=real').json()['items']
        self.assertEqual([r['status'] for r in rows], ['DUPLICATE', 'PARSED'])
        row = rows[1]
        self.assertEqual((row['instruction_id'], row['lifecycle_state'], row['side'], row['alert_price']),
                         (ready, 'READY', 'OVER', '2.20'))
        self.assertEqual(row['rules_result']['decision'], 'ACCEPT')
        self.assertIn('Status: READY', row['notification'])
        self.assertEqual([e['stage'] for e in row['timeline']],
                         ['RECEIVED', 'PARSED', 'RULES_APPLIED', 'QUEUED', 'DISPATCHED', 'DEVICE_ACTIVE', 'READY'])
        self.assertEqual(row['provenance']['mode'], 'REAL DATA')
        self.assertEqual(self.db.read_bytes(), before)                  # dashboard never writes

    def test_sample_origin_only_in_sample_mode(self):
        shutil.copytree(ROOT / 'tests/fixtures', self.root / 'tests/fixtures')
        self.populate()
        real = self.client.get('/api/alerts?mode=real').json()['items']
        self.assertFalse(any(r['provenance']['mode'] == 'SAMPLE DATA' for r in real))
        sample = self.client.get('/api/alerts?mode=sample').json()['items']
        replayed = [r for r in sample if r['id'].startswith('pipeline-')]
        self.assertEqual(len(replayed), 1)
        self.assertEqual(replayed[0]['provenance']['mode'], 'SAMPLE DATA')

    def test_snapshot_and_pipeline_same_message_shown_once(self):
        self.populate()
        record_alert(self.root / '.local/oddsnotifier.sqlite3', MELBOURNE['raw_text'], channel_id=MELBOURNE['chat_id'],
                     message_id=MELBOURNE['message_id'], source_timestamp=None, received_at='2026-09-23T11:00:00+00:00',
                     origin='production', ordering_profile='oddsnotifier_basketball_v1')
        record_alert(self.root / '.local/oddsnotifier.sqlite3', RYTAS['raw_text'], channel_id=RYTAS['chat_id'],
                     message_id=RYTAS['message_id'], source_timestamp=None, received_at='2026-09-23T11:00:00+00:00',
                     origin='production', ordering_profile='oddsnotifier_basketball_v1')
        rows = self.client.get('/api/alerts?mode=real').json()['items']
        self.assertEqual(sorted(r['source_message_id'] for r in rows), ['67894', '67894', '67895'])
        self.assertEqual(sum(1 for r in rows if r['source_message_id'] == '67894' and r['status'] == 'PARSED'), 1)

    def test_history_status_and_session(self):
        ready = self.populate()
        items = self.client.get('/api/history?mode=real').json()['items']
        self.assertEqual(items[0]['instruction_id'], ready)
        self.assertEqual((items[0]['status'], items[0]['stage'], items[0]['observed_price']), ('READY', 'PASS', '2.20'))
        self.assertEqual(items[0]['dispatch_payload']['execution_mode'], 'ready')
        self.assertEqual(items[0]['evidence'], [])                     # referenced file not present here
        self.assertEqual(self.client.get('/api/history?mode=sample').json()['total'] >= 0, True)
        status = self.client.get('/api/status').json()['pipeline']
        self.assertEqual(status['sessions'][0]['state'], 'AUTHENTICATED')
        self.assertEqual(status['lifecycle'], {'READY': 1})
        self.assertEqual(status['devices'][0]['status'], 'ONLINE')

    def test_corrupt_pipeline_store_fails_explicitly(self):
        self.db.parent.mkdir(parents=True, exist_ok=True)
        self.db.write_text('corrupt')
        self.assertEqual(self.client.get('/api/alerts?mode=real').status_code, 503)
        self.assertFalse(self.client.get('/api/status').json()['pipeline']['available'])


if __name__ == '__main__':
    unittest.main()
