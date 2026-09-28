"""Bet365 desktop event page -> the phone's header lines and market quotes (pure functions over layout words).

Input: word records from layout.read_words ({text, l, t, r, b, q, fs, fw} in page coordinates). Nothing depends on
Bet365's hashed class names: market groups are found by their titles (15px bold) and columns by their bold headers.
Output quotes use the phone's vocabulary (market SPREAD / TOTAL / MONEYLINE, side HOME / AWAY / DRAW / OVER / UNDER,
line as the phone writes it) so the phone's own decisions (decisions.py) and the backend comparison apply unchanged.
Anything that does not read cleanly is left out; the caller fails closed when the requested quote is missing.
"""
import re

from desktop_worker.layout import lines

CENTER_LEFT = 280                      # the left navigation column ends at ~270 px
DATE = re.compile(r'^\d{1,2} (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{1,2}:\d{2}$')
DECIMAL = re.compile(r'^\d+\.\d{2,3}$')
FRACTION = re.compile(r'^(\d+)/(\d+)$')
LINE = re.compile(r'^[+-]?\d+(\.\d+)?(,\s?[+-]?\d+(\.\d+)?)?$')
TOTAL_CELL = re.compile(r'^(O|U|Over|Under)\s+(\d+(\.\d+)?(,\s?\d+(\.\d+)?)?)$')

# Full-game groups only (1st-half, corners, cards ... are never read).
FOOTBALL_1X2 = ('Full Time Result',)
FOOTBALL_TOTALS = ('Goals Over/Under', 'Alternative Total Goals', 'Goal Line', 'Alternative Goal Line')
FOOTBALL_AH = ('Asian Handicap', 'Alternative Asian Handicap')
BASKETBALL_LINES = ('Game Lines',)


def center(words):
    return [w for w in words if w['l'] >= CENTER_LEFT]


def _row_text(ws):
    return ' '.join(w['text'] for w in ws).strip()


def _dedupe(ws):
    """Tab labels are rendered several times at the same place; keep one word per (text, position)."""
    seen, out = set(), []
    for w in ws:
        k = (w['text'], w['l'] // 4, w['t'] // 4)
        if k not in seen:
            seen.add(k); out.append(w)
    return out


def tab_strip(words):
    """(top, [labels]) of the market tab strip (the row that contains 'Popular'), or None."""
    for t, ws in lines(center(words)):
        texts = [w['text'] for w in _dedupe(ws)]
        if 'Popular' in texts and t > 60:
            return t, list(dict.fromkeys(texts))
    return None


def header(words):
    """The phone's header lines: ['<competition> • <date>', '<Home> v <Away>'] (basketball shows competition and date
    on separate rows and 'vs' as its own word: joined into the same shape)."""
    strip = tab_strip(words)
    limit = strip[0] if strip else 400
    rows = [_row_text(_dedupe(ws)) for t, ws in lines(center(words)) if 60 < t < limit]
    rows = [r for r in rows if r and r not in ('Rewards Join Log In',)]
    out = []
    for r in rows:
        if DATE.match(r) and out and ' v ' not in f' {out[-1]} ' and ' vs ' not in f' {out[-1]} ' and '•' not in out[-1]:
            out[-1] = f'{out[-1]} • {r}'
        else:
            out.append(r)
    return out


def groups(words):
    """[(title, [(top, [words])])] of the page's market groups (below the tab strip), in page order."""
    strip = tab_strip(words)
    below = strip[0] if strip else 0
    out = []
    for t, ws in lines(center(words)):
        if t <= below:
            continue
        ws = [w for w in _dedupe(ws) if w['text'] != 'BB']
        if not ws:
            continue
        first = ws[0]
        if first.get('fs', 0) >= 15 and first.get('fw', 400) >= 700 and not any(price(w['text']) for w in ws):
            out.append((_row_text(ws), []))
        elif out:
            out[-1][1].append((t, ws))
    return out


def price(text):
    """(decimal string or None, raw) for a price cell; fractional odds are recognised but carry no decimal price."""
    text = text.strip()
    if DECIMAL.match(text):
        return text
    if text == 'EVS' or FRACTION.match(text):
        return None
    return None


def is_price(text):
    text = text.strip()
    return bool(DECIMAL.match(text) or FRACTION.match(text) or text == 'EVS')


def _quote(market, side, line, w, name, group):
    return dict(market=market, side=side, line=line, price=price(w['text']), raw_price=w['text'], name=name, q=w.get('q'),
                group=group, bounds=[w['l'], w['t'], w['r'], w['b']])


def _columns(header_words):
    """Column spans from bold header words: [(label, left, right)] split at the midpoints between header centres."""
    hs = sorted(header_words, key=lambda w: w['l'])
    centres = [(w['l'] + w['r']) / 2 for w in hs]
    spans = []
    for i, w in enumerate(hs):
        left = -1e9 if i == 0 else (centres[i - 1] + centres[i]) / 2
        right = 1e9 if i == len(hs) - 1 else (centres[i] + centres[i + 1]) / 2
        spans.append((w['text'], left, right))
    return spans


def _in(span, w):
    c = (w['l'] + w['r']) / 2
    return span[1] <= c < span[2]


def basketball_quotes(words, home, away):
    """Game Lines (full game): Spread / Total / Money Line for the page's home (first row) and away (second row)."""
    out = []
    for title, rows in groups(words):
        if title not in BASKETBALL_LINES:
            continue
        head = next(((t, ws) for t, ws in rows if all(w.get('fw', 400) >= 700 for w in ws) and {'Spread', 'Total'} <= {w['text'] for w in ws}), None)
        if head is None:
            continue
        spans = _columns(head[1])
        data = [(t, ws) for t, ws in rows if t > head[0] and any(is_price(w['text']) for w in ws)][:2]
        if len(data) != 2:
            continue
        for (t, ws), side, team in zip(data, ('HOME', 'AWAY'), (home, away)):
            if ws[0]['text'] != team:
                return []                      # the rows are not the page's teams in order: read nothing
            for label, left, right in spans:
                cell = [w for w in ws[1:] if _in((label, left, right), w)]
                prices = [w for w in cell if is_price(w['text'])]
                if len(prices) != 1:
                    continue
                p = prices[0]
                others = [w['text'] for w in cell if w is not p]
                if label == 'Spread' and len(others) == 1 and LINE.match(others[0]):
                    out.append(_quote('SPREAD', side, others[0], p, team, title))
                elif label == 'Total' and len(others) == 1 and TOTAL_CELL.match(others[0]):
                    m = TOTAL_CELL.match(others[0])
                    ou = 'OVER' if m.group(1) in ('O', 'Over') else 'UNDER'
                    out.append(_quote('TOTAL', ou, m.group(2), p, 'Over' if ou == 'OVER' else 'Under', title))
                elif label == 'Money Line' and not others:
                    out.append(_quote('MONEYLINE', side, '', p, team, title))
        break
    return out


def football_quotes(words, home, away, norm_line):
    """Full Time Result, Goals Over/Under (+ Alternative Total Goals), Goal Line (+ Alternative), Asian Handicap
    (+ Alternative) from whatever tab is showing. norm_line: the phone's FootballMarkets.normaliseLine (bridge)."""
    out = []
    for title, rows in groups(words):
        if title in FOOTBALL_1X2:
            for t, ws in rows:
                prices = [i for i, w in enumerate(ws) if is_price(w['text'])]
                if len(prices) == 3 and all(i > 0 and not is_price(ws[i - 1]['text']) for i in prices):
                    names = [ws[i - 1]['text'] for i in prices]
                    if names == [home, 'Draw', away]:
                        for i, side in zip(prices, ('HOME', 'DRAW', 'AWAY')):
                            out.append(_quote('MONEYLINE', side, '', ws[i], ws[i - 1]['text'], title))
                    break
        elif title in FOOTBALL_TOTALS:
            head = next(((t, ws) for t, ws in rows if [w['text'] for w in ws] == ['Over', 'Under']), None)
            if head is None:
                continue
            for t, ws in rows:
                if t <= head[0]:
                    continue
                if len(ws) == 3 and LINE.match(ws[0]['text']) and is_price(ws[1]['text']) and is_price(ws[2]['text']):
                    line = norm_line(ws[0]['text'])
                    if line is None:
                        continue
                    line = line.lstrip('+')
                    out.append(_quote('TOTAL', 'OVER', line, ws[1], 'Over', title))
                    out.append(_quote('TOTAL', 'UNDER', line, ws[2], 'Under', title))
        elif title in FOOTBALL_AH:
            head = next(((t, ws) for t, ws in rows if [w['text'] for w in ws] == [home, away]), None)
            if head is None:
                continue
            for t, ws in rows:
                if t <= head[0]:
                    continue
                if len(ws) == 4 and LINE.match(ws[0]['text']) and is_price(ws[1]['text']) and LINE.match(ws[2]['text']) and is_price(ws[3]['text']):
                    for (lw, pw), side, team in (((ws[0], ws[1]), 'HOME', home), ((ws[2], ws[3]), 'AWAY', away)):
                        line = norm_line(lw['text'])
                        if line is not None:
                            out.append(_quote('SPREAD', side, line, pw, team, title))
    return out


def collapsed(words, titles):
    """Titles from `titles` whose group shows no rows (collapsed), with the title word to click."""
    out = []
    all_rows = lines(center(words))
    for title, rows in groups(words):
        if title in titles and not rows:
            for t, ws in all_rows:
                if _row_text([w for w in _dedupe(ws) if w['text'] != 'BB']) == title:
                    out.append((title, ws[0]))
                    break
    return out


def logged_in(words):
    """True / False / None from the top bar: 'Log In' shown = logged out; a balance or 'My Bets' = logged in."""
    top = [w['text'] for w in words if w['t'] < 70]
    if 'Log In' in top or 'Join' in top:
        return False
    # the balance widget exists only for a signed-in account; '£--.--' is it still loading
    if any(re.match(r'^£(\d|--)', t) for t in top) or 'My Bets' in top:
        return True
    return None
