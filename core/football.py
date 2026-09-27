"""Football (soccer) interpretation of OddsNotifier Feed 1 alerts: 1X2, Asian-handicap "Spread" and "Totals".

Basketball behaviour is untouched: `core.market_interpretation.interpret` enters this module only for a football
header. Principle unchanged: the reference market (Pinnacle opening -> current) selects WHAT outcome we want; Bet365
is then read for that SAME outcome only. A better-looking Bet365 price on another outcome never switches the target.

Established from the real Feed 1 corpus (tests/fixtures/feed1_football/*.jsonl; 72 alerts 26-27 Sep 2026 covering every
layout variant seen) and Bet365 football event pages captured on the phone (evidence/football/pages, 27 Sep 2026):
  * OddsNotifier 1X2 rows are HOME - DRAW - AWAY (provider guide; corroborated by every alert: the unique opening-to-
    current shortener is always the bold Bet365 price's position, home 5 / away 2). The 1X2 Opening row carries HOME
    and AWAY only (the draw's opening price is not supplied), so the draw can never be the opening-to-current candidate
    unless a three-price opening row is present.
  * Spread rows are HOME - AWAY with the displayed line as the HOME handicap; Totals rows are OVER - UNDER.
  * Bet365 rows follow the same order. On the phone the Full Time Result columns read home team | Draw | away team,
    Asian Handicap columns read home team | away team, Goals Over/Under and Goal Line columns read Over | Under.
  * The bold Bet365 price is the owner of the displayed EV. It qualifies the SAME side only; it never selects.
  * Football lines rarely move between opening and current (25 of 28 Spread and 37 of 37 Totals alerts kept the line):
    at an equal line the unique net PRICE shortener is the sharp side. When the line moved, the main-line direction
    selects (HOME handicap down -> HOME, up -> AWAY; total up -> OVER, down -> UNDER) unless the current row is an
    alternate line (the main line is then unknown) or the price evidence contradicts it: both AMBIGUOUS.
Verdicts (alert['football']['verdict']): EXECUTABLE_HOME / EXECUTABLE_DRAW / EXECUTABLE_AWAY / EXECUTABLE_OVER /
EXECUTABLE_UNDER / NO_BET / AMBIGUOUS; INVALID is the interpretation status for malformed alerts.
See docs/FOOTBALL_STRATEGY_SPEC.md.
"""
import re
from urllib.parse import urlsplit

from core.market_interpretation import (
    NUMBER, LINE, ALT, TRANSITION, MARKET_LABELS, SHARP_SOURCE, AMBIGUOUS, ACTIONABLE_SIGNALS,
    EV_SUPPLIED, EV_UNEQUAL, EV_MISSING, EV_INVALID, dec, invert, Contradiction, Unrecognised,
    _cells, _check_fixture_url, _link, _is_price_row, _direction, compare_side, bet_quality, side_movement,
    spread_perspective_conflict)

VERSION = 'sharp-money-football-1'
PROFILE_1X2 = 'oddsnotifier_football_1x2_v1'
PROFILE_TWO_SIDED = 'oddsnotifier_football_two_sided_v1'
SIDES = {'1X2': ('HOME', 'DRAW', 'AWAY'), 'SPREAD': ('HOME', 'AWAY'), 'TOTALS': ('OVER', 'UNDER')}
CONFIRMATION = {
    '1X2': ('Feed 1 corpus 26-27 Sep 2026 (7 real 1X2 alerts): current row HOME-DRAW-AWAY, opening row HOME-AWAY, Bet365 row '
            'HOME-DRAW-AWAY; the bold Bet365 price always sat on the unique opening-to-current shortener; phone captures of '
            'Bet365 Full Time Result columns home | Draw | away (evidence/football/pages); docs/FOOTBALL_STRATEGY_SPEC.md'),
    'SPREAD': ('Feed 1 corpus 26-27 Sep 2026 (28 real Spread alerts): HOME-AWAY with the displayed line as the HOME handicap; '
               'phone capture of Bet365 Asian Handicap columns home team | away team with signed lines per team '
               '(evidence/football/pages/pg-vihiga-103021); docs/FOOTBALL_STRATEGY_SPEC.md'),
    'TOTALS': ('Feed 1 corpus 26-27 Sep 2026 (37 real Totals alerts): OVER-UNDER; phone captures of Bet365 Goals Over/Under and '
               'Goal Line columns Over | Under (evidence/football/pages); docs/FOOTBALL_STRATEGY_SPEC.md'),
}
EXECUTABLE = {'HOME': 'EXECUTABLE_HOME', 'DRAW': 'EXECUTABLE_DRAW', 'AWAY': 'EXECUTABLE_AWAY',
              'OVER': 'EXECUTABLE_OVER', 'UNDER': 'EXECUTABLE_UNDER'}
NO_BET, INVALID = 'NO_BET', 'INVALID'
MARKET_ROW = re.compile(rf'(?P<label>Totals|Total|Spread) \((?P<a>{LINE})(?:{TRANSITION}(?P<b>{LINE}))?\)(?P<alt>{ALT})?(?:\s+(?P<rest>[^:].*))?')
NAMES = {'HOME': 'home', 'AWAY': 'away'}


def in_play_link(url):
    """Bet365 in-play event links (#/IP/EV...) point at a live page: no scheduled kick-off, no pre-match identity."""
    return bool(url) and '/#/IP/' in url


def is_football_alert(rows, head):
    """The layouts this module understands: linked/labelled 1X2 and the two-sided Spread/Totals rows (either order)."""
    if head.get('sport') != 'football' or len(rows) < 6:
        return False
    if _is_1x2(rows, head):
        return True
    return any(MARKET_ROW.fullmatch(r) for r in rows[4:7])


def _is_1x2(rows, head):
    if rows[4] in ('ML', '1X2', 'Moneyline'):
        return True
    url = head.get('fixture_url')
    market = None
    if url:
        from urllib.parse import parse_qs
        market = (parse_qs(urlsplit(url).query).get('market') or [None])[0]
    return market == 'ML' and _is_price_row(rows[4]) or (market is None and _is_price_row(rows[4])
                                                          and len(re.split(r'\s+-\s+', rows[4])) == 3)


# ------------------------------------------------------------------ sharp signals (pure)
def _prices(quotes, sides):
    out = {}
    for index, q in enumerate(quotes):
        price = dec(q.get('price'))
        if price is None or price <= 1:
            raise ValueError('Pinnacle decimal odds must be finite and greater than one')
        out[sides[index]] = price
    return out


def sharp_signal_1x2(opening_quotes, current_quotes):
    """Unique net price shortener among the outcomes the Opening row supplies (HOME/AWAY; DRAW only with a 3-price opening)."""
    out = dict(source=SHARP_SOURCE, side=None, status=AMBIGUOUS, reason=None, basis='price', opening_line=None, current_line=None,
               change=None, magnitude=None, magnitude_units='decimal_odds', direction=None, opening_prices={}, current_prices={},
               changes_by_side={}, draw_opening_supplied=False, candidates=[])
    try:
        if not isinstance(current_quotes, list) or len(current_quotes) != 3:
            raise ValueError('Exactly three current Pinnacle outcomes (HOME, DRAW, AWAY) are required')
        if not isinstance(opening_quotes, list) or len(opening_quotes) not in (2, 3):
            raise ValueError('Opening Pinnacle prices for HOME and AWAY (optionally DRAW) are required')
        cur = _prices(current_quotes, SIDES['1X2'])
        opening_sides = SIDES['1X2'] if len(opening_quotes) == 3 else ('HOME', 'AWAY')
        op = _prices(opening_quotes, opening_sides)
        out['draw_opening_supplied'] = 'DRAW' in op
        out['candidates'] = list(opening_sides)
        changes = {s: cur[s] - op[s] for s in opening_sides}
        out.update(opening_prices={s: str(v) for s, v in op.items()}, current_prices={s: str(v) for s, v in cur.items()},
                   changes_by_side={s: str(v) for s, v in changes.items()})
        shorter = [s for s in opening_sides if changes[s] < 0]
        if len(shorter) != 1:
            raise ValueError('No opening-to-current price movement' if all(v == 0 for v in changes.values())
                             else 'No unique net shortener: both sides shortened or neither side shortened')
        side = shorter[0]
        others = ', '.join(f'{s} {op[s]} -> {cur[s]}' for s in opening_sides if s != side)
        out.update(side=side, status='IDENTIFIED', change=str(changes[side]), magnitude=str(-changes[side]), direction='SHORTENED',
                   opening_to_current_percent=str(100 * changes[side] / op[side]),
                   reason=f'Pinnacle {side} opening {op[side]} -> current {cur[side]} shortens; {others} does not shorten'
                          + ('' if out['draw_opening_supplied'] else '; draw opening not supplied, draw never a candidate'))
    except (ValueError, TypeError, AttributeError) as error:
        out['reason'] = str(error)
    return out


def sharp_signal_two_sided(market, opening_line, current_line, *, current_alt, opening_quotes, current_quotes):
    """Football Spread (HOME handicap) / Totals candidate from Pinnacle opening -> current.

    Equal lines: the unique net price shortener. Moved main line: HOME handicap down -> HOME, up -> AWAY; total up ->
    OVER, down -> UNDER, provided the current row is not an alternate line and the price evidence does not contradict.
    """
    sides = SIDES[market]
    out = dict(source=SHARP_SOURCE, side=None, status=AMBIGUOUS, reason=None, basis=None, opening_line=opening_line,
               current_line=current_line, change=None, magnitude=None, magnitude_units=None, direction=None,
               opening_prices={}, current_prices={}, changes_by_side={}, line_candidate=None, price_candidate=None)
    try:
        opening, current = dec(opening_line), dec(current_line)
        if opening is None or current is None:
            raise ValueError('Opening and current Pinnacle lines are required')
        if not isinstance(opening_quotes, list) or len(opening_quotes) != 2 or not isinstance(current_quotes, list) or len(current_quotes) != 2:
            raise ValueError('Opening and current Pinnacle price pairs are required')
        op, cur = _prices(opening_quotes, sides), _prices(current_quotes, sides)
        changes = {s: cur[s] - op[s] for s in sides}
        out.update(opening_prices={s: str(op[s]) for s in sides}, current_prices={s: str(cur[s]) for s in sides},
                   changes_by_side={s: str(changes[s]) for s in sides})
        shorter = [s for s in sides if changes[s] < 0]
        drifted = [s for s in sides if changes[s] > 0]
        price_candidate = shorter[0] if len(shorter) == 1 and len(drifted) <= 1 and (not drifted or drifted[0] != shorter[0]) else None
        out['price_candidate'] = price_candidate
        line_change = current - opening
        if line_change == 0:
            if price_candidate is None:
                raise ValueError('Line unchanged and no unique net price shortener (both sides shortened, both drifted or unchanged)')
            other = sides[1] if price_candidate == sides[0] else sides[0]
            out.update(side=price_candidate, status='IDENTIFIED', basis='price_same_line', change=str(changes[price_candidate]),
                       magnitude=str(-changes[price_candidate]), magnitude_units='decimal_odds', direction='SHORTENED',
                       reason=f'Pinnacle line {current_line} unchanged; {price_candidate} {op[price_candidate]} -> {cur[price_candidate]} '
                              f'shortens, {other} {op[other]} -> {cur[other]} does not')
            return out
        line_candidate = (('HOME' if line_change < 0 else 'AWAY') if market == 'SPREAD' else ('OVER' if line_change > 0 else 'UNDER'))
        out['line_candidate'] = line_candidate
        if current_alt:
            raise ValueError(f'Current row is an alternate line ({current_line} vs opening {opening_line}): the main-line movement '
                             'is not shown, so no side is selected')
        if price_candidate is not None and price_candidate != line_candidate:
            raise ValueError(f'Line movement {opening_line} -> {current_line} points to {line_candidate} but the prices shortened '
                             f'{price_candidate}: contradictory evidence')
        out.update(side=line_candidate, status='IDENTIFIED', basis='line_move', change=str(line_change), magnitude=str(abs(line_change)),
                   magnitude_units='goals', direction=_direction(line_change),
                   reason=f'Pinnacle main line {opening_line} -> {current_line} ({"HOME handicap" if market == "SPREAD" else "total"}) '
                          f'selects {line_candidate}' + (f'; prices agree ({price_candidate} shortened)' if price_candidate else ''))
    except (ValueError, TypeError, AttributeError) as error:
        out['reason'] = str(error)
    return out


def sharp_signal_for_alert(alert, *, verified=True):
    """Recompute the football signal from a stored alert (rules engine re-derivation; never trusts target_side)."""
    market = alert.get('market')
    opening = (alert.get('opening') or {})
    pinnacle = (alert.get('pinnacle') or {})
    if not verified:
        return dict(source=SHARP_SOURCE, side=None, status=AMBIGUOUS, reason='Football quote ordering is unverified', magnitude=None, basis=None)
    if market == '1X2':
        return sharp_signal_1x2(opening.get('quotes'), pinnacle.get('quotes'))
    if market in ('SPREAD', 'TOTALS'):
        alt = bool((alert.get('alternate_line') or {}).get('current'))
        return sharp_signal_two_sided(market, opening.get('line'), pinnacle.get('line'), current_alt=alt,
                                      opening_quotes=opening.get('quotes'), current_quotes=pinnacle.get('quotes'))
    return dict(source=SHARP_SOURCE, side=None, status=AMBIGUOUS, reason=f'Unsupported football market {market}', magnitude=None, basis=None)


# ------------------------------------------------------------------ verdict
def verdict_for(alert, ambiguities):
    """Strategy verdict for one interpreted football alert (before the rules engine's time/limit checks)."""
    if ambiguities:
        return AMBIGUOUS, '; '.join(ambiguities)
    football = alert.get('football') or {}
    if football.get('in_play_link'):
        return NO_BET, 'Bet365 link is an in-play page (#/IP/): no scheduled kick-off or pre-match identity to verify'
    target = alert.get('target_side')
    if not target:
        return AMBIGUOUS, (alert.get('sharp_signal') or {}).get('reason') or 'no sharp target'
    quality = alert.get('bet_quality')
    if quality in ACTIONABLE_SIGNALS and alert.get('alert_price'):
        return EXECUTABLE[target], f"{quality}: Bet365 {target} {alert.get('alert_price')} vs Pinnacle {(alert.get('reference') or {}).get('odds')}"
    comparison = alert.get('comparison') or {}
    return NO_BET, (f"{quality or 'no comparable offer'} for {target} (line {alert.get('line_quality')}, price {alert.get('price_quality')}, "
                    f"EV {comparison.get('ev_status')})")


# ------------------------------------------------------------------ parsing
def parse(rows, head, opening_marker):
    """(alert, ambiguities, partial) for a football alert; raises Unrecognised for other layouts, Contradiction for malformed data."""
    if head.get('sport') != 'football':
        raise Unrecognised('not football')
    if _is_1x2(rows, head):
        return _parse_1x2(rows, head, opening_marker)
    ordered = _market_first(rows)
    if ordered is None:
        raise Unrecognised('football market layout')
    return _parse_two_sided(ordered, head, opening_marker, reordered=ordered is not rows)


def _market_first(rows):
    """The two-sided layout with the market row first; the opening-first variant (Kenya, 27 Sep 2026) is reordered."""
    if MARKET_ROW.fullmatch(rows[4]):
        return rows
    if rows[4].startswith('Opening') and len(rows) > 6 and _is_price_row(rows[5]) and MARKET_ROW.fullmatch(rows[6]) \
            and len(rows) > 7 and _is_price_row(rows[7]):
        return rows[:4] + [rows[6], rows[7], rows[4], rows[5]] + rows[8:]
    return None


def _bet365_row(row):
    """('Bet365 ...' label text, url or None) for the linked and plain Bet365 row forms."""
    link = re.fullmatch(r'\[(Bet365[^\]]*)\]\((https://[^\s)]+)\)(.*)', row)
    if link:
        _link(link[2], lambda h: h in ('bet365.com', 'www.bet365.com'), 'Bet365')
        return link[1] + link[3], link[2]
    bare = re.fullmatch(r'(Bet365(?: \([^)]*\))?) \((https://[^\s()]+)\)', row)
    if bare:
        _link(bare[2], lambda h: h in ('bet365.com', 'www.bet365.com'), 'Bet365')
        return bare[1], bare[2]
    if re.match(r'Bet365\b', row):
        return row, None
    raise Contradiction('Unrecognised Bet365 row')


def _parse_1x2(rows, head, opening_marker):
    _check_fixture_url(head, 'ML')
    sides = SIDES['1X2']
    cursor = 4
    ambiguities = []
    if rows[cursor] in ('ML', '1X2', 'Moneyline'):
        cursor += 1

    def take(what):
        nonlocal cursor
        if cursor >= len(rows):
            raise Contradiction(f'Incomplete football 1X2 alert: {what} missing')
        row = rows[cursor]
        cursor += 1
        return row

    pinnacle, _, issue = _cells(take('current prices'), 3, allow_bold=False, group='Pinnacle')
    if issue:
        ambiguities.append(issue)
    if take('Opening') != 'Opening':
        raise Contradiction('1X2 requires an explicit Opening row')
    opening_row = take('opening prices')
    count = len(re.split(r'\s+-\s+', opening_row))
    if count not in (2, 3):
        raise Contradiction('Opening: expected the HOME and AWAY prices (optionally with the draw)')
    opening, _, issue = _cells(opening_row, count, allow_bold=False, group='Opening')
    if issue:
        ambiguities.append(issue)
    if any('movement' in q or 'parenthetical_price' in q for q in opening):
        raise Contradiction('Opening: unexpected arrow or bracketed price')
    opening_sides = sides if count == 3 else ('HOME', 'AWAY')
    label, comparison_url = _bet365_row(take('Bet365'))
    if label not in ('Bet365', 'Bet365 (ML)', 'Bet365 (1X2)'):
        raise Contradiction('Bet365 market conflicts with a 1X2 alert')
    book, highlights, _ = _cells(take('Bet365 prices'), 3, allow_bold=True, group='Bet365', allow_nonpaying=True)
    if any('movement' in q or 'parenthetical_price' in q for q in book):
        raise Contradiction('Bet365: unexpected arrow or bracketed price')
    supplied_ev, ev_status = None, EV_MISSING
    if cursor < len(rows):
        ev = re.fullmatch(rf'EV:\s*({NUMBER})%', take('EV'))
        if not ev:
            raise Contradiction('Invalid 1X2 EV; unequal-line EV is not applicable')
        supplied_ev, ev_status = ev[1], EV_SUPPLIED
    if cursor != len(rows):
        raise Contradiction(f'Unexpected content: {rows[cursor][:60]!r}')
    if len(highlights) > 1:
        ambiguities.append('More than one Bet365 price highlighted; EV owner is ambiguous')
    highlighted = sides[highlights[0]] if len(highlights) == 1 else None
    for index, q in enumerate(pinnacle):
        q.update(side=sides[index], line=None)
    for index, q in enumerate(opening):
        q.update(side=opening_sides[index], line=None)
    for index, q in enumerate(book):
        q.update(side=sides[index], line=None, executable_price=dec(q['price']) > 1)
    signal = sharp_signal_1x2(opening, pinnacle)
    if signal['side'] is None:
        ambiguities.append(signal['reason'])
    signal['highlight_agrees'] = highlighted == signal['side'] if highlighted and signal['side'] else None
    in_play = in_play_link(comparison_url)
    entries = []
    for index, side in enumerate(sides):
        cmp = compare_side('1X2', side, None, pinnacle[index]['price'], None, book[index]['price'])
        ev = supplied_ev if highlighted == side else None
        side_status = ev_status if highlighted == side or ev_status != EV_SUPPLIED else 'SUPPLIED_FOR_OTHER_SIDE' if highlighted else 'SUPPLIED_OWNER_UNKNOWN'
        target = side == signal['side'] and not ambiguities and not in_play
        quality = bet_quality(cmp, verified=True, bet365_present=True, is_target=target, ev_status=side_status, supplied_ev=ev)
        opening_price = next((q['price'] for q in opening if q['side'] == side), None)
        movement = side_movement(opening_line=None, previous_line=None, current_line=None, opening_price=opening_price,
                                 current_price=pinnacle[index]['price'], marker=pinnacle[index].get('movement_marker'),
                                 previous_price=pinnacle[index].get('parenthetical_price'))
        entries.append(dict(side=side, selection_name='Draw' if side == 'DRAW' else head[NAMES[side]], selection_line=None,
                            is_target=target, reference=dict(bookmaker='Pinnacle', line=None, odds=pinnacle[index]['price'], fair_odds=None),
                            comparison=dict(cmp, bookmaker='Bet365', ev_status=side_status, supplied_ev=ev), movement=movement,
                            line_quality=cmp['line_quality'], price_quality=cmp['price_quality'], bet_quality=quality))
    target = next((e for e in entries if e['is_target']), None)
    comparison = dict(site='Bet365', bookmaker='Bet365', line=None, quotes=book, bet365_present=True, bet365_line_displayed=None,
                      reference_line_displayed=None, bet365_line=None, bet365_odds=None, line_applicable=False, equal_line=True,
                      line_difference=None, line_advantage=None, ev_status=ev_status, supplied_ev=None, line_quality=None, price_quality=None)
    if target:
        comparison.update(target['comparison'], bet365_odds=target['comparison']['bet365_price'])
    alert = dict(head, format_variant='football_1x2', market='1X2', market_label='ML', displayed_line=None,
                 interpretation_version=VERSION, comparison_url=comparison_url, opening_marker=opening_marker,
                 pinnacle=dict(line=None, previous_line=None, quotes=pinnacle),
                 opening=dict(line=None, quotes=opening, outcome_count_matches_market=count == 3),
                 comparison=comparison, alternate_line=dict(current=False, opening=False, comparison=False),
                 quote_mapping=dict(profile=PROFILE_1X2, production_verified=True, sides_by_position=list(sides),
                                    group_sides_by_position=dict(pinnacle=list(sides), opening=list(opening_sides), comparison=list(sides)),
                                    confirmation_source=CONFIRMATION['1X2']),
                 displayed_ev_percent=target['comparison']['supplied_ev'] if target else None, feed_displayed_ev_percent=supplied_ev,
                 highlighted_side=highlighted, sharp_signal=signal, sides=entries,
                 market_movement=dict(line_perspective='NONE', price_perspective='HOME_DRAW_AWAY', changes_by_side=signal['changes_by_side']),
                 limit=None, target_side=target['side'] if target else None, target_line=None,
                 alert_price=target['comparison']['bet365_price'] if target else None,
                 target_price_source=SHARP_SOURCE if target else None, implied_target=None,
                 selection_side=target['side'] if target else None, selection_name=target['selection_name'] if target else None,
                 selection_line=None, reference=target['reference'] if target else None, movement=target['movement'] if target else None,
                 line_quality=target['line_quality'] if target else None, price_quality=target['price_quality'] if target else None,
                 bet_quality=target['bet_quality'] if target else None,
                 football=dict(profile=PROFILE_1X2, in_play_link=in_play, signal_basis=signal.get('basis'),
                               draw_opening_supplied=signal.get('draw_opening_supplied')))
    partial = []
    if in_play:
        partial.append('Bet365 link is an in-play page; pre-match identity cannot be verified, no executable target')
    elif target is None and not ambiguities:
        partial.append('No executable sharp target; side-level comparisons retained')
    if ev_status == EV_MISSING:
        partial.append('EV not supplied')
    verdict, why = verdict_for(alert, ambiguities)
    alert['football'].update(verdict=verdict, verdict_reason=why)
    return alert, ambiguities, partial


def _parse_two_sided(rows, head, opening_marker, *, reordered=False):
    m = MARKET_ROW.fullmatch(rows[4])
    market = MARKET_LABELS[m['label']]
    sides = SIDES[market]
    _check_fixture_url(head, market)
    previous, current = (m['a'], m['b']) if m['b'] is not None else (None, m['a'])
    ambiguities, cursor = [], 5

    def prices(inline):
        nonlocal cursor
        if inline:
            return inline
        if cursor < len(rows) and _is_price_row(rows[cursor]):
            cursor += 1
            return rows[cursor - 1]
        return None

    pinnacle_row = prices(m['rest'])
    if not pinnacle_row:
        raise Contradiction('Pinnacle prices missing')
    pinnacle, _, issue = _cells(pinnacle_row, 2, allow_bold=False, group='Pinnacle')
    if issue:
        ambiguities.append(issue)
    opening_line = opening = None
    opening_alt = False
    if cursor < len(rows) and rows[cursor].startswith('Opening'):
        o = re.fullmatch(rf'Opening(?: \((?P<l>{LINE})\))?(?P<alt>{ALT})?(?:\s+(?P<rest>.*))?', rows[cursor])
        if not o or o['l'] is None:
            raise Contradiction('Opening line missing for a line market')
        cursor += 1
        opening_line, opening_alt = o['l'], bool(o['alt'])
        opening_row = prices(o['rest'])
        if not opening_row:
            raise Contradiction('Opening prices missing')
        opening, _, issue = _cells(opening_row, 2, allow_bold=False, group='Opening')
        if issue:
            ambiguities.append(issue)
    else:
        # In-play alerts arrive without an Opening row (Las Palmas Atletico v Badajoz, 27 Sep 2026): a valid message with no
        # opening-to-current signal, so AMBIGUOUS / NO BET below, not INVALID.
        opening = []
    bet365_present, bet365_line, bet365_alt, comparison_url, bet365, highlighted = False, None, False, None, [], []
    if cursor < len(rows) and re.match(r'\[?Bet365\b', rows[cursor]):
        row, comparison_url = _bet365_row(rows[cursor])
        cursor += 1
        b = re.fullmatch(rf'Bet365(?: \((?P<m>Totals|Total|Spread) (?P<l>{LINE})\))?(?P<alt>{ALT})?(?:\s+(?P<rest>.*))?', row)
        if not b:
            raise Contradiction('Unrecognised Bet365 row')
        bet365_row = prices(b['rest'])
        if b['m'] is None and bet365_row:
            raise Contradiction('Bet365 prices without a Bet365 line for a line market')
        if b['m'] is not None:
            if MARKET_LABELS[b['m']] != market:
                raise Contradiction('Bet365 market conflicts with the alert market')
            if not bet365_row:
                raise Contradiction('Bet365 line without prices')
            bet365_present, bet365_line, bet365_alt = True, b['l'], bool(b['alt'])
            bet365, highlighted, _ = _cells(bet365_row, 2, allow_bold=True, group='Bet365')
    ev_text = None
    if cursor < len(rows) and rows[cursor].startswith('EV:'):
        ev_text = rows[cursor][3:].strip()
        cursor += 1
    if cursor != len(rows):
        raise Contradiction(f'Unexpected content: {rows[cursor][:60]!r}')
    lines = [current] + ([previous] if previous else []) + ([opening_line] if opening_line else []) + ([bet365_line] if bet365_line else [])
    if market == 'TOTALS' and any(dec(v) < 0 for v in lines):
        raise Contradiction('Total lines cannot be negative')
    equal_line = dec(bet365_line) == dec(current) if bet365_present else None
    supplied_ev, ev_status = None, EV_MISSING
    if ev_text is not None:
        number = re.fullmatch(rf'({NUMBER})%', ev_text)
        if number:
            if not bet365_present or not equal_line:
                raise Contradiction('EV supplied although Bet365 line is absent or differs from Pinnacle line')
            supplied_ev, ev_status = number[1], EV_SUPPLIED
        elif re.fullmatch(r'None \(not equal lines\)', ev_text):
            if not bet365_present:
                raise Contradiction('"Not equal lines" without a Bet365 line')
            if equal_line:
                if market == 'SPREAD':
                    ambiguities.append('Bet365 spread line equals Pinnacle as displayed but OddsNotifier reports '
                                       'unequal lines: spread sign reference cannot be normalised safely')
                else:
                    raise Contradiction('Equal total lines but OddsNotifier reports unequal lines')
            ev_status = EV_UNEQUAL
        else:
            ev_status = EV_INVALID
            ambiguities.append(f'Unrecognised EV field: {ev_text[:40]!r}')
    if len(highlighted) > 1:
        ambiguities.append('More than one Bet365 price highlighted; meaning unclear')
    names = {'HOME': head['home'], 'AWAY': head['away'], 'OVER': 'Over', 'UNDER': 'Under'}

    def side_line(line, index):
        if line is None:
            return None
        return line if market == 'TOTALS' or index == 0 else invert(line)

    highlighted_index = highlighted[0] if len(highlighted) == 1 else None
    signal = sharp_signal_two_sided(market, opening_line, current, current_alt=bool(m['alt']), opening_quotes=opening, current_quotes=pinnacle)
    in_play = in_play_link(comparison_url)
    target_index = sides.index(signal['side']) if signal['side'] else None
    for groups in (pinnacle, opening, bet365):
        for quote in groups:
            quote['side'] = sides[quote['position'] - 1]
    for group, line in ((pinnacle, current), (opening, opening_line), (bet365, bet365_line)):
        for quote in group:
            quote['line'] = side_line(line, quote['position'] - 1)
    side_entries = []
    for index, side in enumerate(sides):
        ref, bq = pinnacle[index], bet365[index] if bet365 else {}
        cmp = compare_side(market, side, side_line(current, index), ref['price'], side_line(bet365_line, index), bq.get('price'))
        is_target = index == target_index and not in_play
        ev = supplied_ev if index == highlighted_index else None
        side_ev_status = ev_status if ev_status != EV_SUPPLIED or index == highlighted_index else \
            'SUPPLIED_FOR_OTHER_SIDE' if highlighted_index is not None else 'SUPPLIED_OWNER_UNKNOWN'
        quality = bet_quality(cmp, verified=True, bet365_present=bet365_present, is_target=is_target, ev_status=side_ev_status, supplied_ev=ev)
        if quality == 'FAVOURABLE_LINE_SIGNAL':
            # Football lines move in quarter/half goals and prices change steeply with them: a different Bet365 goal line is
            # a different bet, not a measurable advantage (Bet365 "Totals 2.5" against Pinnacle 3.75 at 1.44 vs 1.909).
            # Without a same-line EV the offer is retained as POTENTIAL_VALUE (non-actionable): NO BET.
            quality = 'POTENTIAL_VALUE'
        side_entries.append(dict(
            side=side, selection_name=names[side], selection_line=side_line(bet365_line if bet365_present else current, index),
            is_target=is_target,
            reference=dict(bookmaker='Pinnacle', line=cmp['reference_line'], odds=ref['price'], fair_odds=None),
            comparison=dict(cmp, bookmaker='Bet365', ev_status=side_ev_status, supplied_ev=ev),
            movement=side_movement(opening_line=side_line(opening_line, index), previous_line=side_line(previous, index),
                                   current_line=side_line(current, index), opening_price=(opening or [{}, {}])[index].get('price'),
                                   current_price=ref['price'], marker=ref.get('movement_marker'), previous_price=ref.get('parenthetical_price')),
            line_quality=cmp['line_quality'], price_quality=cmp['price_quality'], bet_quality=quality))
    market_move = side_movement(opening_line=opening_line, previous_line=previous, current_line=current, opening_price=None, current_price=None)
    market_move.update(line_perspective='TOTAL' if market == 'TOTALS' else 'HOME')
    if signal['side'] is None:
        ambiguities.append(signal['reason'])
    conflict = spread_perspective_conflict(side_entries) if market == 'SPREAD' and bet365_present else None
    if conflict:
        ambiguities.append(conflict)
    target = side_entries[target_index] if target_index is not None and not ambiguities and not in_play else None
    if target is None:
        for entry in side_entries:
            entry['is_target'] = False
    highlighted_side = sides[highlighted_index] if highlighted_index is not None else None
    signal['highlight_agrees'] = highlighted_side == signal['side'] if highlighted_side and signal['side'] else None
    signal['recent_line_reversal'] = (dec(current) - dec(previous)) * dec(signal['change']) < 0 \
        if previous and signal.get('change') and signal.get('basis') == 'line_move' else False
    selected_ev = target['comparison']['supplied_ev'] if target else None
    raw_difference = str(dec(bet365_line) - dec(current)) if bet365_present else None
    comparison = dict(site='Bet365', line=bet365_line, quotes=bet365, bookmaker='Bet365', bet365_present=bet365_present,
                      bet365_line_displayed=bet365_line, reference_line_displayed=current,
                      bet365_line=target['comparison']['bet365_line'] if target else bet365_line,
                      bet365_odds=target['comparison']['bet365_price'] if target else None,
                      equal_line=equal_line, line_difference=raw_difference,
                      line_advantage=target['comparison']['line_advantage'] if target else None,
                      line_quality=target['line_quality'] if target else None,
                      price_quality=target['price_quality'] if target else None,
                      ev_status=target['comparison']['ev_status'] if target else ev_status, supplied_ev=selected_ev)
    alert = dict(
        head, format_variant='two_sided' + ('_opening_first' if reordered else ''), market=market, market_label=m['label'],
        displayed_line=current, interpretation_version=VERSION, comparison_url=comparison_url, opening_marker=opening_marker,
        pinnacle=dict(line=current, previous_line=previous, quotes=pinnacle),
        opening=dict(line=opening_line, quotes=opening, outcome_count_matches_market=bool(opening)),
        comparison=comparison,
        alternate_line=dict(current=bool(m['alt']), opening=opening_alt, comparison=bet365_alt),
        quote_mapping=dict(profile=PROFILE_TWO_SIDED, production_verified=True, sides_by_position=list(sides),
                           group_sides_by_position={k: list(sides) for k in ('pinnacle', 'opening', 'comparison')},
                           confirmation_source=CONFIRMATION[market]),
        displayed_ev_percent=selected_ev, feed_displayed_ev_percent=supplied_ev,
        highlighted_side=highlighted_side, sharp_signal=signal,
        sides=side_entries, market_movement=market_move, limit=None,
        target_side=target['side'] if target else None, target_line=target['selection_line'] if target else None,
        alert_price=target['comparison']['bet365_price'] if target else None,
        target_price_source=SHARP_SOURCE if target else None, implied_target=None,
        selection_side=target['side'] if target else None, selection_name=target['selection_name'] if target else None,
        selection_line=target['selection_line'] if target else None,
        reference=target['reference'] if target else dict(bookmaker='Pinnacle', line=current, odds=None, fair_odds=None,
                                                          line_perspective=market_move['line_perspective']),
        movement=target['movement'] if target else market_move,
        line_quality=target['line_quality'] if target else None,
        price_quality=target['price_quality'] if target else None,
        bet_quality=target['bet_quality'] if target else None,
        football=dict(profile=PROFILE_TWO_SIDED, in_play_link=in_play, signal_basis=signal.get('basis'),
                      line_candidate=signal.get('line_candidate'), price_candidate=signal.get('price_candidate')))
    partial = []
    if in_play:
        partial.append('Bet365 link is an in-play page; pre-match identity cannot be verified, no executable target')
    if not bet365_present:
        partial.append('Bet365 section absent; no comparable offer captured')
    if target is None and not ambiguities and not in_play and len(highlighted) <= 1:
        partial.append('No executable sharp target; side-level comparisons retained')
    if bet365_present and ev_status == EV_UNEQUAL and target is None:
        partial.append('EV not available: unequal lines (evaluated directionally)')
    elif ev_status == EV_MISSING:
        partial.append('EV not supplied')
    verdict, why = verdict_for(alert, ambiguities)
    alert['football'].update(verdict=verdict, verdict_reason=why)
    return alert, ambiguities, partial
