"""Two-outcome basketball ML: opening/current Pinnacle selects; same-side Bet365 qualifies.

Profile established from the stored linked basketball feed and the provider's
HOME/[DRAW]/AWAY convention; see docs/MONEYLINE_AUDIT.md. No three-way inference,
de-vig model, recent-arrow target or opposite-highlight substitution is permitted.
"""
import re
from core.market_interpretation import (
    NUMBER, SHARP_SOURCE, AMBIGUOUS, EV_SUPPLIED, EV_MISSING, dec,
    Contradiction, _cells, _check_fixture_url, _link, compare_side, bet_quality, side_movement,
)

VERSION = 'sharp-money-ml-1'
PROFILE = 'oddsnotifier_basketball_moneyline_v1'
SIDES = ('HOME', 'AWAY')
CONFIRMATION = ('Provider ML HOME/[DRAW]/AWAY convention, restricted to audited two-outcome basketball ML; '
                '318 stored alerts / 62 fixtures, 2026-09-26; docs/MONEYLINE_AUDIT.md')


def sharp_signal(opening, current, *, verified=False):
    """Require one net shortener and a nonshortening opponent, with both pairs mapped.

    This avoids choosing a side from simultaneous margin changes. A zero/ambiguous
    move remains visible but supplies no executable candidate. No minimum drop is added.
    """
    out = dict(source=SHARP_SOURCE, side=None, status=AMBIGUOUS, reason=None,
               opening_prices={}, current_prices={}, changes_by_side={}, magnitude=None,
               magnitude_units='decimal_odds', direction=None)
    def pair(quotes):
        if not isinstance(quotes, list) or len(quotes) != 2:
            raise ValueError('Exactly two Pinnacle opening and current outcomes are required')
        result = {}
        for index, q in enumerate(quotes):
            if q.get('side') != SIDES[index] or q.get('position') != index+1:
                raise ValueError('Pinnacle HOME/AWAY ordering is missing, duplicated or inconsistent')
            price = dec(q.get('price'))
            if price is None or price <= 1:
                raise ValueError('Pinnacle decimal odds must be finite and greater than one')
            result[SIDES[index]] = price
        return result
    try:
        if not verified:
            raise ValueError('Moneyline quote ordering is unverified')
        op, cur = pair(opening), pair(current)
        changes = {side: cur[side]-op[side] for side in SIDES}
        out.update(opening_prices={s:str(op[s]) for s in SIDES}, current_prices={s:str(cur[s]) for s in SIDES},
                   changes_by_side={s:str(changes[s]) for s in SIDES})
        shorter = [s for s in SIDES if changes[s] < 0]
        if len(shorter) != 1:
            raise ValueError('No opening-to-current price movement' if all(v == 0 for v in changes.values())
                             else 'No unique net shortener: both sides shortened or neither side shortened')
        side = shorter[0]
        other = 'AWAY' if side == 'HOME' else 'HOME'
        out.update(side=side, status='IDENTIFIED', magnitude=str(-changes[side]), direction='SHORTENED',
                   opening_role='FAVOURITE' if op[side] < op[other] else 'UNDERDOG' if op[side] > op[other] else 'EVEN',
                   current_role='FAVOURITE' if cur[side] < cur[other] else 'UNDERDOG' if cur[side] > cur[other] else 'EVEN',
                   opening_to_current_percent=str(100 * changes[side] / op[side]),
                   reason=f'Pinnacle {side} opening {op[side]} -> current {cur[side]} shortens; '
                          f'{other} {op[other]} -> {cur[other]} does not shorten')
    except (ValueError, TypeError, AttributeError) as error:
        out['reason'] = str(error)
    return out


def parse(rows, head, opening_marker):
    """Parse the complete stored linked profile, or its explicit ML-label equivalent."""
    _check_fixture_url(head, 'ML')
    if head['sport'] != 'basketball':
        raise Contradiction('Two-outcome ML profile requires basketball')
    cursor = 4
    if rows[cursor] in ('ML', 'Moneyline'):
        cursor += 1
    ambiguities = []

    def take():
        nonlocal cursor
        if cursor >= len(rows):
            raise Contradiction('Incomplete basketball MONEYLINE alert')
        row = rows[cursor]; cursor += 1
        return row

    def pair(group, bold=False):
        quotes, highlights, issue = _cells(take(), 2, allow_bold=bold, group=group, allow_nonpaying=group=='Bet365')
        if issue: ambiguities.append(issue)
        if group != 'Pinnacle' and any('movement' in q or 'parenthetical_price' in q for q in quotes):
            raise Contradiction(f'{group}: unexpected arrow or bracketed price')
        for index, q in enumerate(quotes):
            q.update(side=SIDES[index], line=None)
            if group == 'Bet365': q['executable_price'] = dec(q['price']) > 1
        return quotes, highlights

    pinnacle, _ = pair('Pinnacle')
    if take() != 'Opening':
        raise Contradiction('MONEYLINE requires an explicit Opening price pair without a handicap')
    opening, _ = pair('Opening')
    book_row = take()
    link = re.fullmatch(r'\[(Bet365(?: \(ML\))?)\]\((https://[^\s)]+)\)', book_row)
    comparison_url = link[2] if link else None
    if link:
        _link(comparison_url, lambda h: h in ('bet365.com','www.bet365.com'), 'Bet365')
    elif book_row not in ('Bet365', 'Bet365 (ML)'):
        raise Contradiction('MONEYLINE requires the Bet365 ML price pair')
    book, highlights = pair('Bet365', bold=True)
    supplied_ev, ev_status = None, EV_MISSING
    if cursor < len(rows):
        ev = re.fullmatch(rf'EV:\s*({NUMBER})%', take())
        if not ev:
            raise Contradiction('Invalid MONEYLINE EV; unequal-line EV is not applicable')
        supplied_ev, ev_status = ev[1], EV_SUPPLIED
    if cursor != len(rows):
        raise Contradiction('Unexpected content after MONEYLINE EV')
    if len(highlights) > 1:
        ambiguities.append('More than one Bet365 price highlighted; EV owner is ambiguous')
    highlighted = SIDES[highlights[0]] if len(highlights) == 1 else None
    signal = sharp_signal(opening, pinnacle, verified=True)
    if signal['side'] is None:
        ambiguities.append(signal['reason'])
    signal['highlight_agrees'] = highlighted == signal['side'] if highlighted and signal['side'] else None
    entries = []
    for index, side in enumerate(SIDES):
        cmp = compare_side('MONEYLINE', side, None, pinnacle[index]['price'], None, book[index]['price'])
        ev = supplied_ev if highlighted == side else None
        side_status = ev_status if highlighted == side or ev_status != EV_SUPPLIED else 'SUPPLIED_FOR_OTHER_SIDE' if highlighted else 'SUPPLIED_OWNER_UNKNOWN'
        target = side == signal['side'] and not ambiguities
        quality = bet_quality(cmp, verified=True, bet365_present=True, is_target=target, ev_status=side_status, supplied_ev=ev)
        movement = side_movement(opening_line=None,previous_line=None,current_line=None,
                                 opening_price=opening[index]['price'],current_price=pinnacle[index]['price'],
                                 marker=pinnacle[index].get('movement_marker'),previous_price=pinnacle[index].get('parenthetical_price'))
        entries.append(dict(side=side, selection_name=head['home' if side=='HOME' else 'away'], selection_line=None,
                            is_target=target, reference=dict(bookmaker='Pinnacle',line=None,odds=pinnacle[index]['price'],fair_odds=None),
                            comparison=dict(cmp,bookmaker='Bet365',ev_status=side_status,supplied_ev=ev),movement=movement,
                            line_quality=cmp['line_quality'],price_quality=cmp['price_quality'],bet_quality=quality))
    target = next((e for e in entries if e['is_target']), None)
    comparison = dict(site='Bet365',bookmaker='Bet365',line=None,quotes=book,bet365_present=True,
                      bet365_line_displayed=None,reference_line_displayed=None,bet365_line=None,bet365_odds=None,
                      line_applicable=False,equal_line=True,line_difference=None,line_advantage=None,
                      ev_status=ev_status,supplied_ev=None,line_quality=None,price_quality=None)
    if target:
        comparison.update(target['comparison'],bet365_odds=target['comparison']['bet365_price'])
    alert = dict(head,format_variant='basketball_moneyline',market='MONEYLINE',market_label='ML',displayed_line=None,
                 interpretation_version=VERSION,comparison_url=comparison_url,opening_marker=opening_marker,
                 pinnacle=dict(line=None,previous_line=None,quotes=pinnacle),
                 opening=dict(line=None,quotes=opening,outcome_count_matches_market=True),comparison=comparison,
                 alternate_line=dict(current=False,opening=False,comparison=False),
                 quote_mapping=dict(profile=PROFILE,production_verified=True,sides_by_position=list(SIDES),
                                    group_sides_by_position={g:list(SIDES) for g in ('pinnacle','opening','comparison')},
                                    confirmation_source=CONFIRMATION),
                 displayed_ev_percent=target['comparison']['supplied_ev'] if target else None,
                 feed_displayed_ev_percent=supplied_ev,highlighted_side=highlighted,sharp_signal=signal,sides=entries,
                 market_movement=dict(line_perspective='NONE',price_perspective='HOME_AWAY',changes_by_side=signal['changes_by_side']),
                 limit=None,target_side=target['side'] if target else None,target_line=None,
                 alert_price=target['comparison']['bet365_price'] if target else None,
                 target_price_source=SHARP_SOURCE if target else None,implied_target=None,
                 selection_side=target['side'] if target else None,selection_name=target['selection_name'] if target else None,
                 selection_line=None,reference=target['reference'] if target else None,movement=target['movement'] if target else None,
                 line_quality=target['line_quality'] if target else None,price_quality=target['price_quality'] if target else None,
                 bet_quality=target['bet_quality'] if target else None)
    return alert, ambiguities, []
