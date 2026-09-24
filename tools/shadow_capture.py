"""Shadow capture: record the phone screen while the operator places bets BY HAND.

    python -m tools.shadow_capture --minutes 5 --label manual-bet-1

Runs back-to-back OBSERVE instructions on the phone (screenshot + OCR every 2.5 s, no taps,
typing or navigation) and saves every frame's PNG and OCR text under
evidence/shadow-capture/<label>-<timestamp>/. These real receipt, error, odds-change and
My Bets screens calibrate core.bet_matching and the phone's PlacementClassifier.

It only reads the screen; it never interacts with Bet365. Stop early with Ctrl+C.
"""
import argparse
import json
import time
from datetime import datetime
from pathlib import Path

from tools.coordinator_client import Client

ROOT = Path(__file__).resolve().parents[1]
SEGMENT_MS = 180_000  # one OBSERVE instruction = up to 3 minutes of frames


def save_segment(client, instruction_id, folder):
    result = client.result(instruction_id, seconds=SEGMENT_MS / 1000 + 60)
    (folder / f'{instruction_id}-result.json').write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding='utf-8')
    frames = (result.get('observe') or {}).get('frames') or []
    for frame in frames:
        name = frame.get('image')
        if not name:
            continue
        code, data = client.request('GET', f'/instructions/{instruction_id}/artifacts/{name}', raw=True)
        if code == 200:
            (folder / f'{instruction_id}-{name}').write_bytes(data)
        with (folder / 'frames.jsonl').open('a', encoding='utf-8') as out:
            out.write(json.dumps(dict(instruction=instruction_id, **frame), ensure_ascii=False) + '\n')
    return len(frames)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--minutes', type=float, default=5)
    parser.add_argument('--label', default='manual')
    parser.add_argument('--config', default=str(ROOT / '.local/coordinator.json'))
    args = parser.parse_args()
    client = Client(json.loads(Path(args.config).read_text(encoding='utf-8-sig')))
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    folder = ROOT / 'evidence/shadow-capture' / f'{args.label}-{stamp}'
    folder.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + args.minutes * 60
    total, segment = 0, 0
    print(f'Recording to {folder}. Place your bet(s) by hand on the phone now. Ctrl+C to stop early.')
    try:
        while time.monotonic() < deadline:
            segment += 1
            remaining_ms = int(min(SEGMENT_MS, (deadline - time.monotonic()) * 1000 + 8000))
            if remaining_ms < 15000:
                break
            instruction_id = f'shadow-{stamp}-{segment}'
            client.submit(dict(instruction_id=instruction_id, action='OBSERVE', adapter='live_bet365',
                               timeout_ms=remaining_ms))
            count = save_segment(client, instruction_id, folder)
            total += count
            print(f'segment {segment}: {count} frames saved')
    except KeyboardInterrupt:
        print('Stopped early; the current segment finishes on the phone by itself.')
    print(f'{total} frames saved in {folder}')


if __name__ == '__main__':
    main()
