"""Tree-free physical text acceptance. Host only serves HTML, sends instructions and collects evidence."""
import argparse
import base64
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--adb', default='adb')
    parser.add_argument('--serial', required=True)
    parser.add_argument('--output', default=str(ROOT / 'evidence/text-entry'))
    parser.add_argument('--cases', default=str(ROOT / 'tools/text_acceptance_cases.json'))
    parser.add_argument('--case', help='Run one configured case; otherwise include process-restart tests')
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    prefix = [args.adb, '-s', args.serial]

    def adb(*cmd, binary=False, check=True):
        result = subprocess.run(prefix + list(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, check=check)
        return result.stdout if binary else result.stdout.decode('utf-8', errors='replace').replace('\r\n', '\n')

    def state(run_id):
        raw = adb('exec-out', 'run-as', 'com.bet365agent', 'cat', f'files/text/{run_id}/result.json', check=False)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def wait_result(run_id, timeout=65):
        limit = time.monotonic() + timeout
        while time.monotonic() < limit:
            result = state(run_id)
            if result and result['status'] != 'RUNNING': return result
            time.sleep(.25)
        raise AssertionError(f'No terminal result: {run_id}')

    def trigger(instruction):
        encoded = base64.b64encode(json.dumps(instruction, ensure_ascii=False).encode()).decode()
        result = adb('shell', 'am', 'broadcast', '-n', 'com.bet365agent/.VisualTestReceiver',
                     '--es', 'text_instruction', encoded)
        assert 'result=0' in result, result

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args): pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT / 'tools/neutral-visual')))
    port = server.server_port
    threading.Thread(target=server.serve_forever, daemon=True).start()
    adb('reverse', f'tcp:{port}', f'tcp:{port}')
    keyboard = adb('shell', 'settings', 'get', 'secure', 'default_input_method').strip()
    results = []

    def page(mode):
        url = f'http://127.0.0.1:{port}/text.html?mode={mode}&run={uuid.uuid4().hex}'
        adb('shell', 'am', 'start', '-a', 'android.intent.action.VIEW', '-d', "'" + url + "'", '-p', 'com.android.chrome')
        time.sleep(1.5)

    def collect(case, instruction):
        result = wait_result(instruction['run_id'])
        run_id = instruction['run_id']
        folder = output / run_id
        folder.mkdir(exist_ok=True)
        (folder / 'instruction.json').write_text(json.dumps(instruction, indent=2), encoding='utf-8')
        (folder / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        for filename in ['before.png', 'before.txt', 'focused.png', 'focused.txt', 'after.png', 'after.txt', 'field_after.png']:
            files = adb('shell', 'run-as', 'com.bet365agent', 'ls', f'files/visual/{run_id}', check=False).split()
            if filename in files:
                (folder / filename).write_bytes(adb('exec-out', 'run-as', 'com.bet365agent', 'cat', f'files/visual/{run_id}/{filename}', binary=True))
        result = dict(result, test=case['name'], expected=case['expected'])
        results.append(result)
        print(json.dumps({k: result.get(k) for k in ['test', 'run_id', 'status', 'detail', 'requested_text', 'observed_text', 'visible_field_text', 'duration_ms']}), flush=True)
        assert result['status'] == case['expected'], result
        if result['status'] == 'PASS':
            assert result['requested_text'] == result['observed_text'] == instruction['text']
            assert result['exact_input_match'] and result['visual_text_match']
            assert result['pre_screenshot'] and result['post_screenshot'] and result['field_bounds']
            assert result['input_attempts'] == 1
        return result

    try:
        adb('shell', 'input', 'keyevent', 'KEYCODE_WAKEUP')
        adb('shell', 'wm', 'dismiss-keyguard')
        cases = json.loads(Path(args.cases).read_text(encoding='utf-8'))
        for case in cases:
            if args.case and case['name'] != args.case: continue
            page(case['mode'])
            instruction = dict(run_id=case['name'] + '-' + uuid.uuid4().hex[:12], text=case['text'],
                               field_hint=case.get('field_hint', 'SEARCH'), package='com.android.chrome',
                               timeout_ms=case.get('timeout_ms', 30000))
            trigger(instruction)
            result = collect(case, instruction)
            trigger(instruction)
            time.sleep(.35)
            assert state(instruction['run_id']) == {k: v for k, v in result.items() if k not in ['test', 'expected']}

        if not args.case:
            # Interrupt after text has been sent but before verification; never replay uncertain insertion.
            page('normal')
            instruction = dict(run_id='restart-' + uuid.uuid4().hex[:12], text='restart value',
                               field_hint='SEARCH', package='com.android.chrome', timeout_ms=30000)
            trigger(instruction)
            limit = time.monotonic() + 10
            while time.monotonic() < limit:
                current = state(instruction['run_id'])
                if current and current['phase'] in ['INPUT_SENT', 'VERIFYING']: break
                time.sleep(.1)
            assert current and current['status'] == 'RUNNING', current
            pid = adb('shell', 'pidof', 'com.bet365agent').strip()
            assert pid.isdigit()
            adb('shell', 'run-as', 'com.bet365agent', 'kill', '-9', pid)
            collect(dict(name='process-restart', expected='INTERRUPTED'), instruction)
            assert state(instruction['run_id'])['input_attempts'] == 1
            assert adb('shell', 'pidof', 'com.bet365agent').strip() != pid
            trigger(instruction)
            time.sleep(.5)
            assert state(instruction['run_id'])['status'] == 'INTERRUPTED'
            page('normal')
            instruction = dict(instruction, run_id='after-restart-' + uuid.uuid4().hex[:12], text='Recovered 42')
            trigger(instruction)
            collect(dict(name='after-restart', expected='PASS'), instruction)
        assert adb('shell', 'settings', 'get', 'secure', 'default_input_method').strip() == keyboard
    finally:
        (output / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
        (output / 'keyboard.txt').write_text(keyboard + '\n', encoding='utf-8')
        (output / 'logcat.txt').write_text(adb('logcat', '-d', '-s', 'AgentText:I', 'AgentVisual:I', '*:S'), encoding='utf-8')
        adb('reverse', '--remove', f'tcp:{port}')
        server.shutdown()
    print('TEXT ACCEPTANCE PASS', flush=True)


if __name__ == '__main__': main()
