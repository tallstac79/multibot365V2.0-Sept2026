"""MultiBot365 unattended pipeline service.

    python -m tools.pipeline_service run              # listener + dispatcher + notifier
    python -m tools.pipeline_service telegram-login   # one-time interactive Telegram login
    python -m tools.pipeline_service status           # JSON summary of the store
    python -m tools.pipeline_service replay FILE      # ingest one text file as SAMPLE origin

Settings: untracked .local/pipeline.json (see docs/TELEGRAM_INGESTION.md). Rules come
from the dashboard's decision-support store and are re-read every cycle.
"""
import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.decision_support import Store as ConfigStore  # noqa: E402
from core.pipeline import Pipeline, Settings, SourceMessage  # noqa: E402
from core.pipeline_store import Store, iso, utcnow  # noqa: E402
from core.status_notifier import Notifier, TelegramBotSender, DEFAULT_STATES  # noqa: E402

log = logging.getLogger('multibot.pipeline_service')
DEFAULTS = {'database': '.local/pipeline.sqlite3', 'rules_database': '.local/dashboard.sqlite3',
            'coordinator_config': '.local/coordinator.json', 'status_file': '.local/pipeline_status.json',
            'tick_seconds': 2, 'pipeline': {}, 'telegram_intake': None, 'notifications': {'enabled': False}}


class JsonLines(logging.Formatter):
    """Structured log lines the dashboard's Technical logs view already understands."""

    def format(self, record):
        item = dict(timestamp=datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
                    component=record.name.removeprefix('multibot.'), severity=record.levelname,
                    message=record.getMessage())
        for key in ('instruction_id', 'device_id'):
            if hasattr(record, key):
                item[key] = getattr(record, key)
        return json.dumps(item)


def load_settings(path):
    settings = dict(DEFAULTS)
    if Path(path).exists():
        settings.update(json.loads(Path(path).read_text(encoding='utf-8-sig')))
    for key in ('database', 'rules_database', 'coordinator_config', 'status_file'):
        settings[key] = ROOT / settings[key]
    return settings


class UnconfiguredGateway:
    """Used when .local/coordinator.json is absent: the device is reported OFFLINE."""

    def health(self):
        raise FileNotFoundError('Coordinator configuration missing')

    def submit(self, payload):
        raise FileNotFoundError('Coordinator configuration missing')

    def result(self, instruction_id):
        raise FileNotFoundError('Coordinator configuration missing')


def build(settings):
    store = Store(settings['database'])
    rules = ConfigStore(settings['rules_database'])
    pipeline = Pipeline(store, lambda: rules.get()['config'], Settings.from_dict(settings['pipeline']))
    return store, pipeline


def gateway_for(settings):
    if not settings['coordinator_config'].exists():
        return UnconfiguredGateway()
    from core.device_gateway import CoordinatorGateway
    return CoordinatorGateway(config_path=settings['coordinator_config'])


async def run(settings):
    store, pipeline = build(settings)
    open_count = pipeline.recover()
    log.info('Pipeline started; %s open instruction(s) will be polled, never resent', open_count)
    gateway = gateway_for(settings)
    notify = settings['notifications'] or {}
    sender = TelegramBotSender(notify['bot_token'], notify['chat_id']) if notify.get('enabled') else None
    notifier = Notifier(store, sender, notify.get('states', DEFAULT_STATES), notify.get('include_undispatched', False))
    intake = None
    tasks = []
    if settings.get('telegram_intake'):
        from core.telegram_intake import TelegramIntake
        intake = TelegramIntake(settings['telegram_intake'], pipeline.ingest, store)
        tasks.append(asyncio.create_task(intake.run()))
    else:
        log.warning('telegram_intake not configured: no continuous ingestion')

    async def cycle():
        while True:
            state = dict(heartbeat_at=iso(utcnow()), dispatch_enabled=pipeline.settings.dispatch_enabled,
                         intake=intake.status if intake else dict(state='NOT_CONFIGURED'),
                         notifications='ENABLED' if sender else 'DISABLED', last_error=None)
            try:
                await asyncio.to_thread(pipeline.tick, gateway)
                await asyncio.to_thread(notifier.enqueue)
                await asyncio.to_thread(notifier.deliver)
            except Exception as error:  # keep running; the store stays consistent per transaction
                state['last_error'] = f'{type(error).__name__}: {error}'[:300]
                log.exception('Pipeline cycle failed')
            try:
                settings['status_file'].write_text(json.dumps(state, default=str), encoding='utf-8')
            except OSError:
                pass
            await asyncio.sleep(settings['tick_seconds'])

    tasks.append(asyncio.create_task(cycle()))
    await asyncio.gather(*tasks)


def status(settings):
    store = Store(settings['database'])
    with store.connection() as db:
        summary = dict(
            intake={r[0]: r[1] for r in db.execute('SELECT status, COUNT(*) FROM intake_messages GROUP BY status')},
            instructions={r[0]: r[1] for r in db.execute('SELECT state, COUNT(*) FROM instructions GROUP BY state')},
            devices=[dict(r) for r in db.execute('SELECT device_id,status,checked_at,error FROM device_state')],
            sessions=[dict(r) for r in db.execute('SELECT * FROM session_state')],
            notifications_pending=db.execute('SELECT COUNT(*) FROM notifications WHERE sent_at IS NULL').fetchone()[0])
    print(json.dumps(summary, indent=2))


def replay(settings, path, chat_id, message_id):
    _, pipeline = build(settings)
    now = iso(utcnow())
    result = pipeline.ingest(SourceMessage(chat_id=chat_id, message_id=message_id, origin='sample', source='replay',
                                           text=Path(path).read_text(encoding='utf-8'), received_at=now,
                                           source_timestamp=now, provenance={'replay_file': str(path)}))
    print(json.dumps(result, indent=2))


async def telegram_login(settings):
    from telethon import TelegramClient
    tg = settings['telegram_intake'] or {}
    session = ROOT / tg.get('session', '.local/telegram/oddsnotifier')
    session.parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(str(session), int(tg['api_id']), tg['api_hash'])
    await client.start()  # prompts for phone number and login code in this terminal
    me = await client.get_me()
    print(f'Authorized as user id {me.id}; session stored at {session}')
    for chat in tg.get('chats', []):
        entity = await client.get_entity(int(chat))
        print(f'Source chat {chat}: {getattr(entity, "title", entity)}')
    await client.disconnect()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--settings', default=str(ROOT / '.local/pipeline.json'))
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('run')
    sub.add_parser('status')
    sub.add_parser('telegram-login')
    play = sub.add_parser('replay')
    play.add_argument('file')
    play.add_argument('--chat-id', default='-999')
    play.add_argument('--message-id', required=True)
    args = parser.parse_args()
    settings = load_settings(args.settings)
    if args.command == 'run':
        (ROOT / 'logs').mkdir(exist_ok=True)
        handler = logging.FileHandler(ROOT / 'logs/pipeline.log', encoding='utf-8')
        handler.setFormatter(JsonLines())
        logging.basicConfig(level=logging.INFO, handlers=[handler, logging.StreamHandler()])
        asyncio.run(run(settings))
    elif args.command == 'status':
        status(settings)
    elif args.command == 'telegram-login':
        asyncio.run(telegram_login(settings))
    else:
        replay(settings, args.file, args.chat_id, args.message_id)


if __name__ == '__main__':
    main()
