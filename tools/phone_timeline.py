"""Read-only: print one phone job's checkpoint timeline (every capture/gesture/delay boundary) with deltas.

    python -m tools.phone_timeline <instruction_id>            # from the phone's own evidence (GET only)

Uses the coordinator client's GET /instructions/ID/evidence. Nothing is sent to the phone but that read.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.coordinator_client import Client   # noqa: E402


def timeline(evidence):
    """[(elapsed_ms, label)] from every place a phone record carries stage checkpoints, in time order."""
    rec = evidence.get('record') if isinstance(evidence.get('record'), dict) else evidence
    out = []
    prog = rec.get('progress') or {}
    for s in prog.get('stages') or []:
        out.append((s.get('elapsed_ms', 0), s.get('stage')))
    for t in rec.get('stage_timings') or []:
        out.append((t.get('start_elapsed_ms', 0), '> ' + str(t.get('stage'))))
        out.append((t.get('end_elapsed_ms', 0), '< ' + str(t.get('stage'))))
    for e in rec.get('events') or []:
        if e.get('phase'):
            out.append((e.get('elapsed_ms', 0), f"[{e.get('phase')}]"))
        else:
            out.append((e.get('elapsed_ms', 0), f"[{e.get('effect')}] {e.get('target') or e.get('artifact') or ''}"))
    return sorted(set(out), key=lambda x: x[0])


def main():
    iid = sys.argv[1]
    cfg = json.loads((ROOT / '.local' / 'coordinator.json').read_text(encoding='utf-8-sig'))
    code, ev = Client(cfg).request('GET', f'/instructions/{iid}/evidence')
    if code != 200:
        raise SystemExit(f'evidence HTTP {code}: {ev}')
    last = 0
    for at, label in timeline(ev):
        print(f'{at:>7} ms  (+{at - last:>5})  {label}')
        last = at


if __name__ == '__main__':
    main()
