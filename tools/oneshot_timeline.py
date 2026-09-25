"""End-to-end timeline of one live instruction: backend timestamps (DB) + the phone's run records.

    python tools/oneshot_timeline.py <instruction_id>

Prints every milestone with its absolute UTC time and the offset from the OddsNotifier message, then the two
headline figures: OddsNotifier -> SLIP_READY and approval -> Place Bet gesture.
"""
import json
import sqlite3
import sys
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding='utf-8')
DB = '.local/pipeline.sqlite3'


def ts(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, timezone.utc)
    return datetime.fromisoformat(str(value).replace('Z', '+00:00'))


def main():
    iid = sys.argv[1]
    db = sqlite3.connect(DB); db.row_factory = sqlite3.Row
    row = db.execute("SELECT * FROM instructions WHERE instruction_id=?", (iid,)).fetchone()
    if row is None:
        sys.exit(f'{iid} not found')
    intake = db.execute("SELECT source_timestamp, received_at, processed_at FROM intake_messages WHERE instruction_id=?", (iid,)).fetchone()
    result = json.loads(row['result_payload'] or '{}')
    marks = []

    def mark(name, when):
        if when is not None:
            marks.append((name, ts(when)))

    mark('OddsNotifier message (Telegram timestamp)', intake['source_timestamp'] if intake else None)
    mark('backend received', row['received_at'])
    mark('backend parsed', row['parsed_at'])
    mark('rules applied', row['rules_applied_at'])
    mark('queued', row['queued_at'])
    mark('dispatched to phone', row['dispatched_at'])
    mark('phone started (device_started_at)', row['device_started_at'])
    # phone-side events of the hold run: wall_ts_ms per phase
    events = (result.get('events') or [])
    phase_ts = {}
    for e in events:
        if 'phase' in e and 'wall_ts_ms' in e:
            phase_ts.setdefault(e['phase'], e['wall_ts_ms'])
    for label, phase in (('event verified (MARKET_NAV starts)', 'MARKET_NAV'), ('market found (READ_SELECTION)', 'READ_SELECTION'),
                         ('selection tapped (OPEN_SELECTION)', 'OPEN_SELECTION'), ('stake entry starts (ENTER_STAKE)', 'ENTER_STAKE'),
                         ('stake complete (VERIFY_FINAL_STATE)', 'VERIFY_FINAL_STATE'), ('slip verified on phone (PREPARE_COMPLETE_EXECUTION)', 'PREPARE_COMPLETE_EXECUTION')):
        mark(label, phase_ts.get(phase))
    mark('SLIP_READY at backend (ready_at)', row['ready_at'])
    mark('APPROVAL NEEDED sent (approval_requested_at)', row['approval_requested_at'])
    mark('approval received (approved_at)', row['approved_at'])
    place = db.execute("SELECT * FROM instructions WHERE instruction_id=?", (iid,)).fetchone()
    # the -place run: timestamps live in the placement result payload
    for key, label in (('t_start_ms', 'pre-tap run started on phone'), ('t_pretap_done_ms', 'pre-tap verified'),
                       ('t_tap_ms', 'Place Bet gesture'), ('t_receipt_ms', 'receipt classified'), ('t_home_ms', 'HOME verified')):
        mark(label, result.get(key))
    mark('completed at backend (completed_at)', row['completed_at'])
    for t in db.execute("SELECT to_state, at, actor, reason FROM transitions WHERE instruction_id=? ORDER BY at", (iid,)):
        pass
    base = marks[0][1]
    print(f"instruction {iid}  state={row['state']}  {row['fixture']}  {row['market']} {row['selection']} {row['line']} @ {row['observed_price']}  stake {row['stake']}")
    print(f"placement: {row['placement']}  bet_reference: {row['bet_reference']}")
    for name, when in marks:
        print(f"  {when.isoformat(timespec='milliseconds'):32s} +{(when - base).total_seconds():7.2f}s  {name}")
    by = dict(marks)

    def span(a, b, label):
        if a in by and b in by:
            print(f"{label}: {(by[b] - by[a]).total_seconds():.2f} s")

    print()
    span('OddsNotifier message (Telegram timestamp)', 'SLIP_READY at backend (ready_at)', 'OddsNotifier -> SLIP_READY')
    span('backend received', 'SLIP_READY at backend (ready_at)', 'backend received -> SLIP_READY')
    span('approval received (approved_at)', 'Place Bet gesture', 'approval -> Place Bet gesture')
    span('Place Bet gesture', 'receipt classified', 'gesture -> receipt')
    span('receipt classified', 'HOME verified', 'receipt -> HOME')
    print('\ntransitions:')
    for t in db.execute("SELECT to_state, at, actor, reason FROM transitions WHERE instruction_id=? ORDER BY at", (iid,)):
        print(f"  {t['at']}  {t['to_state']:20s} {t['actor'] or ''}  {t['reason'] or ''}")


main()
