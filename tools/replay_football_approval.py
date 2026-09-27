"""Replay real football instructions through the backend's automatic path offline (scratch DB, fake coordinator returning
the phone's STORED hold result): intake -> rules (live dashboard config) -> hold -> READY -> automatic approval -> PLACE_HELD.
Nothing reaches the phone."""
import json, os, sqlite3, sys, tempfile
from datetime import datetime, timedelta
os.chdir(r'C:\Users\WINDOWS11\Desktop\MultiBotV2.0\MultiBot365'); sys.path.insert(0, os.getcwd()); sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from core.decision_support import Store as ConfigStore
from core.telegram_intake import SourceMessage
from tests.pipeline_support import Clock, FakeGateway, pipeline

cfg = ConfigStore('.local/dashboard.sqlite3').get()['config']
live = sqlite3.connect('file:.local/pipeline.sqlite3?mode=ro', uri=True); live.row_factory = sqlite3.Row
ids = sys.argv[1:] or [r[0] for r in live.execute(
    "SELECT i.instruction_id FROM instructions i WHERE sport='football' AND EXISTS(SELECT 1 FROM transitions t WHERE "
    "t.instruction_id=i.instruction_id AND t.to_state='READY')")]
out = {}
for iid in ids:
    row = live.execute('SELECT * FROM instructions WHERE instruction_id=?', (iid,)).fetchone()
    msg = live.execute('SELECT * FROM intake_messages WHERE id=?', (row['intake_id'],)).fetchone()
    result = json.loads(row['result_payload'])
    received = datetime.fromisoformat(msg['received_at'].replace('Z', '+00:00'))
    with tempfile.TemporaryDirectory() as tmp:
        clock = Clock(received)
        gw = FakeGateway(clock)
        p = pipeline(Path(tmp) / 'r.sqlite3', clock, cfg=cfg, instant_verification=False, final_action_enabled=True, approval_mode='automatic')
        m = SourceMessage(chat_id=msg['chat_id'], message_id=msg['message_id'], text=msg['formatted_text'] or msg['raw_text'],
                          received_at=msg['received_at'], source_timestamp=msg['source_timestamp'], entities=msg['entities'])
        new = p.ingest(m)['instruction_id']
        p.tick(gw)
        gw.results[new] = dict(result, instruction_id=new)
        clock.advance(15)
        for _ in range(3):
            p.tick(gw); clock.advance(1)
        with p.store.connection() as db:
            r2 = db.execute('SELECT state, failure_reason, approved_by FROM instructions WHERE instruction_id=?', (new,)).fetchone()
            checks = [json.loads(a[0]) for a in db.execute("SELECT detail FROM audit_events WHERE instruction_id=? AND kind IN "
                                                           "('AUTO_APPROVED','AUTO_APPROVAL_REFUSED')", (new,))]
        failed = [c for c in (checks[0]['checks'] if checks else []) if not c['ok']]
        sent = [x['action'] for x in gw.submitted]
        out[iid] = dict(state=r2['state'], approved_by=r2['approved_by'], reason=r2['failure_reason'], failed_checks=failed, sent=sent)
        print(iid, row['fixture'], row['market'], row['selection'], '|', r2['state'], r2['approved_by'], '| failed:', failed, '| sent:', sent)
Path('evidence/live-failures/approval-replay.json').write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding='utf-8')
