"""Telegram intake (reconnect/catch-up/reconcile/formatting) and status notifications."""
import asyncio
import re
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from telethon.tl.types import MessageEntityBold, MessageEntityTextUrl

from core.status_notifier import Notifier, format_instruction
from core.telegram_intake import TelegramIntake, render, to_source_message
from tests.pipeline_support import SNAPSHOT, MELBOURNE, RYTAS, T0, Clock, FakeGateway, message, pipeline, fail_result, ready_result

CHAT = -1001475314653


def split_markdown(markdown):
    """Inverse of render for test data: Markdown -> (plain text, Telethon entities), UTF-16 offsets."""
    plain, entities, position = '', [], 0
    pattern = re.compile(r'\*\*(.+?)\*\*|\[([^\]]+)\]\((https://[^)\s]+)\)', re.DOTALL)
    for match in pattern.finditer(markdown):
        plain += markdown[position:match.start()]
        offset = len(plain.encode('utf-16-le')) // 2
        inner = match[1] if match[1] is not None else match[2]
        length = len(inner.encode('utf-16-le')) // 2
        entities.append(MessageEntityBold(offset, length) if match[1] is not None else
                        MessageEntityTextUrl(offset, length, match[3]))
        plain += inner
        position = match.end()
    return plain + markdown[position:], entities


class Msg:
    def __init__(self, id, markdown, date=T0, edit_date=None):
        self.id, self.date, self.edit_date, self.media, self.post_author = id, date, edit_date, None, None
        self.message, self.entities = split_markdown(markdown)
        self.peer_id = CHAT


class FormattingTests(unittest.TestCase):
    def test_render_round_trips_every_genuine_message(self):
        for sample in SNAPSHOT:
            plain, entities = split_markdown(sample['raw_text'])
            self.assertNotIn('**', plain)
            dicts = [dict(type='bold' if isinstance(e, MessageEntityBold) else 'text_url', offset=e.offset,
                          length=e.length, **({'url': e.url} if hasattr(e, 'url') else {})) for e in entities]
            self.assertEqual(render(plain, dicts), sample['raw_text'], sample['message_id'])

    def test_render_nested_emoji_and_bad_entities(self):
        text = '🎯 EV bold link'
        entities = [dict(type='text_url', offset=6, length=9, url='https://x.io'), dict(type='bold', offset=6, length=4),
                    dict(type='italic', offset=0, length=2), dict(type='bold', offset=90, length=3)]
        self.assertEqual(render(text, entities), '🎯 EV [**bold** link](https://x.io)')
        self.assertEqual(render('', entities), '')

    def test_source_message_preserves_raw_entities_ids_and_times(self):
        item = to_source_message(Msg(67894, MELBOURNE['raw_text']), CHAT, received_at=T0.isoformat())
        self.assertEqual((item.chat_id, item.message_id, item.text), (str(CHAT), '67894', MELBOURNE['raw_text']))
        self.assertNotIn('**', item.raw_text)
        self.assertEqual(item.source_timestamp, T0.isoformat())
        self.assertIn({'type': 'bold', 'offset': item.entities[-1]['offset'], 'length': 4}, item.entities)
        self.assertIsNone(item.edit_date)
        self.assertEqual(item.provenance['peer_id'], str(CHAT))

    def test_source_message_keeps_the_feed_identity(self):
        # 2026-09-27: two OddsNotifier feeds; every row must say which one it came from
        feed = dict(title='OddsNotifier Feed 1', username='oddsnotifierfeed1bot', peer_id='1645770730')
        item = to_source_message(Msg(71160, MELBOURNE['raw_text']), 1645770730, received_at=T0.isoformat(), feed=feed)
        self.assertEqual((item.chat_id, item.message_id), ('1645770730', '71160'))
        self.assertEqual((item.provenance['feed_title'], item.provenance['feed_username'], item.provenance['peer_id']),
                         ('OddsNotifier Feed 1', 'oddsnotifierfeed1bot', '1645770730'))


class FakeWorld:
    def __init__(self):
        self.messages = []        # ascending ids
        self.fail_connects = 0
        self.clients = []

    def add(self, markdown, id=None):
        message = Msg(id or (self.messages[-1].id + 1 if self.messages else 1), markdown)
        self.messages.append(message)
        return message


class FakeClient:
    def __init__(self, world):
        self.world, self.handlers = world, []
        self.disconnected = asyncio.get_running_loop().create_future()
        world.clients.append(self)

    async def connect(self):
        if self.world.fail_connects:
            self.world.fail_connects -= 1
            raise ConnectionError('network down')

    async def is_user_authorized(self):
        return True

    def on(self, event):
        def register(handler):
            self.handlers.append((event, handler))
            return handler
        return register

    async def get_entity(self, chat):
        return chat

    async def get_messages(self, entity, limit):
        return list(reversed(self.world.messages))[:limit]

    async def iter_messages(self, entity, min_id, reverse):
        for message in list(self.world.messages):
            if message.id > min_id:
                yield message

    def is_connected(self):
        return not self.disconnected.done()

    async def disconnect(self):
        if not self.disconnected.done():
            self.disconnected.set_result(None)

    async def deliver(self, message):
        class Event:
            pass
        event = Event()
        event.message = message
        await self.handlers[0][1](event)


class IntakeListenerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock = Clock()
        self.p = pipeline(Path(self.tmp.name) / 'p.sqlite3', self.clock)
        self.world = FakeWorld()

    def listener(self, **settings):
        values = dict(api_id=1, api_hash='x', chats=[CHAT], reconcile_seconds=0.05, reconnect_initial_seconds=0.01)
        values.update(settings)
        return TelegramIntake(values, self.p.ingest, self.p.store, client_factory=lambda: FakeClient(self.world))

    def rows(self):
        with self.p.store.connection() as db:
            return [(r['message_id'], r['status'], r['delivery']) for r in
                    db.execute('SELECT * FROM intake_messages ORDER BY CAST(message_id AS INTEGER), id')]

    async def wait_for(self, predicate, seconds=3):
        for _ in range(int(seconds / 0.01)):
            if predicate():
                return
            await asyncio.sleep(0.01)
        self.fail('condition not reached')

    def test_reconnect_restart_catch_up_reconcile_and_duplicates(self):
        async def scenario():
            for index in range(1, 4):
                self.world.add('Old channel message', index)       # predates first start
            self.world.fail_connects = 2                            # Telegram unreachable at boot
            intake = self.listener()
            task = asyncio.create_task(intake.run())
            await self.wait_for(lambda: intake.status['state'] == 'LISTENING')
            self.assertGreaterEqual(intake.status['reconnects'], 2)
            self.assertEqual(self.rows(), [])                       # history not back-processed
            live = self.world.add(MELBOURNE['raw_text'], 4)
            await self.world.clients[-1].deliver(live)             # live event
            await self.world.clients[-1].deliver(live)             # Telegram re-delivery
            await self.world.clients[-1].disconnect()               # connection drop
            self.world.add('Channel notice while offline', 5)
            self.world.add(RYTAS['raw_text'], 6)
            await self.wait_for(lambda: len(self.rows()) == 4)       # catch-up after reconnect
            self.world.add('New odds update on Pinnacle\nbroken', 7)  # event missed entirely
            await self.wait_for(lambda: len(self.rows()) == 5)       # periodic reconciliation
            intake.stopped.set()
            await self.world.clients[-1].disconnect()
            await asyncio.wait_for(task, 2)
            return intake
        asyncio.run(scenario())
        self.assertEqual(self.rows(), [('4', 'PARSED', 'event'), ('4', 'DUPLICATE', 'event'), ('5', 'IGNORED', 'catch_up'),
                                       ('6', 'PARSED', 'catch_up'), ('7', 'INVALID', 'reconcile')])

    def test_process_restart_resumes_from_stored_messages(self):
        async def run_until(count):
            intake = self.listener()
            task = asyncio.create_task(intake.run())
            await self.wait_for(lambda: len(self.rows()) >= count and intake.status['state'] == 'LISTENING')
            intake.stopped.set()
            await self.world.clients[-1].disconnect()
            await asyncio.wait_for(task, 2)

        async def scenario():
            self.world.add('Old message', 10)
            await run_until(0)                                      # first start: mark at 10
            self.world.add(MELBOURNE['raw_text'], 11)               # arrives while mini PC is down
            self.world.add('Notice', 12)
            await run_until(2)                                      # restart: catch-up from mark
            await run_until(2)                                      # another restart: nothing new
        asyncio.run(scenario())
        self.assertEqual(self.rows(), [('11', 'PARSED', 'catch_up'), ('12', 'IGNORED', 'catch_up')])

    def test_edited_message_event_is_recorded_not_executed(self):
        async def scenario():
            # Test the edit event in isolation; reconciliation/redelivery has its own test.
            intake = self.listener(reconcile_seconds=30)
            task = asyncio.create_task(intake.run())
            await self.wait_for(lambda: intake.status['state'] == 'LISTENING')
            original = self.world.add(MELBOURNE['raw_text'], 20)
            await self.world.clients[-1].deliver(original)
            original.edit_date = T0 + timedelta(seconds=30)
            await intake._store(original, CHAT, 'event', edited=True)
            intake.stopped.set()
            await self.world.clients[-1].disconnect()
            await asyncio.wait_for(task, 2)
        asyncio.run(scenario())
        self.assertEqual([r[1] for r in self.rows()], ['PARSED', 'IGNORED'])


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock = Clock()
        self.p = pipeline(Path(self.tmp.name) / 'p.sqlite3', self.clock)
        self.gateway = FakeGateway(self.clock)
        self.sent = []

    def send(self, text):
        self.sent.append(text)

    def ready(self, sample=MELBOURNE):
        iid = self.p.ingest(message(sample))['instruction_id']
        self.p.tick(self.gateway)
        self.gateway.results[iid] = ready_result(iid)
        self.p.tick(self.gateway)
        return iid

    def test_ready_message_matches_contract(self):
        iid = self.ready()
        notifier = Notifier(self.p.store, type('S', (), {'send': lambda _, t: self.send(t)})(), clock=self.clock)
        self.assertEqual(notifier.enqueue(), 1)
        self.assertEqual(notifier.deliver(), (1, 0))
        text = self.sent[0]
        # concise contract (2026-09-26): headline, event, one bet line (market, selection, odds, alert odds, minimum,
        # stake) and the short id with the device stage; nothing else for a READY-only verification
        for line in ('MultiBot365', 'Event: SE Melbourne Phoenix vs Melbourne United',
                     'Bet: TOTALS Over 190.5 @ 2.20 (alert 2.20, min 2.20) stake £1.00', f'Id: {iid[:10]} | stage PASS'):
            self.assertIn(line, text.splitlines())
        self.assertLessEqual(len(text.splitlines()), 5)
        self.assertNotIn('Reason:', text)
        self.assertEqual((notifier.enqueue(), notifier.deliver()), (0, (0, 0)))  # never twice

    def test_failure_reason_is_exact_stored_reason(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.p.tick(self.gateway)
        self.gateway.results[iid] = fail_result(iid, 'PRICE_CHANGED', 'live 2.05 below minimum 2.20')
        self.p.tick(self.gateway)
        with self.p.store.connection() as db:
            row = db.execute('SELECT * FROM instructions WHERE instruction_id=?', (iid,)).fetchone()
        text = format_instruction(row)
        self.assertTrue(text.startswith('MultiBot365 - PRICE CHANGED'))
        self.assertIn(f"Reason: {row['failure_reason']}", text)
        self.assertEqual(row['failure_reason'], 'PRICE_CHANGED: live 2.05 below minimum 2.20')

    def test_send_failure_retries_with_backoff_and_never_changes_state(self):
        iid = self.ready()

        class Flaky:
            calls = 0

            def send(self, text):
                Flaky.calls += 1
                if Flaky.calls == 1:
                    raise OSError('telegram unreachable')
        notifier = Notifier(self.p.store, Flaky(), clock=self.clock)
        notifier.enqueue()
        self.assertEqual(notifier.deliver(), (0, 1))
        self.assertEqual(notifier.deliver(), (0, 0))       # backoff: not yet due
        self.clock.advance(31)
        self.assertEqual(notifier.deliver(), (1, 0))
        self.assertEqual(notifier.deliver(), (0, 0))
        with self.p.store.connection() as db:
            self.assertEqual(db.execute('SELECT state FROM instructions').fetchone()[0], 'READY')
            self.assertEqual(db.execute('SELECT attempts, sent_at IS NOT NULL FROM notifications').fetchone()[:], (2, 1))

    def test_rules_rejections_and_samples_not_notified_by_default(self):
        self.p.settings.dispatch_enabled = False
        stale = self.p.ingest(message(MELBOURNE, source=T0 - timedelta(hours=1)))
        self.assertEqual(stale['state'], 'STALE')
        self.assertEqual(Notifier(self.p.store, None, clock=self.clock).enqueue(), 0)
        self.assertEqual(Notifier(self.p.store, None, include_undispatched=True, clock=self.clock).enqueue(), 1)
        sample = message(RYTAS, origin='sample')
        self.p.ingest(sample)
        self.assertEqual(Notifier(self.p.store, None, include_undispatched=True, clock=self.clock).enqueue(), 0)


if __name__ == '__main__':
    unittest.main()
