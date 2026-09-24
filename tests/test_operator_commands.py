"""Telegram operator commands and final-action notifications (fake Bot API, no network)."""
import tempfile
import unittest
from pathlib import Path

from core.status_notifier import Notifier
from core.telegram_commands import CommandHandler
from tests.pipeline_support import MELBOURNE, RYTAS, T0, Clock, FakeGateway, message, pipeline
from tests.test_final_action import placement_result

CHAT = '5550001'


class FakeApi:
    def __init__(self):
        self.updates, self.sent, self.next_id = [], [], 100

    def push(self, text, chat=CHAT, age=0, clock=None):
        self.next_id += 1
        self.updates.append({'update_id': self.next_id, 'message': {
            'chat': {'id': int(chat)}, 'text': text, 'date': int((clock() if clock else T0).timestamp()) - age}})

    def get_updates(self, offset):
        return [u for u in self.updates if u['update_id'] >= offset]

    def send(self, chat_id, text):
        self.sent.append((chat_id, text))


class CommandTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.clock = Clock()
        self.gateway = FakeGateway(self.clock)
        self.p = pipeline(Path(tmp.name) / 'p.sqlite3', self.clock, final_action_enabled=True)
        self.api = FakeApi()
        self.handler = CommandHandler(self.p, self.api, CHAT)
        self.api.push('/stop')                           # already waiting before the service started
        self.assertEqual(self.handler.poll(), 0)         # first run: baseline, never acted on
        self.assertFalse(self.p.final.paused())

    def state(self, iid):
        with self.p.store.connection() as db:
            return db.execute('SELECT state FROM instructions WHERE instruction_id=?', (iid,)).fetchone()[0]

    def test_approve_by_short_id_places_next(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.p.tick(self.gateway)
        self.api.push(f'/approve {iid[:10]}', clock=self.clock)
        self.assertEqual(self.handler.poll(), 1)
        self.assertEqual(self.state(iid), 'APPROVED')
        self.assertIn('APPROVED', self.api.sent[-1][1])
        self.p.tick(self.gateway)
        self.assertEqual(self.gateway.submitted[-1]['execution_mode'], 'dispatch')

    def test_unauthorised_and_stale_commands_are_ignored(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.p.tick(self.gateway)
        self.api.push(f'/approve {iid}', chat='999', clock=self.clock)
        self.api.push(f'/approve {iid}', age=301, clock=self.clock)
        self.assertEqual(self.handler.poll(), 0)
        self.assertEqual(self.state(iid), 'AWAITING_APPROVAL')
        with self.p.store.connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM audit_events WHERE kind='UNAUTHORISED_COMMAND'").fetchone()[0], 1)
        self.assertEqual(self.api.sent, [])

    def test_commands_are_never_replayed(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.p.tick(self.gateway)
        self.api.push(f'/reject {iid}', clock=self.clock)
        self.handler.poll()
        self.handler.poll()
        restarted = CommandHandler(self.p, self.api, CHAT)
        self.assertEqual(restarted.poll(), 0)
        self.assertEqual(len(self.api.sent), 1)

    def test_stop_resume_status_and_errors(self):
        self.api.push('/stop', clock=self.clock)
        self.handler.poll()
        self.assertTrue(self.p.final.paused())
        self.api.push('/status', clock=self.clock)
        self.api.push('/approve nothing-matches', clock=self.clock)
        self.api.push('/resume', clock=self.clock)
        self.handler.poll()
        replies = [text for _, text in self.api.sent]
        self.assertIn('PAUSED', replies[1])
        self.assertTrue(replies[2].startswith('Not done'))
        self.assertIn('RESUMED', replies[3])
        self.assertFalse(self.p.final.paused())


class NotificationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.clock = Clock()
        self.gateway = FakeGateway(self.clock)
        self.p = pipeline(Path(tmp.name) / 'p.sqlite3', self.clock, final_action_enabled=True)
        self.sent = []
        sender = type('S', (), {'send': lambda _, text: self.sent.append(text)})()
        self.notifier = Notifier(self.p.store, sender, clock=self.clock)

    def flush(self):
        self.notifier.enqueue()
        self.notifier.deliver()

    def test_approval_request_then_bet_placed(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.p.tick(self.gateway)
        self.flush()
        self.assertIn('APPROVAL NEEDED', self.sent[0])
        self.assertIn(f'/approve {iid[:10]}', self.sent[0])
        self.p.final.approve(iid, 'operator')
        self.p.tick(self.gateway)
        self.gateway.results[iid] = placement_result(iid)
        self.p.tick(self.gateway)
        self.flush()
        self.assertIn('BET PLACED', self.sent[-1])
        self.assertIn('Bet ref: JL1234567890', self.sent[-1])
        self.flush()
        self.assertEqual(len(self.sent), 2)                # never twice

    def test_uncertain_placement_and_manual_check_alerts(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.p.tick(self.gateway)
        self.p.final.approve(iid, 'operator')
        self.p.tick(self.gateway)
        self.gateway.results[iid] = placement_result(iid, 'PLACEMENT_UNKNOWN')
        self.p.tick(self.gateway)
        self.flush()
        self.assertIn('PLACEMENT UNCERTAIN', self.sent[-1])
        self.assertIn('nothing will be re-tapped', self.sent[-1])
        with self.p.store.tx() as db:
            self.p.store.audit(db, 'MANUAL_CHECK_REQUIRED', {'why': 'test'}, iid)
        self.flush()
        self.assertIn('MANUAL CHECK REQUIRED', self.sent[-1])


if __name__ == '__main__':
    unittest.main()
