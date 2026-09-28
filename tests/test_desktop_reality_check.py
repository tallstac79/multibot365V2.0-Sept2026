"""Reality Check auto-recovery (28 Sep 2026), offline: the dialog is detected from a screenshot, the worker becomes
not routable at once (health + the backend selector), David gets ONE Telegram alert, the idle probe speeds up from
PROBE_S to BLOCKED_PROBE_S while blocked (screenshot only; the dialog is never clicked, answered or dismissed), and as
soon as the next screenshot shows Bet365 logged in again the worker is READY/IDLE by itself - no restart, no manual
worker action - with one recovery message. Drives the real Worker._probe -> lifecycle.session_state -> read_state path on
the captured fixtures (tests/fixtures/desktop/session). No browser, no network."""
import asyncio
import base64
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from core import device_routing as dr
from desktop_worker import server
from desktop_worker.alerts import Alerter

FIX = Path(__file__).parent / 'fixtures' / 'desktop' / 'session'


class FakePage:
    """A page whose only possible interaction is a CDP screenshot; anything else fails the test."""
    def __init__(self, frames):
        self.frames, self.cdp_calls, self.url = list(frames), [], 'https://www.bet365.com/#/HO/'
        page = self

        class Cdp:
            async def send(self, method, params=None):
                page.cdp_calls.append(method)
                if method != 'Page.captureScreenshot':
                    raise AssertionError(f'unexpected CDP call {method}')
                return dict(data=base64.b64encode((FIX / page.frames.pop(0)).read_bytes()).decode())

            async def detach(self):
                pass

        async def new_cdp_session(p):
            return Cdp()
        self.context = SimpleNamespace(new_cdp_session=new_cdp_session)

    def __getattr__(self, name):                     # click, mouse, keyboard, locator, evaluate, goto, ...
        raise AssertionError(f'the probe touched page.{name}')


class Browser:
    def is_connected(self):
        return True


class RealityCheckRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for target, value in (('desktop_worker.workflow.OPERATOR_LOG', Path(self.tmp.name) / 'op.log'),
                              ('desktop_worker.server.ROOT', Path(self.tmp.name))):
            p = mock.patch(target, value); p.start(); self.addCleanup(p.stop)
        self.sent, self.t = [], [1000.0]
        self.alerter = Alerter(SimpleNamespace(send=self.sent.append), state_path=Path(self.tmp.name) / 'a.json',
                               clock=lambda: self.t[0])
        self.w = server.Worker(dict(port=0, token='t', worker_id='dw-1', account_fingerprint='fp1'),
                               ledger_path=Path(self.tmp.name) / 'l.sqlite3', start_executor=False, alerter=self.alerter)
        self.w.chrome['state'] = 'UP'

    def probe(self, page):
        """One queued PROBE_SESSION exactly as the executor runs it: the probe, then the alert update."""
        self.assertEqual(self.w.queue.get_nowait(), dict(_internal='PROBE_SESSION'))
        asyncio.run(self.w._probe(None, Browser(), page, None, lambda: True))
        self.w.alert_update()

    def routable(self):
        h = self.w.health()
        return h['healthy'], h['ready'], h['state'], h['blocked_reason'], dr.routable(h, 'desktop-chrome', 'dw-1', 'fp1')[0]

    def test_detect_block_poll_fast_and_resume_by_itself(self):
        w = self.w
        page = FakePage(['logged_in.png', 'reality_check.png', 'reality_check.png', 'reality_check.png', 'logged_in.png', 'logged_in.png'])
        marks = dict(watch=0.0, probe=0.0)
        up = lambda port: True
        # routable and idle: the probe runs every PROBE_S (120 s)
        self.assertEqual(w.watch_step(server.PROBE_S, marks, up), ('UP', True))
        self.probe(page)
        self.assertEqual(self.routable(), (True, True, 'IDLE', None, True))
        self.assertEqual(w.health()['probe_interval_s'], server.PROBE_S)
        self.assertEqual(w.watch_step(server.PROBE_S + 30, marks, up)[1], False)       # not yet
        # the dialog appears: next probe sees it -> blocked, not routable, one Telegram alert
        self.assertEqual(w.watch_step(2 * server.PROBE_S, marks, up)[1], True)
        self.probe(page)
        self.assertEqual(self.routable(), (False, False, 'IDLE', 'REALITY_CHECK', False))
        self.assertEqual(w.health()['operator_alert']['code'], 'REALITY_CHECK_OPEN')
        self.assertEqual(len(self.sent), 1)
        self.assertIn('Reality Check is open', self.sent[0])
        # while blocked the probe runs every BLOCKED_PROBE_S (10-15 s), still screenshot only; no repeat alert
        self.assertTrue(10 <= server.BLOCKED_PROBE_S <= 15)
        self.assertEqual(w.health()['probe_interval_s'], server.BLOCKED_PROBE_S)
        base = 2 * server.PROBE_S
        self.assertEqual(w.watch_step(base + server.BLOCKED_PROBE_S - 1, marks, up)[1], False)
        for i in (1, 2):
            self.assertEqual(w.watch_step(base + i * server.BLOCKED_PROBE_S, marks, up)[1], True)
            self.probe(page)
            self.assertEqual(self.routable()[3], 'REALITY_CHECK')
        self.assertEqual(len(self.sent), 1)
        # David clears the dialog: the next fast probe sees Bet365 logged in (1 of RECOVERY_CONFIRM_READS, still blocked),
        # the one after confirms it -> READY/IDLE by itself, one recovery message
        self.assertEqual(server.RECOVERY_CONFIRM_READS, 2)
        self.assertEqual(w.watch_step(base + 3 * server.BLOCKED_PROBE_S, marks, up)[1], True)
        self.probe(page)
        self.assertEqual(self.routable()[3:], ('REALITY_CHECK', False))
        self.assertEqual(w.watch_step(base + 4 * server.BLOCKED_PROBE_S, marks, up)[1], True)
        self.probe(page)
        self.assertEqual(self.routable(), (True, True, 'IDLE', None, True))
        self.assertIsNone(w.health()['operator_alert'])
        self.assertEqual(len(self.sent), 2)
        self.assertIn('RESUMED', self.sent[1])
        self.assertEqual(w.health()['probe_interval_s'], server.PROBE_S)               # back to the slow idle probe
        # the dialog was never touched: every browser call was a CDP screenshot
        self.assertEqual(set(page.cdp_calls), {'Page.captureScreenshot'})
        self.assertEqual(len(page.cdp_calls), 6)
        hist = sorted(p.name for p in (Path(self.tmp.name) / '.local' / 'desktop-evidence' / 'probe' / 'hist').glob('*.png'))
        self.assertTrue(hist and any('REALITY_CHECK' in n for n in hist))          # frames around the block are kept

    def test_fast_poll_for_each_manual_block_and_slow_otherwise(self):
        w = self.w
        w.note_probe(dict(state='LOGGED_IN'))
        self.assertEqual(w.probe_interval(), server.PROBE_S)
        for visual, reason in (('REALITY_CHECK', 'REALITY_CHECK'), ('LOGGED_OUT', 'LOGGED_OUT'), ('UNKNOWN', 'SESSION_UNKNOWN')):
            w.note_probe(dict(state=visual))
            self.assertEqual((w.blocked_reason(), w.probe_interval()), (reason, server.BLOCKED_PROBE_S))
        w.watch_once(probe=lambda p: False)       # Chrome down is the watchdog's relaunch path, not the fast probe
        self.assertEqual(w.probe_interval(), server.PROBE_S)

    def test_a_run_that_meets_the_dialog_blocks_at_once_and_the_probe_clears_it(self):
        w = self.w
        w.note_probe(dict(state='LOGGED_IN'))
        w.note_result(dict(instruction_id='i-1', status='FAIL', operator_alert=dict(code='REALITY_CHECK_OPEN')))
        w.alert_update()
        self.assertEqual(self.routable()[3:], ('REALITY_CHECK', False))
        self.assertEqual(w.probe_interval(), server.BLOCKED_PROBE_S)
        page = FakePage(['logged_in.png', 'logged_in.png'])
        for _ in range(2):
            self.assertTrue(w.queue_probe())
            self.probe(page)
        self.assertEqual(self.routable(), (True, True, 'IDLE', None, True))
        self.assertEqual(len(self.sent), 2)
        self.assertTrue(self.sent[0].startswith('[MultiBot365 desktop worker] BLOCKED (Reality Check open'))
        self.assertIn('RESUMED', self.sent[1])

    def test_a_single_frame_without_the_dialog_does_not_resume(self):
        """28 Sep 2026 22:19-22:25 BST: the live Reality Check alternated with LOGGED_IN reads; one such read must not
        make the worker routable (nor send RESUMED) while the dialog is still there."""
        w = self.w
        w.note_probe(dict(state='LOGGED_IN')); w.alert_update()
        page = FakePage(['reality_check.png', 'logged_in.png', 'reality_check.png', 'logged_in.png', 'reality_check.png'])
        for _ in range(5):
            self.assertTrue(w.queue_probe())
            self.probe(page)
            self.assertEqual(self.routable()[3:], ('REALITY_CHECK', False))
        self.assertEqual(len(self.sent), 1)                                    # one BLOCKED, no RESUMED/BLOCKED flapping
        self.assertIn('BLOCKED', self.sent[0])

    def test_no_probe_while_executing_or_chrome_down(self):
        w = self.w
        w.note_probe(dict(state='REALITY_CHECK'))
        marks = dict(watch=0.0, probe=0.0)
        w.current = 'x'
        self.assertEqual(w.watch_step(server.BLOCKED_PROBE_S, marks, lambda p: True)[1], False)   # an instruction owns the page
        w.current = None
        self.assertEqual(w.watch_step(server.WATCH_S, marks, lambda p: False), ('RECOVER_QUEUED', False))


if __name__ == '__main__':
    unittest.main()
