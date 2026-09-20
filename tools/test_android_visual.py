"""Physical-device acceptance test. Host serves neutral HTML; Android performs all OCR/taps.

python tools/test_android_visual.py --adb PATH --serial R5CT61TE14Z
Evidence contains screenshots captured by AccessibilityService, OCR bounds, prefs and logcat.
"""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import threading
import time
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--adb', default='adb')
    parser.add_argument('--serial', required=True)
    parser.add_argument('--output', default=str(ROOT / 'evidence' / 'visual-acceptance'))
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    prefix = ['%s' % args.adb, '-s', args.serial]

    def adb(*cmd, binary=False):
        data = subprocess.check_output(prefix + list(cmd), timeout=20)
        return data if binary else data.decode('utf-8', errors='replace').replace('\r\n', '\n')

    def prefs():
        # SharedPreferences replaces its XML during commit; a concurrent host read may see an empty file.
        for attempt in range(10):
            try:
                data = adb('shell', 'run-as', 'com.bet365agent', 'cat', 'shared_prefs/visual_agent.xml')
                return {e.get('name'): e.text or e.get('value') for e in ET.fromstring(data)}, data
            except (ET.ParseError, subprocess.CalledProcessError):
                if attempt == 9: raise
                time.sleep(.1)

    def trigger(run_id, capture=False, display=0):
        return adb('shell', 'am', 'broadcast', '-n', 'com.bet365agent/.VisualTestReceiver',
                   '--es', 'run_id', run_id, '--ez', 'capture_only', str(capture).lower(),
                   '--ei', 'display_id', str(display))

    def wait_result(run_id):
        limit = time.monotonic() + 38
        while time.monotonic() < limit:
            state, raw = prefs()
            if state.get('run_id') == run_id and state.get('status') != 'RUNNING':
                return state, raw
            time.sleep(.5)
        raise AssertionError(f'No terminal result for {run_id}')

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT / 'tools/neutral-visual')))
    port = server.server_port
    threading.Thread(target=server.serve_forever, daemon=True).start()
    adb('reverse', f'tcp:{port}', f'tcp:{port}')
    results = []

    def page(mode='normal'):
        url = f'http://127.0.0.1:{port}/?mode={mode}%26run={uuid.uuid4().hex}'
        # adb shell parses '&'; quoting as a single shell argument preserves the query separator.
        url = url.replace('%26', '&')
        adb('shell', 'am', 'start', '-a', 'android.intent.action.VIEW', '-d', "'" + url + "'", '-p', 'com.android.chrome')
        time.sleep(2)

    def collect(name, run_id, expected):
        state, raw = wait_result(run_id)
        folder = output / run_id
        folder.mkdir(exist_ok=True)
        (folder / 'prefs.xml').write_text(raw, encoding='utf-8')
        for filename in ['before.png', 'before.txt', 'after.png', 'after.txt']:
            exists = adb('shell', 'run-as', 'com.bet365agent', 'ls', 'files/visual')
            if run_id not in exists.split(): break
            exists = adb('shell', 'run-as', 'com.bet365agent', 'ls', 'files/visual/' + run_id)
            if filename in exists.split():
                (folder / filename).write_bytes(adb('exec-out', 'run-as', 'com.bet365agent', 'cat',
                                                     f'files/visual/{run_id}/{filename}', binary=True))
        record = dict(state, test=name, expected=expected)
        record.pop('consumed_ids', None)
        results.append(record)
        print(json.dumps(record), flush=True)
        assert state.get('status') == expected, record
        return state

    try:
        adb('shell', 'input', 'keyevent', 'KEYCODE_WAKEUP')
        adb('shell', 'wm', 'dismiss-keyguard')
        run_id = 'invalid-display-' + uuid.uuid4().hex[:12]
        trigger(run_id, capture=True, display=999)
        state = collect('invalid-display', run_id, 'FAIL')
        assert state['capture_error_code'] == '4', state
        for mode, expected in [('normal', 'PASS'), ('normal', 'PASS'), ('duplicate', 'FAIL'),
                               ('missing', 'FAIL'), ('unchanged', 'FAIL')]:
            page(mode)
            run_id = mode + '-' + uuid.uuid4().hex[:12]
            trigger(run_id)
            state = collect(mode, run_id, expected)
            if mode == 'duplicate':
                assert 'found 2' in state['detail'], state
            if mode == 'missing':
                assert 'found 0' in state['detail'], state
            if mode == 'unchanged':
                assert 'not verified' in state['detail'], state
            if mode == 'normal':
                trigger(run_id)
                time.sleep(1)
                current, _ = prefs()
                assert current['status'] == 'PASS' and current['run_id'] == run_id
                logs = adb('logcat', '-d', '-s', 'AgentVisual:I', '*:S')
                assert 'DUPLICATE_OR_BUSY rejected id=' + run_id in logs

        # Kill only our app process while a run is active, then observe OS service rebind.
        page('normal')
        run_id = 'restart-' + uuid.uuid4().hex[:12]
        trigger(run_id)
        state, _ = prefs()
        assert state.get('status') == 'RUNNING', state
        old_pid = adb('shell', 'pidof', 'com.bet365agent').strip()
        assert old_pid.isdigit(), old_pid
        adb('shell', 'run-as', 'com.bet365agent', 'kill', '-9', old_pid)
        limit = time.monotonic() + 35
        while time.monotonic() < limit:
            state, _ = prefs()
            if state.get('status') == 'INTERRUPTED': break
            time.sleep(1)
        state = collect('process-restart', run_id, 'INTERRUPTED')
        new_pid = adb('shell', 'pidof', 'com.bet365agent').strip()
        assert new_pid != old_pid
        trigger(run_id)
        time.sleep(1)
        assert prefs()[0]['status'] == 'INTERRUPTED'
        page('normal')
        run_id = 'after-restart-' + uuid.uuid4().hex[:12]
        trigger(run_id)
        collect('after-restart', run_id, 'PASS')
    finally:
        (output / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
        (output / 'logcat.txt').write_text(adb('logcat', '-d', '-s', 'AgentVisual:I', '*:S'), encoding='utf-8')
        (output / 'accessibility.txt').write_text(adb('shell', 'dumpsys', 'accessibility'), encoding='utf-8')
        adb('reverse', '--remove', f'tcp:{port}')
        server.shutdown()
    print('ACCEPTANCE PASS', flush=True)


if __name__ == '__main__':
    main()
