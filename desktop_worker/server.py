"""Desktop Chrome worker: the phone coordinator's HTTP contract, served on loopback, executing in the dedicated Chrome.

    python -m desktop_worker.server                      run the worker (127.0.0.1:8768 by default)
    python -m desktop_worker.server --set-account NAME   store ONLY the account fingerprint (sha256(lower(NAME))[:12],
                                                          the phone's WorkerIdentity.fingerprint); the name is not kept

Contract (tools/COORDINATOR.md): GET /health, POST /instructions (202 durable receipt; 409 DUPLICATE for a seen ID; 409
BUSY 'ID not consumed' while another instruction runs), GET /instructions/ID (202 pending + progress, 200 terminal),
GET /instructions/ID/evidence, GET /instructions/ID/artifacts/NAME. Bearer token from .local/desktop_worker.json.

Scope: SESSION_CHECK, RESET_BETSLIP, ADAPTER_WORKFLOW (hold / ready, supervised-only 'discover'), and (desktop routing
work, 28 Sep 2026; see desktop_worker/held.py) HOLD records, PLACE_HELD and MY_BETS. PLACE_HELD is a DRY RUN (everything
except the physical click) unless BOTH live_click_enabled=true in .local/desktop_worker.json AND DESKTOP_LIVE_CLICK=1 are
set. Health reports final_action_armed=True only while that live click is enabled (phone_final_action_armed is always
False: this is not the phone); the backend's automatic policy requires final_action_armed for a desktop instruction.

Health is fail-closed: healthy=false / ready=false with blocked_reason CHROME_DOWN / LOGGED_OUT / REALITY_CHECK /
SESSION_UNKNOWN (incl. no session read yet, or a read older than SESSION_MAX_AGE_S) / RECOVERING. The session is read from
a screenshot every PROBE_S while idle (no navigation), every BLOCKED_PROBE_S while a Reality Check / logout / unknown session
blocks it, so it returns to READY/IDLE by itself seconds after David clears the dialog (never clicked by the worker).
Blocking episodes are sent to Telegram once, with one recovery message when they clear (desktop_worker.alerts).
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

from desktop_worker import held as held_mod
from desktop_worker.ledger import Ledger, now_ms

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / '.local' / 'desktop_worker.json'
LEDGER = ROOT / '.local' / 'desktop_worker.sqlite3'
VERSION = 'desktop-0.1.0'
WATCH_S = 30                                   # Chrome watchdog period (CDP /json/version probe)
PROBE_S = 120                                  # visual session probe period while idle (screenshot only)
BLOCKED_PROBE_S = 12                           # faster read-only probe while a manual block (Reality Check/logout) is open
TICK_S = 3                                     # watchdog loop granularity
FAST_PROBE_REASONS = ('REALITY_CHECK', 'LOGGED_OUT', 'SESSION_UNKNOWN')
SESSION_MAX_AGE_S = 300                        # an older session read is not trusted (SESSION_UNKNOWN)
ID = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
ACTIONS = {'ADAPTER_WORKFLOW', 'SESSION_CHECK', 'RESET_BETSLIP', 'PLACE_HELD', 'MY_BETS'}


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
    def __init__(self, cfg, ledger_path=LEDGER, start_executor=True, alerter=None, import_markers=None):
        self.cfg = cfg
        self.ledger = Ledger(ledger_path)
        # the supervised run's day marker (BT7071586031I) becomes a durable per-instruction intent; the marker is kept
        self.imported_markers = self.ledger.import_markers(held_mod.MARKERS, held_mod.FINAL_EVIDENCE) \
            if (start_executor if import_markers is None else import_markers) else []
        self.closed_at_start = self.ledger.reconcile_restart()
        self.queue = Queue()
        self.current = None
        self.started = time.monotonic()
        self.session = dict(state='UNKNOWN', observed_at_ms=0, detail='no session check yet')
        self.operator_alert = None            # e.g. Bet365 Reality Check open: the operator must answer it on the mini PC
        self.chrome = dict(state='UNKNOWN', cdp_up=None, checked_at_ms=0, last_recovery=None)
        self.recovering = False
        self.recover_queued = False
        self.lock = threading.Lock()
        self.probe_queued = False
        if alerter is None:
            from desktop_worker.alerts import Alerter, NullAlerter
            alerter = Alerter.from_config() if start_executor else NullAlerter()
        self.alerter = alerter
        if start_executor:
            self.queue_probe()
            threading.Thread(target=self._executor, daemon=True).start()
            threading.Thread(target=self._watchdog, daemon=True).start()

    # ------------------------------------------------------------------ Chrome watchdog
    def watch_once(self, probe=None):
        """One Chrome check (the CDP port on 9333). Down while idle -> queue a recovery (relaunch the same profile
        detached, then a visual session check). Never touches the worker identity or the ledger."""
        from desktop_worker import chrome
        up = (probe or chrome._listening)(chrome.PORT)
        self.chrome.update(cdp_up=up, state='UP' if up else 'DOWN', checked_at_ms=now_ms())
        with self.lock:
            if not up and not self.current and not self.recovering and not self.recover_queued:
                self.recover_queued = True
                self.queue.put(dict(_internal='RECOVER_CHROME'))
                return 'RECOVER_QUEUED'
        return 'UP' if up else 'DOWN'

    def probe_interval(self):
        """PROBE_S while routable; BLOCKED_PROBE_S while a manual block is open, so the worker returns to READY/IDLE within
        seconds of David clearing the dialog (screenshot only: the dialog is never clicked, answered or dismissed)."""
        return BLOCKED_PROBE_S if self.blocked_reason() in FAST_PROBE_REASONS else PROBE_S

    def watch_step(self, now, marks, probe=None):
        """One watchdog tick at monotonic `now`. marks = {'watch': t, 'probe': t}. The CDP check runs every WATCH_S; a
        visual probe is queued when Chrome is up and probe_interval() has elapsed. Returns (cdp_status, probe_queued)."""
        status = None
        if now - marks['watch'] >= WATCH_S:
            marks['watch'] = now
            status = self.watch_once(probe)
            self.chrome['last_cdp_status'] = status
        up = self.chrome.get('state') == 'UP' if status is None else status == 'UP'
        queued = False
        if up and now - marks['probe'] >= self.probe_interval():
            queued = self.queue_probe()
            if queued:
                marks['probe'] = now
        return status, queued

    def _watchdog(self):
        start = time.monotonic()
        marks = dict(watch=start, probe=start)
        while True:
            time.sleep(TICK_S)
            try:
                self.watch_step(time.monotonic(), marks)
            except Exception as e:            # the watchdog never stops the worker
                self.chrome['watch_error'] = f'{type(e).__name__}: {e}'

    def queue_probe(self):
        """A visual session read (screenshot only, no navigation) when idle; never queued twice."""
        with self.lock:
            if self.current or self.probe_queued or self.recover_queued:
                return False
            self.probe_queued = True
        self.queue.put(dict(_internal='PROBE_SESSION'))
        return True

    def note_probe(self, session, chrome_up=True):
        """Record a visual session read: session state and the matching operator alert (cleared when LOGGED_IN)."""
        from desktop_worker import lifecycle
        visual = (session or {}).get('state', 'UNKNOWN')
        self.session = dict(state={'LOGGED_IN': 'AUTHENTICATED', 'LOGGED_OUT': 'LOGGED_OUT'}.get(visual, 'UNKNOWN'), visual_state=visual,
                            observed_at_ms=(session or {}).get('observed_at_ms') or now_ms(), detail=(session or {}).get('detail'), source='probe')
        self.chrome.update(state='UP' if chrome_up else 'DOWN', cdp_up=chrome_up, checked_at_ms=now_ms())
        current = (self.operator_alert or {}).get('code')
        wanted = {'REALITY_CHECK': 'REALITY_CHECK_OPEN', 'LOGGED_OUT': 'SESSION_LOGGED_OUT', 'UNKNOWN': 'SESSION_UNKNOWN'}.get(visual)
        if wanted is None:
            self.operator_alert = None
        elif current != wanted:
            self.operator_alert = lifecycle.alert_for(visual)
        return visual

    def blocked_reason(self):
        """Why the worker must not be routed to now (None = routable as far as Chrome and the session go)."""
        if self.recovering:
            return 'RECOVERING'
        if self.chrome.get('state') in ('DOWN', 'HUNG'):
            return 'CHROME_DOWN'
        code = (self.operator_alert or {}).get('code')
        visual = self.session.get('visual_state') or {'AUTHENTICATED': 'LOGGED_IN', 'LOGGED_OUT': 'LOGGED_OUT'}.get(self.session.get('state'), 'UNKNOWN')
        if visual == 'REALITY_CHECK' or code == 'REALITY_CHECK_OPEN':
            return 'REALITY_CHECK'
        if visual == 'LOGGED_OUT' or code == 'SESSION_LOGGED_OUT':
            return 'LOGGED_OUT'
        if code == 'CHROME_DOWN':
            return 'CHROME_DOWN'
        if visual != 'LOGGED_IN':
            return 'SESSION_UNKNOWN'
        if not self.current and now_ms() - (self.session.get('observed_at_ms') or 0) > SESSION_MAX_AGE_S * 1000:
            return 'SESSION_UNKNOWN'
        return None

    def alert_update(self):
        try:
            return self.alerter.update(self.blocked_reason())
        except Exception as e:                # alerts never stop the worker
            self.chrome['alert_error'] = f'{type(e).__name__}'[:80]

    def note_recovery(self, r):
        """Record a recovery / session check (chrome state, visual session state, operator alert); identity untouched."""
        session = r.get('session') or {}
        visual = session.get('state', 'UNKNOWN')
        self.session = dict(state={'LOGGED_IN': 'AUTHENTICATED', 'LOGGED_OUT': 'LOGGED_OUT'}.get(visual, 'UNKNOWN'), visual_state=visual,
                            observed_at_ms=session.get('observed_at_ms') or now_ms(), detail=session.get('detail'))
        self.chrome.update(state='UP' if r.get('page') is not None or visual != 'UNKNOWN' else 'DOWN',
                           last_recovery=dict(at_ms=now_ms(), relaunched=r.get('relaunched'),
                                              method=(r.get('launch') or {}).get('method'), session=visual))
        self.operator_alert = r.get('alert')
        return visual

    # ------------------------------------------------------------------ admission
    def health(self):
        blocked = self.blocked_reason()
        state = 'EXECUTING' if self.current else 'RECOVERING' if self.recovering else 'IDLE'
        lim = held_mod.limits(self.cfg)
        live = held_mod.live_click_enabled(self.cfg)
        return dict(healthy=blocked is None, ready=blocked is None and state == 'IDLE', blocked_reason=blocked,
                    heartbeat_ms=now_ms(), uptime_ms=int((time.monotonic() - self.started) * 1000),
                    state=state, current_instruction=self.current, app_version=VERSION,
                    version_code=1, kind='desktop_chrome', device_id='desktop-chrome', worker_id=self.cfg['worker_id'],
                    account_fingerprint=self.cfg.get('account_fingerprint'), session=json.dumps(self.session),
                    phone_final_action_armed=False, final_action_armed=live, probe_interval_s=self.probe_interval(),
                    local_execution=dict(enabled=live, worker_id=self.cfg['worker_id'],
                                         authorised_account_fingerprint=self.cfg.get('account_fingerprint'),
                                         last_reason='desktop PLACE_HELD is a dry run unless live_click_enabled and DESKTOP_LIVE_CLICK=1'),
                    desktop_final_action=dict(live_click_enabled=live, dry_run=not live, max_stake_per_bet=lim['max_stake_per_bet'],
                                              hold_max_age_seconds=lim['hold_max_age_seconds'],
                                              max_daily_live_stake=lim['max_daily_live_stake']),
                    last_result=self.ledger.last_result(), restarted_pending=self.closed_at_start, pid=os.getpid(),
                    operator_alert=self.operator_alert, chrome=self.chrome)

    def note_result(self, result):
        """The latest result's operator alert (None clears it: a later run got past the dialog). A Reality Check / logout
        seen by a run also marks the session, so health blocks at once (the next probe confirms or clears it)."""
        self.operator_alert = result.get('operator_alert') if isinstance(result, dict) else None
        code = (self.operator_alert or {}).get('code')
        visual = {'REALITY_CHECK_OPEN': 'REALITY_CHECK', 'SESSION_LOGGED_OUT': 'LOGGED_OUT'}.get(code)
        if visual:
            self.session = dict(state='UNKNOWN' if visual == 'REALITY_CHECK' else 'LOGGED_OUT', visual_state=visual,
                                observed_at_ms=now_ms(), detail=f'seen by instruction {result.get("instruction_id")}', source='result')

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
        from desktop_worker.chrome import connect, _listening as chrome_up
        from desktop_worker.decisions import Decisions
        decisions = Decisions()
        async with async_playwright() as pw:
            browser = page = None
            while True:
                body = await asyncio.get_running_loop().run_in_executor(None, self.queue.get)
                if body.get('_internal') == 'RECOVER_CHROME':
                    browser, page = await self._recover(pw, browser, page)
                    await asyncio.get_running_loop().run_in_executor(None, self.alert_update)
                    continue
                if body.get('_internal') == 'PROBE_SESSION':
                    browser, page = await self._probe(pw, browser, page, connect, chrome_up)
                    await asyncio.get_running_loop().run_in_executor(None, self.alert_update)
                    continue
                iid = body['instruction_id']
                try:
                    if not chrome_up():                # Chrome stopped: relaunch the same profile, then check the session
                        browser, page = await self._recover(pw, None, None)
                        refusal = self.recovery_refusal(iid)
                        if refusal:
                            raise _Refusal(refusal)
                    if browser is None or not browser.is_connected():
                        browser, context, page = await connect(pw)
                    result = await asyncio.wait_for(self._run(body, page, decisions), timeout=body.get('timeout_ms', 300000) / 1000)
                except _Refusal as r:
                    result = r.result
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
                self.queue_probe()                     # re-read the session after every instruction

    async def _probe(self, pw, browser, page, connect, chrome_up):
        """Screenshot-only session read (no navigation, nothing clicked)."""
        from desktop_worker import lifecycle
        try:
            if not chrome_up():
                self.chrome.update(state='DOWN', cdp_up=False, checked_at_ms=now_ms())
                return None, None
            if browser is None or not browser.is_connected():
                browser, context, page = await connect(pw)
            session = await lifecycle.session_state(page, ROOT / '.local' / 'desktop-evidence' / 'probe', name='last')
            self.note_probe(session)
        except Exception as e:
            self.note_probe(dict(state='UNKNOWN', detail=f'probe failed: {type(e).__name__}: {e}'[:200]))
            browser = None
        finally:
            self.probe_queued = False
        return browser, page

    async def _recover(self, pw, browser, page):
        """Relaunch (if down) + visual session check; returns (browser, page) to use, (None, None) if Chrome is down."""
        from desktop_worker import lifecycle
        self.recovering = True
        try:
            r = await lifecycle.recover(pw, out_dir=ROOT / '.local' / 'desktop-evidence' / ('recovery-' + time.strftime('%Y%m%d-%H%M%S')))
        except Exception as e:
            r = dict(session=dict(state='UNKNOWN', detail=f'{type(e).__name__}: {e}'), alert=lifecycle.alert_for('CHROME_DOWN'))
        finally:
            self.recovering = False
            self.recover_queued = False
        self.note_recovery(r)
        return r.get('browser') or browser, r.get('page') or page

    def recovery_refusal(self, iid):
        """A fail-closed result when the session is not LOGGED_IN after a recovery (the alert says what to do)."""
        visual = self.session.get('visual_state')
        if visual == 'LOGGED_IN':
            return None
        alert = dict(self.operator_alert or {}, instruction_id=iid)
        return dict(instruction_id=iid, status='FAIL', stage=alert.get('stage') or 'SESSION_REQUIRED', wager_submitted=False,
                    detail=alert.get('message') or f'Bet365 session {visual} after a Chrome restart', operator_alert=alert)

    async def _run(self, body, page, decisions):
        from desktop_worker.workflow import DesktopBet365, Failure, Run
        iid, action = body['instruction_id'], body['action']
        if action == 'PLACE_HELD':
            refused, _ = held_mod.precheck(self, body)       # every refusal that needs no page, before a Run touches anything
            if refused:
                return refused
        if action == 'ADAPTER_WORKFLOW' and body.get('execution_mode') == 'hold':
            cap = held_mod.limits(self.cfg)['max_stake_per_bet']
            if (betslip_money(body.get('stake')) or 0) > (betslip_money(cap) or 0) + 1e-9:
                return dict(instruction_id=iid, status='FAIL', stage='STAKE_CAP', wager_submitted=False,
                            detail=f"stake {body.get('stake')} is above the desktop per-bet cap {cap}; nothing was opened")
        run = Run(body, lambda progress, run_id: self.ledger.progress(iid, progress, run_id))
        site = DesktopBet365(page, decisions)
        try:
            if action == 'PLACE_HELD':
                r = await held_mod.place_held(self, body, page, decisions, run)
                run.record.update(r)
                return run.finish(r['status'], r['stage'], r['detail'])
            if action == 'MY_BETS':
                r = await held_mod.my_bets(self, body, page, run)
                run.record.update(r)
                return run.finish(r['status'], r['stage'], r['detail'])
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
            if body.get('execution_mode') == 'hold' and detail == 'COMPLETE_EXECUTION_READY' and site.ready:
                digest = self.ledger.record_hold(iid, run.run_id, held_mod.hold_terms(body, run.record, site.ready))
                run.put('terms_hash', digest)
                run.put('hold_max_age_seconds', held_mod.limits(self.cfg)['hold_max_age_seconds'])
            return run.finish('PASS', 'PASS', detail if stage != 'DISCOVERED' else f'DISCOVERED: {detail}')
        except Failure as f:
            return run.finish('FAIL', f.stage, f.detail)


def betslip_money(v):
    from desktop_worker import betslip
    return betslip.money(v)


class _Refusal(Exception):
    def __init__(self, result):
        super().__init__(result.get('detail'))
        self.result = result


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
