"""Hold-only smoke test of the phone's hot path on a REAL upcoming event, with per-stage timings.

    python -m tools.speed_smoke football-spread|football-total|football-1x2|basketball-total|basketball-spread [--repeat N]

Sends ONE `hold` ADAPTER_WORKFLOW (verify everything, leave the bet on the slip with the stake typed, Place Bet located,
NEVER tapped) and then the same RESET_BETSLIP the backend uses to release an unused hold. It cannot place a bet: it has no
PLACE_HELD and no approval path, and it refuses to run unless

  * the backend's kill switch is ON (paused), and
  * no instruction is in flight, queued for the phone or holding its slip.

The payload's line tolerance is deliberately wide so the phone reads whatever main line is on the page: this is a timing and
navigation probe of a synthetic job, not a betting decision (the production rules never see it).
"""
import argparse
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.coordinator_client import Client   # noqa: E402

FOOTBALL = dict(sport='football', event_url='https://www.bet365.com/#/AC/B1/C1/D8/E201885656/F3/', query='Estonia||France',
                kickoff_utc='2026-09-29T17:00', competition='U21 Euro Championship Qualifiers', country='UEFA')
BASKETBALL = dict(sport='basketball', event_url='https://www.bet365.com/#/AC/B18/C21168228/D19/E26844754/F19/I0/',
                  query='Kangoeroes Mechelen||CS Rapid Bucuresti', kickoff_utc='2026-09-29T18:00', competition='Club Friendlies Women',
                  country='World', competition_women='true')
KIDSGROVE = dict(sport='football', event_url='https://www.bet365.com/#/AC/B1/C1/D8/E201885715/F3/I1/', query='Kidsgrove Athletic||Lichfield City',
                 kickoff_utc='2026-09-29T18:45', competition='Northern League Division 1', country='England')
MARKHIYA = dict(sport='football', event_url='https://www.bet365.com/#/AC/B1/C1/D8/E201917178/F3/I1/', query='Al Markhiya||Al Ahli Doha',
                kickoff_utc='2026-09-29T17:15', competition='Stars Cup', country='Qatar', aliases='{"al ahli doha": "Al-Ahli Doha"}')
CASES = {
    'am-total': dict(MARKHIYA, market='TOTALS', side='OVER', line='3.5', band='0.25'),
    'am-spread': dict(MARKHIYA, market='SPREAD', side='HOME', line='2.0', band='0.25'),
    'am-spread-band': dict(MARKHIYA, market='SPREAD', side='HOME', line='2.1', band='0.25'),
    # alternative-line fallback: a line far from the main row with the production allowance (band), so the normal path finds nothing
    'alt-total': dict(KIDSGROVE, market='TOTALS', side='OVER', line='3.0', band='0.25'),
    'alt-total-under': dict(KIDSGROVE, market='TOTALS', side='UNDER', line='5.5', band='0.25'),
    'alt-spread': dict(KIDSGROVE, market='SPREAD', side='HOME', line='-3.25', band='0.25'),
    'football-spread': dict(FOOTBALL, market='SPREAD', side='HOME', line='0.0'),
    'football-total': dict(FOOTBALL, market='TOTALS', side='OVER', line='2.5'),
    'football-1x2': dict(FOOTBALL, market='MONEYLINE', side='HOME', line=None),
    'basketball-total': dict(BASKETBALL, market='TOTALS', side='OVER', line='160.5'),
    'basketball-spread': dict(BASKETBALL, market='SPREAD', side='HOME', line='-6.5'),
}
BUSY = ('QUEUED', 'APPROVED', 'DISPATCHED', 'DEVICE_ACTIVE', 'READY', 'PLACEMENT_UNKNOWN')


def guard():
    """Refuse unless the kill switch is on and nothing can reach the phone."""
    out = subprocess.run([sys.executable, '-m', 'tools.pipeline_service', 'status'], capture_output=True, cwd=ROOT).stdout.decode()
    status = json.loads(out)
    if not status.get('paused'):
        raise SystemExit('REFUSED: the backend is not paused (kill switch off). Pause it first: python -m tools.pipeline_service pause')
    db = sqlite3.connect(f"file:{ROOT / '.local' / 'pipeline.sqlite3'}?mode=ro", uri=True)
    marks = ','.join('?' * len(BUSY))
    busy = db.execute(f'SELECT COUNT(*) FROM instructions WHERE state IN ({marks})', BUSY).fetchone()[0]
    if busy:
        raise SystemExit(f'REFUSED: {busy} instruction(s) queued/in flight/held; not touching the phone')


POLL_ERRORS = []


def wait(client, iid, seconds, gap=0.15):
    """Poll the job's result every `gap` s (fast on purpose: also a stress test of the phone's progress snapshot). A non-2xx
    reply is COUNTED and polling continues - the backend does the same (RESULT_POLL_FAILED, retried next tick)."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            code, value = client.request('GET', '/instructions/' + iid)
            if code == 200:
                return value
            if code != 202:
                POLL_ERRORS.append((iid, code, str(value)[:120]))
        except Exception as error:
            POLL_ERRORS.append((iid, 'EXC', f'{type(error).__name__}: {error}'[:120]))
        time.sleep(gap)
    raise TimeoutError(f'no result for {iid} within {seconds}s')


def run(case, client):
    spec = dict(CASES[case])
    band = spec.pop('band', '50')
    stamp = time.strftime('%H%M%S')
    iid = f'speed-{case}-{stamp}'.replace('_', '-')
    payload = dict(instruction_id=iid, action='ADAPTER_WORKFLOW', adapter='live_bet365', scenario='live', minimum_price='1.01', stake='0.10',
                   timeout_ms=120000, execution_mode='hold', period='FULL_GAME', max_line_deterioration=band, **{k: v for k, v in spec.items() if v is not None})
    t0 = time.monotonic()
    client.submit(payload)
    res = wait(client, iid, 150)
    elapsed = time.monotonic() - t0
    timings = {t['stage']: t.get('duration_ms') for t in res.get('stage_timings') or [] if t.get('stage')}
    print(f"\n== {case}  {res.get('status')} {res.get('stage')} {str(res.get('detail'))[:110]}  wall {elapsed:.1f}s  phone {res.get('duration_ms')} ms")
    print('   ', {k: v for k, v in timings.items() if v is not None})
    sel = res.get('selection') or {}
    print('    selection', sel.get('market'), sel.get('side'), sel.get('line'), sel.get('price'), '| identity', res.get('identity_verdict'),
          '| event_load_ms', res.get('event_load_ms'), '| football_band_revisit', res.get('football_band_revisit'))
    if res.get('football_alt_lines') or res.get('football_alt_result'):
        print('    alt:', res.get('football_alt_result'), '| reads', [(x.get('view'), x.get('cells')) for x in (res.get('football_market_reads') or []) if str(x.get('view', '')).startswith('alt')])
    # release the held slip exactly as the backend does (never taps Place Bet)
    rid = 'rs-' + iid
    client.submit(dict(instruction_id=rid, action='RESET_BETSLIP', adapter='live_bet365', scenario='live', timeout_ms=60000))
    reset = wait(client, rid, 90)
    print('    reset:', reset.get('status'), reset.get('stage'), '| phone', reset.get('duration_ms'), 'ms')
    return dict(case=case, id=iid, result=res, reset=reset, wall_s=elapsed)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('case', choices=sorted(CASES))
    ap.add_argument('--repeat', type=int, default=1)
    ap.add_argument('--out')
    args = ap.parse_args()
    guard()
    client = Client(json.loads((ROOT / '.local' / 'coordinator.json').read_text(encoding='utf-8-sig')))
    runs = [run(args.case, client) for _ in range(args.repeat)]
    print(f'\npoll replies that were not 200/202: {len(POLL_ERRORS)}', POLL_ERRORS[:5])
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(runs, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
