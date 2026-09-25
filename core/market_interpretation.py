"""Market interpretation and alert normalisation for OddsNotifier alerts.

Turns one alert into what it actually says about a market, before anything downstream
sees it. Nothing here calculates a synthetic EV, interacts with a bookmaker or dispatches.

Layouts understood (all observed in genuine production messages):

* two-sided  - "Totals (L)" / "Spread (L)" with an optional "(P -> L)" line update, optional
  "(alt. line)", Pinnacle prices, Opening, "Bet365 (Market L)" prices and
  "EV: N%" or "EV: None (not equal lines)". Fixture/Bet365 rows may be links or plain text.
* side-labelled - "Opening: Away 2.030" / "Spread (-1.5): Away 1.724 ↓ [-11.7%]" with optional
  "Limit:" and "Fair Odds:" rows and a (possibly empty) "Bet365" section.

Quote ordering is used only where confirmed from production: basketball Totals
(first=OVER, second=UNDER) and basketball Spread (first=HOME at the displayed line,
second=AWAY at the inverse line), for every bookmaker group. A side-labelled row names its
side explicitly. Anything else is kept, but no side is assigned.

Separate dimensions are produced, per side:
  line_quality   FAVOURABLE | EQUAL | UNFAVOURABLE | UNKNOWN
  price_quality  FAVOURABLE | EQUAL | UNFAVOURABLE | NOT_COMPARABLE | UNKNOWN
  bet_quality    CLEAR_VALUE_SIGNAL | FAVOURABLE_LINE_SIGNAL | POTENTIAL_VALUE | NO_ADVANTAGE |
                 UNFAVOURABLE | INSUFFICIENT_INFORMATION
and for the alert: ev_status SUPPLIED_EQUAL_LINE | NOT_AVAILABLE_UNEQUAL_LINES | MISSING | INVALID.
See docs/MARKET_INTERPRETATION.md.
"""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re
from urllib.parse import parse_qs, urlsplit

from core.oddsnotifier_parser import HEADER, AlertFormatError, _source

VERSION = 'sharp-money-1'
NUMBER = r'[0-9]+(?:\.[0-9]+)?'
LINE = r'[+-]?[0-9]+(?:\.[0-9]+)?'
ARROW = r'[⬇⬆↓↑]️?'
TRANSITION = r'\s*(?:->|→)\s*'
ALT = r'\s*\(alt\. line\)'

PARSED, PARSED_PARTIAL, AMBIGUOUS, INVALID = 'PARSED', 'PARSED_PARTIAL', 'AMBIGUOUS', 'INVALID'
FAVOURABLE, EQUAL, UNFAVOURABLE, UNKNOWN, NOT_COMPARABLE = (
    'FAVOURABLE', 'EQUAL', 'UNFAVOURABLE', 'UNKNOWN', 'NOT_COMPARABLE')
EV_SUPPLIED, EV_UNEQUAL, EV_MISSING, EV_INVALID = (
    'SUPPLIED_EQUAL_LINE', 'NOT_AVAILABLE_UNEQUAL_LINES', 'MISSING', 'INVALID')
CLEAR_VALUE_SIGNAL, FAVOURABLE_LINE_SIGNAL, POTENTIAL_VALUE, NO_ADVANTAGE, INSUFFICIENT_INFORMATION = (
    'CLEAR_VALUE_SIGNAL', 'FAVOURABLE_LINE_SIGNAL', 'POTENTIAL_VALUE', 'NO_ADVANTAGE', 'INSUFFICIENT_INFORMATION')
# Signals the rules engine may act on (each still subject to every configured rule).
ACTIONABLE_SIGNALS = (CLEAR_VALUE_SIGNAL, FAVOURABLE_LINE_SIGNAL)
SHORTENED, DRIFTED = 'SHORTENED', 'DRIFTED'

TWO_SIDED_PROFILE = 'oddsnotifier_basketball_v1'
SIDE_LABELLED_PROFILE = 'oddsnotifier_side_labelled_v1'
VERIFIED_TWO_SIDED = {('basketball', 'TOTALS'): ('OVER', 'UNDER'), ('basketball', 'SPREAD'): ('HOME', 'AWAY')}
TWO_SIDED_CONFIRMATION = ('User confirmation 2026-09-23: production basketball Totals first=OVER, second=UNDER; '
                          'Spread first=HOME at displayed line, second=AWAY at inverse line (all groups)')
SIDE_LABELLED_CONFIRMATION = ('Side named in message text. Spread line attributed to the named side per the '
                              "user's expected interpretation of HJK Helsinki vs Brann (2026-09-23)")
MARKET_LABELS = {'Totals': 'TOTALS', 'Total': 'TOTALS', 'Spread': 'SPREAD', 'ML': 'ML', 'Moneyline': 'ML', '1X2': 'ML'}
URL_MARKETS = {'Totals': 'TOTALS', 'Spread': 'SPREAD', 'ML': 'ML'}
CURRENCIES = {'€': 'EUR', '$': 'USD', '£': 'GBP'}
SIDE_WORDS = {'Home': 'HOME', 'Away': 'AWAY', 'Draw': 'DRAW', 'Over': 'OVER', 'Under': 'UNDER'}


class Unrecognised(Exception):
    """Not one of these layouts; the caller may try the legacy grammar."""


class Contradiction(AlertFormatError):
    """Recognised layout with malformed or self-contradictory data -> INVALID."""


# ------------------------------------------------------------------ small helpers
def dec(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def invert(line):
    """Opposite side of a signed handicap, formatted like the production parser (+18.5)."""
    value = -dec(line)
    return '0' if value == 0 else format(value, '+f') if value > 0 else str(value)


def _price(value):
    if dec(value) is None or dec(value) <= 1:
        raise Contradiction(f'Decimal price must exceed 1: {value}')
    return value


def _sign_quality(value):
    return UNKNOWN if value is None else FAVOURABLE if value > 0 else UNFAVOURABLE if value < 0 else EQUAL


def _pct(new, old):
    new, old = dec(new), dec(old)
    if new is None or old is None or old == 0:
        return None
    return float(((new / old - 1) * 100).quantize(Decimal('0.01')))


def _direction(change):
    return None if change is None else 'UP' if change > 0 else 'DOWN' if change < 0 else 'UNCHANGED'


def _arrow_direction(marker):
    if not marker:
        return None
    return SHORTENED if marker[0] in '⬇↓' else DRIFTED


def strip_non_price_bold(text):
    """Remove **bold** wrappers that do not enclose a single decimal price.

    Telegram bolds headings, fixtures and EV rows; only a bolded Bet365 price carries
    meaning (the feed-highlighted price and supplied EV owner). Price bold is kept untouched.
    """
    return re.sub(r'\*\*(.+?)\*\*', lambda m: m[0] if re.fullmatch(NUMBER, m[1]) else m[1], text, flags=re.DOTALL)


# ------------------------------------------------------------------ comparisons (pure)
def compare_side(market, side, reference_line, reference_price, bet365_line, bet365_price):
    """Compare Bet365 with the reference for ONE side. Lines must already be expressed
    from that side's perspective (spread: the selected team's signed handicap).

    TOTALS OVER: lower line better. TOTALS UNDER: higher line better.
    SPREAD: higher signed handicap better. MONEYLINE/1X2: no line component.
    Prices are compared only when the lines are equal.
    """
    out = dict(reference_line=reference_line, bet365_line=bet365_line, reference_price=reference_price,
               bet365_price=bet365_price, line_applicable=market in ('TOTALS', 'SPREAD'),
               equal_line=None, line_difference=None, line_advantage=None, line_quality=UNKNOWN,
               price_difference=None, price_quality=UNKNOWN)
    if market in ('ML', 'MONEYLINE', '1X2'):
        out.update(equal_line=True, line_quality=EQUAL)
    elif dec(reference_line) is not None and dec(bet365_line) is not None:
        difference = dec(bet365_line) - dec(reference_line)
        if market == 'TOTALS':
            advantage = -difference if side == 'OVER' else difference if side == 'UNDER' else None
        elif market == 'SPREAD':
            advantage = difference if side in ('HOME', 'AWAY') else None
        else:
            advantage = None
        out.update(equal_line=difference == 0, line_difference=str(difference),
                   line_advantage=None if advantage is None else str(advantage),
                   line_quality=_sign_quality(advantage))
    if dec(reference_price) is None or dec(bet365_price) is None or out['equal_line'] is None:
        out['price_quality'] = UNKNOWN
    elif not out['equal_line']:
        out['price_quality'] = NOT_COMPARABLE
    else:
        difference = dec(bet365_price) - dec(reference_price)
        out.update(price_difference=str(difference), price_quality=_sign_quality(difference))
    return out


def bet_quality(comparison, *, verified, bet365_present, is_target, ev_status, supplied_ev):
    """Bet quality is deliberately NOT line quality.

    CLEAR_VALUE_SIGNAL: verified ordering, the highlighted Bet365 target, equal lines, Bet365
    price above the reference price and an OddsNotifier-supplied equal-line EV above 100 %.
    FAVOURABLE_LINE_SIGNAL: verified ordering, the highlighted Bet365 target, a quantified
    Bet365 line advantage for that exact side, and both prices present (not comparable across
    lines, so no EV is implied). Price acceptability and materiality are rules-engine checks.
    Otherwise a favourable line is only POTENTIAL_VALUE (non-actionable): no highlighted
    target, missing price, or an advantage that cannot be quantified.
    """
    if not verified or not bet365_present:
        return INSUFFICIENT_INFORMATION
    line, price = comparison['line_quality'], comparison['price_quality']
    if line == UNFAVOURABLE:
        return UNFAVOURABLE
    if line == FAVOURABLE:
        advantage = dec(comparison.get('line_advantage'))
        if is_target and price == NOT_COMPARABLE and advantage is not None and advantage > 0:
            return FAVOURABLE_LINE_SIGNAL
        return POTENTIAL_VALUE if price in (NOT_COMPARABLE, UNKNOWN, FAVOURABLE) else INSUFFICIENT_INFORMATION
    if line == EQUAL:
        if price == UNFAVOURABLE:
            return UNFAVOURABLE
        if price == EQUAL:
            return NO_ADVANTAGE
        if price == FAVOURABLE:
            ev = dec(supplied_ev)
            if is_target and ev_status == EV_SUPPLIED and ev is not None and ev > 100:
                return CLEAR_VALUE_SIGNAL
            return POTENTIAL_VALUE
    return INSUFFICIENT_INFORMATION


SHARP_SOURCE = 'pinnacle_opening_to_current'


def sharp_signal(market, opening_line, current_line, *, verified=False, perspective=None):
    """Select a candidate using ONLY Pinnacle lines on a verified fixed perspective.

    Bet365 offers, highlighted odds and latest price arrows cannot affect this result.
    Nonzero movement establishes direction, not profitability or sufficient magnitude.
    """
    opening, current = dec(opening_line), dec(current_line)
    out = dict(source=SHARP_SOURCE, side=None, opening_line=opening_line, current_line=current_line,
               change=None, magnitude=None, direction=None, status=AMBIGUOUS, reason=None)
    expected = {'SPREAD': 'HOME', 'TOTALS': 'TOTAL'}.get(market)
    if not verified or expected is None or perspective != expected:
        out['reason'] = 'Opening/current market or line perspective is unverified'
    elif opening is None or current is None:
        out['reason'] = 'Opening and current Pinnacle lines are required'
    else:
        change = current - opening
        out.update(change=str(change), magnitude=str(abs(change)), direction=_direction(change))
        if change == 0:
            out['reason'] = 'No opening-to-current line movement; price-only target policy is unproven'
        else:
            side = ('HOME' if change < 0 else 'AWAY') if market == 'SPREAD' else ('OVER' if change > 0 else 'UNDER')
            out.update(side=side, status='IDENTIFIED',
                       reason=f'Pinnacle opening {opening_line} -> current {current_line} ({expected}) selects {side}')
    return out


def spread_perspective_conflict(entries):
    """Cross-book favourite disagreement is an orientation warning, not proof of reversal.

    The feed contains sign contradictions. Neither a 10-point cutoff nor a smaller
    gap proves which book's perspective is correct. Keep the candidate as evidence,
    but withhold an executable target until the named-team mapping can be verified.
    """
    if not entries:
        return None
    home = entries[0]['comparison']
    ref, book = dec(home.get('reference_line')), dec(home.get('bet365_line'))
    if ref is None or book is None or ref * book >= 0:
        return None
    gap = abs(ref - book)
    return (f'Pinnacle ({ref}) and Bet365 ({book}) favour different teams by {gap} points: the Bet365 spread appears '
            f'to have an unresolved sign reference; do not assume a perspective correction')


def side_movement(*, opening_line, previous_line, current_line, opening_price, current_price,
                  marker=None, previous_price=None, supplied_percent=None):
    """Line and price movement kept as separate facts; causes are never inferred."""
    line_change = dec(current_line) - dec(previous_line) if dec(previous_line) is not None and \
        dec(current_line) is not None else None
    opening_change = dec(current_line) - dec(opening_line) if dec(opening_line) is not None and \
        dec(current_line) is not None else None
    direction = _arrow_direction(marker)
    if direction is None and supplied_percent is not None:
        direction = SHORTENED if supplied_percent < 0 else DRIFTED if supplied_percent > 0 else None
    return dict(opening_line=opening_line, previous_line=previous_line, current_line=current_line,
                line_change=None if line_change is None else str(line_change), line_direction=_direction(line_change),
                opening_line_change=None if opening_change is None else str(opening_change),
                opening_line_direction=_direction(opening_change),
                opening_line_equal=None if opening_change is None else opening_change == 0,
                opening_price=opening_price, current_price=current_price,
                previous_price_displayed=previous_price, price_direction=direction,
                price_direction_source='arrow' if marker else 'supplied_percent' if direction else None,
                price_change_percent=supplied_percent,
                price_change_basis='SUPPLIED_BY_ODDSNOTIFIER_BASE_UNSPECIFIED' if supplied_percent is not None else None,
                opening_to_current_price_change_percent=_pct(current_price, opening_price))


# ------------------------------------------------------------------ row splitting
_ANCHORS = re.compile('|'.join([
    r'(?<![\w-])(?=(?:Basketball|Football) - )',
    r'(?<![\d.])(?=\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}(?!\d))',
    r'(?<![\w(=/\[])(?=(?:Totals|Total|Spread|ML|Moneyline|1X2)\s*[(:])',
    r'(?<![\w/=])(?=Opening\b)', r'(?=\bLimit:)', r'(?=\bEV:)', r'(?=\bFair Odds:)',
    r'(?=\[Bet365\b)', r'(?<![\[\w./])(?=Bet365\b)', r'(?=\[[^\]\n]+ vs [^\]\n]+\]\()']))
_DECORATION = re.compile(r'[🟢🔵🟡🔴🟠🟣⚪💰🎯]️?')


def split_rows(text):
    """Deterministic rows for multi-line and whitespace-flattened pastes alike."""
    value = strip_non_price_bold(text.replace('\xa0', ' '))
    marker = re.search(r'([🟢🔵🟡🔴🟠🟣⚪])️?\s*Opening', value)
    value = _ANCHORS.sub('\n', _DECORATION.sub(' ', value))
    rows = [re.sub(r'[ \t]+', ' ', row).strip() for row in value.splitlines()]
    return [row for row in rows if row], marker[1] if marker else None


def _cells(row, count, *, allow_bold, group):
    cells = re.split(r'\s+-\s+', row)
    if len(cells) != count:
        raise Contradiction(f'{group}: expected exactly {count} prices')
    quotes, highlighted = [], []
    for index, cell in enumerate(cells):
        m = re.fullmatch(rf'(\*\*)?({NUMBER})(\*\*)?\s*({ARROW})?\s*(?:\(({NUMBER})\))?', cell)
        if not m or bool(m[1]) != bool(m[3]):
            raise Contradiction(f'{group}: invalid price cell {cell!r}')
        quote = dict(position=index + 1, price=_price(m[2]))
        if m[4]:
            quote.update(movement='DOWN' if m[4][0] in '⬇↓' else 'UP', movement_marker=m[4])
        if m[5]:
            quote['parenthetical_price'] = _price(m[5])
        if m[1]:
            highlighted.append(index)
        quotes.append(quote)
    if highlighted and not allow_bold:
        return quotes, highlighted, f'Highlighted price in {group} row; meaning unclear'
    return quotes, highlighted, None


def _is_price_row(row):
    return bool(re.match(rf'(\*\*)?{NUMBER}', row))


def _link(url, host_ok, what):
    try:
        parts = urlsplit(url)
        if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.port:
            raise ValueError
    except ValueError:
        raise Contradiction(f'Invalid {what} URL')
    if not host_ok(parts.hostname):
        raise Contradiction(f'Unsupported {what} URL host')
    return parts


# ------------------------------------------------------------------ header (shared)
def _header(rows):
    if len(rows) < 5 or rows[0] != HEADER:
        raise Unrecognised('header')
    sport = re.fullmatch(r'(Basketball|Football) - (.+)', rows[1])
    if not sport:
        raise Unrecognised('sport row')
    parts = sport[2].split(' - ', 1)
    country, competition = (parts[0], parts[1]) if len(parts) == 2 else (None, parts[0])
    linked = re.fullmatch(r'\[([^\]]+)\]\((https://[^\s)]+)\)', rows[2])
    if linked:
        fixture, fixture_url = linked[1], linked[2]
    elif 'http' in rows[2] or ' vs ' not in rows[2]:
        raise Unrecognised('fixture row')
    else:
        fixture, fixture_url = rows[2], None
    teams = re.split(r'\s+vs\s+', fixture)
    if len(teams) != 2 or not all(t.strip() for t in teams) or teams[0].casefold() == teams[1].casefold():
        raise Contradiction('Expected two distinct teams')
    if not re.fullmatch(r'\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}', rows[3]):
        raise Unrecognised('date row')
    try:
        scheduled = datetime.strptime(rows[3], '%d.%m.%Y %H:%M')
    except ValueError:
        raise Contradiction('Invalid event date')
    return dict(sport=sport[1].lower(), country=country, competition=competition,
                competition_full=f'{country} - {competition}' if country else competition,
                fixture=fixture, home=teams[0].strip(), away=teams[1].strip(), fixture_url=fixture_url,
                scheduled_at_local=scheduled.isoformat(timespec='minutes'), scheduled_timezone=None)


def _check_fixture_url(head, market):
    if not head['fixture_url']:
        return
    parts = _link(head['fixture_url'], lambda h: h == 'oddshub.io', 'fixture')
    if not parts.path.startswith(f"/{head['sport']}/"):
        raise Contradiction('Fixture URL sport conflicts with sport row')
    label = parse_qs(parts.query).get('market')
    if label and URL_MARKETS.get(label[0]) != market:
        raise Contradiction('Fixture URL market conflicts with market label')


# ------------------------------------------------------------------ two-sided layout
def _two_sided(rows, head, opening_marker):
    m = re.fullmatch(rf'(?P<label>Totals|Total|Spread) \((?P<a>{LINE})(?:{TRANSITION}(?P<b>{LINE}))?\)'
                     rf'(?P<alt>{ALT})?(?:\s+(?P<rest>[^:].*))?', rows[4])
    if not m:
        raise Unrecognised('two-sided market row')
    market = MARKET_LABELS[m['label']]
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
    bet365_present, bet365_line, bet365_alt, comparison_url, bet365, highlighted = False, None, False, None, [], []
    if cursor < len(rows) and re.match(r'\[?Bet365\b', rows[cursor]):
        row = rows[cursor]
        cursor += 1
        link = re.fullmatch(r'\[(Bet365[^\]]*)\]\((https://[^\s)]+)\)(.*)', row)
        if link:
            row, comparison_url = link[1] + link[3], link[2]
            _link(comparison_url, lambda h: h in ('bet365.com', 'www.bet365.com'), 'Bet365')
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
    lines = [current] + ([previous] if previous else []) + ([opening_line] if opening_line else []) + \
            ([bet365_line] if bet365_line else [])
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

    sides = VERIFIED_TWO_SIDED.get((head['sport'], market))
    names = {'HOME': head['home'], 'AWAY': head['away'], 'OVER': 'Over', 'UNDER': 'Under'}

    def side_line(line, index):
        if line is None:
            return None
        return line if market == 'TOTALS' or index == 0 else invert(line)

    highlighted_index = highlighted[0] if len(highlighted) == 1 and sides else None
    signal = sharp_signal(market, opening_line, current, verified=bool(sides),
                          perspective='TOTAL' if market == 'TOTALS' else 'HOME')
    target_index = sides.index(signal['side']) if sides and signal['side'] else None
    side_entries = []
    if sides:
        for groups in (pinnacle, opening or [], bet365):
            for quote in groups:
                quote['side'] = sides[quote['position'] - 1]
        for group, line in ((pinnacle, current), (opening or [], opening_line), (bet365, bet365_line)):
            for quote in group:
                quote['line'] = side_line(line, quote['position'] - 1)
        for index, side in enumerate(sides):
            ref, bq = pinnacle[index], bet365[index] if bet365 else {}
            cmp = compare_side(market, side, side_line(current, index), ref['price'],
                               side_line(bet365_line, index), bq.get('price'))
            is_target = index == target_index
            ev = supplied_ev if index == highlighted_index else None
            side_ev_status = ev_status if ev_status != EV_SUPPLIED or index == highlighted_index else 'SUPPLIED_FOR_OTHER_SIDE'
            quality = bet_quality(cmp, verified=True, bet365_present=bet365_present, is_target=is_target,
                                  ev_status=side_ev_status, supplied_ev=ev)
            side_entries.append(dict(
                side=side, selection_name=names[side], selection_line=side_line(bet365_line if bet365_present
                                                                                 else current, index),
                is_target=is_target,
                reference=dict(bookmaker='Pinnacle', line=cmp['reference_line'], odds=ref['price'], fair_odds=None),
                comparison=dict(cmp, bookmaker='Bet365', ev_status=side_ev_status, supplied_ev=ev),
                movement=side_movement(opening_line=side_line(opening_line, index),
                                       previous_line=side_line(previous, index), current_line=side_line(current, index),
                                       opening_price=(opening or [{}] * 2)[index].get('price'),
                                       current_price=ref['price'], marker=ref.get('movement_marker'),
                                       previous_price=ref.get('parenthetical_price')),
                line_quality=cmp['line_quality'], price_quality=cmp['price_quality'], bet_quality=quality))
    else:
        ambiguities.insert(0, f"UNSUPPORTED_MAPPING: {head['sport']} {market} two-sided quote ordering is not "
                              'production-verified; no side assigned')

    market_move = side_movement(opening_line=opening_line, previous_line=previous, current_line=current,
                                opening_price=None, current_price=None)
    market_move.update(line_perspective='TOTAL' if market == 'TOTALS' else 'HOME' if sides else 'AS_DISPLAYED')
    if sides and signal['side'] is None:
        ambiguities.append(signal['reason'])
    conflict = spread_perspective_conflict(side_entries) if market == 'SPREAD' and bet365_present else None
    if conflict:
        ambiguities.append(conflict)
    target = side_entries[target_index] if target_index is not None and not ambiguities else None
    if target is None:
        for entry in side_entries:
            entry['is_target'] = False
    highlighted_side = sides[highlighted_index] if highlighted_index is not None else None
    signal['highlight_agrees'] = highlighted_side == signal['side'] if highlighted_side and signal['side'] else None
    signal['recent_line_reversal'] = (dec(current) - dec(previous)) * dec(signal['change']) < 0 if previous and signal['change'] else False
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
        head, format_variant='two_sided', market=market, market_label=m['label'], displayed_line=current,
        comparison_url=comparison_url, opening_marker=opening_marker,
        pinnacle=dict(line=current, previous_line=previous, quotes=pinnacle),
        opening=dict(line=opening_line, quotes=opening or [], outcome_count_matches_market=opening is not None),
        comparison=comparison,
        alternate_line=dict(current=bool(m['alt']), opening=opening_alt, comparison=bet365_alt),
        quote_mapping=dict(profile=TWO_SIDED_PROFILE if sides else None, production_verified=bool(sides),
                           sides_by_position=list(sides) if sides else None,
                           group_sides_by_position={k: list(sides) if sides else None
                                                    for k in ('pinnacle', 'opening', 'comparison')},
                           confirmation_source=TWO_SIDED_CONFIRMATION if sides else None),
        displayed_ev_percent=selected_ev, feed_displayed_ev_percent=supplied_ev,
        highlighted_side=highlighted_side, sharp_signal=signal,
        sides=side_entries, market_movement=market_move, limit=None,
        target_side=target['side'] if target else None, target_line=target['selection_line'] if target else None,
        alert_price=target['comparison']['bet365_price'] if target else None,
        target_price_source=SHARP_SOURCE if target else None,
        implied_target=None,
        selection_side=target['side'] if target else None, selection_name=target['selection_name'] if target else None,
        selection_line=target['selection_line'] if target else None,
        reference=target['reference'] if target else dict(bookmaker='Pinnacle', line=current, odds=None, fair_odds=None,
                                                          line_perspective=market_move['line_perspective']),
        movement=target['movement'] if target else market_move,
        line_quality=target['line_quality'] if target else None,
        price_quality=target['price_quality'] if target else None,
        bet_quality=target['bet_quality'] if target else None)
    partial = []
    if not bet365_present:
        partial.append('Bet365 section absent; no comparable offer captured')
    if sides and target is None and len(highlighted) <= 1:
        partial.append('No executable sharp target; side-level comparisons retained')
    if bet365_present and ev_status == EV_UNEQUAL and target is None:
        partial.append('EV not available: unequal lines (evaluated directionally)')
    elif ev_status == EV_MISSING:
        partial.append('EV not supplied')
    return alert, ambiguities, partial


# ------------------------------------------------------------------ side-labelled layout
_SIDE = r'(?P<side>Home|Away|Draw|Over|Under)'


def _side_labelled(rows, head):
    found, ambiguities = {}, []

    def once(kind, value):
        if kind in found:
            raise Contradiction(f'Duplicate {kind} row')
        found[kind] = value

    for row in rows[4:]:
        if row.startswith('Limit:'):
            m = re.fullmatch(rf'Limit:\s*(?P<c1>[€$£])?\s*(?P<a>{NUMBER})(?:{TRANSITION}(?P<c2>[€$£])?\s*(?P<b>{NUMBER}))?'
                             r'(?:\s*\((?P<when>[^)]*)\))?', row)
            if not m:
                raise Contradiction('Unrecognised Limit row')
            once('limit', m)
        elif row.startswith('Opening'):
            m = re.fullmatch(rf'Opening(?: \((?P<line>{LINE})\))?:\s*{_SIDE}\s+(?P<price>{NUMBER})', row)
            if not m:
                raise Contradiction('Unrecognised Opening row')
            once('opening', m)
        elif re.match(r'(Spread|Totals|Total|ML|Moneyline|1X2)\b', row):
            m = re.fullmatch(rf'(?P<label>Spread|Totals|Total|ML|Moneyline|1X2)(?: \((?P<a>{LINE})(?:{TRANSITION}'
                             rf'(?P<b>{LINE}))?\))?(?P<alt>{ALT})?:\s*{_SIDE}\s+(?P<price>{NUMBER})\s*(?P<arrow>{ARROW})?'
                             rf'\s*(?:\[(?P<pct>[+-]?{NUMBER})%\])?', row)
            if not m:
                if re.fullmatch(rf'[^:]+:\s*{NUMBER}.*', row):
                    ambiguities.append('Selected side is not labelled on the market row')
                    once('market', None)
                    continue
                raise Contradiction('Unrecognised market row')
            once('market', m)
        elif row.startswith('Fair Odds:'):
            m = re.fullmatch(rf'Fair Odds:\s*(?P<price>{NUMBER})', row)
            if not m:
                raise Contradiction('Unrecognised Fair Odds row')
            once('fair', m)
        elif re.match(r'\[?Bet365\b', row):
            if not re.fullmatch(r'\[?Bet365\]?(?:\(https://[^\s)]+\))?', row):
                ambiguities.append('Bet365 section present in an unverified side-labelled layout; not interpreted')
            once('bet365', row)
        elif row.startswith('EV:'):
            once('ev', row[3:].strip())
        else:
            raise Contradiction(f'Unrecognised row: {row[:60]!r}')
    if 'market' not in found:
        raise Unrecognised('no market row')
    m = found['market']
    if m is None:
        return None, ambiguities, []
    market = MARKET_LABELS[m['label']]
    _check_fixture_url(head, market)
    side = SIDE_WORDS[m['side']]
    allowed = {'TOTALS': ('OVER', 'UNDER'), 'SPREAD': ('HOME', 'AWAY'),
               'ML': ('HOME', 'AWAY', 'DRAW') if head['sport'] == 'football' else ('HOME', 'AWAY')}[market]
    if side not in allowed:
        raise Contradiction(f'Side {side} is impossible for {market}')
    if (market == 'ML') != (m['a'] is None):
        raise Contradiction('Line presence conflicts with market')
    previous, current = (m['a'], m['b']) if m['b'] is not None else (None, m['a'])
    if market == 'TOTALS' and any(dec(v) < 0 for v in (previous, current) if v is not None):
        raise Contradiction('Total lines cannot be negative')
    price = _price(m['price'])
    percent = float(m['pct']) if m['pct'] is not None else None
    if m['arrow'] and percent is not None and percent != 0 and (_arrow_direction(m['arrow']) == SHORTENED) != (percent < 0):
        raise Contradiction('Price arrow conflicts with supplied percentage')
    o = found.get('opening')
    if o and SIDE_WORDS[o['side']] != side:
        raise Contradiction('Opening side conflicts with market side')
    opening_price = _price(o['price']) if o else None
    fair = _price(found['fair']['price']) if 'fair' in found else None
    limit = None
    if 'limit' in found:
        lm = found['limit']
        if lm['c1'] and lm['c2'] and lm['c1'] != lm['c2']:
            raise Contradiction('Limit currencies conflict')
        symbol = lm['c2'] or lm['c1']
        limit = dict(previous=lm['a'] if lm['b'] else None, current=lm['b'] or lm['a'],
                     currency=CURRENCIES.get(symbol), changed_at_text=lm['when'])
    ev_text = found.get('ev')
    if ev_text is not None and 'bet365' not in found:
        raise Contradiction('EV supplied without a Bet365 section')
    name = {'HOME': head['home'], 'AWAY': head['away'], 'DRAW': 'Draw', 'OVER': 'Over', 'UNDER': 'Under'}[side]
    cmp = compare_side(market, side, current, price, None, None)
    move = side_movement(opening_line=o['line'] if o else None, previous_line=previous, current_line=current,
                         opening_price=opening_price, current_price=price, marker=m['arrow'], supplied_percent=percent)
    entry = dict(side=side, selection_name=name, selection_line=current, is_target=False,
                 reference=dict(bookmaker='Pinnacle', line=current, odds=price, fair_odds=fair),
                 comparison=dict(cmp, bookmaker='Bet365', ev_status=EV_MISSING, supplied_ev=None),
                 movement=move, line_quality=UNKNOWN, price_quality=UNKNOWN,
                 bet_quality=INSUFFICIENT_INFORMATION)
    entry['comparison'].update(line_quality=UNKNOWN, price_quality=UNKNOWN)
    quote = dict(position=1, side=side, price=price, line=current)
    if m['arrow']:
        quote.update(movement='DOWN' if m['arrow'][0] in '⬇↓' else 'UP', movement_marker=m['arrow'])
    alert = dict(
        head, format_variant='side_labelled', market='1X2' if market == 'ML' and head['sport'] == 'football' else
        'MONEYLINE' if market == 'ML' else market, market_label=m['label'], displayed_line=current, comparison_url=None,
        opening_marker=None,
        pinnacle=dict(line=current, previous_line=previous, quotes=[quote]),
        opening=dict(line=o['line'] if o else None, quotes=[dict(position=1, side=side, price=opening_price,
                                                                   line=o['line'])] if o else [],
                     outcome_count_matches_market=None),
        comparison=dict(site='Bet365', line=None, quotes=[], bookmaker='Bet365', bet365_present=False,
                        bet365_line_displayed=None, reference_line_displayed=current, bet365_line=None, bet365_odds=None,
                        equal_line=None, line_difference=None, line_advantage=None, line_quality=UNKNOWN,
                        price_quality=UNKNOWN, ev_status=EV_MISSING, supplied_ev=None),
        alternate_line=dict(current=bool(m['alt']), opening=False, comparison=False),
        quote_mapping=dict(profile=SIDE_LABELLED_PROFILE, production_verified=True, labelled_sides=True,
                           sides_by_position=[side], group_sides_by_position=dict(pinnacle=[side], opening=[side] if o
                                                                                  else None, comparison=None),
                           confirmation_source=SIDE_LABELLED_CONFIRMATION),
        displayed_ev_percent=None, sides=[entry], limit=limit,
        market_movement=dict(move, line_perspective='SELECTED_SIDE'),
        target_side=None, target_line=None, alert_price=None, target_price_source=None,
        selection_side=side, selection_name=name, selection_line=current,
        reference=entry['reference'], movement=move, line_quality=UNKNOWN, price_quality=UNKNOWN,
        bet_quality=INSUFFICIENT_INFORMATION, fair_odds=fair)
    partial = ['Bet365 section absent; no comparable offer captured'] if 'bet365' in found and not ambiguities \
        else ['Bet365 section not present'] if 'bet365' not in found else []
    return alert, ambiguities, partial


# ------------------------------------------------------------------ entry point
def interpret(text, *, channel_id=None, message_id=None, source_timestamp=None):
    """Return dict(status, reason, parsed, profile) or None if the layout is not handled here.

    status: PARSED (complete, comparable, explicit target) | PARSED_PARTIAL (valid, but no
    target / no Bet365 / EV not available) | AMBIGUOUS | INVALID. Never raises for str input.
    """
    if not isinstance(text, str):
        return None
    rows, opening_marker = split_rows(text)
    try:
        head = _header(rows)
        if re.fullmatch(rf'(Totals|Total|Spread) \({LINE}(?:{TRANSITION}{LINE})?\)({ALT})?(\s+[^:].*)?', rows[4]):
            alert, ambiguities, partial = _two_sided(rows, head, opening_marker)
            profile = alert['quote_mapping']['profile']
        elif any(re.match(r'(Opening(?: \([^)]*\))?:|Limit:|(Spread|Totals|Total|ML|Moneyline|1X2)\b[^:]*:)', r)
                 for r in rows[4:]):
            alert, ambiguities, partial = _side_labelled(rows, head)
            profile = SIDE_LABELLED_PROFILE
        else:
            raise Unrecognised('market layout')
    except Unrecognised:
        return None
    except Contradiction as error:
        return dict(status=INVALID, reason=f'Malformed or contradictory alert: {error}', parsed=None, profile=None)
    if alert is None:
        return dict(status=AMBIGUOUS, reason='; '.join(ambiguities), parsed=None, profile=profile)
    observation_id, source_time = (_source(channel_id, message_id, source_timestamp) if source_timestamp
                                   else (None, None))
    unresolved = ['event_timezone_unspecified']
    if any('parenthetical_price' in q for q in alert['pinnacle']['quotes']):
        unresolved.append('parenthetical_price_meaning_unspecified')
    alert.update(schema_version=6, interpretation_version=VERSION, source='OddsNotifier', observation_id=observation_id,
                 telegram_channel_id=channel_id if source_timestamp else None,
                 telegram_message_id=message_id if source_timestamp else None, source_timestamp=source_time,
                 raw_text=text, sample_provenance='unspecified', market_label_source='label_and_fixture_url'
                 if alert.get('fixture_url') else 'standalone_label',
                 unresolved=unresolved + ambiguities + partial, interpretation_notes=ambiguities + partial)
    if ambiguities:
        status, reason = AMBIGUOUS, '; '.join(ambiguities)
    elif partial:
        status, reason = PARSED_PARTIAL, '; '.join(partial)
    elif alert.get('target_price_source') == SHARP_SOURCE:
        status, reason = PARSED, alert['sharp_signal']['reason'] + '; Bet365 evaluated for that same side only'
    else:
        status, reason = PARSED, ('Production-verified mapping, explicit Bet365 target, equal-line EV supplied'
                                  if alert['comparison']['ev_status'] == EV_SUPPLIED else
                                  'Production-verified mapping, explicit Bet365 target, unequal lines evaluated '
                                  'directionally (no EV calculated)')
    alert['interpretation_status'] = status
    return dict(status=status, reason=reason, parsed=alert, profile=profile)
