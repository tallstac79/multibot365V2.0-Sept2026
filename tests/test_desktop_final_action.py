"""Supervised one-shot final action (desktop_worker/final_action.py), offline: the GBP 0.10 cap, the one-click guard,
PLACEMENT_UNKNOWN without a receipt, the My Bets reconciliation, and refusal on a pre-click mismatch (stake, To Return,
more than one selection, Jackpot 365 toggle, Accept Changes). No browser, no network: the browser steps are stood in for."""
import asyncio
import tempfile
import unittest
from pathlib import Path

from desktop_worker import final_action as fa
from desktop_worker import visual_slip as vs

FIX = Path(__file__).parent / 'fixtures' / 'desktop' / 'slip'


def staked_state():
    """A verified slip as read_slip returns it (Turkiye v Italy, Draw 3.50, stake 0.10, To Return 0.35)."""
    words = [dict(text='Place', l=769, t=735, r=809, b=747), dict(text='Bet', l=815, t=736, r=841, b=747),
             dict(text='To', l=763, t=756, r=775, b=764), dict(text='Return', l=779, t=756, r=813, b=764),
             dict(text='£0.50', l=829, t=682, r=854, b=689)]
    return dict(present=True, panel=[468, 573, 916, 773], items=1, title='Draw', handicap=None, price='3.50',
                title_row=[468, 584, 916, 604], market='Full Time Result', fixture='Turkiye v Italy', stake='0.10',
                to_return='0.35', notices=[], words=words,
                place_bet=dict(text='Place Bet', bounds=[769, 735, 841, 747], centre=[805, 741], colour=[74, 255, 183], enabled=True))


def toggle_image(on=False):
    from PIL import Image, ImageDraw
    im = Image.new('RGB', (1000, 800), (217, 255, 228))
    d = ImageDraw.Draw(im)
    track = (43, 180, 120) if on else fa.TRACK_OFF
    d.rounded_rectangle((874, 677, 900, 693), 8, fill=track)
    kx = 890 if on else 876
    d.ellipse((kx, 679, kx + 10, 691), fill=(255, 255, 255))
    return im


class FakePage:
    def __init__(self):
        self.clicks, self.handlers = [], []
        self.mouse = self

    async def move(self, *a, **k):
        pass

    async def click(self, x, y, **k):
        self.clicks.append((x, y))

    async def wait_for_timeout(self, ms):
        pass

    def on(self, ev, h):
        self.handlers.append(h)

    def remove_listener(self, ev, h):
        self.handlers.remove(h)


class FakeRun:
    run_id = 'd_test'

    def __init__(self):
        self.record, self.dir = {}, Path(tempfile.mkdtemp())

    def put(self, k, v):
        self.record[k] = v

    def ms(self):
        return 0

    def save_look(self, *a):
        return {}

    def observe(self, *a):
        pass

    def finish(self, *a):
        return self.record


def placement(tmp, state, receipt='', my_bets=('PLACED', 'AB1234567890C', '...'), img=None):
    p = fa.Placement(FakePage(), None, dict(instruction_id='t', stake='0.10', sport='football', minimum_price='1.50'),
                     'test-key', out=Path(tmp) / 'out', markers=Path(tmp) / 'markers')
    ready = dict(teams=('Turkiye', 'Italy'), net={}, sport='football', requested='', allowance='0.25', minimum='1.50',
                 actual=dict(market='MONEYLINE', side='DRAW', name='Draw', line='', price='3.50'))
    p.site.ready = ready
    p.calls = dict(reconcile=0)

    async def hold():
        p.run = p.run if isinstance(p.run, FakeRun) else FakeRun()
        p.run.record['complete_execution_ready'] = dict(state='COMPLETE_EXECUTION_READY')
        return ready

    async def scan(name):
        return None

    async def fresh(name):
        return (img or toggle_image()), state

    async def watch(seconds=25):
        return receipt, [dict(frame=1, text=receipt)]

    async def reconcile(home, away, sel):
        p.calls['reconcile'] += 1
        return my_bets

    p.hold, p.scan_prompts, p.fresh_state, p.watch_receipt, p.reconcile = hold, scan, fresh, watch, reconcile
    p.site._check_slip = lambda run, st, net, sport, exp, teams, req, allow, mn: dict(exp, price=st['price'])
    return p


def run(coro):
    return asyncio.run(coro)


class Cap(unittest.TestCase):
    def test_stake_cap(self):
        self.assertEqual(fa.check_stake('0.10'), 0.10)
        for bad in ('0.11', '1.00', '0', '', None, '-0.10'):
            with self.assertRaises(fa.Refused, msg=bad):
                fa.check_stake(bad)

    def test_over_cap_never_touches_the_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = placement(tmp, staked_state())
            p.i['stake'] = '0.20'
            rec, _ = run(_place(p))
            self.assertEqual((rec['outcome'], rec['clicks'], p.page.clicks), ('NOT_PLACED', 0, []))


async def _place(p):
    try:
        rec = await p.execute()
    except Exception as e:
        rec = dict(outcome='PLACEMENT_UNKNOWN (unresolved)' if p.clicked else 'NOT_PLACED', clicks=int(p.clicked), reason=str(e))
    return rec, None


class OneClickGuard(unittest.TestCase):
    def test_second_click_is_refused_even_in_a_new_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = FakePage()
            run(fa.OneClick('k', tmp).click(page, 10, 20, {}))
            with self.assertRaises(fa.Refused):
                run(fa.OneClick('k', tmp).click(page, 10, 20, {}))
            self.assertEqual(page.clicks, [(10, 20)])

    def test_a_used_key_refuses_before_the_hold(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = placement(tmp, staked_state(), receipt='Bet Placed Ref AB1234567890C')
            rec, _ = run(_place(p))
            self.assertEqual((rec['outcome'], len(p.page.clicks)), ('PLACED', 1))
            p2 = placement(tmp, staked_state(), receipt='Bet Placed Ref AB1234567890C')
            rec2, _ = run(_place(p2))
            self.assertEqual((rec2['outcome'], p2.page.clicks), ('NOT_PLACED', []))


class Outcome(unittest.TestCase):
    def test_clear_receipt_is_placed_with_one_click(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = placement(tmp, staked_state(), receipt='Bet Placed Bet Ref: JL5127436581F Draw 3.50 Stake £0.10')
            rec, _ = run(_place(p))
            self.assertEqual((rec['outcome'], rec['reference'], p.page.clicks, p.calls['reconcile']),
                             ('PLACED', 'JL5127436581F', [(805, 741)], 0))

    def test_no_receipt_is_placement_unknown_then_reconciled_without_a_second_click(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = placement(tmp, staked_state(), receipt='', my_bets=('PLACED', 'AB1234567890C', 'Unsettled Draw ...'))
            rec, _ = run(_place(p))
            self.assertEqual((rec['outcome'], rec['clicks'], len(p.page.clicks), p.calls['reconcile']),
                             ('PLACEMENT_UNKNOWN -> PLACED', 1, 1, 1))
            p2 = placement(tmp + '2', staked_state(), receipt='Sorry, there has been an error', my_bets=('NOT_PLACED', None, ''))
            rec2, _ = run(_place(p2))
            self.assertEqual((rec2['outcome'], len(p2.page.clicks)), ('PLACEMENT_UNKNOWN -> NOT_PLACED', 1))

    def test_classify(self):
        self.assertEqual(fa.classify('', [])['outcome'], 'PLACEMENT_UNKNOWN')
        self.assertEqual(fa.classify('Bet Placed', [])['outcome'], 'PLACEMENT_UNKNOWN')          # no reference
        self.assertEqual(fa.classify('Bet Placed', [dict(sr=0, reference='XY1234567890Z')])['reference'], 'XY1234567890Z')
        self.assertEqual(fa.classify('Accept Changes', [dict(sr=0, reference='XY1234567890Z')])['outcome'], 'PLACEMENT_UNKNOWN')

    def test_my_bets_match(self):
        self.assertEqual(fa.my_bets_match('Unsettled Draw Türkiye v Italy Stake £0.10 Ref AB1234567890C', 'Turkiye', 'Italy', 'Draw'),
                         ('PLACED', 'AB1234567890C'))
        self.assertEqual(fa.my_bets_match('My Bets Unsettled You have no unsettled bets', 'Turkiye', 'Italy', 'Draw'), ('NOT_PLACED', None))
        self.assertEqual(fa.my_bets_match('loading', 'Turkiye', 'Italy', 'Draw'), (None, None))
        self.assertEqual(fa.my_bets_match('Open Live Settled ?? ulnsye Vo 20 td fg', 'Turkiye', 'Italy', 'Draw'), (None, None))


class RefuseOnMismatch(unittest.TestCase):
    def check(self, change, img=None):
        s = staked_state()
        change(s)
        return fa.pre_click_problems(img or toggle_image(), s, '3.50', '0.10')

    def test_verified_slip_has_no_problems(self):
        self.assertEqual(self.check(lambda s: None), [])

    def test_each_mismatch_refuses(self):
        self.assertTrue(self.check(lambda s: s.update(stake='0.60')))
        self.assertTrue(self.check(lambda s: s.update(to_return='0.40')))
        self.assertTrue(self.check(lambda s: s.update(items=2)))
        self.assertTrue(self.check(lambda s: s.update(notices=['Accept Changes'])))
        self.assertTrue(self.check(lambda s: s['place_bet'].update(enabled=False)))
        self.assertTrue(self.check(lambda s: None, img=toggle_image(on=True)))
        self.assertEqual(self.check(lambda s: s.update(to_return='0.36')), [])        # 1p rounding tolerance

    def test_mismatch_never_clicks(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = staked_state(); s['to_return'] = '0.85'                          # e.g. the Jackpot 0.50 added
            p = placement(tmp, s)
            rec, _ = run(_place(p))
            self.assertEqual((rec['outcome'], p.page.clicks, p.calls['reconcile']), ('NOT_PLACED', [], 0))

    def test_accept_changes_never_clicks(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = staked_state(); s['notices'] = ['Accept Changes']
            p = placement(tmp, s)
            rec, _ = run(_place(p))
            self.assertEqual((rec['outcome'], p.page.clicks), ('NOT_PLACED', []))

    def test_live_screenshot_jackpot_toggle_is_off(self):
        if not vs.TESSERACT.exists():
            raise unittest.SkipTest('Tesseract not installed')
        from PIL import Image
        img = Image.open(FIX / 'tur_draw_staked.png').convert('RGB')
        s = vs.read_slip(img)
        self.assertTrue(fa.jackpot_toggle(img, s)[0], fa.jackpot_toggle(img, s)[1])
        self.assertEqual(fa.pre_click_problems(img, s, s['price'], '0.10'), [])


if __name__ == '__main__':
    unittest.main()
