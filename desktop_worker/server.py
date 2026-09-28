"""Desktop Chrome worker: the phone coordinator's HTTP contract, served on loopback, executing in the dedicated Chrome.

    python -m desktop_worker.server                      run the worker (127.0.0.1:8768 by default)
    python -m desktop_worker.server --set-account NAME   store ONLY the account fingerprint (sha256(lower(NAME))[:12],
                                                          the phone's WorkerIdentity.fingerprint); the name is not kept

Contract (tools/COORDINATOR.md): GET /health, POST /instructions (202 durable receipt; 409 DUPLICATE for a seen ID; 409
BUSY 'ID not consumed' while another instruction runs), GET /instructions/ID (202 pending + progress, 200 terminal),
GET /instructions/ID/evidence, GET /instructions/ID/artifacts/NAME. Bearer token from .local/desktop_worker.json.

Scope of this build (supervised): SESSION_CHECK, ADAPTER_WORKFLOW (hold / ready, and the supervised-only 'discover').
PLACE_HELD and MY_BETS are admitted and answered with a refusal (placement NOT_TAPPED): final action is not enabled on
the desktop worker, and health reports it unarmed, so the backend's automatic policy can never approve for it.
"""
import argparse
import asyncio
import hashlib
import json
import os
import re
import secrets
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Queue

from desktop_worker.ledger import Ledger, now_ms

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / '.local' / 'desktop_worker.json'
LEDGER = ROOT / '.local' / 'desktop_worker.sqlite3'
VERSION = 'desktop-0.1.0'
ID = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
ACTIONS = {'ADAPTER_WORKFLOW', 'SESSION_CHECK', 'RESET_BETSLIP', 'PLACE_HELD', 'MY_BETS'}
REFUSED = {'PLACE_HELD', 'MY_BETS'}


def load_config():
    if CONFIG.exists():
        cfg = json.loads(CONFIG.read_text(encoding='utf-8-sig'))
    else:
        cfg = {}
    changed = False
    for key, value in (('port', 8768), ('token', None), ('worker_id', None), ('account_fingerprint', None)):
        if key not in cfg:
            cfg[key] = value if value is not None else (secrets.token_urlsafe(24) if key == 'token' else
                                                        'dw-' + secrets.token_hex(6) if key == 'worker_id' else None)
            changed = True
    if changed:
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps(cfg, indent=1), encoding='utf-8')
    return cfg


def fingerprint(username):
    user = (username or '').strip().lower()
    return hashlib.sha256(user.encode()).hexdigest()[:12] if user else None


class Worker:
    def __init__(self, cfg, ledger_path=LEDGER, start_executor=True):
        self.cfg = cfg
        self.ledger = Ledger(ledger_path)
        self.closed_at_start = self.ledger.reconcile_restart()
        self.queue = Queue()
        self.current = None
        self.started = time.monotonic()
        self.session = dict(state='UNKNOWN', observed_at_ms=0, detail='no session check yet')
        self.operator_alert = None            # e.g. Bet365 Reality Check open: the operator must answer it on the mini PC
        self.lock = threading.Lock()
        if start_executor:
            threading.Thread(target=self._executor, daemon=True).start()

    # ------------------------------------------------------------------ admission
    def health(self):
        return dict(healthy=True, heartbeat_ms=now_ms(), uptime_ms=int((time.monotonic() - self.started) * 1000),
                    state='EXECUTING' if self.current else 'IDLE', current_instruction=self.current, app_version=VERSION,
                    version_code=1, kind='desktop_chrome', device_id='desktop-chrome', worker_id=self.cfg['worker_id'],
                    account_fingerprint=self.cfg.get('account_fingerprint'), session=json.dumps(self.session),
                    phone_final_action_armed=False, final_action_armed=False,
                    local_execution=dict(enabled=False, worker_id=self.cfg['worker_id'],
                                         authorised_account_fingerprint=self.cfg.get('account_fingerprint'),
                                         last_reason='final action is not enabled on the desktop worker (supervised build)'),
                    last_result=self.ledger.last_result(), restarted_pending=self.closed_at_start, pid=os.getpid(),
                    operator_alert=self.operator_alert)

    def note_result(self, result):
        """The latest result's operator alert (None clears it: a later run got past the dialog)."""
        self.operator_alert = result.get('operator_alert') if isinstance(result, dict) else None

    def validate(self, body):
        if not isinstance(body, dict):
            return 'body must be a JSON object'
        iid = body.get('instruction_id')
        if not isinstance(iid, str) or not ID.match(iid):
            return 'instruction_id must be 1-64 letters, digits, underscores or hyphens'
        if body.get('action') not in ACTIONS:
            return f"action must be one of {sorted(ACTIONS)}"
        if body['action'] == 'ADAPTER_WORKFLOW':
            if body.get('adapter') != 'live_bet365':
                return 'adapter must be live_bet365'
            if body.get('sport') not in ('football', 'basketball'):
                return 'sport must be football or basketball'
            if body.get('execution_mode') not in ('hold', 'ready', 'discover'):
                return 'execution_mode must be hold, ready or discover'
            for field in ('market', 'side', 'minimum_price', 'stake', 'query'):
                if not body.get(field):
                    return f'{field} is required'
            if not re.match(r'^[0-9]+\.[0-9]{2}$', str(body['minimum_price'])) or not re.match(r'^[0-9]+\.[0-9]{2}$', str(body['stake'])):
                return 'minimum_price and stake must look like 1.85'
        timeout = body.get('timeout_ms', 300000)
        if not isinstance(timeout, int) or not 100 <= timeout <= 600000:
            return 'timeout_ms must be an integer 100-600000'
        return None

    def submit(self, body):
        """(HTTP code, reply)."""
        problem = self.validate(body)
        if problem:
            return 400, dict(status='FAIL', stage='INVALID_INSTRUCTION', detail=problem)
        iid = body['instruction_id']
        existing = self.ledger.get(iid)
        if existing:
            return 409, dict(status='FAIL', stage='DUPLICATE', detail='instruction ID already used; never replaced',
                             instruction_id=iid, result_url=f'/instructions/{iid}')
        with self.lock:
            if self.current or self.ledger.pending():
                return 409, dict(status='FAIL', stage='INTERNAL_ERROR', detail='BUSY: one instruction at a time; ID not consumed',
                                 instruction_id=iid)
            outcome, row = self.ledger.admit(iid, body['action'], body)
            if outcome == 'DUPLICATE':
                return 409, dict(status='FAIL', stage='DUPLICATE', detail='instruction ID already used; never replaced',
                                 instruction_id=iid, result_url=f'/instructions/{iid}')
            self.current = iid
        self.queue.put(body)
        return 202, dict(acknowledged=True, instruction_id=iid, execution_count=0, received_at_ms=row['received_at_ms'],
                         result_url=f'/instructions/{iid}', state='ACCEPTED')

    def result(self, iid):
        row = self.ledger.get(iid)
        if row is None:
            return 404, dict(status='FAIL', stage='UNKNOWN', detail='unknown instruction ID')
        if row['state'] == 'PENDING':
            return 202, dict(status='PENDING', instruction_id=iid, progress=json.loads(row['progress'] or 'null'), run_id=row['run_id'])
        return 200, json.loads(row['result'])

    # ------------------------------------------------------------------ execution (one thread, one browser loop)
    def _executor(self):
        asyncio.run(self._loop())

    async def _loop(self):
        from playwright.async_api import async_playwright
        from desktop_worker.chrome import connect
        from desktop_worker.decisions import Decisions
        decisions = Decisions()
        async with async_playwright() as pw:
            browser = page = None
            while True:
                body = await asyncio.get_running_loop().run_in_executor(None, self.queue.get)
                iid = body['instruction_id']
                try:
                    if browser is None or not browser.is_connected():
                        browser, context, page = await connect(pw)
                    result = await asyncio.wait_for(self._run(body, page, decisions), timeout=body.get('timeout_ms', 300000) / 1000)
                except asyncio.TimeoutError:
                    result = dict(instruction_id=iid, status='FAIL', stage='TIMEOUT', detail='instruction deadline reached', wager_submitted=False)
                except Exception as e:
                    result = dict(instruction_id=iid, status='FAIL', stage='INTERNAL_ERROR', detail=f'{type(e).__name__}: {e}',
                                  trace=traceback.format_exc()[-2000:], wager_submitted=False)
                    browser = None
                if body['action'] == 'PLACE_HELD':
                    result.setdefault('placement', dict(tapped=False, outcome='NOT_TAPPED', detail=result.get('detail')))
                self.ledger.complete(iid, result)
                self.note_result(result)
                with self.lock:
                    self.current = None

    async def _run(self, body, page, decisions):
        from desktop_worker.workflow import DesktopBet365, Failure, Run
        iid, action = body['instruction_id'], body['action']
        if action in REFUSED:
            return dict(instruction_id=iid, status='FAIL', stage='INVALID_INSTRUCTION', wager_submitted=False,
                        detail=f'{action} is not enabled on the desktop worker (supervised hold only)',
                        placement=dict(tapped=False, outcome='NOT_TAPPED', detail='desktop final action is not enabled') if action == 'PLACE_HELD' else None)
        run = Run(body, lambda progress, run_id: self.ledger.progress(iid, progress, run_id))
        site = DesktopBet365(page, decisions)
        try:
            if action == 'SESSION_CHECK':
                logged = await site.session(run)
                self.session = dict(state='AUTHENTICATED' if logged else 'LOGGED_OUT' if logged is False else 'UNKNOWN',
                                    observed_at_ms=now_ms(), detail='session check')
                if logged:
                    return run.finish('PASS', 'PASS', 'SESSION_AUTHENTICATED')
                return run.finish('FAIL', 'SESSION_REQUIRED', 'Not logged in on the desktop worker: log in by hand in its Chrome window')
            if action == 'RESET_BETSLIP':
                # visual: screenshot check + the slip's visible remove control (no script in the page)
                run.stage('RESET_BETSLIP')
                removed = await site.empty_slip(run)
                return run.finish('PASS', 'PASS', f'BETSLIP_CLEARED ({removed} removed)')
            stage, detail = await site.hold(run, body.get('execution_mode', 'hold'))
            return run.finish('PASS', 'PASS', detail if stage != 'DISCOVERED' else f'DISCOVERED: {detail}')
        except Failure as f:
            return run.finish('FAIL', f.stage, f.detail)


def serve(worker, host='127.0.0.1'):
    token = worker.cfg['token']

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, value, raw=None, ctype='application/json'):
            data = raw if raw is not None else json.dumps(value).encode()
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authorised(self):
            if self.headers.get('Origin'):
                self._send(403, dict(detail='browser origins are refused')); return False
            if self.headers.get('Authorization') != 'Bearer ' + token:
                self._send(401, dict(detail='bearer token required')); return False
            return True

        def do_GET(self):
            if not self._authorised():
                return
            parts = [p for p in self.path.split('?')[0].split('/') if p]
            if parts in (['health'], ['state']):
                return self._send(200, worker.health())
            if len(parts) >= 2 and parts[0] == 'instructions':
                code, value = worker.result(parts[1])
                if len(parts) == 2:
                    return self._send(code, value)
                row = worker.ledger.get(parts[1])
                run_dir = ROOT / '.local' / 'desktop-evidence' / (row or {}).get('run_id', '') if row and row.get('run_id') else None
                if len(parts) == 3 and parts[2] == 'evidence':
                    files = sorted(p.name for p in run_dir.iterdir()) if run_dir and run_dir.exists() else []
                    return self._send(code, dict(result=value, files=files))
                if len(parts) == 4 and parts[2] == 'artifacts' and run_dir and re.match(r'^[\w.-]+$', parts[3]):
                    f = run_dir / parts[3]
                    if f.exists():
                        return self._send(200, None, f.read_bytes(), 'image/png' if f.suffix == '.png' else 'text/plain; charset=utf-8')
            self._send(404, dict(detail='not found'))

        def do_POST(self):
            if not self._authorised():
                return
            if self.path.split('?')[0] != '/instructions':
                return self._send(404, dict(detail='not found'))
            length = int(self.headers.get('Content-Length') or 0)
            if length > 64 * 1024:
                return self._send(413, dict(detail='body too large'))
            try:
                body = json.loads(self.rfile.read(length) or b'null')
            except ValueError:
                return self._send(400, dict(status='FAIL', stage='INVALID_INSTRUCTION', detail='malformed JSON'))
            code, value = worker.submit(body)
            self._send(code, value)

    server = ThreadingHTTPServer((host, worker.cfg['port']), Handler)
    print(f"desktop worker {VERSION} on http://{host}:{worker.cfg['port']} worker_id={worker.cfg['worker_id']} "
          f"account={worker.cfg.get('account_fingerprint')} closed_at_start={worker.closed_at_start}", flush=True)
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--set-account', metavar='USERNAME')
    args = parser.parse_args()
    cfg = load_config()
    if args.set_account:
        cfg['account_fingerprint'] = fingerprint(args.set_account)
        CONFIG.write_text(json.dumps(cfg, indent=1), encoding='utf-8')
        print('account fingerprint', cfg['account_fingerprint'])
        return
    serve(Worker(cfg))


if __name__ == '__main__':
    main()
