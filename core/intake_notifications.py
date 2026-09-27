"""Reporting-only outbox projection for alerts that never became instructions."""
import json

BASELINE_KEY = 'notifier_intake_baseline_id_v1'
MISSED_STATE = 'INTAKE_MISSED'


def format_miss(row):
    try:
        event = json.loads(row['normalized'] or '{}')
    except (TypeError, ValueError):
        event = {}
    if not isinstance(event, dict):
        event = {}
    fixture = event.get('fixture') or ' vs '.join(str(event.get(k) or '?') for k in ('home', 'away'))
    reason = ' '.join(str(row['reason'] or row['status']).split())[:500]
    return (f'MultiBot365 - MISSED — {reason}\n\nEvent: {fixture}\n'
            f"Intake: {row['status']} (no instruction created)\n"
            f"Source: {row['chat_id']}/{row['message_id']} | Intake #{row['id']}")


def initialize_baseline(db, now):
    """Run before the listener starts, so catch-up and the first tick have no reporting gap."""
    mark = db.execute('SELECT value FROM controls WHERE key=?', (BASELINE_KEY,)).fetchone()
    if mark is not None:
        return int(json.loads(mark[0]))
    baseline = db.execute('SELECT COALESCE(MAX(id),0) FROM intake_messages').fetchone()[0]
    db.execute('INSERT INTO controls VALUES (?,?,?,?)',
               (BASELINE_KEY, json.dumps(baseline), now, 'notifier-baseline'))
    return baseline


def enqueue_misses(store, db, now, *, intake_ids=None):
    """Use the existing durable outbox; never mutate intake or execution state.

    First activation establishes a persistent high-water baseline to avoid flooding the
    operator with history. Explicit IDs allow an audited, narrowly scoped incident repair.
    Outbox instruction_id is a namespaced reporting key, not an execution instruction.
    """
    baseline = initialize_baseline(db, now)
    query = ("SELECT * FROM intake_messages WHERE origin='production' AND instruction_id IS NULL "
             "AND duplicate_of IS NULL AND edit_key='' AND status IN ('PARSED_PARTIAL','AMBIGUOUS','INVALID')")
    if intake_ids is None:
        query += ' AND id > ?'
        args = (baseline,)
    else:
        args = tuple(sorted(set(int(x) for x in intake_ids)))
        if not args:
            return 0
        query += ' AND id IN (' + ','.join('?' for _ in args) + ')'
    query += (" AND NOT EXISTS (SELECT 1 FROM notifications n WHERE "
              "n.instruction_id='intake-' || intake_messages.id AND n.state=?) ORDER BY id")
    created = []
    for row in db.execute(query, (*args, MISSED_STATE)).fetchall():
        count = db.execute('INSERT OR IGNORE INTO notifications(instruction_id,state,text,created_at,next_attempt_at) '
                           'VALUES (?,?,?,?,?)',
                           (f"intake-{row['id']}", MISSED_STATE, format_miss(row), now, now)).rowcount
        if count:
            created.append(row['id'])
    if created:
        store.audit(db, 'INTAKE_MISSES_ENQUEUED',
                    dict(intake_ids=created, explicit_backfill=intake_ids is not None), at=now)
    return len(created)
