"""Match Bet365 "My Bets" OCR text to a pipeline instruction. Pure functions, no I/O.

The phone returns every OCR line it saw on the My Bets view (several scrolled frames).
A bet is matched only when the fixture, the selection (side + line for spread/totals)
and the stake all appear inside one bet-card-sized window of consecutive lines. Odds are
compared in decimal or fractional form. Anything weaker is NOT a match: reconciliation
must never claim a bet exists (or does not) on partial evidence.

Calibrated on real My Bets screens (shadow capture 2026-09-24, tests/fixtures/
mybets_real_20260924.json):
* each bet is a card that starts with a header such as "£0.10 Single" or "£300.00 Bet Builder";
* only the newest card is expanded; older ones collapse to "£0.10 Single Portugal";
* the fixture appears as two lines next to the kick-off ("Austria Thu 24 Sep" / "Israel 19:45");
* OCR mangles amounts ("£O.1 0"), so money is normalised first;
* settled cards say "£514.29 Returned" or "... Lost".
A collapsed card that could be ours is INCONCLUSIVE, never "not found". The view must be
confirmed from the address bar (#/MB/U unsettled, #/MB/S settled) before absence counts.
"""
from decimal import Decimal, InvalidOperation
import re

WINDOW_BEFORE, WINDOW_AFTER = 6, 10
SETTLED_WORDS = (('cashed out', 'CASHED_OUT'), ('cash out', 'CASHED_OUT'), ('void', 'VOID'), ('won', 'WON'),
                 ('lost', 'LOST'), ('lose', 'LOST'), ('returned', 'RETURNED'))
REFERENCE = re.compile(r'\b(?:bet\s*ref(?:erence)?\.?:?\s*)([A-Z0-9]{6,20})\b', re.IGNORECASE)
MONEY = r'[£€$]?\s?(\d+(?:[.,]\d{1,2})?)'


def _money_fix(text):
    """'£O.1 0' -> '£0.10 ': OCR letter O and stray spaces inside amounts."""
    return re.sub(r'£\s*([0-9Oo][0-9Oo.,\s]{0,9})',
                  lambda m: '£' + m.group(1).replace(' ', '').replace('O', '0').replace('o', '0').strip() + ' ', text)


def _norm(text):
    text = _money_fix(str(text))
    return re.sub(r'\s+', ' ', re.sub(r'[^0-9a-z+\-./£# ]', ' ', text.lower())).strip()


CARD_HEADER = re.compile(r'^£\d+(?:\.\d{1,2})?\s+(single|double|treble|bet builder|accumulator|trixie|yankee|patent|lucky|\d+ fold)')
VIEW_MARKERS = {'OPEN': '/mb/u', 'SETTLED': '/mb/s'}


def _tokens(name):
    """Significant words of a team name ('BC Beroe (W)' -> ['beroe'])."""
    stop = {'bc', 'fc', 'kk', 'bk', 'cd', 'ca', 'sk', 'the', 'w', 'u', 'club', 'basket', 'basketball', 'and', 'de', 'vs', 'v'}
    return [t for t in re.findall(r'[a-z0-9]+', str(name).lower()) if len(t) > 2 and t not in stop]


def plain(value):
    """Decimal line as text without exponent or trailing zeros: 170 -> '170', 190.50 -> '190.5'."""
    text = format(Decimal(str(value)), 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def team_present(blob, name, other=None):
    """At least half of the team's words, including one that distinguishes it from the opponent
    ('SE Melbourne Phoenix' vs 'Melbourne United' needs 'phoenix', not just 'melbourne')."""
    if '|' in blob:
        return any(team_present(part, name, other) for part in blob.split('|'))
    def protected(value):
        text = re.sub(r'\bu[ -](\d{2})\b', r'u\1', str(value).lower())
        parts = set(re.findall(r'\b(?:w|women|womens|ladies|u\d{2}|ii|iii|b|reserves?|academy|youth|juniors?)\b', text))
        return {'women' if p in ('w','women','womens','ladies') else 'reserve' if p in ('reserve','reserves') else p for p in parts}
    if protected(blob) != protected(name):
        return False
    tokens = _tokens(name)
    if not tokens:
        return False
    present = {t for t in tokens if re.search(rf'\b{re.escape(t)}\b', blob)}
    distinct = set(tokens) - set(_tokens(other)) if other else set(tokens)
    if distinct and not (present & distinct):
        return False
    return len(present) >= max(1, (len(tokens) + 1) // 2)


def decimal_from_display(value):
    """'1.83' -> 1.83, '5/6' -> 1.8333; None if not odds-like."""
    value = value.strip()
    try:
        if '/' in value:
            num, den = value.split('/', 1)
            return Decimal(1) + Decimal(int(num)) / Decimal(int(den))
        return Decimal(value)
    except (ValueError, InvalidOperation, ZeroDivisionError):
        return None


def odds_present(blob, odds):
    target = Decimal(str(odds)) if odds else None
    if target is None:
        return False
    for token in re.findall(r'\b\d+/\d+\b|\b\d+\.\d{2,3}\b', blob):
        value = decimal_from_display(token)
        if value is not None and abs(value - target) <= Decimal('0.02'):
            return True
    return False


def stake_present(blob, stake):
    target = Decimal(str(stake))
    for match in re.finditer(r'(?:stake|£|€|\$)\s?(\d+(?:[.,]\d{1,2})?)', blob):
        try:
            if Decimal(match.group(1).replace(',', '.')) == target:
                return True
        except InvalidOperation:
            continue
    return False


ODDS_TOKEN = re.compile(r'(?<![\d.:/])(\d+\.\d{2,3}|\d+/\d+)(?![\d.:])')


def selection_present(blob, instruction):
    """The card's selection line: the side and its line/odds on ONE line ("Hapoel Tel Aviv 1.23",
    "Rytas Vilnius -18.5", "Over 190.5"). A fixture line such as "Bayern Munich 17:00" is not a
    selection, so an unplaced AWAY bet never matches a HOME card of the same game."""
    market, side, line = instruction.get('market'), instruction.get('selection'), instruction.get('line')
    segments = [seg.strip() for seg in blob.split('|')]
    if market == 'TOTALS':
        if line is None:
            return False
        word = 'over' if side == 'OVER' else 'under'
        return any(re.search(rf'\b{word}\b', seg) and re.search(rf'(?<![\d.]){re.escape(plain(line))}(?![\d])', seg)
                   for seg in segments)
    if market == 'SPREAD':
        team, other = ((instruction.get('home'), instruction.get('away')) if side == 'HOME'
                       else (instruction.get('away'), instruction.get('home')))
        if line is None:
            return False
        value = Decimal(line)
        text = plain(abs(value))
        signed = ('+' if value > 0 else '-' if value < 0 else '') + text
        pattern = (rf'(?<![\d.]){re.escape(signed)}(?![\d])' if value != 0 else r'(?<![\d.])0(?:\.0)?(?![\d])')
        return any(team_present(seg, team, other) and re.search(pattern, seg) for seg in segments)
    team, other = {'HOME': (instruction.get('home'), instruction.get('away')),
                   'AWAY': (instruction.get('away'), instruction.get('home'))}.get(side, (None, None))
    if not team:
        return any(re.search(r'\bdraw\b', seg) and ODDS_TOKEN.search(seg) for seg in segments)
    return any(team_present(seg, team, other) and ODDS_TOKEN.search(seg) for seg in segments)


def lines_of(my_bets):
    """Ordered OCR line texts from a MY_BETS device result (frames in order, top-to-bottom)."""
    rows = my_bets.get('lines') if isinstance(my_bets, dict) else None
    if not isinstance(rows, list):
        raise ValueError('MY_BETS result has no lines')
    ordered = sorted((r for r in rows if isinstance(r, dict) and isinstance(r.get('text'), str)),
                     key=lambda r: (r.get('frame', 0), r.get('top', 0), r.get('left', 0)))
    return [r['text'] for r in ordered]


def _check_card(instruction, text):
    home, away = instruction.get('home'), instruction.get('away')
    return dict(fixture=team_present(text, home, away) and team_present(text, away, home),
                one_team=team_present(text, home, away) or team_present(text, away, home),
                selection=selection_present(text, instruction), stake=stake_present(text, instruction.get('stake')),
                odds=odds_present(text, instruction.get('odds') or instruction.get('observed_price')
                                  or instruction.get('alert_price')))


def _found(checks):
    """Require stake, selection and both teams on one bounded card.
    Missing opponent text is inconclusive, even when the odds happen to match."""
    return checks['stake'] and checks['selection'] and checks['fixture']


def _cards(normalised):
    """Split into bet cards at each '£x Single/Bet Builder...' header. None if no header is seen.
    Lines above the first header (below the address bar) form a card of their own: an expanded
    settled card shows its details above its header."""
    cards, current, preamble = [], None, []
    for index, line in enumerate(normalised):
        if CARD_HEADER.match(line):
            current = [index]
            cards.append(current)
        elif current is not None:
            current.append(index)
        elif index >= 2:
            preamble.append(index)
    if not cards:
        return None
    return ([preamble] if preamble else []) + cards


def _settlement(text):
    status = None
    for word, value in SETTLED_WORDS:
        if re.search(rf'\b{re.escape(word)}\b', text):
            status = value
            break
    returns = None
    for pattern in (r'£(\d+(?:\.\d{1,2})?)\s*returned', r'return(?:ed|s)?\s*:?\s*£\s?(\d+(?:\.\d{1,2})?)'):
        found = re.search(pattern, text)
        if found:
            returns = found.group(1)
            break
    return status, returns


def match(instruction, my_bets, view=None):
    """Return dict(found, confidence, window, bet_reference, status, returns) for one instruction.

    confidence: EXACT/STRONG (found), INCONCLUSIVE (a collapsed card could be this bet),
    PARTIAL / NO_FIXTURE_TEXT (not found). Raises ValueError if the requested view is not
    confirmed by the address bar, or the result has no lines: absence is then unproven.
    """
    frames = sorted({r.get('frame', 0) for r in my_bets.get('lines', []) if isinstance(r, dict)})
    if len(frames) > 1:
        # Never borrow a fixture, selection or stake from a different screenshot/card.
        results = []
        for frame in frames:
            sub = dict(my_bets, lines=[r for r in my_bets['lines'] if r.get('frame',0)==frame])
            try: results.append(match(instruction, sub, view))
            except ValueError: continue
        found = [r for r in results if r['found']]
        if found: return found[0]
        return dict(found=False, confidence='INCONCLUSIVE', window=None, bet_reference=None, status=None, returns=None)
    lines = lines_of(my_bets)
    normalised = [_norm(t) for t in lines]
    view = view or (my_bets.get('view') if isinstance(my_bets, dict) else None)
    if view in VIEW_MARKERS and not any(VIEW_MARKERS[view] in line for line in normalised[:4]):
        raise ValueError(f'My Bets {view} view not confirmed by the address bar')
    cards = _cards(normalised)
    if cards:
        best = None
        for card in cards:
            text = ' | '.join(normalised[i] for i in card)
            checks = _check_card(instruction, text)
            score = sum(checks.values()) + (2 if _found(checks) else 0)
            raw = ' | '.join(lines[i] for i in card)
            collapsed = len(card) == 1 and CARD_HEADER.match(normalised[card[0]]) is not None
            candidate = collapsed and checks['stake'] and (
                team_present(text, instruction.get('home'), instruction.get('away'))
                or team_present(text, instruction.get('away'), instruction.get('home')))
            if best is None or score > best['score'] or (candidate and not best.get('candidate')):
                best = dict(score=score, window=raw, text=text, candidate=candidate, **checks)
        found = _found(best)
        status, returns = _settlement(best['text'])
        reference = REFERENCE.search(best['window'])
        confidence = ('EXACT' if found and best['odds'] else 'STRONG' if found
                      else 'INCONCLUSIVE' if best['candidate'] else 'PARTIAL')
        return dict(found=found, confidence=confidence, window=best['window'],
                    checks={k: best[k] for k in ('fixture', 'selection', 'stake', 'odds')},
                    bet_reference=reference.group(1) if reference else None, status=status, returns=returns)
    # No reliable card boundary: a sliding window could join two different bets.
    return dict(found=False, confidence='INCONCLUSIVE', window=None, bet_reference=None, status=None, returns=None)
