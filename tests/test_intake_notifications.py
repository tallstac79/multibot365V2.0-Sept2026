"""Intake-only reporting regression for the real 27 September 18:56 BST incident."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from core.intake_notifications import enqueue_misses, MISSED_STATE, BASELINE_KEY
from core.pipeline_store import iso
from core.status_notifier import Notifier
from tests.pipeline_support import Clock, message, pipeline
from tests.test_pipeline_io import FakeClient, FakeWorld
from core.telegram_intake import TelegramIntake

CORPUS = json.loads((Path(__file__).resolve().parents[1] /
                    'evidence/intake-notifications/20260927-1856.json').read_text(encoding='utf-8'))


class IntakeMissTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock = Clock()
        self.p = pipeline(Path(self.tmp.name) / 'test.sqlite3', self.clock)
        self.notifier = Notifier(self.p.store, clock=self.clock)

    def ingest(self, sample, **extra):
        return self.p.ingest(message(text=sample['formatted_text'], chat_id=sample['chat_id'],
                                     message_id=sample['message_id'], received=self.clock(), **extra))

    def outbox(self):
        with self.p.store.connection() as db:
            return [dict(x) for x in db.execute('SELECT * FROM notifications')]

    def test_three_real_alerts_keep_classification_but_each_get_one_missed(self):
        self.assertEqual(self.notifier.enqueue(), 0)
        for sample in CORPUS:
            result = self.ingest(sample)
            self.assertEqual(result['status'], sample['status'])
            self.assertEqual(result['reason'], sample['reason'])
            self.assertIsNone(result['instruction_id'])
        self.assertEqual(self.notifier.enqueue(), 3)
        for row, sample in zip(self.outbox(), CORPUS):
            self.assertEqual(row['state'], MISSED_STATE)
            self.assertIn(sample['normalized']['fixture'], row['text'])
            self.assertIn(sample['reason'], row['text'])
            self.assertIn(sample['message_id'], row['text'])
        with self.p.store.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM instructions').fetchone()[0], 0)

    def test_restart_and_redelivery_are_idempotent(self):
        self.notifier.enqueue()
        self.ingest(CORPUS[0])
        self.ingest(CORPUS[0])
        self.assertEqual(self.notifier.enqueue(), 1)
        self.assertEqual(Notifier(self.p.store, clock=self.clock).enqueue(), 0)
        self.assertEqual(len(self.outbox()), 1)

    def test_baseline_prevents_historical_flood_explicit_repair_is_audited(self):
        ids = [self.ingest(s)['intake_id'] for s in CORPUS]
        # Simulate installing this notifier version over an existing historical database.
        with self.p.store.tx() as db:
            db.execute('DELETE FROM controls WHERE key=?', (BASELINE_KEY,))
        self.notifier = Notifier(self.p.store, clock=self.clock)
        self.assertEqual(self.notifier.enqueue(), 0)
        for expected in (1, 0):
            with self.p.store.tx() as db:
                self.assertEqual(enqueue_misses(self.p.store, db, iso(self.clock()), intake_ids=[ids[1]]), expected)
        self.assertEqual(len(self.outbox()), 1)
        with self.p.store.connection() as db:
            details = json.loads(db.execute("SELECT detail FROM audit_events WHERE kind='INTAKE_MISSES_ENQUEUED'").fetchone()[0])
        self.assertEqual(details, dict(intake_ids=[ids[1]], explicit_backfill=True))

    def test_sample_edits_and_ignored_messages_do_not_notify(self):
        self.notifier.enqueue()
        self.ingest(CORPUS[0], origin='sample')
        self.ingest(CORPUS[1], edit_date=iso(self.clock()))
        self.p.ingest(message(text='Service announcement', message_id='999999'))
        self.assertEqual(self.notifier.enqueue(), 0)

    def test_invalid_and_ambiguous_have_reasons_without_an_instruction(self):
        self.notifier.enqueue()
        first = self.ingest(CORPUS[0])['intake_id']
        second = self.ingest(CORPUS[1])['intake_id']
        with self.p.store.tx() as db:
            db.execute("UPDATE intake_messages SET status='INVALID', normalized='[]',reason='Malformed quote' WHERE id=?", (first,))
            db.execute("UPDATE intake_messages SET status='AMBIGUOUS',reason='Uncertain ordering' WHERE id=?", (second,))
        self.assertEqual(self.notifier.enqueue(), 2)
        self.assertIn('Malformed quote', self.outbox()[0]['text'])
        self.assertIn('Uncertain ordering', self.outbox()[1]['text'])

    def test_failed_delivery_retries_without_new_outbox_or_instruction(self):
        sent = []
        class Sender:
            def send(self, text):
                sent.append(text)
                if len(sent) == 1:
                    raise RuntimeError('temporary failure')
        self.notifier.sender = Sender()
        self.notifier.enqueue()
        self.ingest(CORPUS[0])
        self.notifier.enqueue()
        self.assertEqual(self.notifier.deliver(), (0, 1))
        self.assertEqual(self.notifier.deliver(), (0, 0))
        self.clock.advance(31)
        self.assertEqual(self.notifier.deliver(), (1, 0))
        self.assertEqual(self.notifier.enqueue(), 0)
        self.assertEqual(self.outbox()[0]['attempts'], 2)

    def test_both_quiet_feeds_have_reconcile_heartbeat(self):
        async def run():
            listener = TelegramIntake(dict(api_id=1, api_hash='test', chats=[1645770730, 1475314653]),
                                      self.p.ingest, self.p.store)
            client = FakeClient(FakeWorld())
            await listener.catch_up(client)
            await listener.reconcile(client)
            self.assertEqual(set(listener.status['feed_checks']), {'1645770730', '1475314653'})
            self.assertEqual(listener.status['reconcile_count'], 1)
            self.assertTrue(listener.status['last_reconcile_completed_at'])
            self.assertIsNone(listener.status['last_event_at'])
            for value in listener.status['feed_checks'].values():
                self.assertTrue(value['checked_at'])
                self.assertEqual(value['messages_checked'], 0)
        asyncio.run(run())

    def test_failed_feed_poll_does_not_claim_completed_heartbeat(self):
        async def run():
            listener = TelegramIntake(dict(api_id=1, api_hash='test', chats=[1645770730]),
                                      self.p.ingest, self.p.store)
            class Broken(FakeClient):
                async def get_messages(self, entity, limit):
                    raise ConnectionError('offline')
            with self.assertRaises(ConnectionError):
                await listener.reconcile(Broken(FakeWorld()))
            self.assertTrue(listener.status['last_reconcile_started_at'])
            self.assertIsNone(listener.status['last_reconcile_completed_at'])
            self.assertEqual(listener.status['reconcile_count'], 0)
        asyncio.run(run())
