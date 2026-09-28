"""The desktop worker's Bet365 workflows (Playwright over CDP on the dedicated Chrome).

ADAPTER_WORKFLOW (execution_mode 'hold'): the phone's hold, step for step - open the alert's own event link, require
the logged-in session, decide the event with the phone's EventPage/EventIdentity (decision bridge), find the requested
market/side at the EXACT alert line first (football: then the nearest line within the +/- allowance, the phone's
FootballLineCheck.nearest), require a decimal price at or above the minimum, add it to the slip, enter the stake,
verify slip terms / stake / returns and locate Place Bet - never pressing it. The result uses the phone's schema.

Desktop-only supervised mode 'discover' stops after the selection decision (nothing is added to the slip); it is
accepted only from the supervised tool, never from the pipeline (the pipeline only sends 'hold' / 'ready').

PLACE_HELD and MY_BETS are refused: final action is not enabled on the desktop worker.

Betslip flow (28 Sep 2026): from the empty-slip check to the Place Bet check NO script runs in the page and the slip is
never queried through the DOM (visual_slip.py): screenshots + OCR, ordinary mouse clicks and keyboard input, and
Bet365's own BetsWebAPI responses read passively. A main-world class-selector query before the selection click made
Bet365 refuse the addbet (evidence/desktop-worker-addbet/); the old DOM slip reader that did it is gone.
"""
import asyncio
import json
import re
import time
import uuid
from datetime import datetime
from pathlib import Path

from desktop_worker import bet365_page as bp
from desktop_worker import betslip
from desktop_worker import visual_slip as vs
from desktop_worker.layout import as_text, read_words

EVENT_URL = re.compile(r'^https://www\.bet365\.com/#/AC/B(\d{1,3})(/[A-Z]\d{1,12}){2,8}/?$')
SPORT_CODES = {'1': 'football', '18': 'basketball'}
EVIDENCE = Path(__file__).resolve().parents[1] / '.local' / 'desktop-evidence'
CLOSED = 'Sorry, this page is no longer available'
# Operator notices go to a JSON-lines file under logs/: the dashboard's Technical logs page tails logs/*.log.
OPERATOR_LOG = Path(__file__).resolve().parents[1] / 'logs' / 'desktop_worker.log'
# An expanded alternative-line group is read only once two consecutive layout reads agree (the rows render before the
# groups below it move down: 28 Sep 2026, final-11, the 0.0 line was filed under the next group's title).
SETTLE_GAP_MS, SETTLE_READS = 400, 15


class Failure(Exception):
    def __init__(self, stage, detail):
        super().__init__(detail)
        self.stage, self.detail = stage, detail


def require(ok, stage, detail):
    if not ok:
        raise Failure(stage, detail)


def wire_market(market):
    return {'TOTALS': 'TOTAL', '1X2': 'MONEYLINE', 'ML': 'MONEYLINE'}.get(market, market)


def observed(q):
    return dict(market=q['market'], side=q['side'], line=q['line'], price=q['price'] or q['raw_price'], availability='OPEN',
                selection_role=q['side'], selection_name=q['name'], bounds=q['bounds'])


class Run:
    """One instruction's run: evidence directory, stage timings, progress, result record."""

    def __init__(self, instruction, on_progress):
        self.i = instruction
        self.run_id = 'd_' + uuid.uuid4().hex[:20]
        self.dir = EVIDENCE / self.run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.t0 = time.monotonic()
        self.n = 0
        self.record = dict(instruction_id=instruction['instruction_id'], run_id=self.run_id, worker='desktop', wager_submitted=False)
        self.stages, self.timings, self.observations = [], [], []
        self.on_progress = on_progress
        self.stage('STARTED')

    def ms(self):
        return int((time.monotonic() - self.t0) * 1000)

    def stage(self, name):
        self.stages.append(dict(stage=name, elapsed_ms=self.ms(), at_ms=int(time.time() * 1000)))
        self.record['device_stage'] = name
        self.on_progress(dict(stage=name, elapsed_ms=self.ms(), instruction_id=self.i['instruction_id'], stages=self.stages), self.run_id)

    def put(self, key, value):
        self.record[key] = value

    def observe(self, stage, quote, identity_verified):
        self.observations.append(dict(stage=stage, observed_at_ms=int(time.time() * 1000), observed=None if quote is None else observed(quote),
                                      identity_verified=identity_verified))
        self.record['execution_observations'] = self.observations

    async def capture(self, page, name, words=None):
        """Evidence: the page's text layout (phone OCR format) and a screenshot, numbered in order."""
        self.n += 1
        base = self.dir / f's{self.n:03d}_{name}'
        words = words if words is not None else await read_words(page)
        base.with_suffix('.txt').write_text(as_text(words), encoding='utf-8')
        try:
            await page.screenshot(path=str(base.with_suffix('.png')))
        except Exception as e:                # evidence only; never decides anything
            self.record.setdefault('evidence_errors', []).append(f'{name}: {e}')
        return words

    def save_look(self, name, png, state):
        """Evidence for a visual step: the screenshot, the OCR words and the slip state read from them."""
        self.n += 1
        base = self.dir / f's{self.n:03d}_{name}'
        base.with_suffix('.png').write_bytes(png)
        words = state.get('words') or []
        (self.dir / f'{base.name}.ocr.txt').write_text(vs.as_text(words), encoding='utf-8')
        slim = {k: v for k, v in state.items() if k != 'words'}
        (self.dir / f'{base.name}.slip.json').write_text(json.dumps(slim, indent=1), encoding='utf-8')
        return slim

    def finish(self, status, stage, detail):
        self.record.update(status=status, stage=stage, detail=detail, duration_ms=self.ms(), stage_timings=self.timings,
                           progress=dict(stage=self.record.get('device_stage'), elapsed_ms=self.ms(), stages=self.stages),
                           execution_count=1)
        (self.dir / 'result.json').write_text(json.dumps(self.record, indent=1, ensure_ascii=False), encoding='utf-8')
        return self.record


class DesktopBet365:
    def __init__(self, page, decisions):
        self.page, self.d = page, decisions
        self.ready = None                          # the verified slip context (read by the supervised final_action.py)

    # ------------------------------------------------------------------ page helpers
    async def words(self):
        return await read_words(self.page)

    async def open_event(self, run, url):
        run.stage('OPEN_EVENT')
        # A fresh document load, as the phone opens the link in Chrome. A hash-only change inside the running Bet365 app
        # leaves its state stale: the event showed "no longer available" and the slip answered "Sorry, there has been
        # an error" (28 Sep 2026), while the same clicks after a full load worked.
        await self.page.goto('about:blank')
        await self.page.goto(url, wait_until='domcontentloaded', timeout=30000)
        words = []
        reloaded = False
        for attempt in range(14):                 # the event header renders after the shell
            await self.page.wait_for_timeout(700 if attempt else 1800)
            words = await self.words()
            if _reality_check(words):
                await run.capture(self.page, 'reality_check', words)
                raise reality_check_failure(run, "Bet365 'Reality Check' dialog is open: answer it by hand in the worker's Chrome window "
                                                 '(the worker never answers it)')
            if self.d.call('teams', bp.header(words)) is not None and bp.logged_in(words) is not None:
                break
            if any(CLOSED in w['text'] for w in words):
                # A hash-only navigation can leave Bet365's page state stale and show the closed notice for an open
                # event (28 Sep 2026: NIR v Hungary / BC Dubai v Barcelona); one full reload decides.
                if reloaded:
                    await run.capture(self.page, 'event_closed', words)
                    raise Failure('SUSPENDED', 'Bet365 event page: betting has closed or been suspended (no search fallback)')
                reloaded = True
                run.put('event_reloaded', True)
                await self.page.reload(wait_until='domcontentloaded', timeout=30000)
        return await run.capture(self.page, 'event_direct', words)

    async def open_tab(self, run, label):
        words = await self.words()
        strip = bp.tab_strip(words)
        require(strip is not None, 'EVENT_NOT_VERIFIED', 'Football market tab strip not visible')
        if label not in strip[1]:
            return None
        buttons = self.page.locator('button[type=button]', has_text=label)
        for i in range(await buttons.count()):
            if (await buttons.nth(i).inner_text()).strip().split('\n')[0] == label:
                await buttons.nth(i).click()
                await self.page.wait_for_timeout(1800)
                return await run.capture(self.page, 'markets_' + label.lower().replace(' ', '_'))
        return None

    async def element_for(self, quote):
        """The element showing exactly this quote's price at its read position (document coordinates, +/-3 px), or None.
        Read-only: the page is never tagged or modified."""
        sx, sy = await self.page.evaluate('[window.scrollX, window.scrollY]')
        cx, cy = (quote['bounds'][0] + quote['bounds'][2]) / 2, (quote['bounds'][1] + quote['bounds'][3]) / 2
        cells = self.page.get_by_text(quote['raw_price'], exact=True)
        matches = []
        for i in range(await cells.count()):
            box = await cells.nth(i).bounding_box()      # the element box contains the centre of the text read
            if box and box['x'] + sx <= cx <= box['x'] + sx + box['width'] and box['y'] + sy <= cy <= box['y'] + sy + box['height']:
                matches.append(cells.nth(i))
        return matches[0] if len(matches) == 1 else None

    async def expand(self, run, words, titles):
        """Open collapsed alternative-line groups (Alternative Asian Handicap / Alternative Goal Line) once."""
        opened = False
        for title, _ in bp.collapsed(words, titles):
            await self.page.get_by_text(title, exact=True).first.click()
            for _ in range(10):                   # until its rows render (they load after the click)
                await self.page.wait_for_timeout(400)
                if not any(t == title for t, _ in bp.collapsed(await self.words(), (title,))):
                    break
            opened = True
            words = await self.settled(run, title)
        return await run.capture(self.page, 'markets_expanded', words) if opened else words

    async def settled(self, run, title):
        """The page layout once two consecutive reads (the same read-only layout read) agree; fails closed if it keeps
        moving. Stops the rows of an expanding group being filed under the titles of the groups below it."""
        previous = None
        for k in range(SETTLE_READS):
            await self.page.wait_for_timeout(SETTLE_GAP_MS)
            words = await self.words()
            signature = bp.layout_signature(words)
            if signature == previous:
                run.put('expand_settle', dict(group=title, reads=k + 1))
                return words
            previous = signature
        await run.capture(self.page, 'markets_unsettled', words)
        raise Failure('EVENT_NOT_VERIFIED', f"'{title}' layout still changing after {SETTLE_READS} reads "
                                            f'({SETTLE_READS * SETTLE_GAP_MS} ms): nothing read from it')

    # ------------------------------------------------------------------ session
    async def session(self, run):
        run.stage('SESSION_CHECK')
        if 'bet365.com' not in (self.page.url or ''):
            await self.page.goto('https://www.bet365.com/#/HO/', wait_until='domcontentloaded', timeout=30000)
            await self.page.wait_for_timeout(4000)
        words = await run.capture(self.page, 'session')
        return bp.logged_in(words)

    # ------------------------------------------------------------------ hold
    async def hold(self, run, mode):
        i = run.i
        sport, market, side = i['sport'], wire_market(i['market']), i['side']
        requested, allowance, minimum = i.get('line') or '', i.get('max_line_deterioration') or '', i['minimum_price']
        home, _, away = (i.get('query') or '').partition('||')
        require(away, 'WRONG_EVENT', 'Alert opponent is required')
        require(i.get('period', 'FULL_GAME') == 'FULL_GAME', 'WRONG_EVENT', 'Full-game period required')
        url = (i.get('event_url') or '').strip()
        if not url:
            raise Failure('EVENT_NOT_VERIFIED', 'No Bet365 event link: the Search route is not implemented on the desktop worker')
        m = EVENT_URL.match(url)
        require(m is not None, 'EVENT_NOT_VERIFIED', 'Bet365 event link is not a pre-match #/AC/ event link')
        require(SPORT_CODES.get(m.group(1)) == sport, 'WRONG_EVENT', f'link sport B{m.group(1)} is not {sport}')
        run.put('route', 'event_link'); run.put('event_url', url)
        words = await self.open_event(run, url)
        logged = bp.logged_in(words)
        run.put('session', 'AUTHENTICATED' if logged else 'LOGGED_OUT' if logged is False else 'UNKNOWN')
        if mode != 'discover':
            require(logged is True, 'SESSION_EXPIRED', 'Not logged in on the desktop worker (log in by hand in its Chrome window)')
            # start from an empty slip, judged from the screen; if a selection had to be removed, load the page afresh
            if await self.empty_slip(run):
                words = await self.open_event(run, url)
                require(not (await self.look(run, 'slip_after_reload'))['present'], 'BETSLIP_NOT_SINGLE',
                        'Betslip still shows a selection after removing it and reloading')

        # --- event identity: the phone's own decision
        run.stage('VERIFY_EVENT')
        header = bp.header(words)
        run.put('direct_event_header', header)
        aliases = {}
        try:
            aliases = json.loads(i.get('aliases') or '{}') or {}
        except ValueError:
            aliases = {}
        women = str(i.get('competition_women', '')).lower() == 'true'
        r = self.d.decide(header, sport, home, away, i.get('kickoff_utc') or '', i.get('competition') or '', i.get('country') or '', True, women, aliases)
        require(r.get('teams'), 'EVENT_NOT_VERIFIED', 'Event page header teams not read')
        teams = r['teams']
        run.put('competition_check', dict(feed=i.get('competition'), country=i.get('country'), page=header[0] if header else '',
                                          matches=r.get('competition_matches')))
        run.put('identity', {k: r.get(k) for k in ('verdict', 'reason', 'home', 'away', 'kickoff_known', 'kickoff_agrees', 'reversed', 'evidence')})
        run.put('identity_verdict', r.get('verdict'))
        if r.get('alias_candidates'):
            run.put('alias_candidate', dict(feed_home=home, feed_away=away, bet365_home=teams[0], bet365_away=teams[1], event_url=url,
                                            kickoff_shown=r.get('kickoff_shown'), kickoff_expected=r.get('kickoff_expected'),
                                            verdict=r.get('verdict'), confidence=r.get('confidence'), candidates=r['alias_candidates'], sport=sport))
        if not r.get('accepted'):
            detail = f"Event link shows '{teams[0]} v {teams[1]}'; alert says '{home} v {away}': {r.get('reason')}"
            raise Failure('ALIAS_REQUIRED' if r.get('verdict') in ('AMBIGUOUS', 'NEEDS_RECHECK') else 'WRONG_EVENT', detail)
        competition_line = header[0] if header else ''
        run.put('home', teams[0]); run.put('away', teams[1]); run.put('competition', competition_line)
        run.put('fixture_name', f'{teams[0]} v {teams[1]}')
        run.put('event_context', dict(home=teams[0], away=teams[1], competition=r.get('competition_key'),
                                      kickoff_utc=i.get('kickoff_utc'), period='FULL_GAME'))

        # --- market discovery and selection
        run.stage('MARKET_NAV')
        pick, quotes = await self.discover(run, words, sport, market, side, requested, allowance, teams)
        run.put('markets', [observed(q) for q in quotes])
        run.stage('READ_SELECTION')
        for q in quotes:
            if q['market'] == market and q['side'] == side:
                run.observe('grid', q, False)
        require(pick is not None, 'TARGET_NOT_FOUND', f'No live selection for {market}/{side}' + (f'/{requested}' if requested else ''))
        require(pick['price'] is not None, 'EVENT_NOT_VERIFIED',
                f"Price shown as '{pick['raw_price']}': the account must display decimal odds on the desktop worker")
        run.observe('selection', pick, True)
        run.put('selection', observed(pick))
        run.put('selection_role', pick['side']); run.put('selection_name', pick['name'])
        run.stage('READ_PRICE')
        if not self.d.price_ok(pick['price'], minimum):
            raise Failure('BELOW_MINIMUM', f"Visible price {pick['price']} is below minimum {minimum}")
        if mode == 'discover':
            return 'DISCOVERED', f"{pick['market']} {pick['side']} {pick['line']} @ {pick['price']} (supervised discovery; nothing added to the slip)"
        return await self.slip(run, sport, pick, teams, requested, allowance, minimum, i['stake'], mode)

    # ------------------------------------------------------------------ betslip (never presses Place Bet)
    # No script in the page and no DOM query of the slip from here on: screenshots + OCR, ordinary clicks and typing,
    # and Bet365's own BetsWebAPI responses read passively (visual_slip.py).
    async def look(self, run, name):
        img, png = await vs.screenshot(self.page)
        state = vs.read_slip(img)
        if not state['present'] and vs.reality_check(img):
            run.save_look(name, png, state)
            raise reality_check_failure(run, "Bet365 'Reality Check' dialog is open: answer it by hand in the worker's Chrome window")
        return run.save_look(name, png, state)

    async def empty_slip(self, run):
        """Remove whatever the slip shows with its own visible remove (X) control; number of selections removed."""
        run.stage('CLEAR_BETSLIP')
        state = await self.look(run, 'slip_check')
        removed = 0
        while state['present']:
            require(removed < 6, 'BETSLIP_NOT_SINGLE', 'Betslip could not be cleared before the selection')
            require(state.get('remove_x'), 'BETSLIP_NOT_SINGLE', 'Betslip shown but its remove control was not located on the screen')
            await vs.click(self.page, *state['remove_x'])
            await self.page.wait_for_timeout(1200)
            removed += 1
            state = await self.look(run, 'slip_after_remove')
        run.put('betslip_clear', dict(cleared=True, removed=removed, method='visual: screenshot check, visible remove control'))
        return removed

    async def look_until(self, run, name, ok, tries=6, gap_ms=400):
        """Screenshots until `ok(state)` holds (a slip still animating in, the stake box's blinking caret hiding a digit, a
        single bad OCR frame); the last state. Nothing is accepted from a frame that does not read cleanly."""
        state = None
        for k in range(tries):
            state = await self.look(run, name if k == 0 else f'{name}_reread{k}')
            if ok(state):
                break
            await self.page.wait_for_timeout(gap_ms)
        return state

    async def slip(self, run, sport, pick, teams, requested, allowance, minimum, stake, mode):
        run.stage('CLEAR_BETSLIP')
        before = await self.look(run, 'slip_before_click')
        require(not before['present'], 'BETSLIP_NOT_SINGLE', 'Betslip is not empty before the selection')
        # fresh read of the chosen cell immediately before the click: same element, same line, terms still acceptable
        run.stage('OPEN_SELECTION')
        words = await self.words()
        quotes = bp.basketball_quotes(words, *teams) if sport == 'basketball' else bp.football_quotes(words, *teams, self.d.norm_line)
        fresh = next((q for q in quotes if q['market'] == pick['market'] and q['side'] == pick['side'] and _same(q['line'], pick['line'])
                      and q['group'] == pick['group']), None)
        require(fresh is not None and fresh['q'] is not None, 'LINE_CHANGED',
                f"{pick['market']} {pick['side']} {pick['line']} no longer shown before selecting it")
        run.observe('selection_preflight', fresh, False)
        run.put('selection_group', fresh['group'])
        self._terms(sport, fresh, requested, allowance, minimum)
        cell = await self.element_for(fresh)
        require(cell is not None, 'PRICE_CHANGED', 'Selection cell changed between the read and the click')
        # Bet365's own betslip API exchanges from the click to the end, read passively (never altered)
        api = []

        async def record(resp):
            if 'BetsWebAPI' in resp.url:
                try:
                    body = await resp.text()
                except Exception as e:
                    body = f'<{type(e).__name__}>'
                api.append(dict(url=resp.url.split('?')[0][:120], status=resp.status, body=body, at_ms=run.ms()))
        handler = lambda r: asyncio.ensure_future(record(r))
        self.page.on('response', handler)
        try:
            run.put('click_at_ms', run.ms())
            await cell.click()
            for _ in range(40):                                    # Bet365's addbet answer to this click
                await self.page.wait_for_timeout(200)
                if any('addbet' in a['url'] for a in api):
                    break
            add = next((a for a in api if 'addbet' in a['url']), None)
            net = vs.addbet_terms(add['body']) if add else dict(accepted=False, missing=True)
            run.put('addbet', dict(net, at_ms=add and add['at_ms'], status=add and add['status'],
                                   response=vs.redacted(add['body']) if add else None))
            if not net.get('accepted'):
                await self.look(run, 'slip_refused')
                raise Failure('BETSLIP_ERROR', 'Bet365 did not answer the selection click with addbet' if add is None else
                              f"Bet365 addbet refused the selection: cs={net.get('cs')} sr={net.get('sr')}")
            state = await self.look_until(run, 'slip_selection', lambda st: st['present'] and st.get('price') and st.get('fixture')
                                          and st.get('stake_control') and st.get('place_bet'))
            run.stage('VERIFY_SLIP')
            actual = await self._verify_visual(run, 'slip_selection', state, net, sport, fresh, teams, requested, allowance, minimum)
            run.stage('ENTER_STAKE')
            control = state.get('stake_control')
            require(control, 'TARGET_NOT_FOUND', 'Stake control not located on the slip screenshot')
            await vs.type_stake(self.page, control, stake)
            run.put('stake_entry', dict(control=control['kind'], click=control['click'], typed=stake, method='mouse click + keyboard'))
            run.stage('VERIFY_FINAL_STATE')
            want = betslip.money(stake)
            state = await self.look_until(run, 'slip_stake', lambda st: st['present'] and betslip.money(st.get('stake')) == want
                                          and st.get('to_return') and (st.get('place_bet') or {}).get('enabled'))
            actual = await self._verify_visual(run, 'slip_stake', state, net, sport, actual, teams, requested, allowance, minimum)
            self._verify_stake(state, stake, actual)
            await self.page.wait_for_timeout(800)                 # still the same a moment later (no late notice)
            final = await self.look_until(run, 'slip_final', lambda st: st['present'] and betslip.money(st.get('stake')) == want
                                          and (st.get('place_bet') or {}).get('enabled'))
            actual = await self._verify_visual(run, 'slip_final', final, net, sport, actual, teams, requested, allowance, minimum)
            self._verify_stake(final, stake, actual)
        finally:
            self.page.remove_listener('response', handler)
            run.put('betslip_api', [dict(url=a['url'], status=a['status'], at_ms=a['at_ms'],
                                         response=vs.redacted(a['body'])) for a in api])
        refusals = [a['url'] for a in api if '"sr":-1' in (a['body'] or '')]
        require(not refusals, 'BETSLIP_ERROR', f'Bet365 betslip API refused a later step: {refusals}')
        pb = final['place_bet']
        run.stage('PREPARE_COMPLETE_EXECUTION')
        run.observe('final', actual, True)
        run.put('selection', observed(actual))
        home, away = teams
        common = dict(market=actual['market'], line=actual['line'], price=actual['price'], stake=stake)
        run.put('stake_field_state', 'ENTERED')
        run.put('ready_state', dict(fixture_home=home, fixture_away=away, selection_role=actual['side'], selection_name=actual['name'],
                                    session='LOGGED_IN', state='READY', minimum_price_ok=True, place_bet_visible=True,
                                    wager_submitted=False, stop_before_wager=True, **common))
        run.put('final_state', dict(home=home, away=away, side=actual['side'], state='READY', place_bet_visible=True, wager_submitted=False, **common))
        run.put('complete_execution_ready', dict(state='COMPLETE_EXECUTION_READY', fixture=f'{home} v {away}', fixture_home=home, fixture_away=away,
                                                 selection_role=actual['side'], selection_name=actual['name'], minimum_price=minimum,
                                                 final_control='Place Bet', final_control_bounds=pb.get('bounds'), final_control_enabled=True,
                                                 final_control_actionable=True, gesture_dispatched=False, wager_submitted=False,
                                                 to_return=final.get('to_return'), verified_by='screenshot+OCR, addbet response',
                                                 timestamp_ms=int(time.time() * 1000), **common))
        self.ready = dict(actual=actual, net=net, sport=sport, teams=teams, requested=requested, allowance=allowance,
                          minimum=minimum, stake=stake)
        run.put('held', mode == 'hold')
        run.put('verification_detail', 'HELD: verified bet on the slip (screenshot + OCR, cross-checked with Bet365 addbet), '
                                       'stake + To Return verified, Place Bet visible and enabled; NOT pressed, slip kept')
        return 'PASS', 'COMPLETE_EXECUTION_READY'

    def _terms(self, sport, q, requested, allowance, minimum):
        """The configured tolerances on a fresh quote (football: FootballLineCheck.freshTerms; basketball: the
        one-sided line rule and the minimum), exactly as the phone applies them."""
        require(q.get('price') is not None, 'EVENT_NOT_VERIFIED', f"Price shown as '{q.get('raw_price')}': decimal odds display required")
        if sport == 'football':
            refusal = self.d.fresh(q['market'], q['side'], requested, q['line'], q['price'], allowance, minimum)
            if refusal:
                raise Failure(refusal[0], refusal[1])
            return
        if q['market'] != 'MONEYLINE' and requested:
            require(self.d.line_ok(sport, q['market'], q['side'], requested, q['line'], allowance), 'LINE_CHANGED',
                    'Line deterioration exceeds original alert allowance')
        require(self.d.price_ok(q['price'], minimum), 'BELOW_MINIMUM', f"Price {q['price']} below original alert minimum {minimum}")

    async def _verify_visual(self, run, name, state, net, sport, expected, teams, requested, allowance, minimum):
        """The slip's terms from the screen, re-read on a fresh screenshot up to twice if one OCR frame disagrees (the
        phone's readback rule); a real difference fails every read and is reported as it is."""
        for k in range(3):
            try:
                return self._check_slip(run, state, net, sport, expected, teams, requested, allowance, minimum)
            except Failure as f:
                if k == 2 or f.stage not in REREAD_STAGES:
                    raise
                run.record.setdefault('readback_rereads', []).append(dict(frame=name, stage=f.stage, detail=f.detail))
                await self.page.wait_for_timeout(500)
                state = await self.look(run, f'{name}_verify{k + 1}')

    def _check_slip(self, run, state, net, sport, expected, teams, requested, allowance, minimum):
        """Exactly one bet on the slip, for this fixture, market, selection and line, shown on the screen AND in
        Bet365's addbet answer; the price shown judged by the tolerances. Accept Change is never pressed."""
        run.put('betslip', state)
        require(state.get('present'), 'BETSLIP_ERROR', 'Betslip not visible on the screen after the selection click')
        notices = state.get('notices') or []
        require(not any('accept' in n.lower() for n in notices), 'PRICE_CHANGED',
                f'Bet365 asks to accept a change on the slip; Accept Change is never pressed: {notices}')
        require(not notices, 'PRICE_CHANGED', f'Betslip notice: {notices}')
        bets = net.get('bets') or []
        require(len(bets) == 1 and state.get('items') == 1, 'BETSLIP_NOT_SINGLE',
                f"Betslip holds {len(bets)} selection(s) per Bet365 and {state.get('items')} on the screen")
        bet = bets[0]
        for source, fixture in (('addbet', bet.get('fixture')), ('screen', state.get('fixture'))):
            parts = (fixture or '').split(' v ')
            require(len(parts) == 2 and self.d.same_slip_name(teams[0], parts[0]) and self.d.same_slip_name(teams[1], parts[1]),
                    'WRONG_EVENT', f"Slip fixture ({source}) {fixture!r} is not '{teams[0]} v {teams[1]}'")
        labels = betslip.LABELS.get((sport, expected['market']), set()) | betslip.GROUP_LABELS.get((sport, expected.get('group')), set())
        for source, market in (('addbet', bet.get('market')), ('screen', state.get('market'))):
            require((market or '').strip().lower() in labels, 'WRONG_EVENT',
                    f"Slip market ({source}) {market!r} is not {expected['market']} ({sorted(labels)})")
        for source, title in (('addbet', bet.get('selection')), ('screen', state.get('title'))):
            require(self.d.same_slip_name(expected['name'], (title or '').strip()), 'SELECTION_CHANGED',
                    f"Slip selection ({source}) {title!r} is not {expected['name']!r}")
        line = expected['line']
        if expected['market'] != 'MONEYLINE':
            net_line = self.d.norm_line(bet.get('handicap') or '') if bet.get('handicap') else None
            shown = self.d.norm_line(state.get('handicap') or '') if state.get('handicap') else None
            require(shown is not None and net_line is not None, 'PRICE_CHANGED',
                    f"Slip line unreadable (screen {state.get('handicap')!r}, addbet {bet.get('handicap')!r})")
            require(_same(shown, net_line), 'LINE_CHANGED', f'Slip line on the screen {shown} is not the addbet line {net_line}')
            line = shown.lstrip('+') if expected['market'] == 'TOTAL' else shown
        price = state.get('price')
        require(price and vs.DECIMAL.match(price), 'PRICE_CHANGED', f'Slip price unreadable ({price!r})')
        require(bet.get('decimal') is not None and abs(float(price) - bet['decimal']) <= 0.011, 'PRICE_CHANGED',
                f"Slip price on the screen {price} does not agree with Bet365's addbet odds {bet.get('odds')}")
        actual = dict(expected, line=line, price=price, raw_price=price)
        run.observe('slip', actual, True)
        self._terms(sport, actual, requested, allowance, minimum)
        return actual

    def _verify_stake(self, state, stake, actual):
        require(betslip.money(state.get('stake')) == betslip.money(stake), 'STAKE_REJECTED',
                f"Slip stake {state.get('stake')!r} is not {stake}")
        returned, expected = betslip.money(state.get('to_return')), betslip.money(stake) * float(actual['price'])
        require(returned is not None and abs(returned - expected) <= 0.011, 'STAKE_REJECTED',
                f"To Return {state.get('to_return')!r} does not agree with {stake} x {actual['price']}")
        pb = state.get('place_bet') or {}
        require(pb.get('text') == 'Place Bet' and pb.get('enabled'), 'TARGET_NOT_FOUND',
                f"Place Bet not ready on the slip (seen={bool(pb)}, colour={pb.get('colour')})")

    async def discover(self, run, words, sport, market, side, requested, allowance, teams):
        """(quote to use or None, all quotes read). Basketball: the Game Lines row, one-sided rule (unchanged). Football:
        the exact alert line on Popular, then the market's tabs (expanding alternative groups); if no view shows it, the
        nearest line within the band (FootballLineCheck.nearest), re-read on its own tab so the click target is fresh."""
        home, away = teams
        if sport == 'basketball':
            quotes = bp.basketball_quotes(words, home, away)
            pool = [q for q in quotes if q['market'] == market and q['side'] == side
                    and (market == 'MONEYLINE' or not requested or self.d.line_ok('basketball', market, side, requested, q['line'], allowance))]
            require(len(pool) <= 1, 'TARGET_NOT_FOUND', 'Multiple executable lines; no implicit alternate-line choice')
            return (pool[0] if pool else None), quotes
        norm = self.d.norm_line
        alt = {'SPREAD': 'Alternative Asian Handicap', 'TOTAL': 'Alternative Goal Line'}.get(market)
        seen, views = [], []           # views: [((tab, expanded group or None), quotes)]

        def exact(qs):
            for q in qs:
                if q['market'] == market and q['side'] == side and (market == 'MONEYLINE' or not requested or _same(q['line'], requested)):
                    return q
            return None

        def note(view, qs):
            seen.extend(qs); views.append((view, qs))
            return exact(qs)

        # 1. every view as it opens, then its own alternative group - the exact alert line ends the hunt
        hit = note(('Popular', None), bp.football_quotes(words, home, away, norm))
        for tab in ([] if hit else {'SPREAD': ['Asian Lines'], 'TOTAL': ['Goals', 'Asian Lines']}.get(market, [])):
            tw = await self.open_tab(run, tab)
            if tw is None:
                continue
            hit = note((tab, None), bp.football_quotes(tw, home, away, norm))
            if hit:
                break
            if alt and any(t == alt for t, _ in bp.collapsed(tw, (alt,))):
                tw = await self.expand(run, tw, (alt,))
                hit = note((tab, alt), bp.football_quotes(tw, home, away, norm))
                if hit:
                    break
        if hit:
            return hit, seen
        # 2. no view shows it: the nearest line inside the band (the phone's FootballLineCheck.nearest), re-read on its view
        index = self.d.nearest(seen, market, side, requested, allowance)
        if index < 0:
            refusal = self.d.refusal(seen, market, side, requested, allowance)
            require(refusal is None, 'LINE_CHANGED', refusal)
            return None, seen
        chosen = seen[index]
        run.put('football_band_choice', observed(chosen))
        tab, group = next(view for view, qs in views if any(q is chosen for q in qs))
        tw = await self.open_tab(run, tab)
        require(tw is not None, 'EVENT_NOT_VERIFIED', f'Football market tab {tab!r} not found again')
        if group and any(t == group for t, _ in bp.collapsed(tw, (group,))):
            tw = await self.expand(run, tw, (group,))
        fresh = bp.football_quotes(tw, home, away, norm)
        again = next((q for q in fresh if q['market'] == market and q['side'] == side and _same(q['line'], chosen['line'])
                      and q['group'] == chosen['group']), None)
        return again, seen


REREAD_STAGES = {'LINE_CHANGED', 'PRICE_CHANGED', 'STAKE_REJECTED', 'SELECTION_CHANGED', 'WRONG_EVENT', 'TARGET_NOT_FOUND',
                 'BETSLIP_NOT_SINGLE', 'BETSLIP_ERROR'}


def reality_check_failure(run, detail):
    """SESSION_EXPIRED for an open Reality Check (never answered by the worker) plus the operator notice: a structured
    `operator_alert` on the result (and so on /health) and an ERROR line in logs/desktop_worker.log (dashboard logs)."""
    at = datetime.now().astimezone()
    alert = dict(code='REALITY_CHECK_OPEN', severity='ERROR', stage='SESSION_EXPIRED', at=at.isoformat(timespec='seconds'),
                 at_ms=int(at.timestamp() * 1000), instruction_id=run.i.get('instruction_id'), run_id=run.run_id,
                 message=f"Bet365 Reality Check is open; answer it on the mini PC to continue "
                         f"(desktop worker stopped at {at.isoformat(sep=' ', timespec='seconds')}; it never answers the dialog)")
    run.put('operator_alert', alert)
    try:
        OPERATOR_LOG.parent.mkdir(parents=True, exist_ok=True)
        with OPERATOR_LOG.open('a', encoding='utf-8') as f:
            f.write(json.dumps(dict(timestamp=alert['at'], component='desktop_worker', severity='ERROR', device_id='desktop-chrome',
                                    instruction_id=alert['instruction_id'], run_id=alert['run_id'], code=alert['code'],
                                    stage=alert['stage'], message=alert['message']), ensure_ascii=False) + '\n')
    except OSError as e:                      # the result still carries the alert
        run.record.setdefault('evidence_errors', []).append(f'operator log: {e}')
    return Failure('SESSION_EXPIRED', f"{alert['message']}. {detail}")


def _reality_check(words):
    texts = {w['text'] for w in words}
    return 'Reality Check' in texts and 'Remain Logged In' in texts


def _same(a, b):
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return (a or '') == (b or '')
