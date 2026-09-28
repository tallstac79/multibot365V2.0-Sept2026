"""The Bet365 desktop betslip as a person sees it: screenshots, OCR, ordinary mouse clicks and keyboard input.

Why (28 Sep 2026, evidence/desktop-worker-addbet/): Bet365 wraps document.querySelector / querySelectorAll /
getElementsByClassName / getElementsByTagName (on document and Element.prototype). A class-selector lookup run inside the
page before the selection click made the next BetsWebAPI/addbet answer {"cs":2,"sr":-1} ("Sorry, there has been an
error"); plain clicks were accepted. The flagged action is removed, not hidden: from the empty-slip check to the Place
Bet check the worker runs NO script in the page and makes NO DOM query of the slip (no page.evaluate, no Playwright
locator, no CDP DOM/Runtime read). It only
  - takes screenshots (CDP Page.captureScreenshot: a copy of the rendered pixels, nothing runs in the page),
  - reads them with Tesseract OCR (C:\\Program Files\\Tesseract-OCR),
  - clicks / types with ordinary input events (page.mouse / page.keyboard at coordinates read from the screenshot),
  - reads Bet365's own BetsWebAPI responses to those clicks passively (the Playwright 'response' event; requests are
    never changed).
Nothing here presses Place Bet: there is no function that clicks it, and the jackpot toggle is never touched.

Captured live 28 Sep 2026: the slip opens as a white panel over the lower middle of the event page: an item row
(remove X, green bold selection + handicap, price at the right), the market, the fixture, a Jackpot 365 strip, and a
footer (dark Stake box on the left, Place Bet button on the right, green when a stake is entered, 'To Return £x').
"""
import base64
import io
import json
import os
import re
from fractions import Fraction
from pathlib import Path

import pytesseract
from PIL import Image, ImageOps, ImageStat

TESSERACT = Path(os.environ.get('TESSERACT_CMD') or r'C:\Program Files\Tesseract-OCR\tesseract.exe')
pytesseract.pytesseract.tesseract_cmd = str(TESSERACT)

SCALE = 3                                      # OCR upscaling (slip text is 11-13 px)
MONEY = re.compile(r'(\d+[.,]\d{2})$')
DECIMAL = re.compile(r'^\d+\.\d{2,3}$')
LINE = re.compile(r'^[+-]?\d+(\.\d+)?(,[+-]?\d+(\.\d+)?)?$')
NOTICE = re.compile(r'accept|chang|suspend|unavailable|closed|error|sorry|limit|maximum|minimum|no longer', re.I)
BACKGROUND = ((17, 17, 17), (34, 34, 34))


# ---------------------------------------------------------------------------------------------------- pixels
async def screenshot(page):
    """(PIL image, png bytes) of the viewport via CDP Page.captureScreenshot - no script is run in the page."""
    cdp = await page.context.new_cdp_session(page)
    try:
        r = await cdp.send('Page.captureScreenshot', {'format': 'png'})
    finally:
        await cdp.detach()
    png = base64.b64decode(r['data'])
    return Image.open(io.BytesIO(png)).convert('RGB'), png


def _white(p):
    return p[0] >= 248 and p[1] >= 248 and p[2] >= 248


def _bg(p):
    return any(all(abs(p[i] - b[i]) <= 3 for i in range(3)) for b in BACKGROUND)


def find_panel(img, min_width=300):
    """[l, t, r, b] of the slip panel (the big white rectangle in the lower part of the viewport plus its footer), or
    None when no slip is showing."""
    w, h = img.size
    px = img.load()
    rows = []                                          # (y, l, r) rows with a long white run
    for y in range(int(h * 0.3), h):
        segs, start, last = [], None, None           # white segments; gaps up to 24 px (text) are bridged
        for x in range(0, w, 2):
            if _white(px[x, y]):
                if start is None or x - last > 24:
                    if start is not None:
                        segs.append((start, last))
                    start = x
                last = x
        if start is not None:
            segs.append((start, last))
        best = max(segs, key=lambda s: s[1] - s[0], default=None)
        if best and best[1] - best[0] >= min_width:
            rows.append((y, best[0], best[1] + 2))
    if not rows:
        return None
    from collections import Counter
    right = Counter(r[2] // 4 for r in rows).most_common(1)[0][0]      # the panel's right edge: the commonest run end
    rows = [r for r in rows if abs(r[2] // 4 - right) <= 2]
    blocks, cur = [], [rows[0]]                        # contiguous runs of such rows (text lines and the jackpot strip bridged)
    for r in rows[1:]:
        if r[0] - cur[-1][0] <= 80:
            cur.append(r)
        else:
            blocks.append(cur); cur = [r]
    blocks.append(cur)
    block = max(blocks, key=len)
    if len(block) < 20:
        return None
    ls = sorted(r[1] for r in block); rs = sorted(r[2] for r in block)
    l, r = ls[len(ls) // 2], rs[len(rs) // 2]
    t, b = block[0][0], block[-1][0]
    y = b + 1                                          # the footer (stake box / Place Bet) until the page background
    while y < h and not (_bg(px[min(l + 12, w - 1), y]) and _bg(px[max(r - 12, 0), y])):
        y += 1
    return [l, t, r, y]


def mean_colour(img, box):
    l, t, r, b = [int(v) for v in box]
    crop = img.crop((max(l, 0), max(t, 0), min(r, img.width), min(b, img.height)))
    if crop.width <= 0 or crop.height <= 0:
        return (0, 0, 0)
    return tuple(round(v) for v in ImageStat.Stat(crop).mean[:3])


def is_green(c):
    """Bet365's active Place Bet green (43,255,189)->(138,255,171); disabled is grey."""
    return c[1] >= 200 and c[1] - c[0] >= 60


def green_text_rows(img, panel):
    """Rows of the white item area holding the selection-title green (dark green bold text) - one per selection."""
    l, t, r, b = panel
    px = img.load()
    hits = []
    for y in range(t, b):
        n = 0
        for x in range(l + 30, int(l + (r - l) * 0.75), 2):
            p = px[x, y]
            if abs(p[0] - 18) <= 14 and abs(p[1] - 110) <= 14 and abs(p[2] - 81) <= 14:     # title green (18,110,81)
                n += 1
        if n >= 4:
            hits.append(y)
    groups = []
    for y in hits:
        if groups and y - groups[-1][-1] <= 3:
            groups[-1].append(y)
        else:
            groups.append([y])
    return [(g[0], g[-1]) for g in groups if len(g) >= 6]


# ---------------------------------------------------------------------------------------------------- OCR
def ocr_words(img, box, invert=False):
    """Tesseract words inside `box` in viewport coordinates: [{text, l, t, r, b, conf}]."""
    l, t, r, b = [int(v) for v in box]
    crop = img.crop((l, t, r, b)).convert('L')
    if invert:
        crop = ImageOps.invert(crop)
    crop = crop.resize((crop.width * SCALE, crop.height * SCALE), Image.LANCZOS)
    d = pytesseract.image_to_data(crop, config='--psm 11', output_type=pytesseract.Output.DICT)
    out = []
    for i, text in enumerate(d['text']):
        text = (text or '').strip()
        if not text:
            continue
        x0, y0 = l + d['left'][i] / SCALE, t + d['top'][i] / SCALE
        out.append(dict(text=text, l=round(x0), t=round(y0), r=round(x0 + d['width'][i] / SCALE), b=round(y0 + d['height'][i] / SCALE),
                        conf=float(d['conf'][i])))
    return out


def _overlap(a, b):
    return not (a['r'] <= b['l'] or b['r'] <= a['l'] or a['b'] <= b['t'] or b['b'] <= a['t'])


def panel_words(img, panel):
    """OCR of the panel: the whole panel, then the footer band (Stake / Place Bet / To Return) on its own, each plain and
    inverted (light-on-dark stake box); a word is added only where no word was read yet."""
    l, t, r, b = panel
    words = []
    for box in (panel, (l, max(t, b - 56), r, b)):
        for invert in (False, True):
            for w in ocr_words(img, box, invert=invert):
                if w['conf'] >= 30 and not any(_overlap(w, k) for k in words):
                    words.append(w)
    return sorted(words, key=lambda w: (w['t'], w['l']))


def rows(words, tol=5):
    out = []
    for w in sorted(words, key=lambda w: ((w['t'] + w['b']) / 2, w['l'])):
        c = (w['t'] + w['b']) / 2
        if out and abs(out[-1][0] - c) <= tol:
            out[-1][1].append(w)
        else:
            out.append((c, [w]))
    return [(c, sorted(ws, key=lambda w: w['l'])) for c, ws in out]


def as_text(words):
    return '\n'.join(f"{w['text']} [{w['l']},{w['t']}][{w['r']},{w['b']}] {w.get('conf', 0):.0f}" for w in words)


def _money(text):
    m = MONEY.search(text.replace(',', '.') if text.count(',') == 1 and '.' not in text else text.replace(',', ''))
    return m.group(1) if m else None


# ---------------------------------------------------------------------------------------------------- slip state
def read_slip(img):
    """What the slip shows, from pixels only. Keys: present, panel, items (visual title-row count), title, handicap,
    price, market, fixture, stake, to_return, place_bet {bounds, enabled, colour}, stake_box, remove_x, notices,
    reality_check, words."""
    state = dict(present=False)
    panel = find_panel(img)
    if panel is None:
        return state
    words = panel_words(img, panel)
    l, t, r, b = panel
    state.update(present=True, panel=panel, words=words, items=len(green_text_rows(img, panel)))
    rs = rows(words)
    # item row: the first row with a decimal price at the right-hand quarter
    item = None
    for c, ws in rs:
        prices = [w for w in ws if DECIMAL.match(w['text']) and w['l'] > l + (r - l) * 0.7]
        if prices:
            item = (c, ws, prices[-1])
            break
    if item:
        c, ws, pw = item
        title = [w for w in ws if w is not pw and w['l'] > l + 26 and w['r'] < pw['l']]
        texts = [w['text'] for w in title]
        handicap = None
        if texts and LINE.match(texts[-1]):
            handicap = texts.pop()
        state.update(title=' '.join(texts), handicap=handicap, price=pw['text'], title_row=[l, round(c - 10), r, round(c + 10)],
                     remove_x=[l + 18, round(c)])
        below = [(c2, ws2) for c2, ws2 in rs if c2 > c + 6]
        if below:
            state['market'] = ' '.join(w['text'] for w in below[0][1] if w['r'] < pw['l'])
        if len(below) > 1:
            state['fixture'] = ' '.join(w['text'] for w in below[1][1] if w['r'] < pw['l'])
    # footer: Stake label/value, Place Bet words, To Return
    stake_label = next((w for w in words if w['text'] == 'Stake' and w['t'] > t + (b - t) * 0.5), None)
    if stake_label:
        before = [w for w in words if w['text'] == 'Set' and abs(w['t'] - stake_label['t']) <= 4 and 0 < stake_label['l'] - w['r'] <= 14]
        if before:                                     # no stake yet: the footer offers a 'Set Stake' control
            s0 = before[0]
            state['stake_control'] = dict(kind='set_stake', bounds=[s0['l'], s0['t'], stake_label['r'], stake_label['b']],
                                          click=[round((s0['l'] + stake_label['r']) / 2), round((s0['t'] + stake_label['b']) / 2)])
            state['stake'] = None
        else:                                          # the stake box: 'Stake' label with the amount below it
            state['stake_control'] = dict(kind='stake_box', bounds=[stake_label['l'] - 8, stake_label['t'] - 6, stake_label['l'] + 160, stake_label['b'] + 26],
                                          click=[stake_label['l'] + 40, stake_label['b'] + 12])
            vals = [w for w in words if stake_label['b'] - 2 <= w['t'] <= stake_label['b'] + 30
                    and stake_label['l'] - 10 <= w['l'] <= stake_label['l'] + 150 and _money(w['text'])]
            state['stake'] = _money(vals[0]['text']) if vals else None
    place = next(((a, bb) for a in words for bb in words if a['text'] == 'Place' and bb['text'] == 'Bet'
                  and abs(a['t'] - bb['t']) <= 4 and 0 < bb['l'] - a['r'] <= 14), None)
    if place:
        a, bb = place
        cx, cy = (a['l'] + bb['r']) / 2, (a['t'] + bb['b']) / 2
        # the button face: sample left of the words and below them (no text), within the footer
        colour = mean_colour(img, (a['l'] - 40, a['b'] + 1, a['l'] - 10, a['b'] + 6))
        state['place_bet'] = dict(text='Place Bet', bounds=[a['l'], a['t'], bb['r'], bb['b']], centre=[round(cx), round(cy)],
                                  colour=colour, enabled=is_green(colour))
    to = next(((a, bb) for a in words for bb in words if a['text'] == 'To' and bb['text'] == 'Return'
               and abs(a['t'] - bb['t']) <= 4 and 0 < bb['l'] - a['r'] <= 12), None)
    if to:
        amounts = sorted((w for w in words if w['l'] > to[1]['r'] and abs(w['t'] - to[1]['t']) <= 5 and _money(w['text'])), key=lambda w: w['l'])
        state['to_return'] = _money(amounts[0]['text']) if amounts else None
    state['notices'] = [' '.join(w['text'] for w in ws) for c, ws in rs if any(NOTICE.search(w['text']) for w in ws)]
    return state


def reality_check(img):
    """Bet365's Reality Check dialog (a responsible-gambling prompt) is open: an operator must answer it by hand."""
    w, h = img.size
    words = ocr_words(img, (int(w * 0.25), int(h * 0.15), int(w * 0.75), int(h * 0.6)))
    text = ' '.join(x['text'] for x in words)
    return 'Reality' in text and 'Check' in text


# ---------------------------------------------------------------------------------------------------- network
def fraction_decimal(od):
    """Bet365 addbet 'od' (fractional '39/40', 'EVS') -> decimal float."""
    od = (od or '').strip()
    if od.upper() in ('EVS', '1/1'):
        return 2.0
    try:
        return float(1 + Fraction(od))
    except (ValueError, ZeroDivisionError):
        return None


def addbet_terms(body):
    """Bet365's own addbet response -> {accepted, cs, sr, bets:[{fixture, selection, handicap, market, odds, decimal}]}."""
    try:
        j = json.loads(body)
    except (TypeError, ValueError):
        return dict(accepted=False, parse_error=True)
    bets = []
    for bt in j.get('bt') or []:
        pt = (bt.get('pt') or [{}])[0]
        bets.append(dict(fixture=bt.get('fd'), selection=pt.get('bd'), handicap=pt.get('hd'), market=pt.get('md'),
                         odds=bt.get('od'), decimal=fraction_decimal(bt.get('od')), sr=bt.get('sr'), cs=bt.get('cs')))
    accepted = j.get('sr') == 0 and j.get('cs') == 1 and bool(bets) and all(x['sr'] == 0 for x in bets)
    return dict(accepted=accepted, cs=j.get('cs'), sr=j.get('sr'), bets=bets)


REDACT = ('bg', 'pc', 'cc', 'sa')


def redacted(body):
    """The addbet response for evidence: account/session tokens replaced by <redacted>."""
    try:
        j = json.loads(body)
    except (TypeError, ValueError):
        return '<unparsed>'
    def walk(o):
        if isinstance(o, dict):
            return {k: ('<redacted>' if k in REDACT else walk(v)) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v) for v in o]
        return o
    return walk(j)


# ---------------------------------------------------------------------------------------------------- input
async def click(page, x, y):
    """An ordinary mouse click at viewport coordinates (move there first, as a pointer does)."""
    await page.mouse.move(x - 30, y - 12)
    await page.mouse.move(x, y, steps=5)
    await page.mouse.click(x, y)


async def type_stake(page, control, stake):
    """Click the slip's stake control (the 'Set Stake' button or the stake box, found on the screenshot) and type the
    amount with the keyboard, clearing whatever the box held first."""
    x, y = control['click']
    await click(page, x, y)
    await page.wait_for_timeout(400)
    await page.keyboard.press('Control+A')
    await page.keyboard.press('Backspace')
    await page.keyboard.type(stake, delay=90)
    await page.wait_for_timeout(1300)
