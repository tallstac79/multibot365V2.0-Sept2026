"""Event wall-time uncertainty must never change the sharp-side interpretation."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
import unittest
from core.rules_engine import event_start, evaluate
from tests.test_sharp_strategy import parsed, ROWS
from tests.pipeline_support import config


class FeedTimeTests(unittest.TestCase):
    def decide(self, alert, cfg, now):
        return evaluate(alert, cfg, instruction_id='time-test', received_at=now.isoformat(), now=now)

    def test_provisional_gate_keeps_strategy_and_reports_changed_start_eligibility(self):
        p = parsed(9)
        p['scheduled_at_local'] = '2026-09-25T18:00'
        now = datetime(2026, 9, 25, 17, 30, tzinfo=timezone.utc)
        before = deepcopy(p)
        results = [self.decide(p, config(event_timezone=z, feed_timezone_verified=False), now)
                   for z in ('UTC', 'Europe/London')]
        for d in results:
            self.assertEqual(d['decision'], 'REJECT')
            self.assertTrue(d['reason'].startswith('feed_timezone_verified'))
            self.assertTrue(d['timezone_eligibility_uncertain'])
            self.assertTrue(d['event_time_assumptions']['UTC']['event_not_started'])
            self.assertFalse(d['event_time_assumptions']['Europe/London']['event_not_started'])
        self.assertEqual(p, before)
        self.assertEqual(results[0]['checks'][:8], results[1]['checks'][:8])

    def test_real_feed_is_europe_london_since_26_september_2026(self):
        """Empirical (tests/fixtures/timezone_probe_20260926.json): five upcoming fixtures opened on the phone on
        26 Sep 2026 16:46 UTC; every Bet365 page kick-off (UK) equals the feed wall time read as Europe/London (BST),
        none equals it read as UTC. The feed switched from UTC to Europe/London between 06:01 and 07:08 UTC that day
        (14 fixtures re-alerted with their event time one hour later); alerts before the switch keep UTC semantics."""
        from pathlib import Path
        rows = json.loads((Path(__file__).parent / 'fixtures/timezone_probe_20260926.json').read_text(encoding='utf-8'))
        self.assertGreaterEqual(len(rows), 5)
        for row in rows:
            self.assertTrue(row['kickoff_agrees'], row['fixture'])
            self.assertTrue(row['page_uk'].startswith(row['uk_if_feed_is_london']), row)
            self.assertFalse(row['page_uk'].startswith(row['uk_if_feed_is_utc']), row)
        # the rules engine under the corrected setting: Landstede Hammers v Antwerp Giants, feed 19:30 -> 18:30 UTC
        p = parsed(9); p['scheduled_at_local'] = '2026-09-26T19:30'
        self.assertEqual(event_start(p, 'Europe/London').isoformat(), '2026-09-26T18:30:00+00:00')
        self.assertEqual(event_start(p, 'UTC').isoformat(), '2026-09-26T19:30:00+00:00')
        now = datetime(2026, 9, 26, 18, 45, tzinfo=timezone.utc)          # after the real tip-off, before the UTC misreading
        self.assertEqual(self.decide(p, config(event_timezone='Europe/London'), now)['decision'], 'STALE')
        self.assertEqual(self.decide(p, config(event_timezone='UTC'), now)['decision'], 'ACCEPT')   # the error that was live

    def test_verification_only_changes_time_gate(self):
        p = parsed(9); p['scheduled_at_local'] = '2026-09-25T18:00'
        now = datetime(2026, 9, 25, 17, 30, tzinfo=timezone.utc)
        utc = self.decide(p, config(event_timezone='UTC'), now)
        london = self.decide(p, config(event_timezone='Europe/London'), now)
        self.assertEqual(utc['decision'], 'ACCEPT')
        self.assertEqual(london['decision'], 'STALE')
        self.assertEqual(utc['instruction']['side'], p['target_side'])

    def test_aware_source_age_independent_of_event_timezone(self):
        now = datetime.fromisoformat(ROWS[9]['received_at'])
        p = parsed(9); p['source_timestamp'] = (now - timedelta(seconds=301)).isoformat()
        for z in ('UTC', 'Europe/London'):
            d = self.decide(p, config(event_timezone=z, feed_timezone_verified=False), now)
            self.assertEqual(d['decision'], 'STALE')
            self.assertTrue(d['reason'].startswith('alert_age'))

    def test_future_source_and_receipt_fail_closed(self):
        now = datetime.fromisoformat(ROWS[9]['received_at'])
        p = parsed(9); p['source_timestamp'] = (now + timedelta(seconds=31)).isoformat()
        self.assertTrue(self.decide(p, config(), now)['reason'].startswith('timestamp_consistency'))
        p['source_timestamp'] = now.isoformat()
        d = evaluate(p, config(), instruction_id='x', now=now, received_at=(now + timedelta(minutes=2)).isoformat())
        self.assertTrue(d['reason'].startswith('timestamp_consistency'))

    def test_dst_overlap_gap_and_explicit_offset_fail_closed(self):
        for wall in ('2026-03-29T01:30', '2026-10-25T01:30', '2026-09-25T18:00+01:00'):
            with self.subTest(wall=wall), self.assertRaises(ValueError):
                event_start({'scheduled_at_local': wall}, 'Europe/London')
        self.assertEqual(event_start({'scheduled_at_local':'2026-09-25T18:00'}, 'Europe/London').hour, 17)
        self.assertEqual(event_start({'scheduled_at_local':'2026-12-25T18:00'}, 'Europe/London').hour, 18)

    def test_old_config_upgrades_unverified_and_rejects_string_boolean(self):
        from core.decision_support import validate
        cfg = config(); del cfg['global']['feed_timezone_verified']
        self.assertFalse(validate(cfg)['global']['feed_timezone_verified'])
        cfg['global']['feed_timezone_verified'] = 'true'
        with self.assertRaises(ValueError): validate(cfg)

    def test_phone_payload_uses_converted_utc(self):
        import tempfile
        from pathlib import Path
        from tests.pipeline_support import Clock, pipeline, message, MELBOURNE
        from core.alert_classifier import classify
        with tempfile.TemporaryDirectory() as tmp:
            c=Clock();p=pipeline(Path(tmp)/'p.db',c,config(event_timezone='Europe/London'))
            result=p.ingest(message(MELBOURNE))
            with p.store.connection() as db: row=p.store.get_instruction(db,result['instruction_id'])
            expected=event_start(classify(MELBOURNE['raw_text'])['parsed'],'Europe/London').strftime('%Y-%m-%dT%H:%M')
            self.assertEqual(p.build_payload(row)['kickoff_utc'],expected)
            self.assertNotEqual(p.build_payload(row)['kickoff_utc'],row['event_time'])

    def test_sensitive_alert_gets_durable_warning(self):
        import tempfile
        from pathlib import Path
        from tests.pipeline_support import Clock, pipeline, message, MELBOURNE
        from core.alert_classifier import classify
        alert=classify(MELBOURNE['raw_text'])['parsed']
        now=event_start(alert,'UTC')-timedelta(minutes=30)
        with tempfile.TemporaryDirectory() as tmp:
            p=pipeline(Path(tmp)/'p.db',Clock(now),config(feed_timezone_verified=False))
            with self.assertLogs('multibot.pipeline',level='WARNING') as log:
                p.ingest(message(MELBOURNE,received=now))
            self.assertIn('feed_timezone_verified=false',log.output[0])
            with p.store.connection() as db:
                row=db.execute("SELECT detail FROM audit_events WHERE kind='TIMEZONE_ELIGIBILITY_UNCERTAIN'").fetchone()
            detail=json.loads(row[0]);self.assertFalse(detail['feed_timezone_verified'])
            self.assertTrue(detail['timezone_eligibility_uncertain'])
