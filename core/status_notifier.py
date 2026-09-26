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

TERMINAL_NAMES = frozenset(s.value for s in TERMINAL)
DEFAULT_STATES = ('READY', 'AWAITING_APPROVAL', 'PLACEMENT_UNKNOWN') + tuple(sorted(TERMINAL_NAMES))
# Automatic mode also announces QUALIFIED (QUEUED) and AUTO APPROVED (APPROVED). Both are transient (an instruction
# passes through them inside one dispatcher tick), so they are derived from the transitions history, not sampled.
TRANSIENT_STATES = ('QUEUED', 'APPROVED')
AUTOMATIC_STATES = TRANSIENT_STATES + DEFAULT_STATES
TRANSIENT_SINCE_KEY = 'notifier_transient_since'   # controls row: only transitions from this moment on are announced
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


def _signal(row):
    """One line naming a line-advantage signal (no EV) so the operator sees why an unequal-line bet qualified."""
    alert = row.get('normalized_alert')
    try:
        alert = json.loads(alert) if isinstance(alert, str) else (alert or {})
    except (TypeError, ValueError):
        return None
    sharp = alert.get('sharp_signal') or {}
    if sharp.get('side'):
        cmp = alert.get('comparison') or {}
        return (f"Pinnacle opening {sharp.get('opening_line')} -> current {sharp.get('current_line')}: "
                f"{sharp['side']}; same-side Bet365 advantage {cmp.get('line_advantage')} pts; "
                f"EV {cmp.get('ev_status')}")
    if alert.get('bet_quality') != 'FAVOURABLE_LINE_SIGNAL':
        return None
    cmp = alert.get('comparison') or {}
    text = (f"Bet365 line {cmp.get('line_advantage')} pts better than Pinnacle "
            f"({cmp.get('reference_line_displayed')} -> {cmp.get('bet365_line_displayed')}), no EV")
    implied = alert.get('implied_target') or {}
    if implied:
        text += '; target implied from the lines (nothing highlighted)'
        if implied.get('pinnacle_movement_agrees') is True:
            text += ', Pinnacle moved this way'
        elif implied.get('pinnacle_movement_agrees') is False:
            text += ', Pinnacle moved the other way'
    return text


def headline_for(row):
    """Concise headline: what happened, from the persisted state and how it was decided."""
    state, mode = row.get('state'), row.get('execution_mode')
    reason = row.get('failure_reason') or ''
    if state == 'QUEUED':
        return 'QUALIFIED'
    if state == 'AWAITING_APPROVAL':
        return 'APPROVAL NEEDED'
    if state == 'APPROVED':
        return 'AUTO APPROVED' if row.get('approved_by') == 'automatic-policy' else f"APPROVED by {row.get('approved_by')}"
    if state == 'COMPLETED' and mode == 'dispatch':
        return 'BET PLACED'
    if state == 'PLACEMENT_UNKNOWN':
        return 'PLACEMENT UNCERTAIN'
    if reason.startswith('PRE_TAP_REJECTED') or reason.startswith('AUTO_APPROVAL_REFUSED'):
        return 'PRE-TAP REJECTED'
    if state == 'SESSION_REQUIRED':
        return 'SESSION REQUIRED'
    if state == 'REJECTED':
        return 'REJECTED'
    if state in TERMINAL_NAMES:
        return state.replace('_', ' ')
    return None


def format_instruction(row, bet=None):
    """Concise plain-text message from a stored instructions row (dict or sqlite3.Row).

    Automatic mode never waits for a reply; only AWAITING_APPROVAL (manual mode) carries the /approve prompt."""
    row = dict(row)
    bet = dict(bet) if bet else {}
    headline = headline_for(row)
    selection = row.get('selection_name') or row.get('selection')
    if row.get('line') and row.get('market') in ('SPREAD', 'TOTALS'):
        selection = f"{selection} {row['line']}"
    odds = row.get('observed_price') or row.get('alert_price')
    event = row.get('fixture') or (f"{row.get('home')} v {row.get('away')}" if row.get('home') else '?')
    lines = ['MultiBot365' + (f' - {headline}' if headline else ''), '', f"Event: {event}",
             f"Bet: {row.get('market')} {selection} @ {odds} (alert {row.get('alert_price')}, min {row.get('minimum_price')}) stake {_money(row.get('stake'))}"]
    signal = _signal(row)
    if signal and headline in ('QUALIFIED', 'APPROVAL NEEDED', 'AUTO APPROVED'):
        lines.append(f"Signal: {signal}")
    if headline == 'AUTO APPROVED':
        lines.append(f"Decided by automatic policy at {row.get('auto_approved_at')}; strategy {row.get('strategy_version')}, "
                     f"rules {row.get('rules_version')}; job {row.get('execution_job_id')}. Fresh pre-tap check next; nothing placed yet.")
    if headline == 'BET PLACED':
        parts = [bet.get('actual_line') and f"line {bet['actual_line']}", bet.get('actual_odds') and f"odds {bet['actual_odds']}",
                 bet.get('actual_stake') and f"stake {_money(bet['actual_stake'])}"]
        actual = ' '.join(x for x in parts if x)
        lines.append(f"Bet ref: {row.get('bet_reference') or bet.get('bet_reference') or 'pending'}; receipt {actual or 'terms not read'}; "
                     f"approved by {row.get('approved_by')} ({row.get('approval_mode') or 'manual'}). My Bets verification follows.")
    if row.get('state') not in ('COMPLETED', 'QUEUED', 'APPROVED', 'AWAITING_APPROVAL') and row.get('failure_reason'):
        lines.append(f"Reason: {' '.join(str(row['failure_reason']).split())[:300]}")
    if row.get('state') == 'PLACEMENT_UNKNOWN':
        lines.append('Place Bet was tapped but the result was not clear. Checking My Bets now; nothing will be re-tapped.')
    short = (row.get('instruction_id') or '')[:SHORT_ID]
    if row.get('state') == 'AWAITING_APPROVAL':
        lines += ['', f'Reply /approve to place this bet, or /reject. (Bet {short})',
                  'No reply = no bet (the approval window expires).']
    stage = f" | stage {row.get('device_stage')}" if row.get('device_stage') and headline not in ('QUALIFIED', 'AUTO APPROVED') else ''
    lines.append(f"Id: {short}{stage}")
    return '\n'.join(lines)


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


def format_reconciled(bet):
    return '\n'.join(['MultiBot365 - RECONCILED', '', f"Event: {bet['fixture']}",
                      f"Selection: {bet['selection']} {bet['line'] or ''}".rstrip() + f" @ {bet['odds']} stake {_money(bet['stake'])}",
                      f"My Bets: found (ref {bet['bet_reference'] or 'n/a'}); status {bet['status']}",
                      f"Id: {bet['instruction_id'][:SHORT_ID]}"])


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
            query += " AND (dispatched_at IS NOT NULL OR state IN ('QUEUED','READY','AWAITING_APPROVAL','APPROVED'))"
        created = 0
        now = iso(self.clock())
        insert = ('INSERT OR IGNORE INTO notifications(instruction_id,state,text,created_at,next_attempt_at) '
                  'VALUES (?,?,?,?,?)')
        with self.store.tx() as db:
            for row in db.execute(query, self.states).fetchall():
                bet = db.execute('SELECT * FROM bets WHERE instruction_id=?', (row['instruction_id'],)).fetchone() \
                    if row['state'] == 'COMPLETED' else None
                created += db.execute(insert, (row['instruction_id'], row['state'], format_instruction(row, bet), now, now)).rowcount
            # Baseline: history that predates the first run of this notifier version is never announced (a fresh start
            # over an old database would otherwise queue one message per historical instruction; real: 2026-09-26).
            mark = db.execute('SELECT value FROM controls WHERE key=?', (TRANSIENT_SINCE_KEY,)).fetchone()
            if mark is None:
                db.execute('INSERT INTO controls VALUES (?,?,?,?)', (TRANSIENT_SINCE_KEY, json.dumps(now), now, 'notifier-baseline'))
                since = now
            else:
                since = json.loads(mark[0])
            transient = [s for s in TRANSIENT_STATES if s in self.states]
            if transient:
                marks = ','.join('?' * len(transient))
                history = (f"SELECT i.*, t.to_state AS past_state FROM transitions t JOIN instructions i USING(instruction_id) "
                           f"WHERE t.to_state IN ({marks}) AND t.at >= ? AND i.origin='production' AND NOT EXISTS "
                           f"(SELECT 1 FROM notifications n WHERE n.instruction_id=i.instruction_id AND n.state=t.to_state)")
                for row in db.execute(history, (*transient, since)).fetchall():
                    past = dict(row, state=row['past_state'])
                    created += db.execute(insert, (row['instruction_id'], row['past_state'], format_instruction(past), now, now)).rowcount
            for bet in db.execute("SELECT * FROM bets WHERE verified_at IS NOT NULL AND verified_at >= ? AND status NOT IN "
                                  "('NOT_PLACED','NOT_PLACED_CLAIMED')", (since,)).fetchall():
                created += db.execute(insert, (bet['instruction_id'], 'RECONCILED', format_reconciled(bet), now, now)).rowcount
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
