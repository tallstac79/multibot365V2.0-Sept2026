"""Idempotent repair of the audited first receipt; never sends a phone instruction."""
import hashlib
import json
import sqlite3
from pathlib import Path
from core.pipeline_store import Store
from tools.strategy_phone_audit import safety, ROOT

IID='on-ca8c7974821c387ff822222b'
RECEIPT='evidence/live-first-placement/s030_place_bet_after.png'
SHA256='44da3e1399ff21af3b8c58aa7dbd3c55b7eeef431998af0dae4cd54ec05489f3'


def main():
    safety()
    raw=(ROOT/RECEIPT).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==SHA256, 'Receipt evidence changed'
    out=ROOT/'evidence/execution-hardening';out.mkdir(exist_ok=True)
    (out/'historical-return-receipt.png').write_bytes(raw)
    backup=ROOT/'.local/before-return-repair.sqlite3'
    if not backup.exists():
        with sqlite3.connect(ROOT/'.local/pipeline.sqlite3') as source, sqlite3.connect(backup) as dest: source.backup(dest)
    store=Store(ROOT/'.local/pipeline.sqlite3')
    with store.tx() as db:
        row=db.execute('SELECT * FROM bets WHERE instruction_id=?',(IID,)).fetchone()
        assert row and row['bet_reference']=='HT5515901931W' and row['status']=='OPEN'
        previous=db.execute("SELECT detail FROM audit_events WHERE kind='RECEIPT_RETURN_REPAIR' AND instruction_id=?",(IID,)).fetchone()
        if previous:
            assert row['potential_return']=='0.18'
            print('Already repaired; no second mutation');return
        assert row['potential_return']=='0.10'
        provenance=dict(receipt_path=RECEIPT,sha256=SHA256,method='visually inspected original receipt',
                        actual=dict(line='+3.5',odds='1.83',stake='0.10',potential_return='0.18'),
                        reason='Old OCR confused stake with To Return; settlement and returns remain unknown')
        detail=dict(instruction_id=IID,before=dict(row),after=dict(potential_return='0.18',actual_line='+3.5',actual_odds='1.83',actual_stake='0.10'),provenance=provenance)
        store.upsert_bet(db,IID,potential_return='0.18',requested_line=row['line'],requested_odds=row['odds'],requested_stake=row['stake'],
                         actual_line='+3.5',actual_odds='1.83',actual_stake='0.10',terms_provenance=json.dumps(provenance))
        store.audit(db,'RECEIPT_RETURN_REPAIR',detail,IID)
    (out/'historical-return-repair.json').write_text(json.dumps(detail,indent=2),encoding='utf-8')
    print('Audited repair: potential return 0.10 -> 0.18; OPEN status unchanged')


if __name__=='__main__':main()
