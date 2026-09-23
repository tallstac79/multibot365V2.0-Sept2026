"""Read-only dashboard adapter over the authoritative pipeline store (.local/pipeline.sqlite3).

Opened with SQLite mode=ro: the dashboard never creates, migrates or writes it. A missing
database is an empty source; an unreadable one raises so the API reports an error
instead of falling back to sample data. Origins stay separate: 'production' rows only
in REAL DATA, 'sample' rows only in SAMPLE DATA.
"""
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

from core.status_notifier import format_instruction

DB = '.local/pipeline.sqlite3'
STATUS = '.local/pipeline_status.json'


def _open(root):
    path = Path(root) / DB
    if not path.exists():
        return None
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    try:
        present = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='intake_messages'").fetchone()
    except sqlite3.Error:
        db.close()
        raise
    if not present:
        db.close()
        return None
    return db


def _json(value):
    try:
        return json.loads(value) if value else None
    except ValueError:
        return None


def chat_key(chat_id):
    """Telegram marks channel IDs with -100; the web snapshot used the bare ID."""
    value = str(chat_id or '')
    return value[4:] if value.startswith('-100') else value.lstrip('-')


def _evidence(root, paths):
    base = (Path(root) / 'evidence').resolve()
    links = []
    for item in paths or []:
        candidate = (Path(root) / str(item)).resolve()
        if candidate.is_relative_to(base) and candidate.is_file() and candidate.suffix.lower() in ('.png', '.json', '.txt'):
            links.append({'name': candidate.name, 'url': '/api/evidence/' + quote(candidate.relative_to(base).as_posix(), safe='/')})
        else:
            links.append({'name': str(item), 'url': None})
    return links


def _timeline(db, instruction_id):
    return [dict(stage=r['to_state'], timestamp=r['at'], detail=r['reason'], actor=r['actor'],
                 **({'payload': _json(r['detail'])} if r['detail'] else {}))
            for r in db.execute('SELECT * FROM transitions WHERE instruction_id=? ORDER BY id', (instruction_id,))]


def alerts(root, origin, limit=200):
    db = _open(root)
    if db is None:
        return []
    with closing(db):
        rows = []
        for m in db.execute('SELECT * FROM intake_messages WHERE origin=? ORDER BY id DESC LIMIT ?', (origin, limit)):
            parsed = _json(m['normalized']) or {}
            i = db.execute('SELECT * FROM instructions WHERE intake_id=?', (m['id'],)).fetchone()
            rules = _json(i['rules_result']) if i else None
            timeline = [dict(stage='RECEIVED', timestamp=m['received_at'], detail=f"Telegram delivery ({m['delivery']})"),
                        dict(stage=m['status'], timestamp=m['processed_at'], detail=m['reason'])]
            if i:
                timeline = _timeline(db, i['instruction_id'])
            row = dict(
                id=f"pipeline-{m['id']}", instruction_id=i['instruction_id'] if i else None,
                received_at=m['received_at'], source_message_id=m['message_id'], source_chat_id=m['chat_id'],
                source_timestamp=m['source_timestamp'],
                sport=parsed.get('sport'), competition=parsed.get('competition'), fixture=parsed.get('fixture'),
                market=parsed.get('market'), side=parsed.get('target_side') or parsed.get('selection_side'),
                line=next((parsed.get(k) for k in ('target_line', 'selection_line', 'displayed_line')
                           if parsed.get(k) is not None), None),
                alert_price=parsed.get('alert_price'), minimum_price=i['minimum_price'] if i else None,
                displayed_ev=parsed.get('displayed_ev_percent'), status=m['status'],
                lifecycle_state=i['state'] if i else None, failure_reason=i['failure_reason'] if i else None,
                device_id=i['device_id'] if i else None, session_state=i['session_state'] if i else None,
                raw_text=m['formatted_text'], plain_text=m['raw_text'], entities=_json(m['entities']),
                parsed=parsed or None, instruction=(rules or {}).get('instruction'), rules_result=rules,
                warnings=[w for w in list(parsed.get('unresolved') or []) + [m['reason']] if w],
                provenance={'mode': 'REAL DATA' if origin == 'production' else 'SAMPLE DATA',
                            'source': 'pipeline intake (authoritative store)', 'delivery': m['delivery'],
                            'intake_id': m['id'], 'parser': m['parser_profile'], 'parser_version': m['parser_version'],
                            'duplicate_of': m['duplicate_of'], 'stored': _json(m['provenance'])},
                evidence=_evidence(root, _json(i['evidence'])) if i else [],
                notification=format_instruction(i) if i else None, timeline=timeline)
            rows.append(row)
        return rows


def history(root, origin):
    """Device-facing lifecycle records (dispatched or with a device result)."""
    db = _open(root)
    if db is None:
        return []
    with closing(db):
        rows = []
        for i in db.execute("SELECT * FROM instructions WHERE origin=? AND (dispatched_at IS NOT NULL OR result_payload "
                            "IS NOT NULL) ORDER BY COALESCE(completed_at, updated_at) DESC", (origin,)):
            payload = _json(i['result_payload'])
            rows.append(dict(
                instruction_id=i['instruction_id'], time=i['completed_at'] or i['ready_at'] or i['updated_at'],
                recorded_file_time=i['updated_at'], fixture=i['fixture'], sport=i['sport'], market=i['market'],
                side=i['selection'], line=i['line'], alert_price=i['alert_price'], minimum_price=i['minimum_price'],
                observed_price=i['observed_price'], stake=i['stake'], status=i['state'], stage=i['device_stage'],
                duration_ms=i['duration_ms'], device_id=i['device_id'], session_state=i['session_state'],
                failure_reason=i['failure_reason'], payload=payload or {}, dispatch_payload=_json(i['dispatch_payload']),
                rules_result=_json(i['rules_result']), source=DB,
                origin=('REAL DATA · pipeline lifecycle record' if origin == 'production'
                        else 'SAMPLE DATA · pipeline lifecycle record'),
                evidence=[e for e in _evidence(root, _json(i['evidence'])) if e['url']],
                timeline=_timeline(db, i['instruction_id']), notification=format_instruction(i)))
        return rows


def summary(root):
    """Service heartbeat, device/session state, lifecycle counts and outbox (production only)."""
    status_path = Path(root) / STATUS
    try:
        service = json.loads(status_path.read_text(encoding='utf-8')) if status_path.exists() else None
    except (OSError, ValueError):
        service = {'error': 'Unreadable service status file'}
    out = dict(service=service, devices=[], sessions=[], lifecycle={}, intake={}, notifications=[], available=False)
    db = _open(root)
    if db is None:
        return out
    with closing(db):
        out['available'] = True
        out['devices'] = [dict(r, health=_json(r['health'])) for r in db.execute('SELECT * FROM device_state')]
        out['sessions'] = [dict(r) for r in db.execute('SELECT * FROM session_state')]
        out['lifecycle'] = {r[0]: r[1] for r in db.execute(
            "SELECT state, COUNT(*) FROM instructions WHERE origin='production' GROUP BY state")}
        out['intake'] = {r[0]: r[1] for r in db.execute(
            "SELECT status, COUNT(*) FROM intake_messages WHERE origin='production' GROUP BY status")}
        out['notifications'] = [dict(r) for r in db.execute(
            'SELECT instruction_id,state,created_at,sent_at,attempts,last_error FROM notifications ORDER BY id DESC LIMIT 20')]
        active = db.execute("SELECT instruction_id,state,fixture,market,selection,updated_at FROM instructions "
                            "WHERE origin='production' AND terminal=0 ORDER BY updated_at DESC LIMIT 10").fetchall()
        out['active'] = [dict(r) for r in active]
    return out
