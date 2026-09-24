"""MultiBot365 unattended pipeline service.

    python -m tools.pipeline_service run              # listener + dispatcher + notifier
    python -m tools.pipeline_service telegram-login   # one-time interactive Telegram login
    python -m tools.pipeline_service status           # JSON summary of the store
    python -m tools.pipeline_service replay FILE      # ingest one text file as SAMPLE origin
    python -m tools.pipeline_service approve ID       # approve an AWAITING_APPROVAL final action
    python -m tools.pipeline_service reject ID        # decline it
    python -m tools.pipeline_service pause|resume     # kill switch
    python -m tools.pipeline_service bets             # placed bets and their verification/settlement

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
            'tick_seconds': 1, 'pipeline': {}, 'telegram_intake': None, 'notifications': {'enabled': False}}


class JsonLines(logging.Formatter):
    """Structured log lines the dashboard's Technical logs view already understands."""

    def format(self, record):
        item = dict(timestamp=datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
                    component=record.name.removeprefix('multibot.'), severity=record.levelname,
                    message=record.getMessage())
        for key in ('instruction_id', 'device_id'):
            if hasattr(record, key):
                item[key] = getattr(record, key)
        if record.exc_info:
            item['error'] = self.formatException(record.exc_info)[-2000:]
        return json.dumps(item)


def persist_disarm(path, disarmed):
    """One-shot fired: write dispatch/final action OFF to the config so a restart stays disarmed."""
    data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    section = data.setdefault('pipeline', {})
    if section.get('dispatch_enabled') is False and section.get('final_action_enabled') is False:
        return
    section.update(dispatch_enabled=False, final_action_enabled=False, final_action_one_shot=False,
                   disarmed=disarmed)
    Path(path).write_text(json.dumps(data, indent=2), encoding='utf-8')
    log.warning('One-shot final action disarmed after %s; config written OFF', disarmed.get('instruction_id'))


def load_settings(path):
    settings = dict(DEFAULTS)
    if Path(path).exists():
        settings.update(json.loads(Path(path).read_text(encoding='utf-8-sig')))
    settings['config_path'] = Path(path)
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
    commands = None
    if notify.get('enabled') and notify.get('commands', True):
        from core.telegram_commands import BotApi, CommandHandler
        commands = CommandHandler(pipeline, BotApi(notify['bot_token']), notify['chat_id'],
                                  notify.get('allowed_user_ids') or [])
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
                         final_action_enabled=pipeline.settings.final_action_enabled,
                         auto_approve=pipeline.settings.auto_approve, paused=pipeline.final.paused(),
                         intake=intake.status if intake else dict(state='NOT_CONFIGURED'),
                         notifications='ENABLED' if sender else 'DISABLED',
                         commands='ENABLED' if commands else 'DISABLED', last_error=None)
            try:
                if commands:
                    try:
                        await asyncio.to_thread(commands.poll)
                    except Exception as error:  # Telegram outage must never stop the pipeline
                        state['commands_error'] = f'{type(error).__name__}: {error}'[:200]
                await asyncio.to_thread(pipeline.tick, gateway)
                if pipeline.disarmed and settings.get('config_path'):
                    persist_disarm(settings['config_path'], pipeline.disarmed)
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
            notifications_pending=db.execute('SELECT COUNT(*) FROM notifications WHERE sent_at IS NULL').fetchone()[0],
            bets={r[0]: r[1] for r in db.execute('SELECT status, COUNT(*) FROM bets GROUP BY status')},
            paused=bool(json.loads((db.execute("SELECT value FROM controls WHERE key='paused'").fetchone() or ['false'])[0])))
    print(json.dumps(summary, indent=2))


def operator(settings, command, reference=None):
    _, pipeline = build(settings)
    by = 'cli'
    try:
        if command == 'approve':
            print('APPROVED', pipeline.final.approve(reference, by))
        elif command == 'reject':
            print('REJECTED', pipeline.final.reject(reference, by))
        elif command in ('pause', 'resume'):
            pipeline.final.set_paused(command == 'pause', by)
            print('PAUSED' if command == 'pause' else 'RESUMED')
        else:
            print(json.dumps(pipeline.store.bets(), indent=2))
    except (LookupError, PermissionError) as error:
        print('NOT DONE:', error)
        raise SystemExit(1)


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
    for name in ('approve', 'reject'):
        sub.add_parser(name).add_argument('id')
    for name in ('pause', 'resume', 'bets'):
        sub.add_parser(name)
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
    elif args.command in ('approve', 'reject', 'pause', 'resume', 'bets'):
        operator(settings, args.command, getattr(args, 'id', None))
    else:
        replay(settings, args.file, args.chat_id, args.message_id)


if __name__ == '__main__':
    main()
