"""Per-stage latency report for placed bets: alert -> intake -> hold -> approval -> place -> receipt.

Read-only. Joins the backend's own records (instructions, transitions, intake) with each job's phone evidence
(GET /instructions/ID/evidence for the hold job `<id>` and the place job `<id>-place`, cached in .local/latency-cache/).

    python -m tools.latency_report --since 2026-09-27 --until 2026-09-29T16:00 --label before --out evidence/speed/before.json
    python -m tools.latency_report --since 2026-09-29T17:00 --label after

Sample: COMPLETED final-action instructions whose hold used the alert's own event link. Every stage is reported as
p50 / p90 / n (percentiles by linear interpolation). Phone-clock stage durations come from the phone's own stage_timings
and checkpoint events; server-clock intervals from the backend's transitions. Phone stages are anchored on the backend's
DEVICE_ACTIVE (the job ACK) for the "alert -> tap / receipt" estimates, so the same bias applies before and after.
"""
import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CACHE = ROOT / '.local' / 'latency-cache'


def ts(s):
    if not s:
        return None
    return datetime.fromisoformat(str(s).replace('Z', '+00:00')).astimezone(timezone.utc)


def secs(a, b):
    return None if a is None or b is None else (b - a).total_seconds()


def percentile(values, p):
    xs = sorted(v for v in values if v is not None)
    if not xs:
        return None
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def fetch(client, device_id):
    """The phone's evidence record for one job (cached; None when the phone no longer has it)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f'{device_id}.json'
    if f.exists():
        return json.loads(f.read_text(encoding='utf-8'))
    try:
        code, ev = client.request('GET', f'/instructions/{device_id}/evidence')
    except Exception:
        return None
    if code != 200:
        return None
    rec = ev.get('record', ev)
    f.write_text(json.dumps(rec), encoding='utf-8')
    return rec


def stage_ms(rec, name):
    """Duration (ms) of a stage from the phone's stage_timings (first occurrence)."""
    for t in (rec or {}).get('stage_timings') or []:
        if t.get('stage') == name:
            return t.get('duration_ms')
    return None


def stage_end_ms(rec, name):
    for t in (rec or {}).get('stage_timings') or []:
        if t.get('stage') == name:
            return t.get('end_elapsed_ms')
    return None


def stage_start_ms(rec, name):
    for t in (rec or {}).get('stage_timings') or []:
        if t.get('stage') == name:
            return t.get('start_elapsed_ms')
    return None


def count_phase(rec, prefix):
    return sum(1 for e in (rec or {}).get('events') or [] if str(e.get('phase') or '').startswith(prefix))


def count_effect(rec, effect):
    return sum(1 for e in (rec or {}).get('events') or [] if e.get('effect') == effect)


def total_ms(rec):
    ends = [t.get('end_elapsed_ms') for t in (rec or {}).get('stage_timings') or [] if t.get('end_elapsed_ms') is not None]
    return max(ends) if ends else None


def sec(ms):
    return None if ms is None else ms / 1000.0


def measure(db, client, row):
    iid = row['instruction_id']
    trans = [(t['to_state'], ts(t['at'])) for t in db.execute('SELECT to_state, at FROM transitions WHERE instruction_id=? ORDER BY id', (iid,))]
    first = lambda state: next((a for s, a in trans if s == state), None)
    nth = lambda state, n: [a for s, a in trans if s == state][n] if len([1 for s, _ in trans if s == state]) > n else None
    source = None
    if row['intake_id']:
        r = db.execute('SELECT source_timestamp FROM intake_messages WHERE id=?', (row['intake_id'],)).fetchone()
        source = ts(r['source_timestamp']) if r and r['source_timestamp'] else None
    received, queued = ts(row['received_at']), first('QUEUED')
    d1, d2 = nth('DISPATCHED', 0), nth('DISPATCHED', 1)
    a1, a2 = nth('DEVICE_ACTIVE', 0), nth('DEVICE_ACTIVE', 1)
    ready, approved, done = first('READY'), first('APPROVED'), first('COMPLETED')
    hold, place = fetch(client, iid), fetch(client, iid + '-place')
    m = {}
    m['alert_to_intake'] = secs(source, received)
    m['intake_to_hold_dispatch'] = secs(received, d1)
    m['hold_dispatch_to_ack'] = secs(d1, a1)
    # phone hold stages (phone clock)
    m['hold.open_home'] = sec(stage_ms(hold, 'OPEN_HOME'))
    m['hold.market_nav'] = sec(stage_ms(hold, 'MARKET_NAV'))
    m['hold.open_selection'] = sec(stage_ms(hold, 'OPEN_SELECTION'))
    m['hold.enter_stake'] = sec(stage_ms(hold, 'ENTER_STAKE'))
    m['hold.verify_final'] = sec(stage_ms(hold, 'VERIFY_FINAL_STATE'))
    m['hold.prepare'] = sec(stage_ms(hold, 'PREPARE_COMPLETE_EXECUTION'))
    hold_total = sec(stage_end_ms(hold, 'PREPARE_COMPLETE_EXECUTION') or total_ms(hold))
    m['hold.phone_total'] = hold_total
    m['hold.captures'] = count_phase(hold, 'CAPTURED_')
    m['hold.swipes'] = count_effect(hold, 'swipe') + count_effect(hold, 'swipe_horizontal')
    m['hold.result_lag'] = None if hold_total is None else (secs(a1, ready) - hold_total if secs(a1, ready) is not None else None)
    m['ready_to_approved'] = secs(ready, approved)
    m['approved_to_place_dispatch'] = secs(approved, d2)
    m['place_dispatch_to_ack'] = secs(d2, a2)
    # phone place stages
    m['place.pretap'] = sec(stage_start_ms(place, 'PLACE_BET'))
    m['place.tap_stage'] = sec(stage_ms(place, 'PLACE_BET'))
    m['place.outcome_stage'] = sec(stage_ms(place, 'PLACE_BET_OUTCOME'))
    tap, receipt = (place or {}).get('t_tap_ms'), (place or {}).get('t_receipt_ms')
    m['place.tap_to_receipt'] = sec(receipt - tap) if tap and receipt else None
    seen, flushed, frame = (place or {}).get('t_receipt_seen_ms'), (place or {}).get('t_flush_done_ms'), (place or {}).get('t_pretap_frame_ms')
    m['place.tap_to_receipt_seen'] = sec(seen - tap) if tap and seen else None          # 29 Sep speed work: the definitive frame's time
    m['place.pretap_checks'] = sec(tap - frame) if tap and frame else None
    m['place.evidence_flush'] = sec(flushed - tap) if tap and flushed else None
    m['hold.event_load'] = sec((hold or {}).get('event_load_ms'))
    m['place.reset_betslip'] = sec(stage_ms(place, 'RESET_BETSLIP'))
    m['place.return_home'] = sec(stage_ms(place, 'OPEN_HOME'))
    m['place.phone_total'] = sec(total_ms(place))
    m['place.captures'] = count_phase(place, 'CAPTURED_')
    # totals (server clock, phone stages anchored on the job ACK)
    m['total.alert_to_hold_dispatch'] = secs(source, d1)
    m['total.alert_to_ready'] = secs(source, ready)
    tap_at = None if a2 is None or m['place.pretap'] is None else m['place.pretap']
    m['total.alert_to_tap_est'] = None if source is None or a2 is None or tap_at is None else secs(source, a2) + tap_at
    m['total.alert_to_receipt_est'] = None if m['total.alert_to_tap_est'] is None or m['place.tap_to_receipt'] is None \
        else m['total.alert_to_tap_est'] + m['place.tap_to_receipt']
    m['total.alert_to_receipt_seen_est'] = None if m['total.alert_to_tap_est'] is None or m['place.tap_to_receipt_seen'] is None         else m['total.alert_to_tap_est'] + m['place.tap_to_receipt_seen']
    m['total.alert_to_completed'] = secs(source, done)
    m['place.result_lag'] = None if m['place.phone_total'] is None else (secs(a2, done) - m['place.phone_total'] if secs(a2, done) is not None else None)
    # how the hold reached the event page (0.9.49): hot = the persistent tab was already on it, prewarmed = the backend started the
    # load before the job, cold = the job navigated itself (also every pre-0.9.49 bet)
    h = hold or {}
    m['_path'] = 'hot' if h.get('hot_tab') and not h.get('hot_tab_recovered') else 'prewarmed' if h.get('prewarmed_ms_before_job') is not None and not h.get('prewarm_recovered') else 'cold'
    m['_id'] = iid
    m['_market'] = f"{row['sport']}/{row['market']}"
    return m


ORDER = ['alert_to_intake', 'intake_to_hold_dispatch', 'hold_dispatch_to_ack', 'hold.open_home', 'hold.event_load', 'hold.market_nav', 'hold.open_selection',
         'hold.enter_stake', 'hold.verify_final', 'hold.prepare', 'hold.phone_total', 'hold.result_lag', 'ready_to_approved',
         'approved_to_place_dispatch', 'place_dispatch_to_ack', 'place.pretap', 'place.tap_stage', 'place.outcome_stage', 'place.tap_to_receipt', 'place.tap_to_receipt_seen', 'place.pretap_checks', 'place.evidence_flush',
         'place.reset_betslip', 'place.return_home', 'place.phone_total', 'place.result_lag', 'hold.captures', 'hold.swipes', 'place.captures',
         'total.alert_to_hold_dispatch', 'total.alert_to_ready', 'total.alert_to_tap_est', 'total.alert_to_receipt_est', 'total.alert_to_receipt_seen_est', 'total.alert_to_completed']


def summarise(samples):
    out = {}
    for k in ORDER:
        vals = [s[k] for s in samples if s.get(k) is not None]
        out[k] = dict(n=len(vals), p50=percentile(vals, 50), p90=percentile(vals, 90), min=min(vals) if vals else None, max=max(vals) if vals else None)
    return out


def render(label, samples, summary):
    lines = [f'## {label}: {len(samples)} completed event-link bets', '', '| stage | n | p50 | p90 | min | max |', '| --- | ---: | ---: | ---: | ---: | ---: |']
    fmt = lambda v, k: '' if v is None else (f'{v:.0f}' if k.endswith('captures') or k.endswith('swipes') else f'{v:.2f}')
    for k in ORDER:
        s = summary[k]
        lines.append(f"| {k} | {s['n']} | {fmt(s['p50'], k)} | {fmt(s['p90'], k)} | {fmt(s['min'], k)} | {fmt(s['max'], k)} |")
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--since', default='2026-09-27')
    ap.add_argument('--until', default='2999-01-01')
    ap.add_argument('--label', default='report')
    ap.add_argument('--out')
    ap.add_argument('--db', default=str(ROOT / '.local' / 'pipeline.sqlite3'))
    ap.add_argument('--sport')
    args = ap.parse_args()
    from tools.coordinator_client import Client
    client = Client(json.loads((ROOT / '.local' / 'coordinator.json').read_text(encoding='utf-8-sig')))
    db = sqlite3.connect(f'file:{args.db}?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    rows = db.execute("SELECT i.* FROM instructions i JOIN execution_stages s ON s.instruction_id=i.instruction_id AND s.stage='first_quote' "
                      "WHERE i.state='COMPLETED' AND i.execution_mode='dispatch' AND s.route='event_link' AND i.completed_at>=? AND i.completed_at<? "
                      "ORDER BY i.completed_at", (args.since, args.until)).fetchall()
    if args.sport:
        rows = [r for r in rows if r['sport'] == args.sport]
    samples = [measure(db, client, r) for r in rows]
    summary = summarise(samples)
    print(render(args.label, samples, summary))
    by_market = {}
    for s in samples:
        by_market.setdefault(s['_market'], []).append(s)
    for market, group in sorted(by_market.items()):
        if len(group) >= 3:
            print('\n' + render(f'{args.label} / {market}', group, summarise(group)))
    by_path = {}
    for s in samples:
        by_path.setdefault(s['_path'], []).append(s)
    for path, group in sorted(by_path.items()):
        if len(by_path) > 1:
            print()
            print(render(f'{args.label} / path={path}', group, summarise(group)))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(dict(label=args.label, n=len(samples), summary=summary, samples=samples,
                                                  by_market={k: summarise(v) for k, v in by_market.items() if len(v) >= 3}, by_path={k: summarise(v) for k, v in by_path.items()}), indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
