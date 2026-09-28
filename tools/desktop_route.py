"""Explicit, supervised manual targeting of the desktop worker (tests only; normal routing stays OFF).

Talks to desktop-chrome through core.device_routing.DesktopGateway (the coordinator contract) and never touches the
pipeline's routing or the phone. Prints results without the token.

    py -3.11 -m tools.desktop_route health                      desktop /health + the routable verdict + flag values
    py -3.11 -m tools.desktop_route send FILE.json [--out DIR]  submit one instruction, wait for its terminal result
    py -3.11 -m tools.desktop_route approve HOLD_ID [--out DIR] build the approved PLACE_HELD from the hold's result with
                                                                the backend's own Pipeline.place_held_payload, submit it
                                                                (the worker dry-runs it: no physical click) and wait
    py -3.11 -m tools.desktop_route target [--minutes 60 --lead 10]SUPERVISED backend target: the running pipeline sends the
                                                                NEXT eligible new instruction (pre-match football, received
                                                                after arming) to the desktop worker instead of the phone -
                                                                one instruction, expires; normal routing stays OFF
    py -3.11 -m tools.desktop_route untarget                    cancel an unconsumed target
    py -3.11 -m tools.desktop_route record INSTRUCTION_ID       the backend decision record + bet row + device identity
"""
import argparse
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.device_routing import DesktopGateway, routable  # noqa: E402
from core.pipeline import Pipeline, Settings  # noqa: E402


def flags():
    try:
        section = json.loads((ROOT / '.local' / 'pipeline.json').read_text(encoding='utf-8-sig')).get('pipeline') or {}
    except (OSError, ValueError):
        section = {}
    s = Settings.from_dict(section)
    return s, dict(desktop_routing_enabled=s.desktop_routing_enabled, desktop_device_id=s.desktop_device_id,
                   desktop_expected_worker_id=s.desktop_expected_worker_id or None,
                   desktop_expected_account_fingerprint=s.desktop_expected_account_fingerprint or None)


def slim_health(h):
    keys = ('healthy', 'ready', 'blocked_reason', 'state', 'current_instruction', 'device_id', 'worker_id', 'account_fingerprint',
            'phone_final_action_armed', 'final_action_armed', 'probe_interval_s', 'desktop_final_action', 'operator_alert', 'chrome', 'session', 'pid', 'uptime_ms')
    return {k: h.get(k) for k in keys}


def wait(gw, iid, seconds=400):
    end = time.monotonic() + seconds
    last = None
    while time.monotonic() < end:
        r = gw.result(iid)
        if r is not None and not r.get('_pending'):
            return r
        stage = ((r or {}).get('progress') or {}).get('stage')
        if stage != last:
            print(f'  {time.strftime("%H:%M:%S")} {iid}: {stage}', flush=True)
            last = stage
        time.sleep(1.5)
    raise TimeoutError(iid)


def save(out, name, value):
    if out:
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        (out / name).write_text(json.dumps(value, indent=1, ensure_ascii=False, default=str), encoding='utf-8')


def approved_place_held(hold_body, hold_result, instruction_id=None):
    """The backend's own approval payload (Pipeline.place_held_payload) from the desktop hold, confirmation APPROVED."""
    sel = hold_result.get('selection') or {}
    row = dict(result_payload=json.dumps(hold_result), market=hold_body['market'], selection=hold_body['side'],
               observed_price=sel.get('price'), selection_name=sel.get('selection_name'), line=hold_body.get('line') or '',
               minimum_price=hold_body['minimum_price'], stake=hold_body['stake'], sport=hold_body['sport'],
               instruction_id=hold_body['instruction_id'])
    payload = Pipeline.place_held_payload(SimpleNamespace(settings=SimpleNamespace(adapter='live_bet365')), row)
    if instruction_id:
        payload['instruction_id'] = instruction_id
    return payload


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('command', choices=['health', 'send', 'approve', 'target', 'untarget', 'record'])
    ap.add_argument('--minutes', type=int, default=60)
    ap.add_argument('--lead', type=int, default=10, help='target: minimum minutes before kick-off (pre-match only)')
    ap.add_argument('arg', nargs='?')
    ap.add_argument('--out')
    ap.add_argument('--hold-file', help='the hold instruction JSON (for approve; default OUT/hold_instruction.json)')
    a = ap.parse_args()
    gw = DesktopGateway(config_path=ROOT / '.local' / 'desktop_worker.json')
    s, f = flags()
    h = gw.health()
    ok, why = routable(h, s.desktop_device_id, h.get('worker_id'), h.get('account_fingerprint'))   # manual path: bound to what it reports
    normal_ok, normal_why = routable(h, s.desktop_device_id, s.desktop_expected_worker_id, s.desktop_expected_account_fingerprint)
    verdict = dict(manual_target_routable=ok, manual_reason=why,
                   normal_routing=bool(s.desktop_routing_enabled and normal_ok),
                   normal_reason='desktop routing disabled (flag OFF)' if not s.desktop_routing_enabled else normal_why)
    if a.command in ('target', 'untarget', 'record'):
        from tools.pipeline_service import load_settings, build
        store, pipeline = build(load_settings(ROOT / '.local' / 'pipeline.json'))
        if a.command == 'target':
            if not ok:
                print(json.dumps(dict(refused='desktop worker not routable', verdict=verdict, health=slim_health(h)), indent=1, default=str))
                sys.exit(2)
            print(json.dumps(dict(armed=pipeline.arm_desktop_target('operator:desktop_route', minutes=a.minutes,
                                                                          min_lead_minutes=a.lead),
                                  identity=store.device_identity(s.desktop_device_id), flags=f), indent=1, default=str))
        elif a.command == 'untarget':
            print(json.dumps(dict(target=pipeline.cancel_desktop_target('operator:desktop_route')), indent=1, default=str))
        else:
            with store.connection() as db:
                bet = db.execute('SELECT * FROM bets WHERE instruction_id=?', (a.arg,)).fetchone()
                row = store.get_instruction(db, a.arg)
            out = dict(instruction=dict(instruction_id=a.arg, state=row['state'], device_id=row['device_id'], fixture=row['fixture'],
                                        market=row['market'], selection=row['selection'], stake=row['stake']) if row else None,
                       bet=dict(bet) if bet else None, device=store.device_identity(row['device_id']) if row else None,
                       decision=pipeline.final.decision_record(a.arg) if row else None)
            save(a.out, f'backend_record_{a.arg}.json', out)
            print(json.dumps(out, indent=1, default=str, ensure_ascii=False)[:6000])
        return
    if a.command == 'health':
        out = dict(flags=f, verdict=verdict, health=slim_health(h))
        save(a.out, f'health_{time.strftime("%H%M%S")}.json', out)
        print(json.dumps(out, indent=1, default=str))
        return
    if a.command == 'send':
        body = json.loads(Path(a.arg).read_text(encoding='utf-8'))
        if body.get('action') not in ('SESSION_CHECK', 'MY_BETS', 'RESET_BETSLIP') and not ok:
            print(json.dumps(dict(refused='desktop worker not routable', verdict=verdict, health=slim_health(h)), indent=1, default=str))
            sys.exit(2)
        print(f"manual target desktop-chrome: {body['action']} {body['instruction_id']} (normal routing: {verdict['normal_reason']})")
        save(a.out, f"{body['instruction_id']}_instruction.json", body)
        ack = gw.submit(body)
        save(a.out, f"{body['instruction_id']}_ack.json", ack)
        r = wait(gw, body['instruction_id'])
        save(a.out, f"{body['instruction_id']}_result.json", r)
        keys = ('status', 'stage', 'detail', 'run_id', 'held', 'terms_hash', 'placement', 'match', 'wager_submitted', 'next_step')
        print(json.dumps({k: r.get(k) for k in keys if k in r}, indent=1, ensure_ascii=False, default=str))
        return
    if a.command == 'approve':
        hold_id = a.arg
        hold_file = Path(a.hold_file) if a.hold_file else Path(a.out or '.') / f'{hold_id}_instruction.json'
        hold_body = json.loads(hold_file.read_text(encoding='utf-8'))
        hold_result = gw.result(hold_id)
        if not hold_result or hold_result.get('_pending') or hold_result.get('status') != 'PASS' or not hold_result.get('held'):
            print(json.dumps(dict(refused='hold is not a verified PASS hold', result_stage=(hold_result or {}).get('stage')), indent=1))
            sys.exit(2)
        payload = approved_place_held(hold_body, hold_result)
        print(f"approval: confirmation_status={payload['confirmation_status']} -> PLACE_HELD {payload['instruction_id']} "
              f"(held {payload['held_instruction_id']}, stake {payload['stake']}, price {payload['price']})")
        save(a.out, f"{payload['instruction_id']}_instruction.json", payload)
        ack = gw.submit(payload)
        save(a.out, f"{payload['instruction_id']}_ack.json", ack)
        r = wait(gw, payload['instruction_id'], seconds=150)
        save(a.out, f"{payload['instruction_id']}_result.json", r)
        keys = ('status', 'stage', 'detail', 'run_id', 'placement', 'wager_submitted', 'next_step', 'terms_hash')
        print(json.dumps({k: r.get(k) for k in keys if k in r}, indent=1, ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()
