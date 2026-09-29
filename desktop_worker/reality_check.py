"""Bet365 Reality Check on the desktop worker's Chrome: recognise the dialog from a screenshot and, on David's
instruction (29 Sep 2026 05:53 BST), acknowledge it with ONE ordinary mouse click on its 'Remain Logged In' button.

Pure functions over a PIL screenshot (CDP Page.captureScreenshot; no script in the page, no DOM query):

  modal_panel(img)   the light dialog panel centred in the upper half of the viewport (the dark-theme page has no other
                     light panel there; the floating betslip sits lower down and is excluded), or None.
  read_dialog(img)   the dialog's text (title, 'Your session has now exceeded HH:MM:SS', 'after every N minutes', any
                     win/loss figures), its green buttons each read on their own, and the click target - ONLY when:
                       * the panel carries the Reality Check signature (title + one of its own sentences),
                       * exactly one green button reads 'Remain Logged In' (Remain and Logged each with OCR conf >= 60),
                       * that button's text has none of: out / review / history / account / deposit / limit / ...,
                       * the button's rectangle lies inside the dialog and is button-sized.
                     Anything else gives target=None with the reason; the worker then does not click.

The worker never clicks 'Log out', 'Review Your Account History', 'Safer Gambling', 'Contact Us' or any limit option.
"""
import re

import numpy as np

LIGHT = 200                         # dialog grey is (228, 228, 228); the page is 10-40
TITLE = re.compile(r'Reality\s*Check', re.I)
SIGNATURE = re.compile(r'session\s+has\s+now\s+exceeded|requested\s+a\s+Reality\s+Check|after\s+every\s+\d+\s+minutes', re.I)
SUSPECT = re.compile(r'Reality\s*Check|Remain\s+Logged|session\s+has\s+now|has\s+now\s+exceeded|requested\s+a\s+Reality|'
                     r'Review\s+Your\s+Account\s+History|minutes\s+of\s+play', re.I)
FORBIDDEN = re.compile(r'out|review|history|account|deposit|limit|contact|safer|gambling|close|exclu|time|cancel|view', re.I)
ELAPSED = re.compile(r'\b(\d{1,3}\s?[:.]\s?\d{2}\s?[:.]\s?\d{2})\b')      # the only clock on the dialog
INTERVAL = re.compile(r'after\s+every\s+(\d{1,3})\s+minutes', re.I)
MONEY = re.compile(r'((?:net|won|lost|win|loss|losses|winnings|profit|deposit|wager|stake)[^£\n]{0,40}£\s?-?\d+[.,]\d{2})', re.I)
MIN_CONF = 60.0


def _arr(img):
    return np.asarray(img.convert('RGB'), dtype=np.int16)


def _runs(mask, min_len):
    """[(start, end)] of consecutive True in a 1-D bool array, at least min_len long."""
    out, start = [], None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= min_len:
                out.append((start, i))
            start = None
    if start is not None and len(mask) - start >= min_len:
        out.append((start, len(mask)))
    return out


def light_panels(img):
    """Light rectangles [(l, t, r, b)]: rows with enough light pixels, their column block, merged vertically where the
    dialog's dark-green buttons break the rows."""
    a = _arr(img)
    h, w = a.shape[:2]
    light = a.min(axis=2) >= LIGHT
    band = light[:, int(w * 0.15):int(w * 0.85)]
    rows = band.sum(axis=1) >= 0.2 * band.shape[1]
    panels = []
    for t, b in _runs(rows, 20):
        cols = light[t:b].mean(axis=0) >= 0.5
        blocks = _runs(cols, 40)
        if not blocks:
            continue
        l, r = max(blocks, key=lambda x: x[1] - x[0])
        if panels and abs(panels[-1][0] - l) <= 8 and abs(panels[-1][2] - r) <= 8 and t - panels[-1][3] <= 200:
            pl, pt, pr, pb = panels[-1]
            panels[-1] = (min(pl, l), pt, max(pr, r), b)
        else:
            panels.append((l, t, r, b))
    return panels


def modal_panel(img):
    """The centred light dialog in the upper part of the viewport, or None (the betslip floats lower down)."""
    w, h = img.size
    for l, t, r, b in light_panels(img):
        cx, width, height = (l + r) / 2, r - l, b - t
        if abs(cx - w / 2) <= 0.08 * w and 0.18 * w <= width <= 0.55 * w and t <= 0.5 * h and height >= 0.15 * h:
            return (l, t, r, b)
    return None


def green_buttons(img, panel):
    """The dialog's solid green buttons inside the panel: [(l, t, r, b)] top to bottom."""
    l, t, r, b = panel
    a = _arr(img)[t:b, l:r]
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    green = (G - R >= 50) & (G - B >= 15) & (G >= 60) & (G <= 200)
    rows = green.mean(axis=1) >= 0.5
    out = []
    for bt, bb in _runs(rows, 18):
        mid = green[(bt + bb) // 2]
        blocks = _runs(mid | green[bt + 2], 40)
        if not blocks:
            continue
        bl, br = max(blocks, key=lambda x: x[1] - x[0])
        out.append((l + bl, t + bt, l + br, t + bb))
    return out


def _words_text(words, tol=6):
    """Reading order: words clustered into lines by their top (within tol px), each line left to right."""
    lines = []
    for x in sorted(words, key=lambda x: x['t']):
        if lines and abs(x['t'] - lines[-1][0]) <= tol:
            lines[-1][1].append(x)
        else:
            lines.append([x['t'], [x]])
    return ' '.join(' '.join(y['text'] for y in sorted(ws, key=lambda y: y['l'])) for _, ws in lines)


def read_dialog(img, ocr=None):
    """Everything about an open Reality Check dialog (see the module doc). found=False when no dialog panel shows."""
    if ocr is None:
        from desktop_worker.visual_slip import ocr_words as ocr
    panel = modal_panel(img)
    if panel is None:
        return dict(found=False, target=None, reason='no dialog panel on the screen')
    words = ocr(img, panel)
    text = _words_text(words)
    buttons = []
    for rect in green_buttons(img, panel):
        bw = [x for x in ocr(img, rect, invert=True) if re.search(r'[A-Za-z]', x['text'])]
        btext = ' '.join(x['text'] for x in sorted(bw, key=lambda x: x['l']))
        buttons.append(dict(rect=list(rect), text=btext, words=[dict(text=x['text'], conf=x.get('conf')) for x in bw]))
    full = ' '.join([text] + [x['text'] for x in buttons])
    elapsed = ELAPSED.search(full)
    interval = INTERVAL.search(full)
    info = dict(found=True, panel=list(panel), text=full[:600], buttons=buttons,
                title=bool(TITLE.search(full)), signature=bool(TITLE.search(full) and SIGNATURE.search(full)),
                session_elapsed=re.sub(r'\s', '', elapsed.group(1)).replace('.', ':') if elapsed else None,
                interval_min=int(interval.group(1)) if interval else None,
                money=[m.strip() for m in MONEY.findall(full)][:4], target=None)
    info['reason'] = _target(info, panel)
    return info


def _target(info, panel):
    """Sets info['target'] only for an unambiguous, high-confidence 'Remain Logged In'; returns the reason otherwise."""
    if not info['signature']:
        return 'dialog is not recognisably the Reality Check (title + its own sentence not both read)'
    hits = []
    for b in info['buttons']:
        low = {x['text'].lower().strip('.,:;'): float(x['conf'] or 0) for x in b['words']}
        if 'remain' in low or 'logged' in low:
            hits.append((b, low))
    if len(hits) != 1:
        return f"{'no' if not hits else len(hits)} button(s) read as 'Remain Logged In'; not clicking"
    b, low = hits[0]
    if not ('remain' in low and 'logged' in low and low['remain'] >= MIN_CONF and low['logged'] >= MIN_CONF):
        return f"'Remain Logged In' read with low confidence {low}; not clicking"
    rest = re.sub(r'(?i)\b(remain|logged|in)\b', '', b['text'])
    if FORBIDDEN.search(b['text']) or re.search(r'[A-Za-z]{3,}', rest):
        return f"button text {b['text']!r} is not exactly 'Remain Logged In'; not clicking"
    l, t, r, bb = b['rect']
    pl, pt, pr, pb = panel
    if not (pl <= l and r <= pr and pt <= t and bb <= pb) or not (18 <= bb - t <= 90) or (r - l) < 0.5 * (pr - pl):
        return f'button rectangle {b["rect"]} is not a dialog button; not clicking'
    info['target'] = dict(x=(l + r) // 2, y=(t + bb) // 2, rect=b['rect'], text=b['text'])
    return 'recognised'


def suspect(text):
    """Any Reality Check wording in OCR text (the first suspicion blocks routing)."""
    return bool(SUSPECT.search(' '.join((text or '').split())))


def same_target(a, b, tol=6):
    return bool(a and b and abs(a['x'] - b['x']) <= tol and abs(a['y'] - b['y']) <= tol)


def near_rect(x, y, rect, margin):
    l, t, r, b = rect
    return l - margin <= x <= r + margin and t - margin <= y <= b + margin


def message_info(d):
    """What the dialog showed, for David's Telegram message and the log (no account data beyond what the dialog shows)."""
    parts = []
    if d.get('session_elapsed'):
        parts.append(f"session time shown: {d['session_elapsed']}")
    if d.get('interval_min'):
        parts.append(f"reminder interval shown: every {d['interval_min']} minutes")
    parts.append('win/loss shown: ' + ('; '.join(d['money']) if d.get('money') else 'none on the dialog'))
    return parts
