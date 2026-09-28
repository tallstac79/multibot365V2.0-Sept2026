"""The desktop worker's Bet365 workflows (Playwright over CDP on the dedicated Chrome).

ADAPTER_WORKFLOW (execution_mode 'hold'): the phone's hold, step for step - open the alert's own event link, require
the logged-in session, decide the event with the phone's EventPage/EventIdentity (decision bridge), find the requested
market/side at the EXACT alert line first (football: then the nearest line within the +/- allowance, the phone's
FootballLineCheck.nearest), require a decimal price at or above the minimum, add it to the slip, enter the stake,
verify slip terms / stake / returns and locate Place Bet - never pressing it. The result uses the phone's schema.

Desktop-only supervised mode 'discover' stops after the selection decision (nothing is added to the slip); it is
accepted only from the supervised tool, never from the pipeline (the pipeline only sends 'hold' / 'ready').

PLACE_HELD and MY_BETS are refused: final action is not enabled on the desktop worker.
"""
import asyncio
import json
import re
import time
import uuid
from pathlib import Path

from desktop_worker import bet365_page as bp
from desktop_worker import betslip
from desktop_worker.layout import as_text, read_words

EVENT_URL = re.compile(r'^https://www\.bet365\.com/#/AC/B(\d{1,3})(/[A-Z]\d{1,12}){2,8}/?$')
SPORT_CODES = {'1': 'football', '18': 'basketball'}
EVIDENCE = Path(__file__).resolve().parents[1] / '.local' / 'desktop-evidence'
CLOSED = 'Sorry, this page is no longer available'


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

    def finish(self, status, stage, detail):
        self.record.update(status=status, stage=stage, detail=detail, duration_ms=self.ms(), stage_timings=self.timings,
                           progress=dict(stage=self.record.get('device_stage'), elapsed_ms=self.ms(), stages=self.stages),
                           execution_count=1)
        (self.dir / 'result.json').write_text(json.dumps(self.record, indent=1, ensure_ascii=False), encoding='utf-8')
        return self.record


class DesktopBet365:
    def __init__(self, page, decisions):
        self.page, self.d = page, decisions

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
        return await run.capture(self.page, 'markets_expanded') if opened else words

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
    async def slip(self, run, sport, pick, teams, requested, allowance, minimum, stake, mode):
        run.stage('CLEAR_BETSLIP')
        require(await betslip.clear(self.page), 'BETSLIP_NOT_SINGLE', 'Betslip could not be cleared before the selection')
        run.put('betslip_clear', True)
        # fresh read of the chosen cell immediately before the click: same element, same line, terms still acceptable
        run.stage('OPEN_SELECTION')
        words = await self.words()
        quotes = bp.basketball_quotes(words, *teams) if sport == 'basketball' else bp.football_quotes(words, *teams, self.d.norm_line)
        fresh = next((q for q in quotes if q['market'] == pick['market'] and q['side'] == pick['side'] and _same(q['line'], pick['line'])
                      and q['group'] == pick['group']), None)
        require(fresh is not None and fresh['q'] is not None, 'LINE_CHANGED',
                f"{pick['market']} {pick['side']} {pick['line']} no longer shown before selecting it")
        run.observe('selection_preflight', fresh, False)
        self._terms(sport, fresh, requested, allowance, minimum)
        cell = await self.element_for(fresh)
        require(cell is not None, 'PRICE_CHANGED', 'Selection cell changed between the read and the click')
        # evidence: Bet365's own betslip API exchange for this click (request payload, status, response head)
        api = []

        async def record(resp):
            if 'BetsWebAPI' in resp.url:
                try:
                    body = (await resp.text())[:1500]
                except Exception as e:
                    body = f'<{type(e).__name__}>'
                api.append(dict(url=resp.url[:160], status=resp.status, post=(resp.request.post_data or '')[:600], body=body,
                                at_ms=run.ms()))
        handler = lambda r: asyncio.ensure_future(record(r))
        self.page.on('response', handler)
        run.put('click_at_ms', run.ms())
        try:
            await cell.click()
            state = await betslip.wait_items(self.page, 1)
            await self.page.wait_for_timeout(300)
        finally:
            self.page.remove_listener('response', handler)
        run.put('betslip_api', api)
        await run.capture(self.page, 'slip_selection')
        run.stage('VERIFY_SLIP')
        actual = self._verify_slip(run, state, sport, fresh, teams, requested, allowance, minimum)
        run.stage('ENTER_STAKE')
        state = await betslip.enter_stake(self.page, stake)
        await run.capture(self.page, 'slip_stake')
        run.stage('VERIFY_FINAL_STATE')
        actual = self._verify_slip(run, state, sport, actual, teams, requested, allowance, minimum)
        require(betslip.money(state.get('stake')) == betslip.money(stake), 'STAKE_REJECTED',
                f"Slip stake {state.get('stake')!r} is not {stake}")
        returned, expected = betslip.money(state.get('to_return')), betslip.money(stake) * float(actual['price'])
        require(returned is not None and abs(returned - expected) <= 0.011, 'STAKE_REJECTED',
                f"To Return {state.get('to_return')!r} does not agree with {stake} x {actual['price']}")
        pb = state.get('place_bet') or {}
        require(pb and (pb.get('text') or '').strip() == 'Place Bet' and not pb.get('disabled'), 'TARGET_NOT_FOUND',
                f"Place Bet not ready on the slip ({pb.get('text')!r}, disabled={pb.get('disabled')})")
        require(not state.get('messages'), 'PRICE_CHANGED', f"Betslip notice: {state.get('messages')}")
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
                                                 timestamp_ms=int(time.time() * 1000), **common))
        run.put('held', mode == 'hold')
        run.put('verification_detail', 'HELD: verified bet on the slip, stake + To Return verified, Place Bet located; NOT pressed, slip kept')
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

    def _verify_slip(self, run, state, sport, expected, teams, requested, allowance, minimum):
        """Exactly one bet on the slip, for this fixture, market, selection and line; its price judged by the tolerances."""
        run.put('betslip', state)
        require(not state.get('error'), 'BETSLIP_ERROR', f"Bet365 betslip error: {state.get('text')!r}")
        items = state.get('items') or []
        require(len(items) == 1, 'BETSLIP_NOT_SINGLE', f'Betslip holds {len(items)} selections')
        item = items[0]
        fixture = (item.get('fixture') or '').split(' v ')
        require(len(fixture) == 2 and self.d.same_slip_name(teams[0], fixture[0]) and self.d.same_slip_name(teams[1], fixture[1]),
                'WRONG_EVENT', f"Slip fixture {item.get('fixture')!r} is not '{teams[0]} v {teams[1]}'")
        labels = betslip.LABELS.get((sport, expected['market']), set())
        require((item.get('market') or '').strip().lower() in labels, 'WRONG_EVENT',
                f"Slip market {item.get('market')!r} is not {expected['market']} ({sorted(labels)})")
        title = (item.get('title') or '').strip()
        require(self.d.same_slip_name(expected['name'], title), 'SELECTION_CHANGED', f"Slip selection {title!r} is not {expected['name']!r}")
        line = expected['line']
        if expected['market'] != 'MONEYLINE':
            shown = self.d.norm_line(item.get('handicap') or '') if item.get('handicap') else None
            require(shown is not None, 'PRICE_CHANGED', f"Slip line unreadable ({item.get('handicap')!r})")
            line = shown.lstrip('+') if expected['market'] == 'TOTAL' else shown
        actual = dict(expected, line=line, price=item.get('price'), raw_price=item.get('price'))
        run.observe('slip', actual, True)
        self._terms(sport, actual, requested, allowance, minimum)
        return actual

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


def _same(a, b):
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return (a or '') == (b or '')
