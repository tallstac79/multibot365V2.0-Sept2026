"""ENTER_STAKE profile from a phone run record's events (gesture / capture timestamps).

    python tools/stake_profile.py evidence/<dir>/<hold-run>.json ...

Prints, per run, the latency of every step between OPEN_SELECTION and PREPARE_COMPLETE_EXECUTION split into
waits (fixed sleeps / gesture settles), captures (screenshot + evidence + OCR), gestures and parsing, plus the
ENTER_STAKE and VERIFY_FINAL_STATE stage totals, and the mean over the runs.
"""
import json
import sys
from collections import OrderedDict, defaultdict
from statistics import mean

sys.stdout.reconfigure(encoding='utf-8')


def profile(events):
    """Ordered (step, ms) pairs for the stake path of one run."""
    t = {}
    keys = []
    gestures = []
    for e in events:
        if 'phase' in e:
            k = e['phase']
            if k in ('GESTURE_DISPATCHING',):
                continue
            t.setdefault(k, e['elapsed_ms'])
            t[k + '$last'] = e['elapsed_ms']
        elif e.get('effect') == 'gesture':
            gestures.append((e['target'], e['elapsed_ms']))
            if e['target'].startswith('key:'): keys.append(e['elapsed_ms'])
    g = {name: ms for name, ms in gestures}
    steps = OrderedDict()

    def cap(label):
        starts = [e['elapsed_ms'] for e in events if e.get('phase') == 'CAPTURE_' + label]
        ends = [e['elapsed_ms'] for e in events if e.get('phase') == 'CAPTURED_' + label]
        return sum(b - a for a, b in zip(starts, ends)), len(starts)

    def put(name, ms, kind):
        steps[name] = (ms, kind)

    if 'ENTER_STAKE' not in t or 'VERIFY_FINAL_STATE' not in t:
        return None
    sel = g.get(next((n for n in g if n.startswith(('SPREAD', 'TOTAL', 'MONEYLINE'))), ''), None)
    if sel is not None: put('selection tap -> ENTER_STAKE (tap settle)', t['ENTER_STAKE'] - sel, 'wait')
    put('ENTER_STAKE -> first capture', t['CAPTURE_betslip_pre_stake'] - t['ENTER_STAKE'], 'wait')
    ms, n = cap('betslip_pre_stake'); put(f'capture betslip_pre_stake x{n}', ms, 'capture')
    put('parse slip -> Set Stake tap', g['Set Stake'] - t['CAPTURED_betslip_pre_stake$last'], 'parse')
    put('Set Stake tap -> capture (settle/wait)', t['CAPTURE_stake_ui'] - g['Set Stake'], 'wait')
    ms, n = cap('stake_ui'); put(f'capture stake_ui x{n}', ms, 'capture')
    put('keypad parse -> first key', keys[0] - t['CAPTURED_stake_ui$last'], 'parse')
    put(f'typing {len(keys)} keys (gesture + settle)', keys[-1] - keys[0] + (keys[1] - keys[0] if len(keys) > 1 else 0), 'gesture')
    put('last key -> capture stake_typed (wait)', t['CAPTURE_stake_typed'] - keys[-1] - (keys[1] - keys[0] if len(keys) > 1 else 0), 'wait')
    ms, n = cap('stake_typed'); put(f'capture stake_typed x{n}', ms, 'capture')
    put('readback parse -> Done tap', g['Done'] - t['CAPTURED_stake_typed$last'], 'parse')
    put('Done tap -> VERIFY_FINAL_STATE (settle/wait)', t['VERIFY_FINAL_STATE'] - g['Done'], 'wait')
    put('VERIFY_FINAL_STATE -> capture final (wait)', t['CAPTURE_final'] - t['VERIFY_FINAL_STATE'], 'wait')
    ms, n = cap('final'); put(f'capture final x{n}', ms, 'capture')
    for extra in ('final_reread', 'final_enhanced'):
        ms, n = cap(extra)
        if n: put(f'capture {extra} x{n}', ms, 'capture')
    end = t.get('PREPARE_COMPLETE_EXECUTION', t.get('FINISHED'))
    put('final checks -> stage end', end - t['CAPTURED_final$last'] - sum(cap(x)[0] for x in ('final_reread', 'final_enhanced')), 'parse')
    totals = {'ENTER_STAKE': t['VERIFY_FINAL_STATE'] - t['ENTER_STAKE'], 'VERIFY_FINAL_STATE': end - t['VERIFY_FINAL_STATE']}
    return steps, totals


def main():
    allsteps, alltotals = defaultdict(list), defaultdict(list)
    for path in sys.argv[1:]:
        d = json.load(open(path, encoding='utf-8'))
        run = d.get('run') or d
        r = profile(run.get('events') or [])
        if not r:
            continue
        steps, totals = r
        print(f"\n{path}")
        for name, (ms, kind) in steps.items():
            print(f"  {kind:8s} {ms:6d} ms  {name}")
            allsteps[(name, kind)].append(ms)
        for k, v in totals.items():
            print(f"  TOTAL    {v:6d} ms  {k}")
            alltotals[k].append(v)
    if allsteps:
        print(f"\nMEAN over {len(next(iter(alltotals.values())))} runs")
        by_kind = defaultdict(float)
        for (name, kind), v in allsteps.items():
            print(f"  {kind:8s} {mean(v):6.0f} ms  {name}")
            by_kind[kind] += mean(v)
        for k, v in alltotals.items():
            print(f"  TOTAL    {mean(v):6.0f} ms  {k}  (min {min(v)}, max {max(v)})")
        print('  by kind:', {k: round(v) for k, v in by_kind.items()})


main()
