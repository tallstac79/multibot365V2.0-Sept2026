"""Optional parser persistence boundary. Dashboard reads this database in SQLite read-only mode.

The existing Telegram listener is not changed. Future producers call record_alert with
an explicit origin; no record or database is created merely by opening the dashboard.
"""
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from core.oddsnotifier_parser import parse_oddsnotifier, AlertFormatError


def record_alert(path, text, *, channel_id, message_id, source_timestamp,
                 received_at, origin, provenance=None, ordering_profile=None, target_position=None):
    if origin not in ('production', 'sample'):
        raise ValueError('Explicit production or sample origin required')
    import re
    if not isinstance(channel_id,str) or not re.fullmatch(r'-?[1-9][0-9]*',channel_id) or not isinstance(message_id,str) or not re.fullmatch(r'[1-9][0-9]*',message_id):
        raise ValueError('Explicit numeric source chat/message IDs required')
    for value in (received_at,) + ((source_timestamp,) if source_timestamp is not None else ()):
        if datetime.fromisoformat(value.replace('Z', '+00:00')).tzinfo is None:
            raise ValueError('Timezone-aware timestamps required')
    parsed, reason = None, None
    processed_at = datetime.now(timezone.utc).isoformat()
    try:
        parsed = parse_oddsnotifier(text, channel_id=channel_id if source_timestamp else None, message_id=message_id if source_timestamp else None,
                    source_timestamp=source_timestamp,
                    sample_provenance='synthetic' if origin == 'sample' else 'unspecified', ordering_profile=ordering_profile, target_position=target_position)
        status = 'AMBIGUOUS' if parsed and not parsed.get('target_side') else 'PARSED' if parsed else 'IGNORED'
    except AlertFormatError as error:
        status, reason = 'INVALID', str(error)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('''CREATE TABLE IF NOT EXISTS oddsnotifier_records (
            id INTEGER PRIMARY KEY, origin TEXT NOT NULL, channel_id TEXT NOT NULL,
            message_id TEXT NOT NULL, received_at TEXT NOT NULL, payload TEXT NOT NULL)''')
        db.execute('CREATE INDEX IF NOT EXISTS observation_identity ON oddsnotifier_records(origin,channel_id,message_id)')
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM oddsnotifier_records WHERE origin=? AND channel_id=? AND message_id=?',
                      (origin, channel_id, message_id)).fetchone():
            status, reason = 'DUPLICATE', 'Previously recorded channel/message identity'
        warnings = list((parsed or {}).get('unresolved', [])) + ([reason] if reason else [])
        timeline = [{'stage':'RECEIVED','timestamp':received_at,'detail':'Source message recorded'}]
        if status != 'DUPLICATE':
            timeline.append({'stage':'PARSED','timestamp':processed_at,'detail':reason or status})
            if parsed: timeline.append({'stage':'NORMALIZED','timestamp':processed_at,'detail':f"Parser schema v{parsed.get('schema_version')}"})
        payload = dict(origin=origin, raw_text=text, parsed=parsed, status=status,
                       warnings=warnings, received_at=received_at, source_timestamp=source_timestamp,
                       source_message_id=message_id, channel_id=channel_id, timeline=timeline,
                       provenance=provenance or {'producer':'core.observation_store','origin':origin})
        cursor = db.execute('INSERT INTO oddsnotifier_records(origin,channel_id,message_id,received_at,payload) VALUES(?,?,?,?,?)',
                           (origin, channel_id, message_id, received_at, json.dumps(payload)))
        return cursor.lastrowid


def read_records(path, limit=200):
    path = Path(path)
    if not path.exists(): return []
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='oddsnotifier_records'").fetchone():
            return []
        return [dict(json.loads(payload), record_id=key) for key,payload in db.execute(
            "SELECT id,payload FROM oddsnotifier_records WHERE origin='production' ORDER BY id DESC LIMIT ?", (min(limit,200),))]
