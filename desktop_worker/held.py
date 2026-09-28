"""Server-side HOLD record, PLACE_HELD and MY_BETS for the desktop worker (routing work, 28 Sep 2026).

HOLD       an ADAPTER_WORKFLOW 'hold' that reaches COMPLETE_EXECUTION_READY stores the verified slip terms (and their
           sha256) in the ledger's holds table; the result carries held=True, event_context and terms_hash, so the
           backend's own Pipeline.place_held_payload builds the approved PLACE_HELD from it.
PLACE_HELD refused before the page is touched unless: confirmation_status APPROVED; the held instruction exists, is not
           consumed and is no older than hold_max_age_seconds; the approved terms equal the held terms; stake <= the
           per-bet cap (max_stake_per_bet, default 0.10) and today's live stake stays within max_daily_live_stake; no
           intent was ever recorded for this instruction or its hold (an intent without a confirmed receipt ->
           PLACEMENT_UNKNOWN, next step MY_BETS); the session is LOGGED_IN. Then a stop-prompt scan and a FRESH screenshot
           re-verified against the held terms (final_action.Placement.verify_preclick), the hold age once more, and the
           intent committed. Only then ONE click - and only when the live click is enabled by BOTH the config flag
           live_click_enabled=true AND the environment DESKTOP_LIVE_CLICK=1. Otherwise (the default) it is a DRY RUN:
           everything except the physical click, reported as placement.outcome DRY_RUN with would_click coordinates.
MY_BETS    the header 'My Bets' link (ordinary navigation), a screenshot and thresholded OCR of the cards; returns
           my_bets={view, url, lines:[{text, frame, top, left}]} in core.bet_matching's shape, plus a match verdict when
           the instruction carries the bet terms. Nothing on a bet is clicked.
"""
import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path

from desktop_worker import betslip
from desktop_worker.ledger import now_ms

ROOT = Path(__file__).resolve().parents[1]
LIVE_ENV = 'DESKTOP_LIVE_CLICK'
DEFAULTS = dict(max_stake_per_bet='0.10', hold_max_age_seconds=115, live_click_enabled=False, max_daily_live_stake='0.50')
MARKERS = ROOT / '.local' / 'final-action'
FINAL_EVIDENCE = ROOT / 'evidence' / 'desktop-worker-final-action'


def limits(cfg):
    return {k: (cfg or {}).get(k, v) for k, v in DEFAULTS.items()}


def live_click_enabled(cfg, env=None):
    env = os.environ if env is None else env
    return (cfg or {}).get('live_click_enabled') is True and env.get(LIVE_ENV) == '1'


def terms_hash(terms):
    return hashlib.sha256(json.dumps(terms, sort_keys=True, default=str).encode()).hexdigest()


def hold_terms(body, result, ready):
    """The verified slip terms kept for PLACE_HELD (the verified context plus what the approval must repeat)."""
    sel = result.get('selection') or {}
    return dict(event_url=result.get('event_url') or body.get('event_url'), sport=body.get('sport'), market=body.get('market'),
                side=body.get('side'), line=sel.get('line') or '', selection_name=sel.get('selection_name'), price=sel.get('price'),
                minimum_price=body.get('minimum_price'), stake=body.get('stake'), event_context=result.get('event_context'),
                ready=json.loads(json.dumps(ready, default=str)))


def _same_money(a, b):
    return betslip.money(a) is not None and betslip.money(a) == betslip.money(b)


def terms_problems(body, held):
    """Differences between the approved PLACE_HELD and the held terms (empty when they agree)."""
    out = []
    t = held['terms']
    for key in ('sport', 'side'):
        if str(body.get(key) or '') != str(t.get(key) or ''):
            out.append(f"{key} {body.get(key)!r} != held {t.get(key)!r}")
    if (body.get('selection_name') or '').strip().lower() != (t.get('selection_name') or '').strip().lower():
        out.append(f"selection_name {body.get('selection_name')!r} != held {t.get('selection_name')!r}")
    if str(body.get('line') or '') != str(t.get('line') or '') and t.get('market') not in ('ML', 'MONEYLINE', '1X2'):
        out.append(f"line {body.get('line')!r} != held {t.get('line')!r}")
    for key in ('stake', 'minimum_price', 'price'):
        if not _same_money(body.get(key), t.get(key)):
            out.append(f"{key} {body.get(key)!r} != held {t.get(key)!r}")
    ctx = t.get('event_context') or {}
    for key in ('home', 'away'):
        if body.get(key) and ctx.get(key) and body[key] != ctx[key]:
            out.append(f"{key} {body.get(key)!r} != held {ctx.get(key)!r}")
    return out


def day_start_ms():
    d = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    return int(d.timestamp() * 1000)


def refusal(iid, stage, detail, outcome='NOT_TAPPED', **extra):
    placement = dict(tapped=False if outcome != 'PLACEMENT_UNKNOWN' else None, outcome=outcome, detail=detail)
    if outcome == 'PLACEMENT_UNKNOWN':
        placement['next_step'] = 'MY_BETS'
    return dict(instruction_id=iid, status='FAIL', stage=stage, detail=detail, wager_submitted=False if outcome != 'PLACEMENT_UNKNOWN' else None,
                placement=placement, **extra)


def precheck(worker, body, clock=None):
    """Every PLACE_HELD refusal that needs no page: (None, held) when it may proceed to the screen re-verify."""
    iid = body['instruction_id']
    lim = limits(worker.cfg)
    now = clock() if clock else now_ms()
    if body.get('confirmation_status') != 'APPROVED':
        return refusal(iid, 'NOT_APPROVED', f"confirmation_status is {body.get('confirmation_status')!r}, not APPROVED"), None
    stake = betslip.money(body.get('stake'))
    cap = betslip.money(lim['max_stake_per_bet'])
    if stake is None or stake <= 0 or cap is None or stake > cap + 1e-9:
        return refusal(iid, 'STAKE_CAP', f"stake {body.get('stake')!r} is above the desktop per-bet cap {lim['max_stake_per_bet']}"), None
    held_id = body.get('held_instruction_id')
    prior = worker.ledger.intent_for(iid, held_id)
    if prior:
        if prior.get('outcome') == 'PLACED':
            return refusal(iid, 'ALREADY_PLACED', f"Place Bet was already clicked for {prior['instruction_id']} (reference "
                                                   f"{prior.get('reference')}); never clicked twice", intent=prior), None
        if prior.get('live'):
            return refusal(iid, 'PLACEMENT_UNKNOWN', f"a click intent was recorded for {prior['instruction_id']} at {prior['intent_at_ms']} "
                                                      f"without a confirmed receipt; never clicked again - reconcile on MY_BETS",
                           outcome='PLACEMENT_UNKNOWN', next_step='MY_BETS', intent=prior), None
        return refusal(iid, 'HOLD_CONSUMED', f"PLACE_HELD already ran for this hold ({prior['instruction_id']}, {prior.get('outcome')})"), None
    held = worker.ledger.hold(held_id) if held_id else None
    if held is None:
        return refusal(iid, 'HOLD_NOT_FOUND', f'no verified hold {held_id!r} on the desktop worker'), None
    if held.get('consumed_by'):
        return refusal(iid, 'HOLD_CONSUMED', f"hold {held_id} was already used by {held['consumed_by']}"), None
    age = (now - held['held_at_ms']) / 1000
    if age > float(lim['hold_max_age_seconds']):
        return refusal(iid, 'HOLD_EXPIRED', f"hold {held_id} is {age:.0f}s old (> hold_max_age {lim['hold_max_age_seconds']}s); verify a new hold"), None
    problems = terms_problems(body, held)
    if problems:
        return refusal(iid, 'TERMS_MISMATCH', f'approved terms differ from the held slip: {problems}'), None
    if live_click_enabled(worker.cfg):
        spent = worker.ledger.live_stake_on(day_start_ms())
        daily = betslip.money(lim['max_daily_live_stake'])
        if daily is not None and spent + stake > daily + 1e-9:
            return refusal(iid, 'DAILY_LIMIT', f'today live stake {spent:.2f} + {stake:.2f} exceeds max_daily_live_stake {lim["max_daily_live_stake"]}'), None
    blocked = worker.blocked_reason()
    if blocked:
        return refusal(iid, 'SESSION_REQUIRED' if blocked != 'REALITY_CHECK' else 'SESSION_EXPIRED',
                       f'desktop worker blocked: {blocked}'), None
    return None, held


async def place_held(worker, body, page, decisions, run, clock=None, placement_factory=None):
    """PLACE_HELD after an approval: returns the result dict. Physical click only when live_click_enabled()."""
    from desktop_worker.final_action import Placement, Refused
    from desktop_worker.workflow import Failure
    iid = body['instruction_id']
    refused, held = precheck(worker, body, clock)
    if refused:
        return refused
    lim = limits(worker.cfg)
    live = live_click_enabled(worker.cfg)
    t = held['terms']
    p = (placement_factory or Placement)(page, decisions, dict(body), key=iid, out=run.dir)
    p.run = run
    ready = dict(t['ready'])
    ready['teams'] = tuple(ready['teams'])
    p.site.ready = ready
    rec = dict(held_instruction_id=held['instruction_id'], terms_hash=held['terms_hash'], mode='LIVE' if live else 'DRY_RUN', clicks=0)
    run.stage('REVERIFY_HELD')
    try:
        actual, state = await p.verify_preclick(ready, body['stake'], rec)
    except (Refused, Failure) as e:
        detail = getattr(e, 'detail', None) or str(e)
        return refusal(iid, 'PRE_TAP_REJECTED', f'fresh re-verify failed: {detail}'[:600], preclick=rec.get('preclick'))
    if not _same_money(actual.get('price'), t.get('price')):
        return refusal(iid, 'PRICE_CHANGED', f"slip price {actual.get('price')} is not the held {t.get('price')}", preclick=rec.get('preclick'))
    now = clock() if clock else now_ms()
    age = (now - held['held_at_ms']) / 1000
    if age > float(lim['hold_max_age_seconds']):
        return refusal(iid, 'HOLD_EXPIRED', f"hold aged {age:.0f}s during the re-verify (> {lim['hold_max_age_seconds']}s)")
    if not worker.ledger.record_intent(iid, held['instruction_id'], held['terms_hash'], live, body['stake'], actual.get('price'),
                                       source='server-live' if live else 'server-dry-run'):
        return refusal(iid, 'PLACEMENT_UNKNOWN', 'an intent appeared for this instruction; never clicked twice',
                       outcome='PLACEMENT_UNKNOWN', next_step='MY_BETS')
    worker.ledger.consume_hold(held['instruction_id'], iid)
    pb = state['place_bet']
    run.put('preclick', rec.get('preclick'))
    if not live:
        worker.ledger.settle_intent(iid, 'DRY_RUN', detail='dry run: everything except the physical click')
        run.stage('DRY_RUN_NO_CLICK')
        return dict(instruction_id=iid, status='PASS', stage='DRY_RUN', wager_submitted=False,
                    detail='DRY RUN: held slip re-verified on a fresh screenshot and the intent recorded; Place Bet NOT clicked '
                           '(live click disabled: needs live_click_enabled=true and DESKTOP_LIVE_CLICK=1)',
                    placement=dict(tapped=False, outcome='DRY_RUN', dry_run=True, would_click=dict(x=pb['centre'][0], y=pb['centre'][1]),
                                   price=actual.get('price'), stake=body['stake'], to_return=state.get('to_return')),
                    held_instruction_id=held['instruction_id'], terms_hash=held['terms_hash'], preclick=rec.get('preclick'))
    # ---- live path (disabled unless both flags are set)
    from desktop_worker import visual_slip as vs

    async def clicker(x, y):
        await vs.click(page, x, y)
    run.stage('PLACE_BET')
    try:
        verdict = await p.click_and_watch(state, actual, body['stake'], rec, clicker)
    except Exception as e:
        worker.ledger.settle_intent(iid, 'PLACEMENT_UNKNOWN', detail=f'{type(e).__name__}: {e}'[:300])
        return refusal(iid, 'PLACEMENT_UNKNOWN', f'error after the click intent: {type(e).__name__}: {e}'[:400],
                       outcome='PLACEMENT_UNKNOWN', next_step='MY_BETS')
    if verdict['outcome'] == 'PLACED':
        worker.ledger.settle_intent(iid, 'PLACED', verdict.get('reference'), detail=verdict.get('reference_source'))
        return dict(instruction_id=iid, status='PASS', stage='PLACED', wager_submitted=True, detail=f"PLACED {verdict.get('reference')}",
                    placement=dict(tapped=True, outcome='PLACED', bet_reference=verdict.get('reference'), receipt_text=rec.get('receipt_text'),
                                   price=actual.get('price'), stake=body['stake']), held_instruction_id=held['instruction_id'])
    worker.ledger.settle_intent(iid, 'PLACEMENT_UNKNOWN', verdict.get('reference'), detail=verdict.get('reason'))
    return dict(instruction_id=iid, status='FAIL', stage='PLACEMENT_UNKNOWN', wager_submitted=None, next_step='MY_BETS',
                detail=f"no clear receipt ({verdict.get('reason')}); never clicked again - reconcile on MY_BETS",
                placement=dict(tapped=True, outcome='PLACEMENT_UNKNOWN', next_step='MY_BETS', receipt_text=rec.get('receipt_text')))


# ------------------------------------------------------------------------------------------------ MY_BETS
def _strip_ocr(img, box, scale=3, thr=150):
    import pytesseract
    from PIL import Image, ImageOps
    g = ImageOps.invert(img.crop(box).convert('L')).point(lambda v: 255 if v > thr else 0)
    g = g.resize((g.width * scale, g.height * scale), Image.LANCZOS)
    return ' '.join(pytesseract.image_to_string(g, config='--psm 7').split())


def card_lines(img, frame=1, top_offset=0, box=None):
    """Thresholded OCR of the dark My Bets cards (grayscale -> invert -> threshold 150 -> x2 -> psm 6), one entry per line.
    A line that starts with an icon (a team flag / radio mark read as '@', '©)', '®') is re-read from just right of the
    icon on its own (psm 7): the flag next to a capital 'I' made 'Italy' read as 'ttay' (28 Sep 2026)."""
    import pytesseract
    from PIL import Image, ImageOps
    from desktop_worker import visual_slip  # noqa: F401  (sets the tesseract path)
    crop = img.crop(box) if box else img
    g = ImageOps.invert(crop.convert('L')).point(lambda v: 255 if v > 150 else 0)
    g = g.resize((g.width * 2, g.height * 2), Image.LANCZOS)
    d = pytesseract.image_to_data(g, config='--psm 6', output_type=pytesseract.Output.DICT)
    rows = {}
    for i, text in enumerate(d['text']):
        text = (text or '').strip()
        if not text:
            continue
        key = (d['block_num'][i], d['par_num'][i], d['line_num'][i])
        r = rows.setdefault(key, dict(words=[], top=d['top'][i], left=d['left'][i], bottom=0))
        r['words'].append(dict(text=text, left=d['left'][i]))
        r['top'], r['left'] = min(r['top'], d['top'][i]), min(r['left'], d['left'][i])
        r['bottom'] = max(r['bottom'], d['top'][i] + d['height'][i])
    ox, oy = (box[0], box[1]) if box else (0, 0)
    out = []
    for r in rows.values():
        words = r['words']
        text = ' '.join(w['text'] for w in words)
        if len(words) >= 2 and not any(ch.isalnum() for ch in words[0]['text']):
            x0 = ox + words[1]['left'] // 2 - 3
            y0, y1 = oy + r['top'] // 2 - 4, oy + r['bottom'] // 2 + 4
            try:
                again = _strip_ocr(img, (max(x0, 0), max(y0, 0), img.width, min(y1, img.height)))
            except Exception:
                again = ''
            if again:
                text = again
        out.append(dict(text=text, frame=frame, top=oy + r['top'] // 2 + top_offset, left=ox + r['left'] // 2))
    return sorted(out, key=lambda r: (r['top'], r['left']))


def match_terms(body):
    """bet_matching terms from a MY_BETS instruction; team/selection names folded to ASCII like the OCR ('Türkiye' is read
    'Turkiye' from the card)."""
    import unicodedata

    def fold(v):
        return unicodedata.normalize('NFKD', v).encode('ascii', 'ignore').decode() if isinstance(v, str) else v
    terms = {k: body.get(k) for k in ('home', 'away', 'market', 'selection', 'line', 'stake', 'bet_reference', 'selection_name', 'kickoff_utc')}
    for k in ('home', 'away', 'selection_name'):
        terms[k] = fold(terms[k])
    terms['odds'] = body.get('price')
    return terms


async def my_bets(worker, body, page, run):
    """Read-only My Bets (Open): header link, screenshot, thresholded OCR -> bet_matching shape (+ a match verdict)."""
    from desktop_worker import visual_slip as vs
    from desktop_worker.final_action import ocr_text, stop_prompt
    iid = body['instruction_id']
    run.stage('OPEN_MY_BETS')
    img, png = await vs.screenshot(page)
    w, h = img.size
    hw, htext = ocr_text(img, (0, 0, w, 80))
    run.save_look('mybets_before', png, dict(present=False, words=hw))
    p = stop_prompt(htext)
    if p in ('reality check', 'log in'):
        return dict(instruction_id=iid, status='FAIL', stage='SESSION_REQUIRED', detail=f'stop prompt before My Bets: {p}', wager_submitted=False)
    if '#/MB/' not in (page.url or ''):
        pair = next(((a, b) for a in hw for b in hw if a['text'] == 'My' and b['text'] == 'Bets'
                     and abs((a['t'] + a['b']) - (b['t'] + b['b'])) <= 16 and 0 < b['l'] - a['r'] <= 14), None)
        if not pair:
            return dict(instruction_id=iid, status='FAIL', stage='TARGET_NOT_FOUND', detail="header 'My Bets' not found on the screen",
                        wager_submitted=False)
        await vs.click(page, round((pair[0]['l'] + pair[1]['r']) / 2), round((pair[0]['t'] + pair[1]['b']) / 2))
        await page.wait_for_timeout(3500)
    run.stage('READ_MY_BETS')
    img, png = await vs.screenshot(page)
    words, text = ocr_text(img, (0, 60, w, h))
    run.save_look('mybets_open', png, dict(present=False, words=words))
    p = stop_prompt(text)
    if p in ('reality check', 'remain logged in', 'captcha', 'verification'):
        return dict(instruction_id=iid, status='FAIL', stage='SESSION_REQUIRED', detail=f'stop prompt on My Bets: {p}', wager_submitted=False)
    url = page.url or ''
    lines = [dict(text=url.replace('https://www.', ''), frame=1, top=0, left=0)] + card_lines(img, frame=1, box=(0, 60, w, h))
    (run.dir / 'my_bets_lines.json').write_text(json.dumps(lines, indent=1, ensure_ascii=False), encoding='utf-8')
    view = body.get('view') or 'OPEN'
    data = dict(view=view, url=url[:120], lines=lines, frames=1)
    out = dict(instruction_id=iid, status='PASS', stage='MY_BETS_READ', wager_submitted=False, my_bets=data,
               detail=f'My Bets read: {len(lines) - 1} OCR lines (read-only; nothing on a bet was clicked)')
    if body.get('home') and body.get('away'):
        from core import bet_matching
        terms = match_terms(body)
        try:
            out['match'] = bet_matching.match(terms, data)
        except ValueError as e:
            out['match'] = dict(found=False, error=str(e)[:200])
    return out
