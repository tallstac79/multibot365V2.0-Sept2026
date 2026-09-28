"""Durable instruction ledger (SQLite): the desktop worker's at-most-once guarantee, as on the phone.

An instruction ID is committed before it is acknowledged and before any browser effect; IDs are never evicted, so a
repeated ID can only ever return the original result (DUPLICATE). A worker restart never resumes uncertain work: an
instruction still PENDING becomes INTERNAL_ERROR and keeps whatever progress it had recorded.

Final action (28 Sep 2026, desktop routing work):
  holds          the verified slip terms of a HOLD (COMPLETE_EXECUTION_READY) plus their sha256, for PLACE_HELD;
  final_intents  the durable per-instruction 'intent before click' guard, replacing the one-per-day marker file. The
                 intent row is committed BEFORE a live click is dispatched; an intent without a confirmed receipt is
                 never clicked again (the outcome is PLACEMENT_UNKNOWN and the next step is MY_BETS), across restarts.
                 The supervised run's marker (.local/final-action/*.clicked, BT7071586031I) is imported, never removed.
"""
import hashlib
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime
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
CREATE TABLE IF NOT EXISTS holds (
    instruction_id TEXT PRIMARY KEY,  -- the HOLD instruction (the backend instruction ID)
    run_id TEXT,
    terms TEXT NOT NULL,              -- verified slip terms (JSON)
    terms_hash TEXT NOT NULL,
    held_at_ms INTEGER NOT NULL,
    consumed_by TEXT,
    consumed_at_ms INTEGER
);
CREATE TABLE IF NOT EXISTS final_intents (
    instruction_id TEXT PRIMARY KEY,  -- the PLACE_HELD instruction (or the imported supervised run)
    held_instruction_id TEXT,
    terms_hash TEXT,
    live INTEGER NOT NULL,            -- 1: a physical click may follow; 0: dry run (no click ever)
    stake TEXT,
    price TEXT,
    intent_at_ms INTEGER NOT NULL,
    outcome TEXT,                     -- NULL (click in flight) | PLACED | PLACEMENT_UNKNOWN | NOT_PLACED | DRY_RUN
    reference TEXT,
    receipt_at_ms INTEGER,
    detail TEXT,
    source TEXT
);
CREATE INDEX IF NOT EXISTS final_intents_held ON final_intents(held_instruction_id);
"""

CONFIRMED = ('PLACED',)


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
        """PENDING at start-up = interrupted: terminal INTERNAL_ERROR, never replayed. Returns the IDs closed.
        A PLACE_HELD whose live intent was recorded (a click may have been dispatched) and has no confirmed receipt is
        PLACEMENT_UNKNOWN (next step MY_BETS), never NOT_TAPPED; without a live intent no click can have happened."""
        closed = []
        with self.lock, self._db() as db:
            db.execute("UPDATE final_intents SET outcome='PLACEMENT_UNKNOWN', detail=COALESCE(detail, '') || "
                       "'worker restarted with the click in flight; reconcile on MY_BETS' WHERE live=1 AND outcome IS NULL")
            for row in db.execute("SELECT * FROM instructions WHERE state='PENDING'").fetchall():
                result = dict(instruction_id=row['instruction_id'], status='FAIL', stage='INTERNAL_ERROR',
                              detail='Desktop worker restarted during this instruction; uncertain work is never replayed',
                              progress=json.loads(row['progress'] or 'null'), run_id=row['run_id'], wager_submitted=False)
                if row['action'] == 'PLACE_HELD':
                    intent = db.execute('SELECT * FROM final_intents WHERE instruction_id=?', (row['instruction_id'],)).fetchone()
                    if intent is not None and intent['live'] and intent['outcome'] not in CONFIRMED:
                        result.update(stage='PLACEMENT_UNKNOWN', wager_submitted=None, next_step='MY_BETS')
                        result['placement'] = dict(tapped=None, outcome='PLACEMENT_UNKNOWN', next_step='MY_BETS',
                                                   detail='intent was recorded before the click and no receipt was confirmed; '
                                                          'never clicked again - reconcile on My Bets')
                    else:
                        result['placement'] = dict(tapped=False, outcome='NOT_TAPPED',
                                                   detail='no live click intent was recorded, so no click was dispatched')
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

    # ------------------------------------------------------------------ holds (verified slip terms for PLACE_HELD)
    def record_hold(self, instruction_id, run_id, terms):
        text = json.dumps(terms, sort_keys=True, default=str)
        digest = hashlib.sha256(text.encode()).hexdigest()
        with self.lock, self._db() as db:
            db.execute('INSERT OR REPLACE INTO holds(instruction_id, run_id, terms, terms_hash, held_at_ms) VALUES (?,?,?,?,?)',
                       (instruction_id, run_id, text, digest, now_ms()))
        return digest

    def hold(self, instruction_id):
        with self._db() as db:
            row = db.execute('SELECT * FROM holds WHERE instruction_id=?', (instruction_id,)).fetchone()
        if row is None:
            return None
        out = dict(row)
        out['terms'] = json.loads(out['terms'])
        return out

    def consume_hold(self, instruction_id, by):
        with self.lock, self._db() as db:
            db.execute('UPDATE holds SET consumed_by=?, consumed_at_ms=? WHERE instruction_id=? AND consumed_by IS NULL',
                       (by, now_ms(), instruction_id))

    # ------------------------------------------------------------------ final-click intents (durable guard)
    def intent_for(self, instruction_id=None, held_instruction_id=None):
        """Any intent already recorded for this PLACE_HELD ID or for the same held instruction."""
        with self._db() as db:
            row = db.execute('SELECT * FROM final_intents WHERE instruction_id=? OR (held_instruction_id IS NOT NULL AND held_instruction_id=?) '
                             'ORDER BY intent_at_ms LIMIT 1', (instruction_id, held_instruction_id)).fetchone()
        return dict(row) if row else None

    def record_intent(self, instruction_id, held_instruction_id, terms_hash, live, stake, price, source='server'):
        """Commit the intent BEFORE any click. False if an intent already exists for either ID (never clicked twice)."""
        with self.lock, self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                seen = db.execute('SELECT 1 FROM final_intents WHERE instruction_id=? OR (held_instruction_id IS NOT NULL AND held_instruction_id=?)',
                                  (instruction_id, held_instruction_id)).fetchone()
                if seen:
                    db.execute('ROLLBACK')
                    return False
                db.execute('INSERT INTO final_intents(instruction_id, held_instruction_id, terms_hash, live, stake, price, intent_at_ms, source) '
                           'VALUES (?,?,?,?,?,?,?,?)', (instruction_id, held_instruction_id, terms_hash, 1 if live else 0, stake, price, now_ms(), source))
                db.execute('COMMIT')
            except Exception:
                db.execute('ROLLBACK')
                raise
        return True

    def settle_intent(self, instruction_id, outcome, reference=None, detail=None):
        with self.lock, self._db() as db:
            db.execute('UPDATE final_intents SET outcome=?, reference=COALESCE(?, reference), receipt_at_ms=?, detail=? WHERE instruction_id=?',
                       (outcome, reference, now_ms() if outcome in CONFIRMED else None, detail, instruction_id))

    def live_stake_on(self, day_start_ms):
        """Sum of stakes of live intents recorded since day_start_ms (every live intent counts: it may have been placed)."""
        with self._db() as db:
            rows = db.execute('SELECT stake FROM final_intents WHERE live=1 AND intent_at_ms>=?', (day_start_ms,)).fetchall()
        total = 0.0
        for r in rows:
            try:
                total += float(r['stake'])
            except (TypeError, ValueError):
                pass
        return round(total, 2)

    def import_markers(self, markers_dir, evidence_dir=None):
        """One-time, idempotent migration of the supervised run's marker files into final_intents (markers are kept).
        The outcome/reference come from that run's evidence (final_action.json with the same key), else UNKNOWN."""
        markers_dir = Path(markers_dir)
        imported = []
        if not markers_dir.exists():
            return imported
        for marker in sorted(markers_dir.glob('*.clicked')):
            try:
                m = json.loads(marker.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                m = {}
            iid = m.get('instruction_id') or marker.stem
            outcome, ref = 'PLACEMENT_UNKNOWN', None
            if evidence_dir and Path(evidence_dir).exists():
                for f in Path(evidence_dir).glob('*/final_action.json'):
                    try:
                        rec = json.loads(f.read_text(encoding='utf-8'))
                    except (OSError, ValueError):
                        continue
                    if rec.get('key') == marker.stem and rec.get('clicks') == 1:
                        outcome = 'PLACED' if rec.get('outcome') == 'PLACED' and rec.get('reference') else 'PLACEMENT_UNKNOWN'
                        ref = rec.get('reference')
                        break
            try:
                at = int(datetime.fromisoformat(m['at']).timestamp() * 1000)
            except (KeyError, ValueError, TypeError):
                at = int(marker.stat().st_mtime * 1000)
            with self.lock, self._db() as db:
                if db.execute('SELECT 1 FROM final_intents WHERE instruction_id=?', (iid,)).fetchone():
                    continue
                db.execute('INSERT INTO final_intents(instruction_id, held_instruction_id, terms_hash, live, stake, price, intent_at_ms, outcome, '
                           'reference, receipt_at_ms, detail, source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                           (iid, iid, None, 1, m.get('stake'), m.get('price'), at, outcome, ref, at if outcome == 'PLACED' else None,
                            f'imported from marker {marker.name} (kept)', 'marker'))
            imported.append(dict(instruction_id=iid, outcome=outcome, reference=ref, marker=marker.name))
        return imported

    def intents(self):
        with self._db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM final_intents ORDER BY intent_at_ms').fetchall()]
