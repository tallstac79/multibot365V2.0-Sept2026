"""Outbound Telegram status notifications built only from persisted instruction records.

The database stays authoritative: a notification is an outbox row derived from a stored
state, unique per (instruction_id, state), so restarts/retries never double-send and a
failed send never changes lifecycle state. Sending is disabled unless configured.
"""
from datetime import timedelta
from decimal import Decimal, InvalidOperation
import json
import urllib.parse
import urllib.request

from core.lifecycle import TERMINAL
from core.pipeline_store import iso, utcnow

DEFAULT_STATES = ('READY', 'AWAITING_APPROVAL', 'PLACEMENT_UNKNOWN') + tuple(sorted(s.value for s in TERMINAL))
SHORT_ID = 10  # Telegram commands accept this unique prefix of an instruction ID
# Operational alerts raised from the audit log (not instruction states).
EVENT_KINDS = ('MANUAL_CHECK_REQUIRED', 'PLACEMENT_DISCREPANCY')
MAX_ATTEMPTS = 8


def _money(value):
    try:
        amount = Decimal(str(value))
        return f'£{amount:.2f}' if amount.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def format_instruction(row):
    """Plain-text message from a stored instructions row (dict or sqlite3.Row)."""
    row = dict(row)
    selection = row.get('selection_name') or row.get('selection')
    if row.get('line') and row.get('market') in ('SPREAD', 'TOTALS'):
        selection = f"{selection} {row['line']}"
    fields = [('Event', row.get('fixture') or (f"{row['home']} v {row['away']}" if row.get('home') else None)),
              ('Sport', (row.get('sport') or '').title() or None), ('Market', row.get('market')),
              ('Selection', selection), ('Odds', row.get('observed_price') or row.get('alert_price')),
              ('Alert odds', row.get('alert_price') if row.get('observed_price') not in (None, row.get('alert_price'))
               else None),
              ('Minimum', row.get('minimum_price')), ('Stake', _money(row.get('stake'))),
              ('Verified on phone', 'fixture, market, side, line, price, stake + To Return, single selection (slip cleared)'
               if row.get('state') == 'AWAITING_APPROVAL' and row.get('ready_at') else None), (None, None),
              ('Status', row.get('state')),
              ('Bet ref', row.get('bet_reference')),
              ('Approved by', row.get('approved_by') if row.get('execution_mode') == 'dispatch' else None),
              ('Reason', row.get('failure_reason') if row.get('state') != 'COMPLETED' else None),
              ('Device stage', row.get('device_stage')),
              ('Instruction', row.get('instruction_id')), ('Device', row.get('device_id'))]
    headline = {'AWAITING_APPROVAL': 'APPROVAL NEEDED', 'COMPLETED': 'BET PLACED' if row.get('execution_mode') == 'dispatch'
                else None, 'PLACEMENT_UNKNOWN': 'PLACEMENT UNCERTAIN'}.get(row.get('state'))
    lines = ['MultiBot365' + (f' - {headline}' if headline else ''), '']
    for label, value in fields:
        if label is None:
            lines.append('')
        elif value not in (None, ''):
            lines.append(f"{label}: {' '.join(str(value).split())[:300]}")
    short = (row.get('instruction_id') or '')[:SHORT_ID]
    if row.get('state') == 'AWAITING_APPROVAL':
        lines += ['', f'Reply /approve {short} to place this bet, or /reject {short}.',
                  'No reply = no bet (the approval window expires).']
    elif row.get('state') == 'PLACEMENT_UNKNOWN':
        lines += ['', 'Place Bet was tapped but the result was not clear. Checking My Bets now; nothing will be re-tapped.']
    return '\n'.join(lines).replace('\n\n\n', '\n\n')


def format_event(kind, instruction, detail):
    row = dict(instruction or {})
    title = {'MANUAL_CHECK_REQUIRED': 'MANUAL CHECK REQUIRED', 'PLACEMENT_DISCREPANCY': 'PLACEMENT DISCREPANCY'}.get(kind, kind)
    text = [f'MultiBot365 - {title}', '', f"Event: {row.get('fixture')}", f"Instruction: {row.get('instruction_id')}"]
    if kind == 'MANUAL_CHECK_REQUIRED':
        text.append('A Place Bet tap may have placed a bet, but My Bets could not be read. Please check My Bets on the phone.')
    else:
        text.append('The device outcome and My Bets disagree. Please check My Bets on the phone.')
    text.append(f"Detail: {' '.join(str(detail).split())[:300]}")
    return '\n'.join(text)


def format_settlement(bet):
    return '\n'.join(['MultiBot365 - BET SETTLED', '', f"Event: {bet['fixture']}",
                      f"Selection: {bet['selection']} {bet['line'] or ''}".rstrip(), f"Stake: {_money(bet['stake'])}",
                      f"Result: {bet['status']}", f"Returns: {_money(bet['returns']) or 'n/a'}",
                      f"Instruction: {bet['instruction_id']}"])


class Notifier:
    def __init__(self, store, sender=None, states=DEFAULT_STATES, include_undispatched=False, clock=utcnow):
        self.store, self.sender, self.clock = store, sender, clock
        self.states = tuple(states)
        self.include_undispatched = include_undispatched

    def enqueue(self):
        """Create outbox rows for newly reached notifiable states. Returns count."""
        marks = ','.join('?' * len(self.states))
        query = (f"SELECT * FROM instructions i WHERE state IN ({marks}) AND origin='production' AND NOT EXISTS "
                 f"(SELECT 1 FROM notifications n WHERE n.instruction_id=i.instruction_id AND n.state=i.state)")
        if not self.include_undispatched:
            query += " AND (dispatched_at IS NOT NULL OR state IN ('READY','AWAITING_APPROVAL'))"
        created = 0
        now = iso(self.clock())
        insert = ('INSERT OR IGNORE INTO notifications(instruction_id,state,text,created_at,next_attempt_at) '
                  'VALUES (?,?,?,?,?)')
        with self.store.tx() as db:
            for row in db.execute(query, self.states).fetchall():
                created += db.execute(insert, (row['instruction_id'], row['state'], format_instruction(row), now, now)).rowcount
            marks = ','.join('?' * len(EVENT_KINDS))
            for event in db.execute(f'SELECT * FROM audit_events WHERE kind IN ({marks})', EVENT_KINDS).fetchall():
                instruction = db.execute('SELECT * FROM instructions WHERE instruction_id=?',
                                         (event['instruction_id'],)).fetchone()
                created += db.execute(insert, (event['instruction_id'] or '', f"EVENT:{event['kind']}:{event['id']}",
                                               format_event(event['kind'], instruction, event['detail']), now, now)).rowcount
            for bet in db.execute("SELECT * FROM bets WHERE status IN ('WON','LOST','VOID','CASHED_OUT','RETURNED')").fetchall():
                created += db.execute(insert, (bet['instruction_id'], f"SETTLED:{bet['status']}", format_settlement(bet),
                                               now, now)).rowcount
        return created

    def deliver(self):
        """Send due outbox rows. Returns (sent, failed)."""
        if self.sender is None:
            return 0, 0
        now = self.clock()
        with self.store.connection() as db:
            due = db.execute('SELECT * FROM notifications WHERE sent_at IS NULL AND attempts < ? AND '
                             '(next_attempt_at IS NULL OR next_attempt_at <= ?) ORDER BY id',
                             (MAX_ATTEMPTS, iso(now))).fetchall()
        sent = failed = 0
        for row in due:
            # Claim first (attempts+1) so a crash mid-send cannot loop-send the same row.
            with self.store.tx() as db:
                claimed = db.execute('UPDATE notifications SET attempts=attempts+1, next_attempt_at=? '
                                     'WHERE id=? AND sent_at IS NULL AND attempts=?',
                                     (iso(now + timedelta(seconds=30 * 2 ** row['attempts'])), row['id'],
                                      row['attempts'])).rowcount
            if not claimed:
                continue
            try:
                self.sender.send(row['text'])
            except Exception as error:
                failed += 1
                with self.store.tx() as db:
                    db.execute('UPDATE notifications SET last_error=? WHERE id=?',
                               (f'{type(error).__name__}: {error}'[:300], row['id']))
                continue
            sent += 1
            with self.store.tx() as db:
                db.execute('UPDATE notifications SET sent_at=?, last_error=NULL WHERE id=?', (iso(self.clock()), row['id']))
        return sent, failed


class TelegramBotSender:
    """Bot API sendMessage over HTTPS. Token/chat come from untracked local config."""

    def __init__(self, bot_token, chat_id, timeout=10):
        if not bot_token or not chat_id:
            raise ValueError('bot_token and chat_id required')
        self.url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
        self.chat_id, self.timeout = str(chat_id), timeout

    def send(self, text):
        body = urllib.parse.urlencode({'chat_id': self.chat_id, 'text': text, 'disable_web_page_preview': 'true'})
        with urllib.request.urlopen(self.url, data=body.encode(), timeout=self.timeout) as response:
            reply = json.loads(response.read())
        if not reply.get('ok'):
            raise RuntimeError(f"Telegram API error: {reply.get('description')}")
