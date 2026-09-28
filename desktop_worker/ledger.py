"""Durable instruction ledger (SQLite): the desktop worker's at-most-once guarantee, as on the phone.

An instruction ID is committed before it is acknowledged and before any browser effect; IDs are never evicted, so a
repeated ID can only ever return the original result (DUPLICATE). A worker restart never resumes uncertain work: an
instruction still PENDING becomes INTERNAL_ERROR and keeps whatever progress it had recorded.
"""
import hashlib
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS instructions (
    instruction_id TEXT PRIMARY KEY,
    action TEXT NOT NULL,
    payload TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    received_at_ms INTEGER NOT NULL,
    state TEXT NOT NULL,              -- PENDING | DONE
    result TEXT,
    progress TEXT,
    run_id TEXT,
    completed_at_ms INTEGER
);
"""


def now_ms():
    return int(time.time() * 1000)


class Ledger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        with self._db() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)     # autocommit; closed after every use
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    def reconcile_restart(self):
        """PENDING at start-up = interrupted: terminal INTERNAL_ERROR, never replayed. Returns the IDs closed."""
        closed = []
        with self.lock, self._db() as db:
            for row in db.execute("SELECT * FROM instructions WHERE state='PENDING'").fetchall():
                result = dict(instruction_id=row['instruction_id'], status='FAIL', stage='INTERNAL_ERROR',
                              detail='Desktop worker restarted during this instruction; uncertain work is never replayed',
                              progress=json.loads(row['progress'] or 'null'), run_id=row['run_id'], wager_submitted=False)
                if row['action'] == 'PLACE_HELD':
                    result['placement'] = dict(tapped=False, outcome='NOT_TAPPED', detail='desktop final action is not enabled')
                db.execute("UPDATE instructions SET state='DONE', result=?, completed_at_ms=? WHERE instruction_id=?",
                           (json.dumps(result), now_ms(), row['instruction_id']))
                closed.append(row['instruction_id'])
        return closed

    def admit(self, instruction_id, action, payload):
        """('NEW', row) when committed now; ('DUPLICATE', row) when the ID was seen before (never replaced)."""
        text = json.dumps(payload, sort_keys=True)
        digest = hashlib.sha256(text.encode()).hexdigest()
        with self.lock, self._db() as db:
            row = db.execute('SELECT * FROM instructions WHERE instruction_id=?', (instruction_id,)).fetchone()
            if row is not None:
                return 'DUPLICATE', dict(row)
            db.execute("INSERT INTO instructions(instruction_id, action, payload, payload_hash, received_at_ms, state) VALUES (?,?,?,?,?,'PENDING')",
                       (instruction_id, action, text, digest, now_ms()))
            return 'NEW', dict(db.execute('SELECT * FROM instructions WHERE instruction_id=?', (instruction_id,)).fetchone())

    def progress(self, instruction_id, progress, run_id=None):
        with self.lock, self._db() as db:
            db.execute("UPDATE instructions SET progress=?, run_id=COALESCE(?, run_id) WHERE instruction_id=? AND state='PENDING'",
                       (json.dumps(progress), run_id, instruction_id))

    def complete(self, instruction_id, result):
        with self.lock, self._db() as db:
            db.execute("UPDATE instructions SET state='DONE', result=?, completed_at_ms=? WHERE instruction_id=? AND state='PENDING'",
                       (json.dumps(result), now_ms(), instruction_id))

    def get(self, instruction_id):
        with self._db() as db:
            row = db.execute('SELECT * FROM instructions WHERE instruction_id=?', (instruction_id,)).fetchone()
        return dict(row) if row else None

    def pending(self):
        with self._db() as db:
            row = db.execute("SELECT instruction_id FROM instructions WHERE state='PENDING' ORDER BY received_at_ms LIMIT 1").fetchone()
        return row['instruction_id'] if row else None

    def last_result(self):
        with self._db() as db:
            row = db.execute("SELECT result FROM instructions WHERE state='DONE' ORDER BY completed_at_ms DESC LIMIT 1").fetchone()
        return json.loads(row['result']) if row and row['result'] else None
