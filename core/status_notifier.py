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
from core.intake_notifications import enqueue_misses, initialize_baseline
from core.pipeline_store import iso, utcnow

TERMINAL_NAMES = frozenset(s.value for s in TERMINAL)
DEFAULT_STATES = ('READY', 'AWAITING_APPROVAL', 'PLACEMENT_UNKNOWN') + tuple(sorted(TERMINAL_NAMES))
# Automatic mode also announces QUALIFIED (QUEUED) and AUTO APPROVED (APPROVED). Both are transient (an instruction
# passes through them inside one dispatcher tick), so they are derived from the transitions history, not sampled.
TRANSIENT_STATES = ('QUEUED', 'APPROVED')
AUTOMATIC_STATES = TRANSIENT_STATES + DEFAULT_STATES
TRANSIENT_SINCE_KEY = 'notifier_transient_since'   # controls row: only transitions from this moment on are announced
# controls row: from this moment, an instruction announced QUALIFIED that ends before any phone dispatch (daily limit,
# pre-dispatch recheck, session, device) also gets its outcome announced. 27 Sep 2026: on-a177051 / on-a64a66f were
# QUALIFIED then REJECTED "LIMIT: 5 bets already today" with no further message (503 such silent outcomes in history).
QUALIFIED_OUTCOME_SINCE_KEY = 'notifier_qualified_outcome_since'
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


_SIDE_ORDER = ('HOME', 'DRAW', 'AWAY', 'OVER', 'UNDER')


def _percent(opening, current):
    try:
        o, c = Decimal(str(opening)), Decimal(str(current))
        return f'{(c - o) / o * 100:+.1f}%'
    except (InvalidOperation, TypeError, ValueError, ZeroDivisionError):
        return '?'


def _price_signal(sharp, cmp):
    """Price-movement evidence (football 1X2, basketball ML, a same-line football Spread/Totals move): every Pinnacle
    side's opening -> current price, which one uniquely shortened (the selection), sides with no opening price, the line
    when the market has one, and Bet365's price for the selected side. Previously printed 'opening None -> current None'."""
    side, opening, current = sharp['side'], sharp.get('opening_prices') or {}, sharp.get('current_prices') or {}
    moves = []
    for s in [x for x in _SIDE_ORDER if x in opening or x in current]:
        if s in opening and s in current:
            moves.append(f"{s} {opening[s]} -> {current[s]} ({_percent(opening[s], current[s])})" + (' shortened' if s == side else ''))
        elif s in current:
            moves.append(f"{s} {current[s]} (no opening price; not a candidate)")
    line = ''
    if sharp.get('opening_line') is not None or sharp.get('current_line') is not None:
        line = (f"line {sharp.get('current_line')} unchanged; " if sharp.get('opening_line') == sharp.get('current_line')
                else f"line {sharp.get('opening_line')} -> {sharp.get('current_line')}; ")
    text = f"Pinnacle opening -> current selects {side} ({line}{'; '.join(moves)})"
    agrees = sharp.get('highlight_agrees')
    text += f"; Bet365 {side} {cmp.get('bet365_price') or cmp.get('bet365_odds')}"
    text += ' (bold highlight agrees)' if agrees is True else ' (bold highlight on another side)' if agrees is False else ''
    if cmp.get('line_applicable') and cmp.get('line_advantage') is not None:
        text += f"; same-side Bet365 advantage {cmp.get('line_advantage')} pts"
    ev = cmp.get('supplied_ev')
    return text + (f"; EV {ev}%" if ev and cmp.get('ev_status') == 'SUPPLIED_EQUAL_LINE' else f"; EV {cmp.get('ev_status')}")


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
        if sharp.get('opening_prices'):
            return _price_signal(sharp, cmp)
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
    if reason.startswith('LIMIT:'):
        return 'NOT PLACED: DAILY LIMIT' if 'today' in reason or 'daily' in reason else 'NOT PLACED: LIMIT'
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


OUTCOME_SINCE_KEY = 'notifier_outcome_since'   # outcome-only mode: instructions ending before this are never announced
OUTCOME_KEY, CORRECTION_KEY = 'OUTCOME', 'OUTCOME_CORRECTION'
FOUND_STATUSES = ('OPEN', 'WON', 'LOST', 'VOID', 'CASHED_OUT', 'RETURNED', 'DISCREPANCY')
MISSED_REASONS = (
    ('LINE_CHANGED', 'line moved beyond tolerance'), ('BELOW_MINIMUM', 'price below minimum'),
    ('PRICE_CHANGED', 'price changed'), ('WRONG_EVENT', 'event not verified'), ('ALIAS_REQUIRED', 'event not verified'),
    ('EVENT_NOT_VERIFIED', 'event/market not verified'), ('TARGET_NOT_FOUND', 'event/market not found'),
    ('AUTO_APPROVAL_REFUSED', 'automatic approval check failed'), ('PRE_TAP_REJECTED', 'pre-tap check failed'),
    ('LIMIT', 'limit reached'), ('SUSPENDED', 'market suspended'), ('STAKE_LIMITED', 'stake limited by Bet365'),
    ('INSUFFICIENT', 'insufficient funds'), ('SESSION', 'Bet365 session not available'), ('LOGIN', 'Bet365 session not available'),
    ('TAP_NOT_ACCEPTED', 'Place Bet tap not accepted'), ('MANUAL_CHECK_REQUIRED', 'placement unconfirmed'),
    ('DEVICE_OFFLINE', 'phone offline'), ('No device result', 'no phone result'), ('Pre-dispatch recheck: alert_age', 'alert expired before dispatch'),
    ('Pre-dispatch recheck: event_not_started', 'event already started'), ('Pre-dispatch recheck', 'rules recheck failed before dispatch'),
    ('NO BET', 'terms outside tolerance'))


def missed_reason(row, bet=None):
    """Short, stable reason for the MISSED headline; the exact stored reason follows in the body."""
    if (bet or {}).get('status') in ('NOT_PLACED', 'NOT_PLACED_CLAIMED') and row.get('state') == 'UNKNOWN':
        return 'not placed (confirmed in My Bets)'
    reason = str(row.get('failure_reason') or '')
    for key, text in MISSED_REASONS:
        if reason.startswith(key) or f' {key}' in reason[:60]:
            return text
    state = str(row.get('state') or '')
    return {'STALE': 'alert expired', 'TIMEOUT': 'no phone result', 'UNKNOWN': 'placement unconfirmed',
            'PRICE_CHANGED': 'price or line changed', 'TARGET_NOT_FOUND': 'event/market not found',
            'SESSION_REQUIRED': 'Bet365 session not available'}.get(state, state.replace('_', ' ').lower() or 'not placed')


def _terms(market, side, line, price):
    parts = [str(x) for x in (market, side) if x]
    if line not in (None, '', 'NONE', 'None') and market not in ('MONEYLINE', '1X2'):
        parts.append(str(line))
    return ' '.join(parts) + (f' @ {price}' if price else '')


def format_outcome(row, bet=None, observed=None, correction=False):
    """The single operator message for an instruction in automatic mode: PLACED or MISSED - <reason>, with the requested
    terms and, where the phone saw them, the observed terms (receipt terms for a placed bet)."""
    row, bet = dict(row), dict(bet or {})
    kickoff = f" ({row['competition']}, {row['event_time'].replace('T', ' ')} UK)" if row.get('competition') and row.get('event_time') else ''
    requested = (_terms(row.get('market'), row.get('selection_name') or row.get('selection'), row.get('line'), row.get('alert_price'))
                 + f" (min {row.get('minimum_price')}), stake {_money(row.get('stake'))}")
    placed = correction or (row.get('state') == 'COMPLETED' and row.get('execution_mode') == 'dispatch') or bet.get('status') in FOUND_STATUSES
    if placed:
        head = 'MultiBot365 - PLACED' + (' (correction: found in My Bets after a MISSED report)' if correction else '')
        receipt = _terms(row.get('market'), row.get('selection_name') or row.get('selection'),
                         bet.get('actual_line') or bet.get('verified_line') or row.get('line'),
                         bet.get('actual_odds') or bet.get('verified_odds') or bet.get('odds'))
        lines = [head, f"Event: {row.get('fixture')}{kickoff}", f"Placed: {receipt}, stake {_money(bet.get('actual_stake') or bet.get('stake') or row.get('stake'))}"
                 + (f", to return {_money(bet.get('potential_return'))}" if bet.get('potential_return') else ''),
                 f"Requested: {requested}", f"Bet ref: {row.get('bet_reference') or bet.get('bet_reference') or 'not read'}"]
    else:
        lines = [f"MultiBot365 - MISSED - {missed_reason(row, bet)}", f"Event: {row.get('fixture')}{kickoff}", f"Requested: {requested}"]
        if observed:
            lines.append(f"Observed: {_terms(observed.get('market'), observed.get('selection_name') or observed.get('side') or observed.get('selection_role'), observed.get('line'), observed.get('price'))}")
        if row.get('failure_reason'):
            lines.append(f"Reason: {' '.join(str(row['failure_reason']).split())[:300]}")
    lines.append(f"Id: {(row.get('instruction_id') or '')[:SHORT_ID]}")
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
    def __init__(self, store, sender=None, states=DEFAULT_STATES, include_undispatched=False, clock=utcnow, outcome_only=False,
                 unknown_recheck_limit=9):
        self.store, self.sender, self.clock = store, sender, clock
        self.states = tuple(states)
        self.include_undispatched = include_undispatched
        # Automatic mode (operator, 27 Sep 2026): exactly one Telegram message per qualified instruction, PLACED or
        # MISSED - <reason>. Every intermediate lifecycle event stays in the database/dashboard only.
        self.outcome_only = outcome_only
        # A placement left UNKNOWN is reported once My Bets has resolved it or its rechecks are exhausted
        # (reconcile_max_attempts + FinalAction.LATE_RECHECKS), never as a guess while it is still being checked.
        self.unknown_recheck_limit = unknown_recheck_limit
        with self.store.tx() as db:
            initialize_baseline(db, iso(self.clock()))

    def enqueue(self):
        """Create outbox rows for newly reached notifiable states. Returns count."""
        if self.outcome_only:
            return self._enqueue_outcomes()
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
            created += enqueue_misses(self.store, db, now)
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
            if not self.include_undispatched:
                omark = db.execute('SELECT value FROM controls WHERE key=?', (QUALIFIED_OUTCOME_SINCE_KEY,)).fetchone()
                if omark is None:
                    db.execute('INSERT INTO controls VALUES (?,?,?,?)', (QUALIFIED_OUTCOME_SINCE_KEY, json.dumps(now), now, 'notifier-baseline'))
                    osince = now
                else:
                    osince = json.loads(omark[0])
                terminal = [s for s in self.states if s in TERMINAL_NAMES]
                if terminal:
                    marks = ','.join('?' * len(terminal))
                    ended = (f"SELECT * FROM instructions i WHERE state IN ({marks}) AND terminal=1 AND origin='production' "
                             f"AND dispatched_at IS NULL AND COALESCE(terminal_at, updated_at) >= ? AND EXISTS (SELECT 1 FROM "
                             f"notifications q WHERE q.instruction_id=i.instruction_id AND q.state='QUEUED') AND NOT EXISTS "
                             f"(SELECT 1 FROM notifications n WHERE n.instruction_id=i.instruction_id AND n.state=i.state)")
                    for row in db.execute(ended, (*terminal, osince)).fetchall():
                        created += db.execute(insert, (row['instruction_id'], row['state'], format_instruction(row), now, now)).rowcount
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

    def _enqueue_outcomes(self):
        """One OUTCOME row per instruction that was QUALIFIED (reached QUEUED) and has ended (terminal). A superseded alert
        is not an outcome (its newer alert for the same selection reports). The (instruction_id, state) key of the outbox
        makes a second outcome row for the same instruction impossible. Safety exception: a bet reported MISSED that My
        Bets later shows as placed gets ONE correction."""
        now = iso(self.clock())
        insert = ('INSERT OR IGNORE INTO notifications(instruction_id,state,text,created_at,next_attempt_at) '
                  'VALUES (?,?,?,?,?)')
        created = 0
        with self.store.tx() as db:
            mark = db.execute('SELECT value FROM controls WHERE key=?', (OUTCOME_SINCE_KEY,)).fetchone()
            if mark is None:
                db.execute('INSERT INTO controls VALUES (?,?,?,?)', (OUTCOME_SINCE_KEY, json.dumps(now), now, 'notifier-baseline'))
                since = now
            else:
                since = json.loads(mark[0])
            rows = db.execute(
                "SELECT * FROM instructions i WHERE terminal=1 AND origin='production' AND COALESCE(terminal_at, updated_at) >= ? "
                "AND COALESCE(failure_reason, '') NOT LIKE 'SUPERSEDED%' AND COALESCE(failure_reason, '') NOT LIKE 'ALREADY_BET%' "
                "AND EXISTS (SELECT 1 FROM transitions t WHERE t.instruction_id=i.instruction_id AND t.to_state='QUEUED') "
                "AND NOT EXISTS (SELECT 1 FROM notifications n WHERE n.instruction_id=i.instruction_id AND n.state=?) "
                "AND NOT (i.state='UNKNOWN' AND EXISTS (SELECT 1 FROM bets b WHERE b.instruction_id=i.instruction_id AND b.status='UNKNOWN') "
                "AND (SELECT COUNT(*) FROM reconciliations r WHERE r.instruction_id=i.instruction_id) < ?)",
                (since, OUTCOME_KEY, self.unknown_recheck_limit)).fetchall()
            for row in rows:
                bet = db.execute('SELECT * FROM bets WHERE instruction_id=?', (row['instruction_id'],)).fetchone()
                observed = None
                for (detail,) in db.execute("SELECT detail FROM audit_events WHERE instruction_id=? AND kind='ALERT_TO_LIVE_COMPARISON' "
                                            "ORDER BY id DESC", (row['instruction_id'],)):
                    try:
                        live = (json.loads(detail) or {}).get('live')
                    except (TypeError, ValueError):
                        live = None
                    if isinstance(live, dict) and live.get('price'):
                        observed = live
                        break
                created += db.execute(insert, (row['instruction_id'], OUTCOME_KEY, format_outcome(row, bet, observed), now, now)).rowcount
            for row in db.execute(
                    f"SELECT i.* FROM instructions i JOIN bets b USING(instruction_id) JOIN notifications n ON n.instruction_id=i.instruction_id "
                    f"AND n.state=? WHERE b.status IN ({','.join('?' * len(FOUND_STATUSES))}) AND n.text LIKE 'MultiBot365 - MISSED%' "
                    f"AND NOT EXISTS (SELECT 1 FROM notifications c WHERE c.instruction_id=i.instruction_id AND c.state=?)",
                    (OUTCOME_KEY, *FOUND_STATUSES, CORRECTION_KEY)).fetchall():
                bet = db.execute('SELECT * FROM bets WHERE instruction_id=?', (row['instruction_id'],)).fetchone()
                created += db.execute(insert, (row['instruction_id'], CORRECTION_KEY, format_outcome(row, bet, correction=True), now, now)).rowcount
        return created

    def deliver(self, limit=None):
        """Send due outbox rows (at most `limit` per call, oldest first). Returns (sent, failed)."""
        if self.sender is None:
            return 0, 0
        now = self.clock()
        with self.store.connection() as db:
            due = db.execute('SELECT * FROM notifications WHERE sent_at IS NULL AND attempts < ? AND '
                             '(next_attempt_at IS NULL OR next_attempt_at <= ?) ORDER BY id' + (' LIMIT ?' if limit else ''),
                             (MAX_ATTEMPTS, iso(now), *((int(limit),) if limit else ()))).fetchall()
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
