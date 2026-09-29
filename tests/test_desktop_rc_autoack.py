"""Reality Check detection, strict READY and automatic acknowledgement (29 Sep 2026), offline.

David's instruction (29 Sep 2026 05:53 BST): the worker must not rely on the account's Reality Check setting and must clear
the dialog itself - ONE ordinary mouse click on 'Remain Logged In' only, recognised with high confidence; never 'Log out',
'Review Your Account History' or any other option; a Telegram message for every click with what the dialog showed;
at most MAX_ACK_ATTEMPTS clicks per episode; READY again only through the strict multi-read check; never while an
instruction owns the page. These tests replay the real frames captured on 28-29 Sep 2026 (tests/fixtures/desktop/session,
tests/fixtures/desktop/rc_replay and the committed evidence frames). No browser, no network, no bookmaker."""
import asyncio
import base64
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from core import device_routing as dr
from desktop_worker import lifecycle, server
from desktop_worker import reality_check as rc
from desktop_worker import visual_slip as vs
from desktop_worker.alerts import RESUME_QUIET_S, Alerter

ROOT = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / 'fixtures' / 'desktop'
EV = ROOT / 'evidence'
SESSION, REPLAY = FIX / 'session', FIX / 'rc_replay'
RC_813 = SESSION / 'reality_check.png'                   # 18:11 BST dialog, 1384x813 viewport
RC_UNREAD = SESSION / 'reality_check_buttons_unread.png'  # 22:31:39 BST: the centre OCR missed the buttons
LOGGED_IN = SESSION / 'logged_in.png'

# every Reality Check frame captured on 28 Sep 2026 (the 22:06 BST episode and the earlier ones) must read REALITY_CHECK
RC_FRAMES = [RC_813, RC_UNREAD,
             EV / 'desktop-worker-backend-placement/reality_check/probe_reality_check_2211.png',
             EV / 'desktop-worker-backend-placement/reality_check/probe_second_reality_check_2220.png',
             EV / 'desktop-worker-backend-placement/reality_check/probe_hist/223139_misread_LOGGED_IN_dialog_open.png',
             EV / 'desktop-worker-lifecycle/20260928-200423/session_02.png',
             EV / 'desktop-worker-placebet-ready/runs/recheck-01-tur-1x2-draw/s001_reality_check.png'] + \
            sorted(REPLAY.glob('rc_20260928_*.png'))
CLEAN_FRAMES = [LOGGED_IN, REPLAY / 'logged_in_home_20260929.png',
                EV / 'desktop-worker-routing/e2e/runs/1_hold_d_1c8f37ce00f440ecace7/s008_slip_final.png',        # slip + Place Bet
                EV / 'desktop-worker-routing/e2e/runs/4_my_bets_first_read_d_f52d351b51e544d081cb/s002_mybets_open.png']
NOT_READY_FRAMES = {REPLAY / 'relaunch_topbar_incomplete_20260929_053758.png': 'UNKNOWN',       # 05:37 BST relaunch, top bar half drawn
                    EV / 'desktop-worker-lifecycle/20260928-200423/session_01.png': 'UNKNOWN',
                    SESSION / 'logged_out.png': 'LOGGED_OUT'}


def need_tesseract():
    if not vs.TESSERACT.exists():
        raise unittest.SkipTest('Tesseract not installed')


def image(path):
    from PIL import Image
    return Image.open(path).convert('RGB')


class FakePage:
    """Serves the given frames to CDP Page.captureScreenshot; records mouse input; anything else fails the test."""
    def __init__(self, frames):
        self.frames, self.cdp_calls, self.clicks, self.moves, self.url = list(frames), [], [], [], 'https://www.bet365.com/#/HO/'
        page = self

        class Cdp:
            async def send(self, method, params=None):
                page.cdp_calls.append(method)
                if method != 'Page.captureScreenshot':
                    raise AssertionError(f'unexpected CDP call {method}')
                if not page.frames:
                    raise AssertionError('no frame left: an unexpected extra screenshot')
                return dict(data=base64.b64encode(Path(page.frames.pop(0)).read_bytes()).decode())

            async def detach(self):
                pass

        class Mouse:
            async def move(self, x, y, steps=1):
                page.moves.append((x, y))

            async def click(self, x, y):
                page.clicks.append((x, y))

        async def new_cdp_session(p):
            return Cdp()

        async def wait_for_timeout(ms):
            return None
        self.context = SimpleNamespace(new_cdp_session=new_cdp_session)
        self.mouse = Mouse()
        self.wait_for_timeout = wait_for_timeout

    def __getattr__(self, name):                     # keyboard, locator, evaluate, goto, click, ...
        raise AssertionError(f'the worker touched page.{name}')


class Browser:
    def is_connected(self):
        return True


# ------------------------------------------------------------------------------------------------ frame replay
class FrameReplay(unittest.TestCase):
    def test_every_reality_check_frame_reads_blocked_and_its_target_is_remain_logged_in(self):
        need_tesseract()
        for f in RC_FRAMES:
            with self.subTest(frame=f.name):
                a = lifecycle.assess(image(f))
                self.assertEqual(a['state'], 'REALITY_CHECK', f'{f.name}: {a["detail"]}')
                d = a['dialog']
                self.assertTrue(d['signature'])
                t = d['target']
                self.assertIsNotNone(t, d['reason'])
                self.assertEqual(t['text'], 'Remain Logged In')
                remain = [b for b in d['buttons'] if b['text'] == 'Remain Logged In']
                logout = [b for b in d['buttons'] if b['text'] == 'Log out']
                self.assertEqual((len(remain), len(logout)), (1, 1))
                self.assertTrue(rc.near_rect(t['x'], t['y'], remain[0]['rect'], 0))
                self.assertFalse(rc.near_rect(t['x'], t['y'], logout[0]['rect'], 4))      # never on / next to Log out
                self.assertEqual(d['interval_min'], 60)

    def test_clean_frames_are_logged_in_with_every_positive_signal_and_others_are_not(self):
        need_tesseract()
        for f in CLEAN_FRAMES:
            with self.subTest(frame=f.name):
                a = lifecycle.assess(image(f))
                self.assertEqual(a['state'], 'LOGGED_IN', f'{f.name}: {a["detail"]}')
                s = a['signals']
                self.assertEqual((s['my_bets'], s['balance'], s['nav'], s['dialog_wording'], s['modal_panel']), (True, True, True, False, None))
        for f, want in NOT_READY_FRAMES.items():
            with self.subTest(frame=f.name):
                self.assertEqual(lifecycle.assess(image(f))['state'], want)

    def test_session_time_is_read_from_the_dialog(self):
        need_tesseract()
        self.assertEqual(rc.read_dialog(image(RC_813))['session_elapsed'], '06:32:40')
        self.assertEqual(rc.read_dialog(image(REPLAY / 'rc_20260928_234805.png'))['session_elapsed'], '12:09:36')

    def test_text_classification_is_strict(self):
        full = 'bet365 All Sports In-Play My Bets Casino \u00a34.90'
        self.assertEqual(lifecycle.classify(full, '')[0], 'LOGGED_IN')
        self.assertEqual(lifecycle.classify('bet365 All Sports In-Play My Bets Casino', '')[0], 'UNKNOWN')      # no balance
        self.assertEqual(lifecycle.classify('bet365 In-Play \u00a34.90', '')[0], 'UNKNOWN')                    # no My Bets
        self.assertEqual(lifecycle.classify('bet365 My Bets \u00a34.90', '')[0], 'UNKNOWN')                    # no navigation
        self.assertEqual(lifecycle.classify(full, 'Honduras Reserve League Reality Check')[0], 'REALITY_CHECK')   # title alone
        self.assertEqual(lifecycle.classify(full, 'Your session has now exceeded 10:53:10')[0], 'REALITY_CHECK')  # sentence alone
        self.assertEqual(lifecycle.classify(full, 'Remain Logged In')[0], 'REALITY_CHECK')


# ------------------------------------------------------------------------------------------------ click-target safety
class TargetSafety(unittest.TestCase):
    """read_dialog on the real 18:11 dialog frame with the OCR replaced: only an unambiguous, confident 'Remain Logged
    In' on a green dialog button is ever a target."""
    PANEL = ['Reality', 'Check', 'Your', 'session', 'has', 'now', 'exceeded', '06:32:40', 'You', 'have', 'requested', 'a',
             'Reality', 'Check', 'after', 'every', '60', 'minutes', 'of', 'play.']

    def read(self, buttons, panel=None, conf=95.0):
        calls = iter(buttons)

        def ocr(img, box, invert=False):
            if not invert:
                return [dict(text=t, l=i * 10, t=0, r=i * 10 + 8, b=10, conf=95.0) for i, t in enumerate(panel or self.PANEL)]
            words = next(calls).split()
            return [dict(text=t, l=i * 50, t=0, r=i * 50 + 40, b=10, conf=conf if t in ('Remain', 'Logged') else 95.0)
                    for i, t in enumerate(words)]
        return rc.read_dialog(image(RC_813), ocr=ocr)

    def test_the_real_layout_has_two_green_buttons(self):
        panel = rc.modal_panel(image(RC_813))
        self.assertIsNotNone(panel)
        self.assertEqual(len(rc.green_buttons(image(RC_813), panel)), 2)
        self.assertIsNone(rc.modal_panel(image(LOGGED_IN)))
        self.assertIsNone(rc.modal_panel(image(CLEAN_FRAMES[2])))            # the floating betslip is not a dialog

    def test_only_remain_logged_in_is_a_target(self):
        d = self.read(['Remain Logged In', 'Log out'])
        self.assertEqual((d['reason'], d['target']['text']), ('recognised', 'Remain Logged In'))
        self.assertTrue(rc.near_rect(d['target']['x'], d['target']['y'], d['buttons'][0]['rect'], 0))
        d = self.read(['Log out', 'Remain Logged In'])                   # found by its text, wherever it is
        self.assertTrue(rc.near_rect(d['target']['x'], d['target']['y'], d['buttons'][1]['rect'], 0))

    def test_ambiguous_low_confidence_or_unknown_is_never_clicked(self):
        cases = {'both buttons read Remain': (['Remain Logged In', 'Remain Logged In'], None, 95.0),
                 'low confidence': (['Remain Logged In', 'Log out'], None, 40.0),
                 'no Remain button': (['Continue', 'Log out'], None, 95.0),
                 'extra words on the button': (['Remain Logged In Review History', 'Log out'], None, 95.0),
                 'logout text merged': (['Remain Logged In Log out', 'Log out'], None, 95.0),
                 'not the Reality Check': (['Remain Logged In', 'Log out'], ['Deposit', 'Limit', 'Confirm'], 95.0),
                 'title without its sentence': (['Remain Logged In', 'Log out'], ['Reality', 'Check'], 95.0)}
        for name, (buttons, panel, conf) in cases.items():
            with self.subTest(case=name):
                d = self.read(buttons, panel, conf)
                self.assertIsNone(d['target'], d['reason'])
                self.assertNotEqual(d['reason'], 'recognised')

    def test_no_dialog_no_target(self):
        d = rc.read_dialog(image(LOGGED_IN), ocr=lambda *a, **k: self.fail('no OCR without a dialog panel'))
        self.assertEqual((d['found'], d['target']), (False, None))


# ------------------------------------------------------------------------------------------------ worker behaviour
class Base(unittest.TestCase):
    cfg = {}

    def setUp(self):
        need_tesseract()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for target, value in (('desktop_worker.workflow.OPERATOR_LOG', Path(self.tmp.name) / 'op.log'),
                              ('desktop_worker.server.ROOT', Path(self.tmp.name))):
            p = mock.patch(target, value); p.start(); self.addCleanup(p.stop)
        self.sent, self.t = [], [1_000_000.0]
        self.w = self.worker()

    def worker(self):
        alerter = Alerter(SimpleNamespace(send=self.sent.append), state_path=Path(self.tmp.name) / 'a.json', clock=lambda: self.t[0])
        w = server.Worker(dict(dict(port=0, token='t', worker_id='dw-1', account_fingerprint='fp1'), **self.cfg),
                          ledger_path=Path(self.tmp.name) / 'l.sqlite3', start_executor=False, alerter=alerter)
        w.chrome['state'] = 'UP'
        w.now_ms = lambda: int(self.t[0] * 1000)
        return w

    def probe(self, page, w=None, step=server.BLOCKED_PROBE_S):
        """One PROBE_SESSION exactly as the executor runs it (probe, then the alert update), step seconds later."""
        w = w or self.w
        self.t[0] += step
        w.probe_queued = True
        asyncio.run(w._probe(None, Browser(), page, None, lambda: True))
        w.alert_update()

    def ready(self, w=None):
        page = FakePage([LOGGED_IN] * server.RECOVERY_CONFIRM_READS)
        for _ in range(server.RECOVERY_CONFIRM_READS):
            self.probe(page, w)
        self.assertEqual(self.verdict(w), (True, True, None, True))
        self.sent.clear()

    def verdict(self, w=None):
        h = (w or self.w).health()
        return h['healthy'], h['ready'], h['blocked_reason'], dr.routable(h, 'desktop-chrome', 'dw-1', 'fp1')[0]

    def kinds(self, w=None):
        return [e['kind'] for e in reversed((w or self.w).ledger.rc_events())]


class AutoAcknowledge(Base):
    def test_one_click_on_remain_logged_in_telegram_with_the_dialog_info_and_strict_return_to_ready(self):
        w = self.w
        self.ready()
        page = FakePage([RC_813, RC_813, LOGGED_IN])          # probe frame, fresh pre-click frame, after-click frame
        self.probe(page)
        self.assertEqual(len(page.clicks), 1)
        x, y = page.clicks[0]
        self.assertTrue(rc.near_rect(x, y, [495, 319, 889, 363], 0), (x, y))       # inside 'Remain Logged In' (813-high frame)
        self.assertEqual(self.verdict(), (False, False, 'REALITY_CHECK', False))      # still blocked: 1 clean read so far
        self.assertEqual(len(self.sent), 1)
        ack = self.sent[0]
        for part in ('REALITY CHECK AUTO-ACKNOWLEDGED', 'click 1/2', 'session time shown: 06:32:40', 'every 60 minutes',
                     'win/loss shown: none on the dialog', "clicked 'Remain Logged In' once"):
            self.assertIn(part, ack)
        self.assertEqual(self.kinds(), ['DETECTED', 'CLICK_INTENT', 'CLICKED'])
        frames = sorted(p.name for p in (Path(self.tmp.name) / '.local' / 'desktop-evidence' / 'reality-check').rglob('*.png'))
        self.assertEqual(frames, ['1_detected.png', '2_before_click.png', '3_after_click.png'])
        # two more clean reads at the blocked cadence: 3 reads over 24 s -> READY by itself; no BLOCKED message at all
        page = FakePage([LOGGED_IN, LOGGED_IN])
        self.probe(page)
        self.assertEqual(self.verdict()[2], 'REALITY_CHECK')
        self.probe(page)
        self.assertEqual(self.verdict(), (True, True, None, True))
        self.assertEqual(len(self.sent), 1)                                        # RESUMED waits for the quiet window
        page = FakePage([LOGGED_IN] * 4)
        for _ in range(4):
            self.probe(page)
        self.assertEqual(len(self.sent), 2)
        self.assertIn('RESUMED', self.sent[1])
        self.assertIn('after the automatic Reality Check acknowledgement', self.sent[1])
        self.assertEqual(self.kinds()[-1], 'VERIFIED_CLEAR')
        self.assertIsNone(w.ledger.rc_open_episode(create=False))
        self.assertEqual(w.health()['reality_check']['interval_min'], 60)

    def test_at_most_two_clicks_then_blocked_with_one_alert_and_manual_clear(self):
        self.ready()
        page = FakePage([RC_813] * 3 + [RC_813] * 3 + [RC_813] * 3)
        self.probe(page)                                  # click 1
        self.probe(page)                                  # click 2 (the first did not clear it)
        self.probe(page)                                  # gives up: one BLOCKED
        self.probe(page)                                  # nothing more
        self.assertEqual(len(page.clicks), 2)
        self.assertEqual(len(self.sent), 3)
        self.assertIn('click 1/2', self.sent[0]); self.assertIn('click 2/2', self.sent[1])
        self.assertIn('did not clear', self.sent[2]); self.assertIn('still open after 2 clicks', self.sent[2])
        self.assertEqual(self.verdict()[2], 'REALITY_CHECK')
        self.assertIn('GAVE_UP', self.kinds())
        page = FakePage([LOGGED_IN] * 7)                  # David answers it by hand
        for _ in range(7):
            self.probe(page)
        self.assertEqual(self.verdict(), (True, True, None, True))
        self.assertEqual(len(self.sent), 4)
        self.assertIn('RESUMED', self.sent[3])

    def test_a_restart_keeps_the_attempt_count_and_does_not_repeat_messages(self):
        self.ready()
        self.probe(FakePage([RC_813] * 3))                # click 1, then the process restarts
        w2 = self.worker()
        page = FakePage([RC_813] * 3 + [RC_813] * 2)
        self.probe(page, w2)                              # click 2 on the new process
        self.probe(page, w2)                              # gives up
        self.probe(page, w2)
        self.assertEqual(len(page.clicks), 1)
        self.assertEqual(len(self.sent), 3)               # ack 1, ack 2, one BLOCKED

    def test_unrecognised_dialog_is_not_clicked_and_alerts_once(self):
        self.ready()
        fake = lambda img, ocr=None: dict(found=True, title=True, signature=False, target=None, text='Reality Check ...',
                                          buttons=[], reason='dialog is not recognisably the Reality Check')
        with mock.patch.object(rc, 'read_dialog', fake):
            page = FakePage([RC_813] * 3)
            for _ in range(3):
                self.probe(page)
        self.assertEqual((page.clicks, page.moves), ([], []))
        self.assertEqual(len(self.sent), 1)
        self.assertIn('BLOCKED (Reality Check open', self.sent[0])
        self.assertIn('not recognised with confidence', self.sent[0])
        self.assertEqual(self.verdict()[2], 'REALITY_CHECK')
        self.assertIn('NOT_RECOGNISED', self.kinds())

    def test_a_verified_hold_on_the_slip_defers_the_click(self):
        self.ready()
        self.w.ledger.record_hold('h-1', 'run', dict(stake='0.10'))
        page = FakePage([RC_813])
        self.probe(page)
        self.assertEqual(page.clicks, [])
        self.assertIn('verified hold (h-1)', self.w.rc_note)
        self.assertEqual(self.verdict()[2], 'REALITY_CHECK')

    def test_betslip_next_to_the_button_or_a_moved_target_aborts(self):
        self.ready()
        with mock.patch.object(vs, 'find_panel', lambda img, **k: (480, 300, 900, 420)):
            page = FakePage([RC_813, RC_813])
            self.probe(page)
        self.assertEqual(page.clicks, [])
        self.assertIn('betslip panel', self.w.rc_note)
        page = FakePage([RC_813, LOGGED_IN])              # the dialog went away between the two frames
        self.probe(page)
        self.assertEqual(page.clicks, [])
        self.assertIn('not confirmed on a fresh frame', self.w.rc_note)

    def test_never_while_an_instruction_owns_the_page(self):
        self.ready()
        self.w.current = 'on-1'
        session = dict(state='REALITY_CHECK', dialog=rc.read_dialog(image(RC_813)), _png=RC_813.read_bytes())
        page = FakePage([])
        asyncio.run(self.w._auto_ack(page, session, self.w.ledger.rc_open_episode()))
        self.assertEqual((page.clicks, page.cdp_calls), ([], []))
        self.assertEqual(self.w.queue_probe(), False)      # no probe (so no acknowledgement) is even queued meanwhile


class Blocking(Base):
    cfg = dict(reality_check_auto_ack=False)

    def test_flapping_reads_from_the_2206_episode_never_resume_and_alert_once(self):
        self.ready()
        seq = [RC_813, RC_UNREAD, LOGGED_IN, RC_UNREAD, LOGGED_IN, LOGGED_IN, RC_813, LOGGED_IN, RC_UNREAD]
        page = FakePage(seq)
        for _ in seq:
            self.probe(page)
            self.assertEqual(self.verdict()[2], 'REALITY_CHECK')
        self.assertEqual(len(self.sent), 1)
        self.assertIn('BLOCKED', self.sent[0])
        self.assertIn('switched off', self.sent[0])
        self.assertEqual(page.clicks, [])

    def test_ready_needs_three_clean_reads_spanning_twenty_seconds(self):
        w = self.w
        self.assertEqual(self.verdict()[2], 'SESSION_UNKNOWN')
        page = FakePage([LOGGED_IN] * 4)
        self.probe(page, step=1); self.probe(page, step=1); self.probe(page, step=1)     # 3 reads in 2 s: too quick
        self.assertEqual(self.verdict()[2], 'SESSION_UNKNOWN')
        self.probe(page, step=server.MIN_CLEAR_SPAN_S)
        self.assertEqual(self.verdict(), (True, True, None, True))
        self.assertEqual(w.health()['probe_interval_s'], server.PROBE_S)

    def test_pre_run_gate_refuses_without_touching_the_page_when_the_dialog_is_up(self):
        w = self.w
        self.ready()
        page = FakePage([RC_813])
        r = asyncio.run(w.pre_run_gate(page, 'on-1'))
        self.assertEqual((r['status'], r['stage'], r['wager_submitted']), ('FAIL', 'SESSION_EXPIRED', False))
        self.assertEqual(set(page.cdp_calls), {'Page.captureScreenshot'})
        self.assertEqual(page.clicks, [])
        self.assertEqual(self.verdict()[2], 'REALITY_CHECK')                    # blocked for the backend at once
        r2 = asyncio.run(w.pre_run_gate(FakePage([]), 'on-2'))                   # already blocked: not even a screenshot
        self.assertEqual(r2['stage'], 'SESSION_EXPIRED')
        w2 = self.worker(); self.ready(w2)
        self.assertIsNone(asyncio.run(w2.pre_run_gate(FakePage([LOGGED_IN]), 'on-3')))

    def test_one_ambiguous_frame_blocks_a_ready_worker_at_once(self):
        self.ready()
        self.probe(FakePage([REPLAY / 'relaunch_topbar_incomplete_20260929_053758.png']))
        self.assertEqual(self.verdict()[2], 'SESSION_UNKNOWN')


if __name__ == '__main__':
    unittest.main()
