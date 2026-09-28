"""Supervised desktop-worker run: send ONE hold (or discovery) to the desktop Chrome worker and judge its result with the
backend's own code. Never sends PLACE_HELD. Never touches the production database (reads a private copy).

    python -m tools.desktop_supervised --instruction on-xxxxxxxx [--mode hold|discover]
        payload built by Pipeline.build_payload from a copy of the production row (exactly what the phone was sent),
        under a fresh 'sup-' ID so it can never be confused with the phone's own job for that instruction
    python -m tools.desktop_supervised --manual payload.json [--mode ...]
        a hand-written ADAPTER_WORKFLOW payload (for an upcoming event no alert has pointed at)

The result, the alert-to-live comparison (core.execution_terms.comparisons_for_result) and the phone-schema fields the
automatic policy reads are printed and saved under evidence/desktop-worker/supervised/.
"""
import argparse
import json
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.coordinator_client import Client   # noqa: E402

OUT = ROOT / 'evidence' / 'desktop-worker' / 'supervised'
POLICY_FIELDS = ('status', 'stage', 'detail', 'route', 'event_url', 'identity_verdict', 'held', 'event_context', 'selection',
                 'ready_state', 'final_state', 'complete_execution_ready', 'wager_submitted', 'run_id', 'duration_ms')


def desktop_client():
    cfg = json.loads((ROOT / '.local' / 'desktop_worker.json').read_text(encoding='utf-8-sig'))
    return Client(dict(url=f"http://127.0.0.1:{cfg['port']}", token=cfg['token']))


def payload_from_instruction(instruction_id):
    """Pipeline.build_payload on private copies of the production databases (the originals are only read)."""
    from tools.pipeline_service import load_settings
    from core.pipeline import Pipeline, Settings
    from core.pipeline_store import Store
    from core.decision_support import Store as ConfigStore
    settings = load_settings(ROOT / '.local' / 'pipeline.json')
    tmp = Path(tempfile.mkdtemp(prefix='desktop-sup-'))
    copies = {}
    for key in ('database', 'rules_database'):
        src = sqlite3.connect(f"file:{settings[key]}?mode=ro", uri=True)
        dst = sqlite3.connect(tmp / Path(settings[key]).name)
        src.backup(dst); src.close(); dst.close()
        copies[key] = tmp / Path(settings[key]).name
    store = Store(copies['database'])
    rules = ConfigStore(copies['rules_database'])
    pipeline = Pipeline(store, lambda: rules.get()['config'], Settings.from_dict(settings['pipeline']))
    with store.connection() as db:
        row = db.execute('SELECT * FROM instructions WHERE instruction_id LIKE ?', (instruction_id + '%',)).fetchone()
    if row is None:
        raise SystemExit(f'no instruction {instruction_id}')
    return dict(row), pipeline.build_payload(row)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument('--instruction')
    src.add_argument('--manual')
    ap.add_argument('--mode', choices=('hold', 'discover'), default='hold')
    ap.add_argument('--timeout', type=int, default=180)
    args = ap.parse_args()
    row = None
    if args.instruction:
        row, payload = payload_from_instruction(args.instruction)
    else:
        payload = json.loads(Path(args.manual).read_text(encoding='utf-8'))
    source_id = payload.get('instruction_id', 'manual')
    payload.update(instruction_id=f"sup-{time.strftime('%m%d%H%M%S')}-{source_id[:20]}", execution_mode=args.mode)
    payload.pop('confirmation_status', None)
    c = desktop_client()
    print('health', {k: v for k, v in c.health().items() if k in ('state', 'app_version', 'worker_id', 'account_fingerprint', 'session', 'final_action_armed')})
    print('send', json.dumps(payload, ensure_ascii=False))
    print('ack', c.submit(payload))
    result = c.result(payload['instruction_id'], seconds=args.timeout)
    out = dict(payload=payload, result=result, source_instruction=source_id)
    if row is not None and result.get('selection'):
        from core.execution_terms import comparisons_for_result
        policy = (json.loads(row['rules_result'] or '{}').get('instruction') or {})
        request = dict(market=row['market'], side=row['selection'], line=row['line'], price=row['alert_price'])
        out['comparisons'] = comparisons_for_result(request, result, policy, sport=row['sport'])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{payload['instruction_id']}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding='utf-8')
    for k in POLICY_FIELDS:
        if k in result:
            print(f'  {k}: {json.dumps(result[k], ensure_ascii=False)[:300]}')
    for cmp in out.get('comparisons', []):
        print(f"  comparison[{cmp.get('stage')}]: acceptable={cmp.get('acceptable')} {cmp.get('reason')} "
              f"line_dev={cmp.get('line_deterioration')} min={cmp.get('minimum_live_price')}")
    print('saved', OUT / f"{payload['instruction_id']}.json")


if __name__ == '__main__':
    main()
