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
from datetime import datetime

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


# Two half-goal lines (at most one decimal each, odds have two or three) separated by a comma - or a space once _norm
# has replaced the comma - exactly 0.5 apart: "0.0,-0.5" / "0.0 -0.5" = -0.25, "2.0,2.5" = 2.25.
QUARTER_PAIR = re.compile(r'(?<![\d.])([+-]?\d{1,3}(?:\.\d)?)(?:\s*,\s*|\s+)([+-]?\d{1,3}(?:\.\d)?)(?![\d.])')


def _quarter_pairs(segment):
    out = []
    for m in QUARTER_PAIR.finditer(segment):
        try:
            x, y = Decimal(m.group(1)), Decimal(m.group(2))
        except InvalidOperation:
            continue
        if abs(x - y) == Decimal('0.5'):
            out.append((m, (x + y) / 2))
    return out


def _quarter_lines(segment):
    """Bet365's split quarter lines on a My Bets card ("Auto Esporte 0.0,-0.5 1.900" = -0.25, "Over 2.0,2.5" = 2.25)."""
    return {value for _, value in _quarter_pairs(segment)}


def _without_quarter_pairs(segment):
    """The segment with split quarter pairs blanked, so "-0.5" inside "0.0,-0.5" is never read as a -0.5 line."""
    for m, _ in reversed(_quarter_pairs(segment)):
        segment = segment[:m.start()] + ' ' + segment[m.end():]
    return segment


def _line_value(line):
    try:
        return Decimal(str(line))
    except (InvalidOperation, TypeError, ValueError):
        return None


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
        value = _line_value(line)
        return any(re.search(rf'\b{word}\b', seg) and (re.search(rf'(?<![\d.]){re.escape(plain(line))}(?![\d])', _without_quarter_pairs(seg))
                                                      or (value is not None and value in _quarter_lines(seg)))
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
        return any(team_present(seg, team, other) and (re.search(pattern, _without_quarter_pairs(seg)) or value in _quarter_lines(seg))
                   for seg in segments)
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


TOP_OF_LIST = re.compile(r'\bopen\b.*\bsettled\b')
END_OF_LIST = ('information and transmission delays', 'responsible gambling', 'safer gambling', 'terms and conditions',
               'complaints procedure', 'deposit limits')
EMPTY_LIST = ('no open bets', 'no bets to display', 'you have no', 'no unsettled bets')


def proves_absence(instruction, my_bets, view='OPEN'):
    """(absent, reason). Absence of a bet may be concluded only when the whole list was read and nothing could be it:

    * every frame is the requested My Bets view (address bar), the first frame shows the list top (the Open/Settled tab
      row) and a frame shows the end of the list (the page footer) or an explicit empty-list message;
    * no card matches the bet, and no card with the bet's own stake could be it: every card whose header carries that
      stake shows, inside the same frame, a fixture that names neither of the bet's teams (a header cut at a frame
      edge, or a collapsed card, stays a possible match).
    Anything less is not proof (27 Sep 2026: the UD Leiria tap could not be settled because absence was never provable).
    """
    rows = [r for r in (my_bets.get('lines') or []) if isinstance(r, dict) and isinstance(r.get('text'), str)]
    if not rows:
        return False, 'no My Bets lines'
    frames = sorted({r.get('frame', 0) for r in rows})
    per_frame = {f: [_norm(r['text']) for r in sorted((x for x in rows if x.get('frame', 0) == f), key=lambda r: (r.get('top', 0), r.get('left', 0)))]
                 for f in frames}
    marker = VIEW_MARKERS.get(view)
    for f, lines in per_frame.items():
        if marker and not any(marker in line for line in lines[:4]):
            return False, f'frame {f}: {view} view not confirmed by the address bar'
    blob_all = ' | '.join(' | '.join(v) for v in per_frame.values())
    if not any(TOP_OF_LIST.search(line) for line in per_frame[frames[0]][:8]):
        return False, 'list top (Open/Settled tabs) not in the first frame'
    if any(e in blob_all for e in EMPTY_LIST):
        return True, 'My Bets list is empty (tab row and empty-list message read)'
    if not any(any(e in line for e in END_OF_LIST) for lines in per_frame.values() for line in lines):
        return False, 'end of list (page footer) never reached'
    try:
        target = Decimal(str(instruction.get('stake')))
    except (InvalidOperation, TypeError, ValueError):
        return False, 'bet stake unknown'
    home, away = instruction.get('home'), instruction.get('away')
    same_stake = 0
    for f, lines in per_frame.items():
        cards = _cards(lines) or []
        for card in cards:
            header = lines[card[0]]
            m = CARD_HEADER.match(header)
            if not m:
                continue
            amount = re.match(r'^£(\d+(?:\.\d{1,2})?)', header)
            if not amount or Decimal(amount.group(1)) != target:
                continue
            same_stake += 1
            text = ' | '.join(lines[i] for i in card)
            if team_present(text, home, away) or team_present(text, away, home):
                return False, f'frame {f}: a card with the bet stake names one of the teams'
            body = [lines[i] for i in card[1:] if not any(e in lines[i] for e in END_OF_LIST)]
            if len(body) < 3:
                return False, f'frame {f}: a card with the bet stake is not fully visible (possible match)'
    return True, f'whole list read (top to footer); {same_stake} card(s) with the bet stake, none for this fixture'


DATE_ON_CARD = re.compile(r'\b(\d{1,2}) (jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b')
MONTHS = {m: i + 1 for i, m in enumerate(('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'))}


def _reference_key(value):
    """Bet references as printed/OCR'd ("AT3003000811 W", "Bet Ref ST2998906111W") compared on letters and digits only."""
    return re.sub(r'[^A-Z0-9]', '', str(value or '').upper()) or None


def _date_agrees(text, instruction):
    """A card that prints its kick-off date must be on the instruction's event date (UK local) - a repeat fixture on another
    day is a different bet. Cards without a date, or instructions without an event time, are not constrained here."""
    event = instruction.get('event_time')
    shown = DATE_ON_CARD.search(text)
    if not event or not shown:
        return True
    try:
        when = datetime.fromisoformat(str(event)[:16])
    except ValueError:
        return True
    return int(shown.group(1)) == when.day and MONTHS[shown.group(2)] == when.month


def _card_key(text, instruction):
    """Stable identity of a card across scrolled frames: its selection line(s), money lines and date line (live scores and
    clocks change between frames and are left out). Two different bets with identical terms share a key."""
    keep = [seg.strip() for seg in text.split('|') if seg.strip().startswith('\u00a3') or DATE_ON_CARD.search(seg)
            or selection_present(seg, instruction)]
    return ' | '.join(keep)


def _frame_match(instruction, my_bets, view):
    """One screenshot: every card that satisfies fixture + selection + stake (+ date), and the best non-match for
    confidence reporting. Raises ValueError if the requested view is not confirmed or there are no lines."""
    lines = lines_of(my_bets)
    normalised = [_norm(t) for t in lines]
    view = view or (my_bets.get('view') if isinstance(my_bets, dict) else None)
    if view in VIEW_MARKERS and not any(VIEW_MARKERS[view] in line for line in normalised[:4]):
        raise ValueError(f'My Bets {view} view not confirmed by the address bar')
    cards = _cards(normalised)
    found, best = [], None
    for card in cards or []:
        text = ' | '.join(normalised[i] for i in card)
        checks = _check_card(instruction, text)
        raw = ' | '.join(lines[i] for i in card)
        score = sum(checks.values()) + (2 if _found(checks) else 0)
        collapsed = len(card) == 1 and CARD_HEADER.match(normalised[card[0]]) is not None
        candidate = collapsed and checks['stake'] and (
            team_present(text, instruction.get('home'), instruction.get('away'))
            or team_present(text, instruction.get('away'), instruction.get('home')))
        if best is None or score > best['score'] or (candidate and not best.get('candidate')):
            best = dict(score=score, window=raw, text=text, candidate=candidate, **checks)
        if _found(checks) and _date_agrees(text, instruction):
            reference = REFERENCE.search(raw)
            found.append(dict(key=_card_key(text, instruction), window=raw, text=text, checks=checks,
                              reference=_reference_key(reference.group(1)) if reference else None))
    return dict(cards=bool(cards), found=found, best=best)


def match(instruction, my_bets, view=None):
    """Return dict(found, confidence, window, bet_reference, status, returns, card_key) for one instruction.

    Guarantees (27 Sep 2026 cross-layer audit P1-2):
    * reference first - a card printing a DIFFERENT bet reference is never this bet; a card printing ours wins;
    * a card that prints a kick-off date must be on the event date;
    * uniqueness - more than one distinct matching card, or two identical matching cards on one screenshot (two bets
      with the same terms), is AMBIGUOUS and not found, unless the reference singles one out; the same card seen again
      in an overlapping scrolled frame counts once;
    * nothing is borrowed across screenshots (each card is judged within its own frame).
    confidence: EXACT/STRONG (found), AMBIGUOUS, INCONCLUSIVE (a collapsed card could be this bet), PARTIAL.
    Raises ValueError if the requested view is not confirmed by the address bar, or the result has no lines."""
    frames = sorted({r.get('frame', 0) for r in my_bets.get('lines', []) if isinstance(r, dict)})
    reads, errors = [], 0
    for frame in frames or [0]:
        sub = dict(my_bets, lines=[r for r in my_bets.get('lines', []) if r.get('frame', 0) == frame]) if len(frames) > 1 else my_bets
        try:
            reads.append(_frame_match(instruction, sub, view))
        except ValueError:
            if len(frames) <= 1:
                raise
            errors += 1
    none = dict(found=False, confidence='INCONCLUSIVE', window=None, bet_reference=None, status=None, returns=None, card_key=None)
    if not reads or not any(r['cards'] for r in reads):
        return none   # no reliable card boundary: a sliding window could join two different bets
    cards = [c for r in reads for c in r['found']]
    duplicated = {c['key'] for r in reads for c in r['found'] if sum(1 for d in r['found'] if d['key'] == c['key']) > 1}
    known = _reference_key(instruction.get('bet_reference'))
    if known:
        cards = [c for c in cards if c['reference'] in (None, known)]
        own = [c for c in cards if c['reference'] == known]
        if own:
            cards, duplicated = own[:1], set()
    keys = list(dict.fromkeys(c['key'] for c in cards))
    if not keys:
        best = max((r['best'] for r in reads if r['best']), key=lambda b: (b['score'], b.get('candidate', False)), default=None)
        if best is None:
            return none
        status, returns = _settlement(best['text'])   # diagnostic only: settlement acts on found cards alone
        return dict(found=False, confidence='INCONCLUSIVE' if best['candidate'] else 'PARTIAL', window=best['window'],
                    checks={k: best[k] for k in ('fixture', 'selection', 'stake', 'odds')}, bet_reference=None,
                    status=status, returns=returns, card_key=None)
    if len(keys) > 1 or keys[0] in duplicated:
        return dict(none, confidence='AMBIGUOUS', window=' || '.join(c['window'] for c in cards[:3]),
                    ambiguity=(f'{len(keys)} different matching cards' if len(keys) > 1
                               else 'two identical matching cards on one screen (two bets with the same terms)'))
    card = cards[0]
    status, returns = _settlement(card['text'])
    return dict(found=True, confidence='EXACT' if card['checks']['odds'] else 'STRONG', window=card['window'],
                checks={k: card['checks'][k] for k in ('fixture', 'selection', 'stake', 'odds')},
                bet_reference=card['reference'], status=status, returns=returns, card_key=card['key'])
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
