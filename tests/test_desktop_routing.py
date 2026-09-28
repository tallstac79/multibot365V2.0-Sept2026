"""Desktop routing work (28 Sep 2026), offline: the routing flag (OFF = phone only), HOLD -> approval -> PLACE_HELD dry run,
stale hold / stake cap / terms refusals, the durable per-instruction click guard across a restart (PLACEMENT_UNKNOWN), the
marker migration, fail-closed health states and the Telegram episode de-duplication. No browser, no network, no click."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from core import device_routing as dr
from core.pipeline import Settings
from desktop_worker import held
from desktop_worker.alerts import Alerter, sanitise
from desktop_worker.ledger import Ledger, now_ms


def run(coro):
    return asyncio.run(coro)


def good_health(**kw):
    h = dict(healthy=True, ready=True, blocked_reason=None, state='IDLE', current_instruction=None, device_id='desktop-chrome',
             worker_id='dw-1', account_fingerprint='fp1')
    h.update(kw)
    return h


class Gw:
    def __init__(self, health=None, name='gw'):
        self.h, self.name, self.sent = health, name, []

    def health(self):
        if isinstance(self.h, Exception):
            raise self.h
        return self.h

    def submit(self, p):
        self.sent.append(p)
        return dict(acknowledged=True, instruction_id=p['instruction_id'])

    def result(self, iid):
        return dict(instruction_id=iid, by=self.name)


class RoutingFlag(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def settings(self, **kw):
        return Settings.from_dict(dict(dict(desktop_expected_worker_id='dw-1', desktop_expected_account_fingerprint='fp1'), **kw))

    def test_flag_is_off_by_default_and_gateway_is_the_phone(self):
        self.assertIs(Settings().desktop_routing_enabled, False)
        phone = Gw(name='phone')
        built = []
        self.assertIs(dr.gateway(phone, Settings(), desktop_factory=lambda: built.append(1)), phone)
        self.assertEqual(built, [])                               # the desktop gateway is never even constructed

    def test_pipeline_service_gateway_for_flag_off_is_the_plain_phone_gateway(self):
        from tools import pipeline_service as ps
        from core.device_gateway import CoordinatorGateway
        cfg = Path(self.tmp.name) / 'coordinator.json'
        cfg.write_text(json.dumps(dict(url='http://127.0.0.1:1', token='x')), encoding='utf-8')
        g = ps.gateway_for(dict(coordinator_config=cfg, pipeline={}))
        self.assertIs(type(g), CoordinatorGateway)
        g2 = ps.gateway_for(dict(coordinator_config=cfg, pipeline=dict(desktop_routing_enabled=False, desktop_expected_worker_id='dw-1')))
        self.assertIs(type(g2), CoordinatorGateway)

    def test_flag_off_never_sends_to_the_desktop_even_when_it_is_routable(self):
        phone, desk = Gw(dict(healthy=True), 'phone'), Gw(good_health(), 'desk')
        g = dr.RoutingGateway(phone, desk, self.settings(desktop_routing_enabled=False), Path(self.tmp.name) / 'r.json')
        g.health(); g.submit(dict(instruction_id='a'))
        self.assertEqual((len(phone.sent), len(desk.sent)), (1, 0))

    def test_flag_on_routes_only_when_routable_and_bound(self):
        phone, desk = Gw(dict(healthy=True), 'phone'), Gw(good_health(), 'desk')
        g = dr.RoutingGateway(phone, desk, self.settings(desktop_routing_enabled=True), Path(self.tmp.name) / 'r.json')
        self.assertEqual(g.health()['routed_to'], 'desktop')
        g.submit(dict(instruction_id='h1'))
        self.assertEqual(g.result('h1')['by'], 'desk')
        for bad in (dict(healthy=False, blocked_reason='REALITY_CHECK'), dict(ready=False), dict(blocked_reason='LOGGED_OUT'),
                    dict(state='EXECUTING'), dict(worker_id='dw-other'), dict(account_fingerprint='other')):
            desk.h = good_health(**bad)
            self.assertEqual(g.health()['routed_to'], 'phone', bad)
        desk.h = RuntimeError('down')
        self.assertEqual(g.health()['routed_to'], 'phone')
        g.submit(dict(instruction_id='h1-place', held_instruction_id='h1'))   # PLACE_HELD follows its hold
        self.assertEqual(desk.sent[-1]['instruction_id'], 'h1-place')
        unbound = dr.RoutingGateway(phone, Gw(good_health()), Settings(desktop_routing_enabled=True), Path(self.tmp.name) / 'r2.json')
        self.assertEqual(unbound.select(), 'phone')                 # empty expected binding = never routed

    def test_routable_reasons(self):
        self.assertEqual(dr.routable(good_health(), 'desktop-chrome', 'dw-1', 'fp1'), (True, 'routable'))
        self.assertFalse(dr.routable(good_health(healthy=False, blocked_reason='CHROME_DOWN'), 'desktop-chrome', 'dw-1', 'fp1')[0])
        self.assertFalse(dr.routable(None)[0])


# ------------------------------------------------------------------------------------------------ server path
HOLD_BODY = dict(instruction_id='e2e-hold-1', action='ADAPTER_WORKFLOW', adapter='live_bet365', scenario='live', query='Home FC||Away FC',
                 sport='football', market='MONEYLINE', side='DRAW', line='', minimum_price='3.00', stake='0.10', timeout_ms=300000,
                 execution_mode='hold', event_url='https://www.bet365.com/#/AC/B1/C1/D8/E1/F3/', kickoff_utc='2026-09-29T18:00',
                 competition='Test League')
READY = dict(actual=dict(market='MONEYLINE', side='DRAW', line='', price='3.50', name='Draw', group='Full Time Result'),
             net=dict(accepted=True, bets=[dict(fixture='Home FC v Away FC', decimal=3.5)]), sport='football', teams=('Home FC', 'Away FC'),
             requested='', allowance='0.25', minimum='3.00', stake='0.10')
HOLD_RESULT = dict(instruction_id='e2e-hold-1', status='PASS', stage='PASS', detail='COMPLETE_EXECUTION_READY', held=True,
                   event_url=HOLD_BODY['event_url'],
                   selection=dict(market='MONEYLINE', side='DRAW', line='', price='3.50', selection_name='Draw'),
                   event_context=dict(home='Home FC', away='Away FC', competition='test league', kickoff_utc='2026-09-29T18:00', period='FULL_GAME'))


class FakeRun:
    def __init__(self, d):
        self.dir, self.stages, self.record = Path(d), [], {}

    def stage(self, s):
        self.stages.append(s)

    def put(self, k, v):
        self.record[k] = v


class FakePlacement:
    made, verified, clicked = [], 0, 0

    def __init__(self, page, decisions, instruction, key, out):
        FakePlacement.made.append(key)
        self.site, self.run = SimpleNamespace(ready=None), None

    async def verify_preclick(self, ready, stake, rec):
        FakePlacement.verified += 1
        rec['preclick'] = dict(problems=[], price='3.50', stake='0.10')
        return dict(ready['actual']), dict(place_bet=dict(centre=[805, 741], text='Place Bet', enabled=True), to_return='0.35')

    async def click_and_watch(self, *a):
        FakePlacement.clicked += 1
        raise AssertionError('the dry run must never click')


class ServerHoldPlace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'l.sqlite3'
        FakePlacement.made, FakePlacement.verified, FakePlacement.clicked = [], 0, 0
        self.env = mock.patch.dict('os.environ', {}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        # a note_probe(REALITY_CHECK) writes an operator notice: keep it out of the real logs/desktop_worker.log
        self.log = mock.patch('desktop_worker.workflow.OPERATOR_LOG', Path(self.tmp.name) / 'op.log')
        self.log.start()
        self.addCleanup(self.log.stop)

    def worker(self, **cfg):
        from desktop_worker.server import Worker
        w = Worker(dict(dict(port=0, token='t', worker_id='dw-1', account_fingerprint='fp1'), **cfg), ledger_path=self.path, start_executor=False)
        w.note_probe(dict(state='LOGGED_IN', detail='top bar'))
        return w

    def hold(self, w, at_ms=None):
        digest = w.ledger.record_hold('e2e-hold-1', 'd_run', held.hold_terms(HOLD_BODY, HOLD_RESULT, READY))
        if at_ms is not None:
            with w.ledger._db() as db:
                db.execute('UPDATE holds SET held_at_ms=? WHERE instruction_id=?', (at_ms, 'e2e-hold-1'))
        return digest

    def approved(self):
        from tools.desktop_route import approved_place_held
        return approved_place_held(HOLD_BODY, dict(HOLD_RESULT))

    def place(self, w, body, clock=None):
        return run(held.place_held(w, body, page=object(), decisions=None, run=FakeRun(self.tmp.name), clock=clock,
                                   placement_factory=FakePlacement))

    def test_hold_approve_place_dry_run(self):
        w = self.worker()
        digest = self.hold(w)
        body = self.approved()
        self.assertEqual((body['action'], body['confirmation_status'], body['held_instruction_id'], body['instruction_id']),
                         ('PLACE_HELD', 'APPROVED', 'e2e-hold-1', 'e2e-hold-1-place'))
        r = self.place(w, body)
        self.assertEqual((r['status'], r['stage'], r['placement']['outcome'], r['placement']['tapped'], r['wager_submitted']),
                         ('PASS', 'DRY_RUN', 'DRY_RUN', False, False))
        self.assertEqual(r['placement']['would_click'], dict(x=805, y=741))
        self.assertEqual((FakePlacement.verified, FakePlacement.clicked), (1, 0))
        intent = w.ledger.intent_for('e2e-hold-1-place')
        self.assertEqual((intent['live'], intent['outcome'], intent['terms_hash']), (0, 'DRY_RUN', digest))
        self.assertEqual(w.ledger.hold('e2e-hold-1')['consumed_by'], 'e2e-hold-1-place')
        again = self.place(w, dict(body, instruction_id='e2e-hold-1-place2'))
        self.assertEqual(again['stage'], 'HOLD_CONSUMED')          # one PLACE_HELD per hold

    def test_live_click_needs_both_flags(self):
        self.assertFalse(held.live_click_enabled({}, {}))
        self.assertFalse(held.live_click_enabled(dict(live_click_enabled=True), {}))
        self.assertFalse(held.live_click_enabled(dict(live_click_enabled=False), {'DESKTOP_LIVE_CLICK': '1'}))
        self.assertFalse(held.live_click_enabled(dict(live_click_enabled='true'), {'DESKTOP_LIVE_CLICK': '1'}))
        self.assertTrue(held.live_click_enabled(dict(live_click_enabled=True), {'DESKTOP_LIVE_CLICK': '1'}))
        h = self.worker().health()
        self.assertEqual((h['desktop_final_action']['live_click_enabled'], h['desktop_final_action']['dry_run'],
                          h['phone_final_action_armed'], h['desktop_final_action']['max_stake_per_bet']), (False, True, False, '0.10'))

    def test_stale_hold_is_refused_before_the_page(self):
        w = self.worker()
        self.hold(w, at_ms=now_ms() - 116_000)
        r = self.place(w, self.approved())
        self.assertEqual((r['stage'], r['placement']['outcome']), ('HOLD_EXPIRED', 'NOT_TAPPED'))
        self.assertEqual(FakePlacement.made, [])
        self.assertIsNone(w.ledger.intent_for('e2e-hold-1-place'))

    def test_hold_ageing_during_the_reverify_is_refused_without_intent(self):
        w = self.worker()
        self.hold(w)
        t = [now_ms()]

        def clock():
            t[0] += 60_000                                        # 60 s per look: fresh at the precheck, 120 s after the re-verify
            return t[0]
        r = self.place(w, self.approved(), clock=clock)
        self.assertEqual(r['stage'], 'HOLD_EXPIRED')
        self.assertIsNone(w.ledger.intent_for('e2e-hold-1-place'))

    def test_stake_cap_refuses_before_the_page(self):
        w = self.worker()
        self.hold(w)
        r = self.place(w, dict(self.approved(), stake='0.20'))
        self.assertEqual(r['stage'], 'STAKE_CAP')
        self.assertEqual(FakePlacement.made, [])
        w2 = self.worker(max_stake_per_bet='0.50')                   # configurable; the terms check then catches the change
        self.assertEqual(self.place(w2, dict(self.approved(), stake='0.20'))['stage'], 'TERMS_MISMATCH')
        from desktop_worker.server import Worker
        r = run(Worker._run(w, dict(HOLD_BODY, instruction_id='big', stake='1.00'), page=None, decisions=None))
        self.assertEqual(r['stage'], 'STAKE_CAP')                    # a hold above the cap opens nothing

    def test_not_approved_mismatch_and_missing_hold(self):
        w = self.worker()
        self.hold(w)
        self.assertEqual(self.place(w, dict(self.approved(), confirmation_status='PENDING'))['stage'], 'NOT_APPROVED')
        self.assertEqual(self.place(w, dict(self.approved(), selection_name='Home FC'))['stage'], 'TERMS_MISMATCH')
        self.assertEqual(self.place(w, dict(self.approved(), held_instruction_id='nope'))['stage'], 'HOLD_NOT_FOUND')
        w.note_probe(dict(state='REALITY_CHECK'))
        self.assertEqual(self.place(w, self.approved())['stage'], 'SESSION_EXPIRED')
        self.assertEqual(FakePlacement.made, [])

    def test_intent_without_receipt_survives_a_restart_as_placement_unknown(self):
        w = self.worker()
        self.hold(w)
        body = self.approved()
        w.submit(body)                                             # admitted (PENDING) ...
        self.assertTrue(w.ledger.record_intent(body['instruction_id'], 'e2e-hold-1', 'h', True, '0.10', '3.50'))   # ... click in flight
        w2 = self.worker()                                         # the process dies; a new one over the same ledger
        self.assertEqual(w2.closed_at_start, [body['instruction_id']])
        code, r = w2.result(body['instruction_id'])
        self.assertEqual((r['stage'], r['placement']['outcome'], r['next_step']), ('PLACEMENT_UNKNOWN', 'PLACEMENT_UNKNOWN', 'MY_BETS'))
        self.assertEqual(w2.ledger.intent_for(body['instruction_id'])['outcome'], 'PLACEMENT_UNKNOWN')
        again = self.place(w2, dict(body, instruction_id='e2e-hold-1-retry'))
        self.assertEqual((again['stage'], again['placement']['outcome'], again['placement']['next_step']),
                         ('PLACEMENT_UNKNOWN', 'PLACEMENT_UNKNOWN', 'MY_BETS'))
        self.assertEqual((FakePlacement.made, FakePlacement.clicked), ([], 0))

    def test_restart_without_intent_is_not_tapped(self):
        w = self.worker()
        w.submit(dict(self.approved(), instruction_id='p-no-intent'))
        r = self.worker().result('p-no-intent')[1]
        self.assertEqual(r['placement']['outcome'], 'NOT_TAPPED')

    def test_marker_migration_keeps_the_marker_and_is_idempotent(self):
        d = Path(self.tmp.name)
        markers, ev = d / 'final-action', d / 'ev' / 'd_x'
        markers.mkdir(); ev.mkdir(parents=True)
        m = markers / 'final-action-20260928.clicked'
        m.write_text(json.dumps(dict(at='2026-09-28T18:31:58+01:00', x=805, y=741, instruction_id='final-tur-1x2-draw', price='3.50', stake='0.10')))
        (ev / 'final_action.json').write_text(json.dumps(dict(key='final-action-20260928', clicks=1, outcome='PLACED', reference='BT7071586031I')))
        led = Ledger(d / 'm.sqlite3')
        got = led.import_markers(markers, d / 'ev')
        self.assertEqual(got, [dict(instruction_id='final-tur-1x2-draw', outcome='PLACED', reference='BT7071586031I', marker=m.name)])
        self.assertEqual(led.import_markers(markers, d / 'ev'), [])
        self.assertTrue(m.exists())
        i = led.intent_for('final-tur-1x2-draw')
        self.assertEqual((i['outcome'], i['reference'], i['live'], i['source']), ('PLACED', 'BT7071586031I', 1, 'marker'))
        self.assertIsNone(led.reconcile_restart() or None)
        self.assertEqual(led.intent_for('final-tur-1x2-draw')['outcome'], 'PLACED')      # a restart never downgrades it


class HealthStates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = mock.patch('desktop_worker.workflow.OPERATOR_LOG', Path(self.tmp.name) / 'op.log')
        self.log.start()
        self.addCleanup(self.log.stop)

    def worker(self):
        from desktop_worker.server import Worker
        return Worker(dict(port=0, token='t', worker_id='dw-1', account_fingerprint='fp1'), ledger_path=Path(self.tmp.name) / 'l.sqlite3',
                      start_executor=False)

    def verdict(self, w):
        h = w.health()
        return h['healthy'], h['ready'], h['blocked_reason'], dr.routable(h, 'desktop-chrome', 'dw-1', 'fp1')[0]

    def test_states(self):
        w = self.worker()
        self.assertEqual(self.verdict(w), (False, False, 'SESSION_UNKNOWN', False))          # nothing read yet
        w.note_probe(dict(state='LOGGED_IN'))
        self.assertEqual(self.verdict(w), (True, True, None, True))
        w.note_probe(dict(state='REALITY_CHECK'))
        self.assertEqual(self.verdict(w), (False, False, 'REALITY_CHECK', False))
        self.assertEqual(w.health()['operator_alert']['code'], 'REALITY_CHECK_OPEN')
        w.note_probe(dict(state='LOGGED_OUT'))
        self.assertEqual(self.verdict(w), (False, False, 'LOGGED_OUT', False))
        w.note_probe(dict(state='UNKNOWN'))
        self.assertEqual(self.verdict(w)[2], 'SESSION_UNKNOWN')
        w.note_probe(dict(state='LOGGED_IN'))
        self.assertIsNone(w.health()['operator_alert'])
        w.note_probe(dict(state='LOGGED_IN', observed_at_ms=now_ms() - 301_000))
        self.assertEqual(self.verdict(w)[2], 'SESSION_UNKNOWN')                               # stale read
        w.note_probe(dict(state='LOGGED_IN'))
        w.watch_once(probe=lambda p: False)
        self.assertEqual(self.verdict(w), (False, False, 'CHROME_DOWN', False))
        w.chrome['state'] = 'UP'; w.recovering = True
        self.assertEqual(self.verdict(w)[2], 'RECOVERING')
        w.recovering = False
        w.current = 'x'
        h = w.health()
        self.assertEqual((h['healthy'], h['ready'], h['state']), (True, False, 'EXECUTING'))
        w.current = None
        w.note_result(dict(instruction_id='r1', operator_alert=dict(code='REALITY_CHECK_OPEN')))
        self.assertEqual(self.verdict(w)[2], 'REALITY_CHECK')                                  # a run that met the dialog


class TelegramDedup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sent, self.t = [], [1000.0]

    def alerter(self, sender=None):
        s = sender or SimpleNamespace(send=self.sent.append)
        return Alerter(s, secrets=('123456:SECRET-token',), state_path=Path(self.tmp.name) / 'a.json', clock=lambda: self.t[0])

    def test_once_per_episode_and_a_recovery(self):
        a = self.alerter()
        self.assertEqual(a.update('REALITY_CHECK'), 'ALERT')
        self.assertIsNone(a.update('REALITY_CHECK'))
        self.assertIsNone(self.alerter().update('REALITY_CHECK'))        # a server restart during the episode: still once
        self.assertEqual(len(self.sent), 1)
        self.assertIn('Bet365 Reality Check is open on the mini PC; answer it manually to resume the desktop worker', self.sent[0])
        self.assertIsNone(a.update('RECOVERING'))                         # not a recovery yet
        self.assertEqual(a.update(None), 'RECOVERY')
        self.assertIsNone(a.update(None))
        self.assertEqual(len(self.sent), 2)
        self.assertIn('RESUMED', self.sent[1])
        self.assertEqual(a.update('REALITY_CHECK'), 'ALERT')              # a new episode alerts again
        self.assertEqual(a.update('LOGGED_OUT'), 'ALERT')                 # a different block is its own message
        self.assertIn('logged out', self.sent[-1])

    def test_unknown_waits_five_minutes_and_chrome_down_alerts(self):
        a = self.alerter()
        self.assertIsNone(a.update('SESSION_UNKNOWN'))
        self.t[0] += 200
        self.assertIsNone(a.update('SESSION_UNKNOWN'))
        self.t[0] += 120
        self.assertEqual(a.update('SESSION_UNKNOWN'), 'ALERT')
        self.assertEqual(a.update('CHROME_DOWN'), 'ALERT')
        self.assertIn('Chrome is down', self.sent[-1])

    def test_failed_send_is_retried_throttled_and_token_never_kept(self):
        calls = []

        def boom(text):
            calls.append(text)
            raise RuntimeError('HTTP 500 for https://api.telegram.org/bot123456:SECRET-token/sendMessage')
        a = self.alerter(SimpleNamespace(send=boom))
        self.assertIsNone(a.update('REALITY_CHECK'))
        self.assertIsNone(a.update('REALITY_CHECK'))                      # throttled (60 s)
        self.assertEqual(len(calls), 1)
        state = (Path(self.tmp.name) / 'a.json').read_text()
        self.assertNotIn('SECRET', state)
        self.t[0] += 61
        a.sender = SimpleNamespace(send=self.sent.append)
        self.assertEqual(a.update('REALITY_CHECK'), 'ALERT')
        self.assertNotIn('SECRET', sanitise('bot123456:SECRET-token x', ()))

    def test_unconfigured_sender_never_raises(self):
        a = Alerter(None, state_path=Path(self.tmp.name) / 'b.json')
        self.assertIsNone(a.update('REALITY_CHECK'))


class MyBetsShape(unittest.TestCase):
    def test_desktop_lines_feed_bet_matching(self):
        from core import bet_matching
        lines = [dict(text='bet365.com/#/MB/UB', frame=1, top=0, left=0)] + [
            dict(text=t, frame=1, top=100 + 20 * k, left=40) for k, t in enumerate(
                ['£0.10 Single', 'Draw 3.50', 'Full Time Result', 'Home FC 0', 'Away FC 0', 'Stake To Return', '£0.10 £0.35'])]
        data = dict(view='OPEN', url='https://www.bet365.com/#/MB/UB', lines=lines, frames=1)
        terms = dict(home='Home FC', away='Away FC', market='MONEYLINE', selection='DRAW', stake='0.10', odds='3.50', selection_name='Draw')
        got = bet_matching.match(terms, data)
        self.assertTrue(got['found'], got)
        with self.assertRaises(ValueError):                               # the view must be confirmed by the address line
            bet_matching.match(terms, dict(data, lines=lines[1:]))

    def test_real_my_bets_screenshot_reads_and_matches_the_live_bet(self):
        """28 Sep 2026 20:33 BST My Bets (Open) screenshot with the one open bet (BT7071586031I): the flag-adjacent 'Italy'
        is re-read without the icon and the accented feed name is folded, so bet_matching finds it EXACT."""
        from core import bet_matching
        png = Path(__file__).parent / 'fixtures' / 'desktop' / 'my_bets_open_tur_ita.png'
        try:
            from PIL import Image
            from desktop_worker import visual_slip
            if not visual_slip.TESSERACT.exists():
                raise unittest.SkipTest('Tesseract not installed')
        except ImportError as e:
            raise unittest.SkipTest(str(e))
        img = Image.open(png).convert('RGB')
        lines = [dict(text='bet365.com/#/MB/UB', frame=1, top=0, left=0)] + held.card_lines(img, box=(0, 60, img.width, img.height))
        texts = [l['text'].lower() for l in lines]
        self.assertTrue(any(t.startswith('italy') for t in texts), texts)
        terms = held.match_terms(dict(home='Türkiye', away='Italy', market='1X2', selection='DRAW', selection_name='Draw', stake='0.10', price='3.50'))
        self.assertEqual(terms['home'], 'Turkiye')
        got = bet_matching.match(terms, dict(view='OPEN', lines=lines))
        self.assertEqual((got['found'], got['confidence']), (True, 'EXACT'))


if __name__ == '__main__':
    unittest.main()
