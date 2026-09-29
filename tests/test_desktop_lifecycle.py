"""Dedicated-Chrome lifecycle (desktop_worker/chrome.py, lifecycle.py, server.py watchdog), offline: Chrome-down
detection, the relaunch command (same profile and flags, started outside the caller's tree / job), the visual session
state (LOGGED_IN / LOGGED_OUT / REALITY_CHECK / UNKNOWN) from captured screenshots and text, fail-closed alerts, and the
worker binding kept across a relaunch. No browser, no network."""
import asyncio
import json
import socket
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from desktop_worker import chrome, lifecycle, server, workflow

FIX = Path(__file__).parent / 'fixtures' / 'desktop' / 'session'


def free_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]; s.close()
    return port


class ChromeDown(unittest.TestCase):
    def test_closed_port_is_down(self):
        self.assertFalse(chrome._listening(free_port()))

    def test_status_up_down_hung(self):
        self.assertEqual(lifecycle.status(probe=lambda p: True)['state'], 'UP')
        self.assertEqual(lifecycle.status(probe=lambda p: False, pids=lambda: [])['state'], 'DOWN')
        self.assertEqual(lifecycle.status(probe=lambda p: False, pids=lambda: [4242])['state'], 'HUNG')

    def test_ensure_chrome_launches_only_when_down(self):
        calls, answers = [], iter([False, False, True])
        chrome.ensure_chrome(launcher=lambda *a: calls.append(a), probe=lambda p: next(answers))
        self.assertEqual(len(calls), 1)
        chrome.ensure_chrome(launcher=lambda *a: calls.append(a), probe=lambda p: True)
        self.assertEqual(len(calls), 1)


class Relaunch(unittest.TestCase):
    PROFILE = Path(tempfile.gettempdir()) / 'mb-test-profile'

    def test_flags_and_profile_unchanged(self):
        self.assertEqual(chrome.launch_args(9333, self.PROFILE, 'chrome.exe'),
                         ['chrome.exe', '--remote-debugging-port=9333', '--remote-debugging-address=127.0.0.1',
                          f'--user-data-dir={self.PROFILE}', '--no-first-run', '--no-default-browser-check',
                          '--window-size=1400,1000', 'about:blank'])
        self.assertEqual(chrome.PROFILE, chrome.ROOT / '.local' / 'desktop-chrome-profile')

    def test_wmi_start_is_outside_the_callers_tree(self):
        seen = {}

        def run(cmd, **k):
            seen.update(cmd=cmd, env=k['env'])
            return SimpleNamespace(returncode=0, stdout='0 4321\n', stderr='')
        info = chrome.launch(9333, self.PROFILE, 'C:/chrome/chrome.exe', run=run, windows=True)
        self.assertEqual((info['method'], info['pid']), ('wmi_win32_process_create', 4321))
        self.assertIn('Win32_Process -MethodName Create', ' '.join(seen['cmd']))
        self.assertIn(f'--user-data-dir={self.PROFILE}', seen['env']['MB_CHROME_CMD'])
        self.assertIn('--remote-debugging-port=9333', seen['env']['MB_CHROME_CMD'])

    def test_fallback_is_detached_and_breaks_away_from_the_job(self):
        flags = []

        def popen(args, creationflags=0, **k):
            flags.append(creationflags)
            if creationflags & chrome.CREATE_BREAKAWAY_FROM_JOB and len(flags) == 1 and popen.refuse:
                raise OSError('access denied')
            return SimpleNamespace(pid=77)
        failing = lambda cmd, **k: SimpleNamespace(returncode=1, stdout='', stderr='no wmi')
        popen.refuse = False
        info = chrome.launch(9333, self.PROFILE, 'chrome.exe', run=failing, popen=popen, windows=True)
        self.assertEqual(info['method'], 'popen_breakaway')
        self.assertTrue(flags[0] & chrome.DETACHED_PROCESS and flags[0] & chrome.CREATE_BREAKAWAY_FROM_JOB)
        flags.clear(); popen.refuse = True
        info = chrome.launch(9333, self.PROFILE, 'chrome.exe', run=failing, popen=popen, windows=True)
        self.assertEqual(info['method'], 'popen_detached')
        self.assertTrue(flags[1] & chrome.DETACHED_PROCESS)


class SessionState(unittest.TestCase):
    def test_text(self):
        self.assertEqual(lifecycle.classify('bet365 All Sports In-Play My Bets Casino £4.90', '')[0], 'LOGGED_IN')
        self.assertEqual(lifecycle.classify('All Sports In-Play Casino Rewards Join Log In', '')[0], 'LOGGED_OUT')
        self.assertEqual(lifecycle.classify('All Sports In-Play My Bets £5.00',
                                            'Reality Check Your session has now exceeded 06:32:40 Remain Logged In Log out')[0], 'REALITY_CHECK')
        self.assertEqual(lifecycle.classify('All Sports', 'Please enter the verification code')[0], 'UNKNOWN')
        self.assertEqual(lifecycle.classify('', '')[0], 'UNKNOWN')

    def test_captured_screenshots(self):
        from desktop_worker import visual_slip as vs
        if not vs.TESSERACT.exists():
            raise unittest.SkipTest('Tesseract not installed')
        from PIL import Image
        for name, want in (('logged_in', 'LOGGED_IN'), ('logged_out', 'LOGGED_OUT'), ('reality_check', 'REALITY_CHECK')):
            state = lifecycle.read_state(Image.open(FIX / f'{name}.png').convert('RGB'))
            self.assertEqual(state[0], want, f'{name}: {state}')


class FailClosed(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = mock.patch.object(workflow, 'OPERATOR_LOG', Path(self.tmp.name) / 'desktop_worker.log')
        self.log.start()

    def tearDown(self):
        self.log.stop(); self.tmp.cleanup()

    def test_alerts_for_states(self):
        self.assertIsNone(lifecycle.alert_for('LOGGED_IN'))
        for state, code in (('LOGGED_OUT', 'SESSION_LOGGED_OUT'), ('REALITY_CHECK', 'REALITY_CHECK_OPEN'),
                            ('UNKNOWN', 'SESSION_UNKNOWN'), ('CHROME_DOWN', 'CHROME_DOWN')):
            a = lifecycle.alert_for(state)
            self.assertEqual(a['code'], code)
            self.assertIn('mini PC', a['message'])
        lines = (Path(self.tmp.name) / 'desktop_worker.log').read_text(encoding='utf-8').splitlines()
        self.assertEqual(json.loads(lines[0])['device_id'], 'desktop-chrome')

    def test_recover_relaunches_same_profile_then_reads_session(self):
        launched, answers = [], iter([False, False, True])

        async def connect(pw, port):
            return 'browser', None, SimpleNamespace(url='https://www.bet365.com/#/HO/', wait_for_timeout=lambda ms: asyncio.sleep(0))

        async def session(page, out_dir=None, name=''):
            return dict(state='LOGGED_OUT', detail='top bar', observed_at_ms=1)
        with mock.patch.object(lifecycle.chrome, 'connect', connect), mock.patch.object(lifecycle, 'session_state', session), \
                mock.patch.object(lifecycle, 'chrome_pids', lambda *a, **k: []):
            r = asyncio.run(lifecycle.recover(None, launcher=lambda port, profile: launched.append((port, profile)) or dict(method='wmi'),
                                              probe=lambda p: next(answers)))
        self.assertEqual(launched, [(chrome.PORT, chrome.PROFILE)])
        self.assertTrue(r['relaunched'])
        self.assertEqual((r['session']['state'], r['alert']['code']), ('LOGGED_OUT', 'SESSION_LOGGED_OUT'))


class BindingKept(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg_path = Path(self.tmp.name) / 'desktop_worker.json'
        self.cfg_path.write_text(json.dumps(dict(port=8768, token='t-secret', worker_id='dw-abc123', account_fingerprint='f00dfeed1234')),
                                 encoding='utf-8')
        self.patch = mock.patch.object(server, 'CONFIG', self.cfg_path); self.patch.start()
        self.log = mock.patch.object(workflow, 'OPERATOR_LOG', Path(self.tmp.name) / 'op.log'); self.log.start()

    def tearDown(self):
        self.patch.stop(); self.log.stop(); self.tmp.cleanup()

    def worker(self):
        return server.Worker(server.load_config(), ledger_path=Path(self.tmp.name) / 'l.sqlite3', start_executor=False)

    def test_watchdog_queues_one_recovery_and_binding_survives(self):
        before = self.cfg_path.read_text(encoding='utf-8')
        w = self.worker()
        self.assertEqual(w.watch_once(probe=lambda p: False), 'RECOVER_QUEUED')
        self.assertEqual(w.watch_once(probe=lambda p: False), 'DOWN')          # not queued twice
        self.assertEqual(w.queue.get_nowait(), dict(_internal='RECOVER_CHROME'))
        self.assertEqual(w.health()['chrome']['state'], 'DOWN')
        w.recover_queued = False
        t = [1_000_000]
        w.now_ms = lambda: t[0]
        w.note_recovery(dict(relaunched=True, launch=dict(method='wmi_win32_process_create'), page=object(), alert=None,
                             session=dict(state='LOGGED_IN', detail='top bar', observed_at_ms=5)))
        h = w.health()
        self.assertEqual((h['state'], h['device_id'], h['worker_id'], h['account_fingerprint']),
                         ('IDLE', 'desktop-chrome', 'dw-abc123', 'f00dfeed1234'))
        self.assertEqual(h['blocked_reason'], 'SESSION_UNKNOWN')                  # one clean frame after a relaunch is not READY
        for _ in range(server.RECOVERY_CONFIRM_READS - 1):                         # the fast probe confirms it
            t[0] += 12_000
            w.note_probe(dict(state='LOGGED_IN', detail='top bar'))
        h = w.health()
        self.assertEqual((h['ready'], h['blocked_reason']), (True, None))
        self.assertEqual(json.loads(h['session'])['state'], 'AUTHENTICATED')
        self.assertIsNone(h['operator_alert'])
        self.assertEqual(self.cfg_path.read_text(encoding='utf-8'), before)       # config (token, IDs) untouched
        self.assertEqual(self.worker().cfg['worker_id'], 'dw-abc123')             # a restart reuses the same identity

    def test_not_logged_in_after_recovery_refuses_with_the_alert(self):
        w = self.worker()
        w.note_recovery(dict(relaunched=True, page=object(), session=dict(state='REALITY_CHECK', detail='dialog'),
                             alert=lifecycle.alert_for('REALITY_CHECK')))
        r = w.recovery_refusal('i-1')
        self.assertEqual((r['status'], r['stage'], r['wager_submitted'], r['operator_alert']['code']),
                         ('FAIL', 'SESSION_EXPIRED', False, 'REALITY_CHECK_OPEN'))
        self.assertEqual(w.health()['operator_alert']['code'], 'REALITY_CHECK_OPEN')
        t = [1_000_000]
        w.now_ms = lambda: t[0]
        w.note_recovery(dict(page=object(), session=dict(state='LOGGED_IN'), alert=None))
        self.assertEqual(w.recovery_refusal('i-2')['stage'], 'SESSION_EXPIRED')    # the dialog's block holds until confirmed
        for _ in range(server.RECOVERY_CONFIRM_READS - 1):
            t[0] += 12_000
            w.note_probe(dict(state='LOGGED_IN'))
        self.assertIsNone(w.recovery_refusal('i-3'))


if __name__ == '__main__':
    unittest.main()
