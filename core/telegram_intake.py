"""Continuous OddsNotifier intake from Telegram (Telethon user session).

Reliability model (every path ends in Pipeline.ingest, which is idempotent):
* live NewMessage / MessageEdited events
* startup catch-up of every message after the stored checkpoint (mini-PC restart)
* periodic reconciliation of the latest N messages (missed events, reconnect gaps)
* the connection loop reconnects with capped exponential backoff forever

Formatting: Telegram delivers plain text + entities. `render` rebuilds exactly the Markdown
form the production parser was verified against (**bold**, [text](url)) using UTF-16
offsets; the plain text and the full entity list are also stored untouched.
"""
import asyncio
import re
from datetime import timezone
import logging
from pathlib import Path

from core.pipeline import SourceMessage
from core.pipeline_store import iso, utcnow

log = logging.getLogger('multibot.telegram_intake')


# ------------------------------------------------------------------ formatting
def _utf16(text):
    return text.encode('utf-16-le')


def render(text, entities):
    """Plain text + entity dicts -> Markdown with bold and text links preserved.

    entities: [{'type': 'bold'|'text_url'|..., 'offset': int, 'length': int, 'url': str}]
    Offsets/lengths are UTF-16 code units, as Telegram defines them. Other entity types
    are kept in storage but not rendered (the verified grammar does not use them).
    """
    if not text:
        return text or ''
    units = _utf16(text)
    inserts = []
    for index, entity in enumerate(entities or []):
        kind, start, length = entity.get('type'), entity.get('offset'), entity.get('length')
        if kind not in ('bold', 'text_url') or not isinstance(start, int) or not isinstance(length, int) or length <= 0:
            continue
        end = start + length
        if start < 0 or end * 2 > len(units):
            continue
        opening, closing = '**', '**'
        if kind == 'text_url':
            opening, closing = '[', f"]({entity.get('url', '')})"
        # At one position: closes before opens; outer spans open first and close last.
        inserts += [(start, 1, (-end, index), opening), (end, 0, (-start, -index), closing)]
    inserts.sort(key=lambda item: item[:3])
    out, cursor = [], 0
    for position, _, _, marker in inserts:
        out.append(units[cursor * 2:position * 2].decode('utf-16-le'))
        out.append(marker)
        cursor = position
    out.append(units[cursor * 2:].decode('utf-16-le'))
    return ''.join(out)


_PRICE_BOLD = re.compile(r'^[0-9]+\.[0-9]+$')


def render_oddsnotifier(text, entities):
    """Markdown matching the production OddsNotifier grammar.

    Telegram bolds many spans (header, sport, fixture, date, market, EV). The verified
    basketball parser only accepts \**price**\ on the Bet365 quote row, plus \[text](url)    links without nested bold. Suppress non-price bold and bold that coincides with a link.
    Full entity lists remain stored untouched via entity_dicts.
    """
    if not text:
        return text or ''
    units = _utf16(text)
    link_spans = []
    for entity in entities or []:
        if entity.get('type') == 'text_url' and isinstance(entity.get('offset'), int) and isinstance(entity.get('length'), int):
            link_spans.append((entity['offset'], entity['offset'] + entity['length']))
    filtered = []
    for entity in entities or []:
        kind, start, length = entity.get('type'), entity.get('offset'), entity.get('length')
        if kind == 'text_url' and isinstance(start, int) and isinstance(length, int) and length > 0:
            filtered.append(entity)
            continue
        if kind != 'bold' or not isinstance(start, int) or not isinstance(length, int) or length <= 0:
            continue
        end = start + length
        if start < 0 or end * 2 > len(units):
            continue
        fragment = units[start * 2:end * 2].decode('utf-16-le')
        if not _PRICE_BOLD.fullmatch(fragment):
            continue
        if any(start >= lo and end <= hi for lo, hi in link_spans):
            continue
        filtered.append(entity)
    return render(text, filtered)


def entity_dicts(entities):
    """Telethon entity objects -> JSON-serializable dicts."""
    names = {'MessageEntityBold': 'bold', 'MessageEntityTextUrl': 'text_url', 'MessageEntityUrl': 'url',
             'MessageEntityItalic': 'italic', 'MessageEntityUnderline': 'underline', 'MessageEntityCode': 'code',
             'MessageEntityPre': 'pre', 'MessageEntityStrike': 'strike', 'MessageEntitySpoiler': 'spoiler',
             'MessageEntityCustomEmoji': 'custom_emoji', 'MessageEntityMention': 'mention', 'MessageEntityHashtag': 'hashtag'}
    out = []
    for entity in entities or []:
        item = dict(type=names.get(type(entity).__name__, type(entity).__name__),
                    offset=entity.offset, length=entity.length)
        if getattr(entity, 'url', None):
            item['url'] = entity.url
        out.append(item)
    return out


def to_source_message(message, chat_id, *, received_at=None, edited=False, origin='production', feed=None):
    """Telethon Message -> SourceMessage (pure; unit-testable with simple stand-ins).

    feed: {'title', 'username', 'peer_id'} of the source dialog (OddsNotifier Feed 1 / Feed 2), kept on the intake row's
    provenance next to the peer id (chat_id), message id, source timestamp and backend receipt timestamp."""
    entities = entity_dicts(getattr(message, 'entities', None))
    plain = message.message or ''
    stamp = message.date.astimezone(timezone.utc).isoformat() if message.date else None
    edit = getattr(message, 'edit_date', None) if edited else None
    provenance = dict(producer='core.telegram_intake', has_media=bool(getattr(message, 'media', None)),
                      post_author=getattr(message, 'post_author', None), peer_id=str(chat_id))
    if feed:
        provenance.update(feed_title=feed.get('title'), feed_username=feed.get('username'))
    return SourceMessage(chat_id=str(chat_id), message_id=str(message.id), text=render_oddsnotifier(plain, entities),
                         raw_text=plain, entities=entities, source_timestamp=stamp,
                         received_at=received_at or iso(utcnow()), origin=origin,
                         edit_date=edit.astimezone(timezone.utc).isoformat() if edit else None,
                         provenance=provenance)


# ------------------------------------------------------------------ listener
class TelegramIntake:
    """Owns the Telethon connection. `handle(SourceMessage, delivery)` does the storing."""

    def __init__(self, settings, handle, store, origin='production', client_factory=None):
        self.api_id = int(settings['api_id'])
        self.api_hash = settings['api_hash']
        self.session = settings.get('session', '.local/telegram/oddsnotifier')
        self.chats = [int(c) if isinstance(c, int) or str(c).lstrip('-').isdigit() else str(c).lstrip('@')
                      for c in settings['chats']]
        self.backfill = int(settings.get('backfill_on_first_start', 0))
        self.reconcile_seconds = float(settings.get('reconcile_seconds', 30))
        self.backoff_start = float(settings.get('reconnect_initial_seconds', 1))
        self.reconcile_limit = int(settings.get('reconcile_limit', 50))
        self.handle, self.store, self.origin = handle, store, origin
        self.client_factory = client_factory
        self.stopped = asyncio.Event()
        self.feeds = {}   # peer id -> {'title', 'username', 'peer_id', 'configured_as'} resolved at catch-up
        self.status = dict(state='STARTING', connected=False, last_event_at=None, last_error=None, reconnects=0, chats={})

    def _session_path(self):
        path = Path(self.session)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[1] / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _client(self):
        if self.client_factory:
            return self.client_factory()
        from telethon import TelegramClient
        return TelegramClient(str(self._session_path()), self.api_id, self.api_hash, auto_reconnect=True,
                              connection_retries=None, retry_delay=2)

    async def _entity(self, client, chat):
        """Resolve a configured chat id or username; warm dialogs if the session lacks access_hash."""
        from telethon import utils
        try:
            return await client.get_entity(chat)
        except (ValueError, TypeError):
            pass
        async for dialog in client.iter_dialogs():
            peer = utils.get_peer_id(dialog.entity)
            entity_id = getattr(dialog.entity, 'id', None)
            if peer == chat or entity_id == chat:
                return dialog.entity
            if isinstance(chat, int) and entity_id is not None:
                # Accept channel-form (-100…) vs bare id for the same Telegram object.
                if abs(peer) == abs(chat) or entity_id == abs(chat) % 10**10:
                    return dialog.entity
        return await client.get_entity(chat)

    async def _store(self, message, chat_id, delivery, edited=False):
        item = to_source_message(message, chat_id, edited=edited, feed=self.feeds.get(str(chat_id)))
        # SQLite work off the event loop; failures propagate so the message is retried by
        # reconciliation/catch-up instead of being dropped.
        await asyncio.to_thread(self.handle, item, delivery)
        self.status['last_event_at'] = iso(utcnow())

    async def catch_up(self, client):
        from telethon import utils
        for chat in self.chats:
            entity = await self._entity(client, chat)
            peer = utils.get_peer_id(entity)
            # Which dialog this configured chat is: kept for every stored row and reported in the intake status, so the
            # subscription is auditable (2026-09-27: only Feed 2 had been configured; Feed 1 alerts were never seen).
            self.feeds[str(peer)] = dict(title=utils.get_display_name(entity), username=getattr(entity, 'username', None),
                                         peer_id=str(peer), configured_as=str(chat))
            self.status['chats'] = dict(self.feeds)
            last = await asyncio.to_thread(self.store.last_message_id, self.origin, str(peer))
            if last is None:
                # First ever start: optionally backfill; otherwise begin at the newest message.
                newest = await client.get_messages(entity, limit=max(1, self.backfill))
                for message in reversed(newest if self.backfill else []):
                    await self._store(message, peer, 'backfill')
                if newest:
                    await asyncio.to_thread(self.store.set_checkpoint, self.origin, str(peer), newest[0].id)
                continue
            async for message in client.iter_messages(entity, min_id=last, reverse=True):
                await self._store(message, peer, 'catch_up')

    async def reconcile(self, client):
        from telethon import utils
        for chat in self.chats:
            entity = await self._entity(client, chat)
            peer = utils.get_peer_id(entity)
            recent = await client.get_messages(entity, limit=self.reconcile_limit)
            # Only messages after the first-start mark are in scope; older history is never
            # silently back-processed. Gaps above the mark (missed events) are filled.
            floor = await asyncio.to_thread(self.store.checkpoint_mark, self.origin, str(peer)) or 0
            known = await asyncio.to_thread(self.store.known_message_ids, self.origin, str(peer), [m.id for m in recent])
            for message in reversed(recent):
                if str(message.id) not in known and message.id > floor:
                    await self._store(message, peer, 'reconcile')

    async def run(self):
        from telethon import events, utils
        backoff = self.backoff_start
        while not self.stopped.is_set():
            client = self._client()
            try:
                await client.connect()
                if not await client.is_user_authorized():
                    self.status.update(state='NOT_AUTHORIZED', last_error='Telegram session not authorized; '
                                       'run: python -m tools.pipeline_service telegram-login')
                    log.error(self.status['last_error'])
                    await asyncio.sleep(60)
                    continue

                @client.on(events.NewMessage(chats=self.chats))
                async def on_new(event):
                    await self._store(event.message, utils.get_peer_id(event.message.peer_id), 'event')

                @client.on(events.MessageEdited(chats=self.chats))
                async def on_edit(event):
                    await self._store(event.message, utils.get_peer_id(event.message.peer_id), 'event', edited=True)

                await self.catch_up(client)
                self.status.update(state='LISTENING', connected=True, last_error=None)
                backoff = self.backoff_start
                while client.is_connected() and not self.stopped.is_set():
                    done, _ = await asyncio.wait([client.disconnected], timeout=self.reconcile_seconds)
                    if not done:
                        await self.reconcile(client)
            except Exception as error:  # network, auth, flood-wait, storage: never exit the loop
                self.status.update(state='RECONNECTING', connected=False, last_error=f'{type(error).__name__}: {error}'[:300])
                log.warning('Telegram intake error; reconnecting in %ss: %s', backoff, error)
            finally:
                self.status['connected'] = False
                try:
                    await client.disconnect()
                except Exception:
                    pass
            if not self.stopped.is_set():
                self.status['reconnects'] += 1
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
