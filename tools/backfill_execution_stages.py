"""One-off, idempotent backfill of execution_stages for instructions dispatched before per-stage recording existed
(28 Sep 2026). Analysis only: reads the audit trail and stored rows, writes execution_stages rows with source
'backfill: <evidence>', never overwrites a stage (INSERT OR IGNORE) and never touches instructions/bets.

    python -m tools.backfill_execution_stages [database]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.pipeline_store import Store   # noqa: E402

SEARCH_STAGES = ('OPEN_SEARCH', 'ENTER_QUERY', 'SEARCH_RESULTS')


def _json(text):
    try:
        return json.loads(text) if text else {}
    except (TypeError, ValueError):
        return {}


def _quote(o):
    o = o if isinstance(o, dict) else {}
    return dict(market=o.get('market'), side=o.get('side') or o.get('selection_role'), line=o.get('line'), price=o.get('price'),
                selection_name=o.get('selection_name') or o.get('selection'))


def backfill(store):
    written = 0
    with store.tx() as db:
        rows = db.execute("SELECT * FROM instructions WHERE dispatched_at IS NOT NULL ORDER BY dispatched_at").fetchall()
        for row in rows:
            iid = row['instruction_id']
            audits = [(a['kind'], a['at'], _json(a['detail'])) for a in
                      db.execute('SELECT kind, at, detail FROM audit_events WHERE instruction_id=? ORDER BY id', (iid,))]
            payload, result = _json(row['dispatch_payload']), _json(row['result_payload'])
            hold_result_kept = payload.get('action') != 'PLACE_HELD'
            # route: the hold result if it is still the stored one, else the phone's own progress stages for the hold job
            route, route_source = (result.get('route'), 'backfill: stored hold result') if hold_result_kept and result.get('route') else (None, None)
            if route is None:
                stages = [s.get('stage') for k, _, d in audits if k == 'DEVICE_PROGRESS' and (d.get('progress') or {}).get('instruction_id') == iid
                          for s in (d.get('progress') or {}).get('stages') or []]
                if 'OPEN_EVENT' in stages:
                    route, route_source = 'event_link', 'backfill: hold progress stages (OPEN_EVENT)'
                elif any(s in SEARCH_STAGES for s in stages):
                    route, route_source = 'search', 'backfill: hold progress stages (search)'
            if payload:
                stage = 'place_request' if payload.get('action') == 'PLACE_HELD' else 'hold_request'
                written += store.record_stage(db, iid, stage, source='backfill: instructions.dispatch_payload', at=row['dispatched_at'],
                                              device_instruction_id=payload.get('instruction_id'),
                                              route=None if stage == 'place_request' else ('event_link' if payload.get('event_url') else 'search'),
                                              market=payload.get('market'), side=payload.get('side'), line=payload.get('line'),
                                              price=payload.get('price') if stage == 'place_request' else None,
                                              requested_price=row['alert_price'], minimum_price=payload.get('minimum_price'),
                                              stake=payload.get('stake'), selection_name=payload.get('selection_name'), detail=payload)
            comparisons = [(at, d) for k, at, d in audits if k == 'ALERT_TO_LIVE_COMPARISON' and isinstance(d.get('live'), dict)]
            first = next(((at, d) for at, d in comparisons if d.get('stage') != 'pretap'), None)
            if first:
                written += store.record_stage(db, iid, 'first_quote', source='backfill: first ALERT_TO_LIVE_COMPARISON' +
                                              (f'; route {route_source}' if route_source else ''), at=first[0], route=route,
                                              **_quote(first[1]['live']), detail=dict(observation_stage=first[1].get('stage'),
                                                                                      device_outcome=first[1].get('device_outcome')))
            elif route:
                written += store.record_stage(db, iid, 'hold_result', source=route_source, at=row['dispatched_at'], route=route,
                                              outcome='route only (hold result not retained)')
            if hold_result_kept and result:
                written += store.record_stage(db, iid, 'hold_result', source='backfill: stored hold result', at=row['updated_at'], route=route,
                                              outcome=f"{row['state']} ({result.get('status')}/{result.get('stage')})", **_quote(result.get('selection')),
                                              detail=dict(event_url=result.get('event_url'), identity_verdict=result.get('identity_verdict'),
                                                          detail=result.get('detail')))
            pre = next(((at, d['live']) for at, d in comparisons if d.get('stage') == 'pretap'), None) or \
                next(((at, d.get('pretap')) for k, at, d in audits if k in ('PLACED', 'PRE_TAP_REJECTED') and isinstance(d.get('pretap'), dict)), None)
            if pre:
                written += store.record_stage(db, iid, 'pretap', source='backfill: pretap comparison/audit', at=pre[0], **_quote(pre[1]),
                                              stake=pre[1].get('stake'))
            placed = next(((at, d) for k, at, d in audits if k == 'PLACED'), None)
            bet = db.execute('SELECT * FROM bets WHERE instruction_id=?', (iid,)).fetchone()
            if placed:
                receipt = placed[1].get('receipt') or {}
                written += store.record_stage(db, iid, 'receipt', source='backfill: PLACED audit', at=placed[0],
                                              line=receipt.get('line') or (bet['actual_line'] if bet else None),
                                              price=receipt.get('odds'), stake=receipt.get('stake'), bet_reference=placed[1].get('bet_reference'),
                                              outcome='PLACED', detail=dict(receipt=receipt, potential_return=receipt.get('potential_return')))
            elif bet is not None:
                written += store.record_stage(db, iid, 'receipt', source='backfill: bets row', at=bet['placed_at'], line=bet['actual_line'],
                                              price=bet['actual_odds'], stake=bet['actual_stake'] or bet['stake'],
                                              bet_reference=bet['bet_reference'], outcome=f"bet status {bet['status']}")
    return written


if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / '.local' / 'pipeline.sqlite3')
    print('stages written:', backfill(Store(path)))
