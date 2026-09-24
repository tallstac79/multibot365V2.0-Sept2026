"""Match Bet365 "My Bets" OCR text to a pipeline instruction. Pure functions, no I/O.

The phone returns every OCR line it saw on the My Bets view (several scrolled frames).
A bet is matched only when the fixture, the selection (side + line for spread/totals)
and the stake all appear inside one bet-card-sized window of consecutive lines. Odds are
compared in decimal or fractional form. Anything weaker is NOT a match: reconciliation
must never claim a bet exists (or does not) on partial evidence.

These heuristics are calibrated on synthetic cards until real My Bets captures exist
(shadow capture); the tests pin the behaviour so calibration changes are visible.
"""
from decimal import Decimal, InvalidOperation
import re

WINDOW_BEFORE, WINDOW_AFTER = 6, 10
SETTLED_WORDS = (('cashed out', 'CASHED_OUT'), ('cash out', 'CASHED_OUT'), ('void', 'VOID'), ('won', 'WON'),
                 ('lost', 'LOST'), ('lose', 'LOST'), ('returned', 'RETURNED'))
REFERENCE = re.compile(r'\b(?:bet\s*ref(?:erence)?\.?:?\s*)([A-Z0-9]{6,20})\b', re.IGNORECASE)
MONEY = r'[£€$]?\s?(\d+(?:[.,]\d{1,2})?)'


def _norm(text):
    return re.sub(r'\s+', ' ', re.sub(r'[^0-9a-z+\-./£ ]', ' ', str(text).lower())).strip()


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


def selection_present(blob, instruction):
    market, side, line = instruction.get('market'), instruction.get('selection'), instruction.get('line')
    if market == 'TOTALS':
        word = 'over' if side == 'OVER' else 'under'
        return word in blob and line is not None and re.search(rf'(?<![\d.]){re.escape(plain(line))}(?![\d])', blob) is not None
    if market == 'SPREAD':
        team, other = ((instruction.get('home'), instruction.get('away')) if side == 'HOME'
                       else (instruction.get('away'), instruction.get('home')))
        if not team_present(blob, team, other) or line is None:
            return False
        value = Decimal(line)
        text = plain(abs(value))
        signed = ('+' if value > 0 else '-' if value < 0 else '') + text
        return re.search(rf'(?<![\d.]){re.escape(signed)}(?![\d])', blob) is not None or \
            (value == 0 and re.search(r'(?<![\d.])0(?:\.0)?(?![\d])', blob) is not None)
    team, other = {'HOME': (instruction.get('home'), instruction.get('away')),
                   'AWAY': (instruction.get('away'), instruction.get('home'))}.get(side, (None, None))
    return team_present(blob, team, other) if team else 'draw' in blob


def lines_of(my_bets):
    """Ordered OCR line texts from a MY_BETS device result (frames in order, top-to-bottom)."""
    rows = my_bets.get('lines') if isinstance(my_bets, dict) else None
    if not isinstance(rows, list):
        raise ValueError('MY_BETS result has no lines')
    ordered = sorted((r for r in rows if isinstance(r, dict) and isinstance(r.get('text'), str)),
                     key=lambda r: (r.get('frame', 0), r.get('top', 0), r.get('left', 0)))
    return [r['text'] for r in ordered]


def match(instruction, my_bets):
    """Return dict(found, confidence, window, bet_reference, status, returns) for one instruction."""
    lines = lines_of(my_bets)
    normalised = [_norm(t) for t in lines]
    best = None
    home, away = instruction.get('home'), instruction.get('away')
    for index, text in enumerate(normalised):
        if not (team_present(text, home, away) or team_present(text, away, home)):
            continue
        window = ' | '.join(normalised[max(0, index - WINDOW_BEFORE): index + WINDOW_AFTER])
        fixture = team_present(window, home, away) and team_present(window, away, home)
        selection = selection_present(window, instruction)
        stake = stake_present(window, instruction.get('stake'))
        odds = odds_present(window, instruction.get('odds') or instruction.get('observed_price')
                            or instruction.get('alert_price'))
        score = sum((fixture, selection, stake, odds))
        if best is None or score > best['score']:
            raw = ' | '.join(lines[max(0, index - WINDOW_BEFORE): index + WINDOW_AFTER])
            best = dict(score=score, fixture=fixture, selection=selection, stake=stake, odds=odds, window=raw)
    if best is None:
        return dict(found=False, confidence='NO_FIXTURE_TEXT', window=None, bet_reference=None, status=None, returns=None)
    found = best['fixture'] and best['selection'] and best['stake']
    reference = REFERENCE.search(best['window'])
    status = None
    lower = best['window'].lower()
    for word, value in SETTLED_WORDS:
        if re.search(rf'\b{re.escape(word)}\b', lower):
            status = value
            break
    returns = None
    ret = re.search(r'return(?:ed|s)?\s*:?\s*' + MONEY, lower)
    if ret:
        returns = ret.group(1).replace(',', '.')
    confidence = 'EXACT' if found and best['odds'] else 'STRONG' if found else 'PARTIAL'
    return dict(found=found, confidence=confidence, window=best['window'], checks={k: best[k] for k in
                ('fixture', 'selection', 'stake', 'odds')}, bet_reference=reference.group(1) if reference else None,
                status=status, returns=returns)
