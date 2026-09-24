"""Authoritative SQLite store for intake, instruction lifecycle, sessions and notifications.

Default path: .local/pipeline.sqlite3 (untracked). WAL journal; every mutation runs in
a BEGIN IMMEDIATE transaction so concurrent listener/dispatcher processes serialize.
Idempotency is enforced by the schema itself, not only by application checks:

* one non-duplicate intake row per (origin, chat, message, edit key)
* instruction_id is the primary key and is derived deterministically from the source
* state transitions are compare-and-set on the current state; terminal is final
* one notification per (instruction_id, state)
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import sqlite3
from pathlib import Path

from core.lifecycle import State, allowed, TERMINAL

SCHEMA_VERSION = 4  # 2: intake status PARSED_PARTIAL; 3: final action (approval, placement, bets); 4: queue/device timings
SCHEMA = '''
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS intake_messages (
    id INTEGER PRIMARY KEY,
    origin TEXT NOT NULL CHECK (origin IN ('production','sample')),
    source TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    edit_key TEXT NOT NULL DEFAULT '',
    delivery TEXT NOT NULL,
    duplicate_of INTEGER REFERENCES intake_messages(id),
    instruction_id TEXT,
    raw_text TEXT,
    formatted_text TEXT,
    entities TEXT,
    source_timestamp TEXT,
    received_at TEXT NOT NULL,
    processed_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PARSED','PARSED_PARTIAL','AMBIGUOUS','INVALID','DUPLICATE','IGNORED')),
    reason TEXT,
    parser_profile TEXT,
    parser_version TEXT,
    normalized TEXT,
    provenance TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS intake_identity ON intake_messages(origin, chat_id, message_id, edit_key)
    WHERE status != 'DUPLICATE';
CREATE INDEX IF NOT EXISTS intake_chat ON intake_messages(origin, chat_id, message_id);
CREATE TABLE IF NOT EXISTS instructions (
    instruction_id TEXT PRIMARY KEY,
    origin TEXT NOT NULL,
    intake_id INTEGER NOT NULL REFERENCES intake_messages(id),
    chat_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    selection_key TEXT NOT NULL,
    state TEXT NOT NULL,
    terminal INTEGER NOT NULL DEFAULT 0,
    failure_reason TEXT,
    device_stage TEXT,
    sport TEXT, competition TEXT, fixture TEXT, home TEXT, away TEXT, event_time TEXT,
    market TEXT, selection TEXT, selection_name TEXT, line TEXT, alternate_line INTEGER,
    alert_price TEXT, minimum_price TEXT, observed_price TEXT, stake TEXT, displayed_ev TEXT,
    device_id TEXT, session_state TEXT,
    raw_alert TEXT, normalized_alert TEXT, rules_result TEXT, dispatch_payload TEXT,
    result_payload TEXT, evidence TEXT,
    received_at TEXT, parsed_at TEXT, rules_applied_at TEXT, queued_at TEXT,
    dispatched_at TEXT, device_active_at TEXT, ready_at TEXT, completed_at TEXT,
    duration_ms INTEGER,
    dispatch_attempts INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    execution_mode TEXT, approval_requested_at TEXT, approved_at TEXT, approved_by TEXT,
    placement_unknown_at TEXT, placement TEXT, bet_reference TEXT,
    device_started_at TEXT, terminal_at TEXT, queue_wait_ms INTEGER, device_execution_ms INTEGER
);
CREATE INDEX IF NOT EXISTS instruction_state ON instructions(state, queued_at);
CREATE INDEX IF NOT EXISTS instruction_selection ON instructions(origin, selection_key);
CREATE TABLE IF NOT EXISTS transitions (
    id INTEGER PRIMARY KEY,
    instruction_id TEXT NOT NULL REFERENCES instructions(instruction_id),
    from_state TEXT, to_state TEXT NOT NULL, at TEXT NOT NULL,
    actor TEXT NOT NULL, reason TEXT, detail TEXT
);
CREATE INDEX IF NOT EXISTS transition_instruction ON transitions(instruction_id, id);
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY, at TEXT NOT NULL, kind TEXT NOT NULL,
    instruction_id TEXT, device_id TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS device_state (
    device_id TEXT PRIMARY KEY, status TEXT NOT NULL, checked_at TEXT NOT NULL,
    last_online_at TEXT, error TEXT, health TEXT
);
CREATE TABLE IF NOT EXISTS session_state (
    device_id TEXT PRIMARY KEY, state TEXT NOT NULL, observed_at TEXT NOT NULL,
    reported_at TEXT NOT NULL, source TEXT NOT NULL, detail TEXT
);
CREATE TABLE IF NOT EXISTS session_history (
    id INTEGER PRIMARY KEY, device_id TEXT NOT NULL, state TEXT NOT NULL, observed_at TEXT NOT NULL,
    reported_at TEXT NOT NULL, source TEXT NOT NULL, detail TEXT
);
CREATE TABLE IF NOT EXISTS intake_checkpoint (
    origin TEXT NOT NULL, chat_id TEXT NOT NULL, last_message_id INTEGER NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY (origin, chat_id)
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY, instruction_id TEXT NOT NULL, state TEXT NOT NULL, text TEXT NOT NULL,
    created_at TEXT NOT NULL, sent_at TEXT, attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT,
    next_attempt_at TEXT, UNIQUE (instruction_id, state)
);
CREATE TABLE IF NOT EXISTS bets (
    id INTEGER PRIMARY KEY,
    instruction_id TEXT NOT NULL UNIQUE REFERENCES instructions(instruction_id),
    status TEXT NOT NULL,
    bet_reference TEXT, fixture TEXT, market TEXT, selection TEXT, line TEXT,
    stake TEXT, odds TEXT, potential_return TEXT, returns TEXT,
    placed_at TEXT, verified_at TEXT, settled_at TEXT, source TEXT, evidence TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reconciliations (
    id INTEGER PRIMARY KEY,
    device_instruction_id TEXT NOT NULL UNIQUE,
    purpose TEXT NOT NULL,
    instruction_id TEXT,
    view TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    requested_at TEXT NOT NULL,
    submitted_at TEXT, completed_at TEXT, outcome TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS controls (
    key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL, updated_by TEXT
);
'''
# v4 (A4): per-instruction timing. queue_wait_ms = queued_at -> first device start; device_execution_ms = phone
# time summed over the instruction's device runs (verification + placement); terminal_at = terminal state time.
V4_INSTRUCTION_COLUMNS = (('device_started_at', 'TEXT'), ('terminal_at', 'TEXT'), ('queue_wait_ms', 'INTEGER'),
                          ('device_execution_ms', 'INTEGER'))
V3_INSTRUCTION_COLUMNS = ('execution_mode', 'approval_requested_at', 'approved_at', 'approved_by',
                          'placement_unknown_at', 'placement', 'bet_reference')

STAGE_COLUMNS = {State.PARSED: 'parsed_at', State.RULES_APPLIED: 'rules_applied_at', State.QUEUED: 'queued_at',
                 State.AWAITING_APPROVAL: 'approval_requested_at', State.APPROVED: 'approved_at',
                 State.DISPATCHED: 'dispatched_at', State.DEVICE_ACTIVE: 'device_active_at', State.READY: 'ready_at',
                 State.PLACEMENT_UNKNOWN: 'placement_unknown_at'}
UPDATABLE = {'failure_reason', 'device_stage', 'observed_price', 'device_id', 'session_state', 'rules_result',
             'dispatch_payload', 'result_payload', 'evidence', 'dispatch_attempts', 'minimum_price', 'stake',
             'execution_mode', 'approved_by', 'placement', 'bet_reference'}
JSON_COLUMNS = {'normalized_alert', 'rules_result', 'dispatch_payload', 'result_payload', 'evidence',
                'entities', 'normalized', 'provenance', 'detail', 'health', 'placement'}


def utcnow():
    return datetime.now(timezone.utc)


def iso(moment):
    return moment.astimezone(timezone.utc).isoformat(timespec='milliseconds')


def instruction_id_for(origin, chat_id, message_id):
    """Deterministic, coordinator-safe ID (letters/digits/hyphen, <= 64 chars)."""
    identity = json.dumps(['OddsNotifier', origin, str(chat_id), str(message_id)], separators=(',', ':'))
    prefix = 'on-' if origin == 'production' else 'sample-on-'
    return prefix + hashlib.sha256(identity.encode()).hexdigest()[:24]


def selection_key(alert):
    parts = [alert.get(k) for k in ('sport', 'fixture', 'scheduled_at_local', 'market', 'target_side', 'target_line')]
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()[:24]


def _dump(value):
    return None if value is None else json.dumps(value, sort_keys=True, default=str)


def _ms_between(start, end):
    try:
        return int((datetime.fromisoformat(end) - datetime.fromisoformat(start.replace('Z', '+00:00'))).total_seconds() * 1000)
    except (TypeError, ValueError, AttributeError):
        return None


class Store:
    def __init__(self, path, clock=utcnow):
        self.path = Path(path)
        self.clock = clock  # injectable for deterministic tests
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            self._migrate(db)
            db.executescript(SCHEMA)
            db.execute('INSERT OR IGNORE INTO meta VALUES (?,?)', ('schema_version', str(SCHEMA_VERSION)))
            db.execute("UPDATE meta SET value=? WHERE key='schema_version' AND CAST(value AS INTEGER) < ?",
                       (str(SCHEMA_VERSION), SCHEMA_VERSION))

    @classmethod
    def _migrate(cls, db):
        cls._migrate_v2(db)
        cls._migrate_v3(db)
        cls._migrate_v4(db)

    @staticmethod
    def _migrate_v4(db):
        """v3 -> v4: queue/device timing columns on instructions."""
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='instructions'").fetchone() is None:
            return
        present = {r[1] for r in db.execute('PRAGMA table_info(instructions)')}
        missing = [(c, t) for c, t in V4_INSTRUCTION_COLUMNS if c not in present]
        if not missing:
            return
        db.execute('BEGIN IMMEDIATE')
        try:
            for column, kind in missing:
                db.execute(f'ALTER TABLE instructions ADD COLUMN {column} {kind}')
            db.execute('COMMIT')
        except Exception:
            db.execute('ROLLBACK')
            raise

    @staticmethod
    def _migrate_v3(db):
        """v2 -> v3: add final-action columns to instructions (new tables are created by SCHEMA)."""
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='instructions'").fetchone() is None:
            return
        present = {r[1] for r in db.execute('PRAGMA table_info(instructions)')}
        missing = [c for c in V3_INSTRUCTION_COLUMNS if c not in present]
        if not missing:
            return
        db.execute('BEGIN IMMEDIATE')
        try:
            for column in missing:
                db.execute(f'ALTER TABLE instructions ADD COLUMN {column} TEXT')
            db.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', '3')")
            db.execute('COMMIT')
        except BaseException:
            db.execute('ROLLBACK')
            raise

    @staticmethod
    def _migrate_v2(db):
        """v1 -> v2: widen the intake status CHECK. SQLite cannot alter a CHECK, so the table
        is rebuilt in one transaction (documented 12-step procedure, foreign keys off)."""
        row = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='intake_messages'").fetchone()
        if row is None or 'PARSED_PARTIAL' in row[0]:
            return
        create = SCHEMA[SCHEMA.index('CREATE TABLE IF NOT EXISTS intake_messages'):]
        create = create[:create.index(');') + 2].replace('IF NOT EXISTS intake_messages', 'intake_messages_v2')
        db.execute('PRAGMA foreign_keys=OFF')
        db.execute('BEGIN IMMEDIATE')
        try:
            db.execute(create)
            db.execute('INSERT INTO intake_messages_v2 SELECT * FROM intake_messages')
            db.execute('DROP TABLE intake_messages')
            db.execute('ALTER TABLE intake_messages_v2 RENAME TO intake_messages')
            if db.execute('PRAGMA foreign_key_check').fetchall():
                raise sqlite3.IntegrityError('Foreign key check failed during migration')
            db.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', '2')")
            db.execute('COMMIT')
        except BaseException:
            db.execute('ROLLBACK')
            raise
        finally:
            db.execute('PRAGMA foreign_keys=ON')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA busy_timeout=30000')
        db.execute('PRAGMA foreign_keys=ON')
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def tx(self):
        """One atomic unit of work. Rolls back on any exception."""
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                yield db
            except BaseException:
                db.execute('ROLLBACK')
                raise
            db.execute('COMMIT')

    # ---- audit -------------------------------------------------------------------------
    def audit(self, db, kind, detail=None, instruction_id=None, device_id=None, at=None):
        db.execute('INSERT INTO audit_events(at,kind,instruction_id,device_id,detail) VALUES (?,?,?,?,?)',
                   (at or iso(self.clock()), kind, instruction_id, device_id, _dump(detail)))

    # ---- intake ------------------------------------------------------------------------
    def find_intake(self, db, origin, chat_id, message_id, edit_key=''):
        return db.execute("SELECT * FROM intake_messages WHERE origin=? AND chat_id=? AND message_id=? AND edit_key=? "
                          "AND status!='DUPLICATE'", (origin, str(chat_id), str(message_id), edit_key)).fetchone()

    def insert_intake(self, db, **row):
        for key in ('entities', 'normalized', 'provenance'):
            row[key] = _dump(row.get(key))
        columns = ','.join(row)
        cursor = db.execute(f'INSERT INTO intake_messages({columns}) VALUES ({",".join("?" * len(row))})',
                            tuple(row.values()))
        return cursor.lastrowid

    def last_message_id(self, origin, chat_id):
        with self.connection() as db:
            seen = db.execute('SELECT MAX(CAST(message_id AS INTEGER)) FROM intake_messages WHERE origin=? AND chat_id=?',
                              (origin, str(chat_id))).fetchone()[0]
            mark = db.execute('SELECT last_message_id FROM intake_checkpoint WHERE origin=? AND chat_id=?',
                              (origin, str(chat_id))).fetchone()
        values = [v for v in (seen, mark[0] if mark else None) if v is not None]
        return max(values) if values else None

    def set_checkpoint(self, origin, chat_id, message_id):
        with self.tx() as db:
            db.execute('INSERT OR IGNORE INTO intake_checkpoint VALUES (?,?,?,?)',
                       (origin, str(chat_id), int(message_id), iso(self.clock())))

    def checkpoint_mark(self, origin, chat_id):
        """The first-start mark: messages at or below it predate intake and are out of scope."""
        with self.connection() as db:
            mark = db.execute('SELECT last_message_id FROM intake_checkpoint WHERE origin=? AND chat_id=?',
                              (origin, str(chat_id))).fetchone()
        return mark[0] if mark else None

    def known_message_ids(self, origin, chat_id, ids):
        ids = [str(i) for i in ids]
        if not ids:
            return set()
        with self.connection() as db:
            rows = db.execute(f"SELECT message_id FROM intake_messages WHERE origin=? AND chat_id=? AND edit_key='' "
                              f"AND message_id IN ({','.join('?' * len(ids))})", (origin, str(chat_id), *ids)).fetchall()
        return {r[0] for r in rows}

    # ---- instructions ------------------------------------------------------------------
    def create_instruction(self, db, *, at, **row):
        for key in ('normalized_alert', 'rules_result'):
            row[key] = _dump(row.get(key))
        row.update(state=State.RECEIVED.value, terminal=0, updated_at=at)
        columns = ','.join(row)
        db.execute(f'INSERT INTO instructions({columns}) VALUES ({",".join("?" * len(row))})', tuple(row.values()))
        db.execute('INSERT INTO transitions(instruction_id,from_state,to_state,at,actor,reason) VALUES (?,?,?,?,?,?)',
                   (row['instruction_id'], None, State.RECEIVED.value, row['received_at'], 'intake',
                    'Source message received'))

    def get_instruction(self, db, instruction_id):
        return db.execute('SELECT * FROM instructions WHERE instruction_id=?', (instruction_id,)).fetchone()

    def transition(self, db, instruction_id, target, *, reason=None, actor='pipeline', detail=None, at=None, **fields):
        """Compare-and-set state change. Returns True if applied, False if refused (audited)."""
        target = State(target)
        at = at or iso(self.clock())
        row = self.get_instruction(db, instruction_id)
        if row is None:
            raise KeyError(instruction_id)
        current = row['state']
        if not allowed(current, target):
            self.audit(db, 'TRANSITION_REFUSED', dict(from_state=current, to_state=target.value, reason=reason,
                                                     actor=actor), instruction_id, at=at)
            return False
        unknown = set(fields) - UPDATABLE
        if unknown:
            raise ValueError(f'Not updatable: {sorted(unknown)}')
        values = {k: (_dump(v) if k in JSON_COLUMNS else v) for k, v in fields.items()}
        values['state'], values['updated_at'] = target.value, at
        if target in STAGE_COLUMNS:
            values[STAGE_COLUMNS[target]] = at
        # A4 timings: first device start ends the queue wait; every device run adds to device_execution_ms.
        if target == State.DEVICE_ACTIVE and not row['device_started_at']:
            values['device_started_at'] = at
            values['queue_wait_ms'] = _ms_between(row['queued_at'], at)
        if current in (State.DEVICE_ACTIVE.value, State.DISPATCHED.value) and target != State.DEVICE_ACTIVE:
            spent = _ms_between(row['device_active_at'] or row['dispatched_at'], at)
            if spent is not None:
                values['device_execution_ms'] = (row['device_execution_ms'] or 0) + spent
        if target in TERMINAL:
            values.update(terminal=1, completed_at=at, terminal_at=at)
            if reason and 'failure_reason' not in values and target != State.COMPLETED:
                values['failure_reason'] = reason
            try:
                start = datetime.fromisoformat(row['received_at'].replace('Z', '+00:00'))
                values['duration_ms'] = int((datetime.fromisoformat(at) - start).total_seconds() * 1000)
            except (TypeError, ValueError, AttributeError):
                pass
        assignments = ','.join(f'{k}=?' for k in values)
        cursor = db.execute(f'UPDATE instructions SET {assignments} WHERE instruction_id=? AND state=? AND terminal=0',
                            (*values.values(), instruction_id, current))
        if cursor.rowcount != 1:
            self.audit(db, 'TRANSITION_CONFLICT', dict(from_state=current, to_state=target.value), instruction_id, at=at)
            return False
        db.execute('INSERT INTO transitions(instruction_id,from_state,to_state,at,actor,reason,detail) VALUES (?,?,?,?,?,?,?)',
                   (instruction_id, current, target.value, at, actor, reason, _dump(detail)))
        return True

    def update_fields(self, db, instruction_id, **fields):
        unknown = set(fields) - UPDATABLE
        if unknown:
            raise ValueError(f'Not updatable: {sorted(unknown)}')
        values = {k: (_dump(v) if k in JSON_COLUMNS else v) for k, v in fields.items()}
        values['updated_at'] = iso(self.clock())
        db.execute(f'UPDATE instructions SET {",".join(f"{k}=?" for k in values)} WHERE instruction_id=?',
                   (*values.values(), instruction_id))

    def instructions_in(self, states, origin=None):
        states = [State(s).value for s in states]
        query = f'SELECT * FROM instructions WHERE state IN ({",".join("?" * len(states))})'
        args = list(states)
        if origin:
            query += ' AND origin=?'
            args.append(origin)
        with self.connection() as db:
            return db.execute(query + ' ORDER BY queued_at, received_at', args).fetchall()

    # ---- device / session ---------------------------------------------------------------
    def record_device(self, device_id, status, *, health=None, error=None, at=None):
        at = at or iso(self.clock())
        with self.tx() as db:
            db.execute('INSERT INTO device_state(device_id,status,checked_at,last_online_at,error,health) VALUES (?,?,?,?,?,?) '
                       'ON CONFLICT(device_id) DO UPDATE SET status=excluded.status, checked_at=excluded.checked_at, '
                       'last_online_at=COALESCE(excluded.last_online_at, device_state.last_online_at), '
                       'error=excluded.error, health=excluded.health',
                       (device_id, status, at, at if status == 'ONLINE' else None, error, _dump(health)))

    def device(self, device_id):
        with self.connection() as db:
            return db.execute('SELECT * FROM device_state WHERE device_id=?', (device_id,)).fetchone()

    def record_session(self, report, reported_at=None):
        reported_at = reported_at or iso(self.clock())
        values = (report.device_id, report.state.value, report.observed_at, reported_at, report.source, report.detail)
        with self.tx() as db:
            previous = db.execute('SELECT state, observed_at FROM session_state WHERE device_id=?',
                                  (report.device_id,)).fetchone()
            if previous and previous['observed_at'] > report.observed_at:
                return False  # Older observation arriving late never overwrites a newer one.
            db.execute('INSERT INTO session_state VALUES (?,?,?,?,?,?) ON CONFLICT(device_id) DO UPDATE SET '
                       'state=excluded.state, observed_at=excluded.observed_at, reported_at=excluded.reported_at, '
                       'source=excluded.source, detail=excluded.detail', values)
            if not previous or previous['state'] != report.state.value:
                db.execute('INSERT INTO session_history(device_id,state,observed_at,reported_at,source,detail) '
                           'VALUES (?,?,?,?,?,?)', values)
        return True

    def session(self, device_id):
        with self.connection() as db:
            row = db.execute('SELECT * FROM session_state WHERE device_id=?', (device_id,)).fetchone()
        return dict(row) if row else None

    # ---- final action: controls, bets, reconciliations ---------------------------------
    def control(self, key, default=None):
        with self.connection() as db:
            row = db.execute('SELECT value FROM controls WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_control(self, key, value, by='system', db=None):
        values = (key, json.dumps(value), iso(self.clock()), by)
        sql = ('INSERT INTO controls VALUES (?,?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, '
               'updated_at=excluded.updated_at, updated_by=excluded.updated_by')
        if db is not None:
            db.execute(sql, values)
            return
        with self.tx() as tx:
            tx.execute(sql, values)
            self.audit(tx, 'CONTROL_CHANGED', dict(key=key, value=value, by=by))

    def upsert_bet(self, db, instruction_id, **fields):
        fields = {k: (_dump(v) if k == 'evidence' else v) for k, v in fields.items()}
        fields['updated_at'] = iso(self.clock())
        existing = db.execute('SELECT id FROM bets WHERE instruction_id=?', (instruction_id,)).fetchone()
        if existing:
            db.execute(f'UPDATE bets SET {",".join(f"{k}=?" for k in fields)} WHERE instruction_id=?',
                       (*fields.values(), instruction_id))
        else:
            fields['instruction_id'] = instruction_id
            db.execute(f'INSERT INTO bets({",".join(fields)}) VALUES ({",".join("?" * len(fields))})', tuple(fields.values()))

    def bets(self, statuses=None):
        with self.connection() as db:
            if statuses:
                marks = ','.join('?' * len(statuses))
                return [dict(r) for r in db.execute(f'SELECT * FROM bets WHERE status IN ({marks}) ORDER BY id', statuses)]
            return [dict(r) for r in db.execute('SELECT * FROM bets ORDER BY id')]
