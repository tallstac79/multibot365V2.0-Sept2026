import json
import tempfile
import unittest
from pathlib import Path
from core.pipeline_store import Store
from core.device_diagnostics import snapshot


class DeviceDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'db.sqlite3')

    def health(self,ms=1000,level=72,boot=23):
        return dict(healthy=True,heartbeat_ms=ms,pid=11,credentials='NEVER AUDIT',
            current_instruction={'sensitive':'NEVER AUDIT'},worker_health=dict(boot_count=boot,battery=dict(
                level_percent=level,plugged=2,warning='OK',observed_at_ms=ms),user_unlocked=True))

    def rows(self,kind):
        with self.store.connection() as db:
            return [dict(r,detail=json.loads(r['detail'])) for r in db.execute('SELECT * FROM audit_events WHERE kind=?',(kind,))]

    def test_offline_boundary_retains_exact_last_success_after_recovery(self):
        self.store.record_device('phone','ONLINE',health=self.health(1000),at='2026-09-29T00:00:01+00:00')
        self.store.record_device('phone','ONLINE',health=self.health(2000),at='2026-09-29T00:00:02+00:00')
        self.store.record_device('phone','OFFLINE',error='timed out',at='2026-09-29T00:00:08+00:00')
        self.store.record_device('phone','OFFLINE',error='timed out',at='2026-09-29T00:00:14+00:00')
        self.store.record_device('phone','ONLINE',health=self.health(20000),at='2026-09-29T00:00:20+00:00')
        rows=self.rows('DEVICE_AVAILABILITY');self.assertEqual(len(rows),3)
        self.assertEqual(rows[1]['detail']['last_healthy']['heartbeat_ms'],2000)
        self.assertEqual(rows[1]['detail']['previous_last_online_at'],'2026-09-29T00:00:02+00:00')
        self.assertEqual(self.store.device('phone')['status'],'ONLINE')

    def test_sampling_deduplicates_same_level_but_records_drain(self):
        for ms,level in [(1000,72),(2000,72),(3000,71)]:
            self.store.record_device('phone','ONLINE',health=self.health(ms,level))
        self.assertEqual(len(self.rows('DEVICE_POWER')),2)

    def test_new_boot_is_recorded_without_false_offline(self):
        self.store.record_device('phone','ONLINE',health=self.health(1000,72,23))
        self.store.record_device('phone','ONLINE',health=self.health(2000,72,24))
        self.assertEqual(len(self.rows('DEVICE_POWER')),2)
        self.assertEqual(len(self.rows('DEVICE_AVAILABILITY')),1)

    def test_old_agent_and_desktop_health_still_work(self):
        self.store.record_device('desktop','ONLINE',health={'healthy':True})
        self.store.record_device('phone','ONLINE',health={'healthy':True})
        self.assertEqual(self.rows('DEVICE_POWER'),[])
        self.assertEqual(len(self.rows('DEVICE_AVAILABILITY')),2)

    def test_device_histories_are_separate(self):
        self.store.record_device('phone','ONLINE',health=self.health())
        self.store.record_device('desktop','OFFLINE')
        self.assertEqual(self.store.device('phone')['status'],'ONLINE')
        self.assertIsNone(self.rows('DEVICE_AVAILABILITY')[-1]['detail']['last_healthy'])

    def test_no_sensitive_health_payload_in_audit(self):
        h=self.health();h['worker_health']['secret']='NEVER AUDIT'
        self.store.record_device('phone','ONLINE',health=h)
        self.store.record_device('phone','OFFLINE')
        self.assertNotIn('NEVER AUDIT',json.dumps(self.rows('DEVICE_AVAILABILITY')+self.rows('DEVICE_POWER')))

    def test_malformed_or_missing_health_is_diagnostic_only(self):
        self.assertEqual(snapshot('not-json'),{})
        self.assertEqual(snapshot(None),{})
        self.store.record_device('phone','ONLINE',health=None)
        self.store.record_device('phone','OFFLINE')
        self.assertEqual(self.store.device('phone')['status'],'OFFLINE')

    def test_warning_change_is_not_hidden_by_unchanged_level(self):
        h=self.health();self.store.record_device('phone','ONLINE',health=h)
        h['worker_health']['battery']['warning']='DRAINING_WHILE_PLUGGED'
        self.store.record_device('phone','ONLINE',health=h)
        self.assertEqual(len(self.rows('DEVICE_POWER')),2)

if __name__=='__main__':unittest.main()
