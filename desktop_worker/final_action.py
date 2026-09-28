"""Supervised one-shot final action on the desktop worker (28 Sep 2026): ONE live Place Bet click, hard GBP 0.10 cap.

Explicitly invoked from the command line only; NOT wired into server.py or any production routing (the worker still
refuses PLACE_HELD / MY_BETS and reports final_action_armed=False):

    py -3.11 -m desktop_worker.final_action INSTRUCTION.json --confirm-one-live-bet [--key KEY]

Flow (visual only from the empty-slip check on: CDP screenshots, Tesseract OCR, ordinary mouse clicks / typing, Bet365's
BetsWebAPI responses read passively; no page script, no DOM query of the slip, no request change):
  1. the worker's own hold (DesktopBet365.hold): clear the slip, add the selection, type the stake, verify ->
     COMPLETE_EXECUTION_READY;
  2. a stop-prompt scan (Reality Check / login / verification / limits) and a FRESH screenshot + OCR immediately before
     the click: fixture / market / selection / line / odds against Bet365's addbet answer and the minimum (the existing
     _check_slip rules), exactly one selection, no slip notice (an 'Accept Changes' prompt refuses at once), stake box
     0.10, 'To Return' on the Place Bet button = 0.10 x odds (1p), Jackpot 365 toggle OFF;
  3. ONE click on Place Bet through OneClick: a marker file is written BEFORE the click, so no second click can happen in
     this process or a later one (no retry, no double click);
  4. the receipt from screenshots + the passive placebet response; no clear receipt (bet placed + reference) ->
     PLACEMENT_UNKNOWN, reconciled on My Bets through ordinary navigation (Place Bet is never clicked again).
"""
import argparse
import asyncio
import json
import re
import shutil
import time
import unicodedata
from datetime import datetime
from pathlib import Path

from desktop_worker import betslip
from desktop_worker import visual_slip as vs
from desktop_worker.workflow import DesktopBet365, Failure, Run

ROOT = Path(__file__).resolve().parents[1]
MAX_STAKE = 0.10                                   # hard cap for the supervised run
MARKERS = ROOT / '.local' / 'final-action'
OUT = ROOT / 'evidence' / 'desktop-worker-final-action'
REF = re.compile(r'\b([A-Z]{2}\d{8,12}[A-Z]?)\b')
STOP_PHRASES = ('reality check', 'remain logged in', 'log in', 'login', 'captcha', 'not a robot', 'verification',
                'verify your', 'enter the code', 'deposit limit', 'limit reached', 'two-step', 'authentication')
TRACK_OFF = (173, 204, 182)                        # Jackpot 365 toggle track when OFF (grey), knob white on the left


class Refused(Exception):
    """Pre-click refusal: nothing was clicked."""


def fold(text):
    t = unicodedata.normalize('NFKD', text or '').encode('ascii', 'ignore').decode().lower()
    return re.sub(r'\s+', ' ', t)


# ------------------------------------------------------------------------------------------------ guards
def check_stake(stake):
    v = betslip.money(stake)
    if v is None or v <= 0 or v > MAX_STAKE + 1e-9:
        raise Refused(f'stake {stake!r} is outside the supervised cap (0 < stake <= {MAX_STAKE:.2f})')
    return v


class OneClick:
    """At most one Place Bet click per key, ever: the marker is written before the click is dispatched."""

    def __init__(self, key, markers=MARKERS):
        self.path = Path(markers) / (re.sub(r'[^A-Za-z0-9_.-]', '_', key) + '.clicked')

    def used(self):
        return self.path.exists()

    async def click(self, page, x, y, detail):
        if self.path.exists():
            raise Refused(f'Place Bet was already clicked for key {self.path.stem} ({self.path}); never clicked twice')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(dict(at=datetime.now().astimezone().isoformat(timespec='seconds'), x=x, y=y, **detail)),
                             encoding='utf-8')
        await vs.click(page, x, y)                 # one mouse move + one single click


# ------------------------------------------------------------------------------------------------ pre-click checks
def jackpot_toggle(img, state):
    """(off, detail) for the Jackpot 365 toggle on the slip, from pixels: OFF = grey track with the white knob on its left.
    Anything else (green track, knob on the right, strip not found) is not OFF."""
    words, panel = state.get('words') or [], state.get('panel')
    if not panel:
        return False, 'slip panel not found'
    l, t, r, b = panel
    title_b = (state.get('title_row') or [0, t, 0, t])[3]
    amounts = [w for w in words if w['l'] > l + (r - l) * 0.65 and title_b + 30 < w['t'] < b - 60 and re.search(r'\d+[.,]\d{2}$', w['text'])]
    if not amounts:
        return False, 'Jackpot 365 strip amount not read'
    w = amounts[0]
    px = img.load()
    knob, track = [], []
    for y in range(max(w['t'] - 8, 0), min(w['b'] + 9, img.height)):
        for x in range(w['r'] + 6, min(w['r'] + 64, r, img.width)):
            p = px[x, y]
            if p[0] >= 250 and p[1] >= 250 and p[2] >= 250:
                knob.append(x)
            elif all(abs(p[i] - TRACK_OFF[i]) <= 14 for i in range(3)):
                track.append(x)
            elif vs.is_green(p) and p[0] < 150:     # a saturated green track: ON
                return False, f'Jackpot 365 toggle shows green at {x},{y} (ON)'
    if track:                                      # the knob sits inside the track (the panel's white edge does not count)
        lo, hi = min(track) - 4, max(track) + 4
        knob = [x for x in knob if lo <= x <= hi]
    if len(knob) < 10 or len(track) < 10:
        return False, f'Jackpot 365 toggle not read (knob {len(knob)} px, track {len(track)} px)'
    kx, tx = sum(knob) / len(knob), sum(track) / len(track)
    if kx >= tx:
        return False, 'Jackpot 365 toggle knob is on the right (ON)'
    return True, f"OFF (grey track, knob left; strip amount {w['text']} not added)"


def pre_click_problems(img, state, price, stake):
    """Everything the final screenshot must show besides the slip terms (checked by _check_slip); [] when it may be clicked."""
    out = []
    want = betslip.money(stake)
    if not state.get('present'):
        return ['betslip not visible']
    if state.get('items') != 1:
        out.append(f"slip shows {state.get('items')} selection rows, not exactly one")
    if state.get('notices'):
        out.append(f"slip notice: {state['notices']}")
    if betslip.money(state.get('stake')) != want or want is None or want > MAX_STAKE + 1e-9:
        out.append(f"stake box reads {state.get('stake')!r}, not {stake}")
    try:
        expected = round(want * float(price), 4)
    except (TypeError, ValueError):
        expected = None
    ret = betslip.money(state.get('to_return'))
    if expected is None or ret is None or abs(ret - expected) > 0.011:
        out.append(f"To Return {state.get('to_return')!r} is not {stake} x {price} = {expected}")
    pb = state.get('place_bet') or {}
    if not (pb.get('text') == 'Place Bet' and pb.get('enabled')):
        out.append(f"Place Bet not enabled (colour {pb.get('colour')})")
    else:                                          # 'To Return' must sit on the Place Bet button itself
        words = state.get('words') or []
        rw = next((w for w in words if w['text'] == 'Return'), None)
        bl, bt, br, bb = pb['bounds']
        if not rw or not (bl - 30 <= rw['l'] <= br + 10 and 0 <= rw['t'] - bb <= 25):
            out.append('To Return amount is not on the Place Bet button')
    words = state.get('words') or []
    if any(re.search(r'total\s*stake', fold(w['text'])) for w in words):
        out.append('slip shows a Total Stake line (more than the single 0.10 stake)')
    off, detail = jackpot_toggle(img, state)
    if not off:
        out.append(detail)
    return out


def stop_prompt(text):
    t = fold(text)
    return next((p for p in STOP_PHRASES if p in t), None)


# ------------------------------------------------------------------------------------------------ outcome
def placebet_terms(body):
    """Bet365's placebet response (read passively) -> {sr, cs, reference, odds}; tokens never kept."""
    try:
        j = json.loads(body)
    except (TypeError, ValueError):
        return dict(parsed=False)
    ref, odds = None, None
    for bt in j.get('bt') or []:
        ref = ref or bt.get('br') or bt.get('tr')
        odds = odds or bt.get('od')
    if not ref:
        m = REF.search(json.dumps(vs.redacted(body)))
        ref = m.group(1) if m else None
    return dict(parsed=True, sr=j.get('sr'), cs=j.get('cs'), reference=ref, odds=odds)


def classify(screen_text, net):
    """PLACED only for a clear receipt: the screen says the bet is placed AND a reference is read (screen or Bet365's
    placebet answer). Anything else - no receipt, a timeout, an error, an Accept Changes prompt - is PLACEMENT_UNKNOWN."""
    t = fold(screen_text)
    placed = 'bet placed' in t or 'placed' in t.split()
    m = re.search(r'ref\w*[:\s]*([A-Z]{2}\d{8,12}[A-Z]?)', screen_text or '', re.I) or REF.search(screen_text or '')
    screen_ref = m.group(1).upper() if m else None
    net_ref = next((n.get('reference') for n in net if n.get('reference') and n.get('sr') in (0, None)), None)
    ref = screen_ref or net_ref
    if placed and ref:
        return dict(outcome='PLACED', reference=ref, reference_source='screen' if screen_ref else 'placebet response')
    why = 'no receipt on the screen' if not placed else 'receipt shown without a bet reference'
    return dict(outcome='PLACEMENT_UNKNOWN', reference=ref, reason=why)


def my_bets_match(text, home, away, selection, stake='0.10'):
    """My Bets (Unsettled) page text -> PLACED / NOT_PLACED / None (cannot tell)."""
    t = fold(text)
    teams = fold(home) in t and fold(away) in t
    if teams and fold(selection) in t and stake in t:
        m = REF.search(text or '')
        return 'PLACED', (m.group(1) if m else None)
    # NOT_PLACED only on Bet365's explicit empty-list message: an unreadable page (OCR noise) is never 'absent'
    # (28 Sep 2026: a real open bet OCR'd as noise on the dark My Bets card).
    if re.search(r'no (open|unsettled|current)? ?bets|you have no', t) and not (fold(home) in t or fold(away) in t):
        return 'NOT_PLACED', None
    return None, None


# ------------------------------------------------------------------------------------------------ the run
def ocr_text(img, box, both=True):
    words = vs.ocr_words(img, box)
    if both:
        words += vs.ocr_words(img, box, invert=True)
    return words, ' '.join(w['text'] for w in words)


class Placement:
    def __init__(self, page, decisions, instruction, key, out=OUT, markers=MARKERS):
        self.page, self.i = page, dict(instruction)
        self.site = DesktopBet365(page, decisions)
        self.guard = OneClick(key, markers)
        self.out = Path(out)
        self.api = []
        self.run = None
        self.clicked = False

    # --- steps (separate methods so the tests can stand in for the browser)
    async def hold(self):
        await self.site.hold(self.run, 'hold')
        return self.site.ready

    async def shot(self, name):
        img, png = await vs.screenshot(self.page)
        return img, png

    async def scan_prompts(self, name):
        img, png = await self.shot(name)
        w, h = img.size
        words, text = ocr_text(img, (int(w * 0.2), int(h * 0.1), int(w * 0.8), int(h * 0.75)))
        self.run.save_look(name, png, dict(present=False, words=words))
        return stop_prompt(text) or (vs.reality_check(img) and 'reality check') or None

    async def fresh_state(self, name):
        img, png = await self.shot(name)
        state = vs.read_slip(img)
        self.run.save_look(name, png, state)
        return img, state

    async def watch_receipt(self, seconds=25):
        frames, text = [], ''
        end = time.monotonic() + seconds
        k = 0
        while time.monotonic() < end:
            await self.page.wait_for_timeout(900)
            k += 1
            img, png = await self.shot(f'receipt_{k:02d}')
            w, h = img.size
            panel = vs.find_panel(img, min_width=250)
            box = (panel[0], panel[1] - 60, panel[2], panel[3]) if panel else (int(w * 0.25), int(h * 0.3), int(w * 0.75), h)
            box = (box[0], max(box[1], 0), box[2], box[3])
            words, text = ocr_text(img, box)
            self.run.save_look(f'receipt_{k:02d}', png, dict(present=bool(panel), panel=panel, words=words))
            frames.append(dict(frame=k, text=text))
            nets = [n for n in self.api if 'placebet' in n['url'].lower()]
            if classify(text, [placebet_terms(n['body']) for n in nets])['outcome'] == 'PLACED' or stop_prompt(text) == 'reality check':
                break
        return text, frames

    async def reconcile(self, home, away, selection):
        """My Bets through ordinary navigation (header 'My Bets', then 'Unsettled' if offered); read from screenshots."""
        img, png = await self.shot('mybets_pre')
        w, h = img.size
        hw, htext = ocr_text(img, (0, 0, w, 80))
        self.run.save_look('mybets_pre', png, dict(present=False, words=hw))
        if stop_prompt(htext) in ('reality check', 'log in'):
            return None, None, f'stop prompt before My Bets: {stop_prompt(htext)}'
        pair = next(((a, b) for a in hw for b in hw if a['text'] == 'My' and b['text'] == 'Bets' and abs((a['t'] + a['b']) - (b['t'] + b['b'])) <= 16
                     and 0 < b['l'] - a['r'] <= 14), None)
        if not pair:
            return None, None, "header 'My Bets' not found on the screen"
        await vs.click(self.page, round((pair[0]['l'] + pair[1]['r']) / 2), round((pair[0]['t'] + pair[1]['b']) / 2))
        await self.page.wait_for_timeout(3500)
        text = ''
        for step in ('mybets', 'mybets_unsettled'):
            img, png = await self.shot(step)
            words, text = ocr_text(img, (0, 60, w, h))
            self.run.save_look(step, png, dict(present=False, words=words))
            p = stop_prompt(text)
            if p in ('reality check', 'remain logged in', 'log in', 'captcha', 'verification'):
                return None, None, f'stop prompt on My Bets: {p}'
            un = next((x for x in words if x['text'] == 'Unsettled'), None)
            if step == 'mybets' and un:
                await vs.click(self.page, round((un['l'] + un['r']) / 2), round((un['t'] + un['b']) / 2))
                await self.page.wait_for_timeout(3000)
                continue
            break
        verdict, ref = my_bets_match(text, home, away, selection)
        return verdict, ref, text[:3000]

    # --- orchestration
    async def execute(self):
        rec = dict(key=self.guard.path.stem, clicks=0, outcome=None)
        stake = self.i.get('stake')
        check_stake(stake)                          # the cap, before anything touches the page
        if self.guard.used():
            raise Refused(f'Place Bet already clicked once for {self.guard.path.stem}; refusing')
        self.run = Run(dict(self.i, execution_mode='hold'), lambda *a: None)
        rec['run_id'] = self.run.run_id
        ready = await self.hold()                   # raises Failure unless COMPLETE_EXECUTION_READY
        rec['ready'] = self.run.record.get('complete_execution_ready')
        if not ready or (rec['ready'] or {}).get('state') != 'COMPLETE_EXECUTION_READY':
            raise Refused('hold did not reach COMPLETE_EXECUTION_READY')
        home, away = ready['teams']
        prompt = await self.scan_prompts('preclick_prompt_scan')
        if prompt:
            raise Refused(f'stop prompt on the screen before the click: {prompt!r}')
        problems, img, state, actual = ['not read'], None, None, None
        for k in range(3):                          # a fresh screenshot per attempt; the click uses the last one only
            img, state = await self.fresh_state('preclick_verify' if k == 0 else f'preclick_verify_reread{k}')
            if any('accept' in n.lower() for n in state.get('notices') or []):
                raise Refused(f"'Accept Changes' on the slip: {state['notices']} (never accepted)")
            try:
                actual = self.site._check_slip(self.run, state, ready['net'], ready['sport'], ready['actual'], ready['teams'],
                                               ready['requested'], ready['allowance'], ready['minimum'])
                problems = pre_click_problems(img, state, actual['price'], stake)
            except Failure as f:
                problems = [f'{f.stage}: {f.detail}']
            if not problems:
                break
            await self.page.wait_for_timeout(500)
        rec['preclick'] = dict(problems=problems, price=actual and actual['price'], stake=state and state.get('stake'),
                               to_return=state and state.get('to_return'), items=state and state.get('items'),
                               jackpot=jackpot_toggle(img, state)[1] if state and state.get('present') else None,
                               fixture=state and state.get('fixture'), market=state and state.get('market'),
                               selection=state and state.get('title'), line=state and state.get('handicap'))
        if problems:
            raise Refused(f'pre-click verification failed: {problems}')
        pb = state['place_bet']

        async def record(resp):
            if 'BetsWebAPI' in resp.url:
                try:
                    body = await resp.text()
                except Exception as e:
                    body = f'<{type(e).__name__}>'
                self.api.append(dict(url=resp.url.split('?')[0][:120], status=resp.status, body=body, at_ms=self.run.ms()))
        handler = lambda r: asyncio.ensure_future(record(r))
        self.page.on('response', handler)
        try:
            rec['click'] = dict(at=datetime.now().astimezone().isoformat(timespec='seconds'), x=pb['centre'][0], y=pb['centre'][1])
            self.clicked = True                     # from here on the outcome is never NOT_PLACED without My Bets
            await self.guard.click(self.page, pb['centre'][0], pb['centre'][1],
                                   dict(instruction_id=self.i.get('instruction_id'), price=actual['price'], stake=stake))
            rec['clicks'] = 1
            self.run.put('wager_submitted', True)
            text, frames = await self.watch_receipt()
        finally:
            await asyncio.sleep(1.0)
            self.page.remove_listener('response', handler)
        nets = [dict(url=n['url'], status=n['status'], at_ms=n['at_ms'], terms=placebet_terms(n['body']), response=vs.redacted(n['body']))
                for n in self.api]
        rec['network'] = nets
        verdict = classify(text, [n['terms'] for n in nets if 'placebet' in n['url'].lower()])
        rec.update(receipt_text=text, receipt_frames=len(frames), **verdict)
        rec['selection'] = dict(fixture=f'{home} v {away}', market=actual['market'], selection=actual['name'], line=actual['line'],
                                odds_verified=actual['price'], stake=stake, to_return=state.get('to_return'))
        if verdict['outcome'] != 'PLACED':
            rec['reconciliation'] = dict(start=datetime.now().astimezone().isoformat(timespec='seconds'))
            got, ref, detail = await self.reconcile(home, away, actual['name'])
            rec['reconciliation'].update(verdict=got, reference=ref, detail=detail)
            rec['outcome'] = f'PLACEMENT_UNKNOWN -> {got}' if got else 'PLACEMENT_UNKNOWN (unresolved)'
            if ref and not rec.get('reference'):
                rec['reference'] = ref
        return rec

    def save(self, rec):
        dest = self.out / (self.run.run_id if self.run else 'refused-' + time.strftime('%H%M%S'))
        if self.run:
            self.run.finish('PASS' if rec.get('outcome') == 'PLACED' else 'FAIL', rec.get('outcome') or 'REFUSED', json.dumps(rec.get('outcome')))
            shutil.copytree(self.run.dir, dest, dirs_exist_ok=True)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / 'instruction.json').write_text(json.dumps(self.i, indent=1, ensure_ascii=False), encoding='utf-8')
        (dest / 'final_action.json').write_text(json.dumps(rec, indent=1, ensure_ascii=False, default=str), encoding='utf-8')
        return dest


async def place_once(page, decisions, instruction, key, out=OUT, markers=MARKERS):
    p = Placement(page, decisions, instruction, key, out, markers)
    try:
        rec = await p.execute()
    except Exception as e:                         # Refused / Failure before the click; anything after it is UNKNOWN
        reason = f'{getattr(e, "stage", type(e).__name__)}: {getattr(e, "detail", str(e))}'[:600]
        rec = dict(outcome='PLACEMENT_UNKNOWN (unresolved)' if p.clicked else 'NOT_PLACED', clicks=1 if p.clicked else 0,
                   reason=reason, ready=p.run.record.get('complete_execution_ready') if p.run else None)
        if p.clicked and p.site.ready:             # reconcile on My Bets; never a second click
            home, away = p.site.ready['teams']
            try:
                got, ref, detail = await p.reconcile(home, away, p.site.ready['actual']['name'])
            except Exception as e2:
                got, ref, detail = None, None, repr(e2)[:300]
            rec['reconciliation'] = dict(verdict=got, reference=ref, detail=detail)
            if got:
                rec['outcome'], rec['reference'] = f'PLACEMENT_UNKNOWN -> {got}', ref
    return rec, p.save(rec)


def main():
    ap = argparse.ArgumentParser(description='Supervised one-shot Bet365 placement (desktop worker, GBP 0.10 cap)')
    ap.add_argument('instruction')
    ap.add_argument('--confirm-one-live-bet', action='store_true', required=True)
    ap.add_argument('--key', default='final-action-' + time.strftime('%Y%m%d'))
    a = ap.parse_args()
    body = json.loads(Path(a.instruction).read_text(encoding='utf-8'))
    body['instruction_id'] = 'final-' + body['instruction_id']

    async def go():
        from playwright.async_api import async_playwright
        from desktop_worker import chrome
        from desktop_worker.decisions import Decisions
        d = Decisions()
        try:
            async with async_playwright() as pw:
                _, _, page = await chrome.connect(pw)
                rec, dest = await place_once(page, d, body, a.key)
        finally:
            d.close()
        slim = {k: rec.get(k) for k in ('outcome', 'clicks', 'reference', 'reference_source', 'reason', 'selection', 'preclick', 'reconciliation')}
        print(json.dumps(dict(slim, evidence=str(dest)), indent=1, ensure_ascii=False, default=str))
    asyncio.run(go())


if __name__ == '__main__':
    main()
