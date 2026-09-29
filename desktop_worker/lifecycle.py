"""Dedicated-Chrome lifecycle for the desktop worker: detect that Chrome has stopped, relaunch the SAME profile
detached (chrome.launch), and read the Bet365 session state from a screenshot (CDP Page.captureScreenshot + Tesseract;
no script in the page): LOGGED_IN / LOGGED_OUT / REALITY_CHECK / UNKNOWN.

Never logs in. A Reality Check is only ever acknowledged by the worker's idle probe (server.Worker._auto_ack, David's
instruction of 29 Sep 2026: one click on 'Remain Logged In' when recognised with high confidence); nothing here clicks.
LOGGED_IN needs positive evidence (classify / assess): 'My Bets', the balance and the sports navigation in the top bar, no
Reality Check wording in the middle of the page and no light dialog panel over it. Anything else is REALITY_CHECK /
LOGGED_OUT / UNKNOWN and leaves the worker fail-closed, with an operator_alert (workflow.operator_notice: on the
result/health and in logs/desktop_worker.log) telling David what to do.
Worker identity (device_id desktop-chrome, worker_id, account fingerprint in .local/desktop_worker.json) is never
touched here.

    py -3.11 -m desktop_worker.lifecycle            # status; relaunch if down; session state; evidence saved
"""
import asyncio
import json
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

from desktop_worker import chrome
from desktop_worker import reality_check as rc

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'evidence' / 'desktop-worker-lifecycle'
HOME = 'https://www.bet365.com/#/HO/'
ALERTS = {
    'LOGGED_OUT': ('SESSION_LOGGED_OUT', 'SESSION_REQUIRED',
                   "Bet365 is logged out in the desktop worker's Chrome: log in by hand in that Chrome window on the mini PC; "
                   'the worker never logs in'),
    'REALITY_CHECK': ('REALITY_CHECK_OPEN', 'SESSION_EXPIRED',
                      "Bet365 Reality Check is open in the desktop worker's Chrome and was not acknowledged automatically: "
                      'answer it by hand on the mini PC'),
    'UNKNOWN': ('SESSION_UNKNOWN', 'SESSION_REQUIRED',
                "Bet365 session state could not be read in the desktop worker's Chrome: check that window on the mini PC; "
                'a login, verification or other prompt may be open'),
    'CHROME_DOWN': ('CHROME_DOWN', 'INTERNAL_ERROR',
                    "The desktop worker's dedicated Chrome is not running and could not be restarted: start it on the mini PC with "
                    'py -3.11 -m desktop_worker.lifecycle'),
}


# ------------------------------------------------------------------------------------------------ process
def chrome_pids(profile=chrome.PROFILE, run=subprocess.run):
    """PIDs of chrome.exe processes using the dedicated profile (read-only process list)."""
    cmd = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | Where-Object { $_.CommandLine -like $env:MB_PROFILE_LIKE "
           "-and $_.CommandLine -notlike '*--type=*' } | ForEach-Object { $_.ProcessId }")
    import os
    try:
        out = run(['powershell', '-NoProfile', '-NonInteractive', '-Command', cmd], capture_output=True, text=True, timeout=30,
                  env=dict(os.environ, MB_PROFILE_LIKE=f'*--user-data-dir={profile}*'))
    except Exception:
        return None
    return [int(x) for x in (out.stdout or '').split() if x.isdigit()]


def status(port=chrome.PORT, probe=None, pids=None):
    """{cdp_up, running (a browser process with the profile exists; None when unknown), state UP / HUNG / DOWN}."""
    up = (probe or chrome._listening)(port)
    procs = None if up else (pids or chrome_pids)()
    state = 'UP' if up else ('HUNG' if procs else 'DOWN')
    return dict(cdp_up=up, running=True if up else (bool(procs) if procs is not None else None), pids=procs, state=state,
                checked_at_ms=int(time.time() * 1000))


# ------------------------------------------------------------------------------------------------ session state
BALANCE = re.compile(r'£\s?\d+[.,]\d{2}|(?<![\d.,])\d{1,6}[.,]\d{2}(?![\d])')   # the header's only decimal is the balance
NAV = re.compile(r'In-Play|All Sports')


def classify(header_text, centre_text):
    """Session state from the OCR of the top bar and of the centre of the viewport. LOGGED_IN only on positive evidence:
    'My Bets' AND the balance AND the sports navigation in the top bar, and no Reality Check wording in the centre.
    Any Reality Check wording at all (title or one of its sentences) is REALITY_CHECK: the first suspicion blocks."""
    h, c = ' '.join((header_text or '').split()), ' '.join((centre_text or '').split())
    if rc.suspect(c):
        # 28 Sep 2026 22:28-22:32 BST: OCR sometimes misses the buttons (or the title) while the dialog is open
        full = 'Reality Check' in c and re.search(r'Remain Logged In|Log ?out|session has now exceeded|requested a Reality Check|'
                                                  r'Review Your Account History', c)
        return 'REALITY_CHECK', 'Reality Check dialog open' if full else 'Reality Check wording read: treated as open'
    if re.search(r'\bLog In\b', h) or re.search(r'\bJoin\b', h):
        return 'LOGGED_OUT', "top bar shows 'Log In' / 'Join'"
    if re.search(r'\b(Password|Username)\b', c) and re.search(r'\bLog In\b', c):
        return 'LOGGED_OUT', 'login form open'
    if re.search(r'verification|captcha|not a robot|enter the code', c, re.I):
        return 'UNKNOWN', 'verification / captcha prompt'
    signals = dict(my_bets=bool(re.search(r'\bMy Bets\b', h)), balance=bool(BALANCE.search(h)), nav=bool(NAV.search(h)))
    if all(signals.values()):
        return 'LOGGED_IN', "top bar shows 'My Bets', the balance and the sports navigation; no dialog wording"
    if signals['my_bets'] or signals['balance']:
        return 'UNKNOWN', 'only some logged-in markers read (' + ', '.join(k for k, v in signals.items() if not v) + ' missing)'
    return 'UNKNOWN', 'neither logged-in nor logged-out markers read'


def _ocr_regions(img):
    from desktop_worker import visual_slip as vs
    w, h = img.size
    header = vs.ocr_words(img, (0, 0, w, 60), invert=True) + vs.ocr_words(img, (0, 0, w, 60))
    centre = vs.ocr_words(img, (int(w * 0.25), int(h * 0.15), int(w * 0.75), int(h * 0.6)))
    return ' '.join(x['text'] for x in sorted(header, key=lambda x: x['l'])), ' '.join(x['text'] for x in centre)


def assess(img, dialog_reader=None):
    """{state, detail, header_text, centre_text, signals, dialog} from a screenshot (PIL image). Independent signals:
    the top-bar markers, Reality Check wording in the centre, and a light dialog panel over the page (pixels). A light
    panel that is not recognisably the Reality Check makes the read UNKNOWN, never LOGGED_IN."""
    ht, ct = _ocr_regions(img)
    state, detail = classify(ht, ct)
    panel = rc.modal_panel(img)
    dialog = None
    if panel is not None or state == 'REALITY_CHECK':
        dialog = (dialog_reader or rc.read_dialog)(img)
        if dialog.get('found') and dialog.get('title'):
            state, detail = 'REALITY_CHECK', 'Reality Check dialog open' + ('' if dialog.get('signature') else ' (its sentence not read)')
        elif dialog.get('found') and state != 'REALITY_CHECK':
            state, detail = 'UNKNOWN', 'an unrecognised dialog panel is open over the page'
    signals = dict(my_bets=bool(re.search(r'\bMy Bets\b', ht)), balance=bool(BALANCE.search(ht)), nav=bool(NAV.search(ht)),
                   dialog_wording=rc.suspect(ct), modal_panel=list(panel) if panel else None)
    return dict(state=state, detail=detail, header_text=ht, centre_text=ct, signals=signals, dialog=dialog)


def read_state(img):
    """(state, detail, header_text, centre_text) from a screenshot (PIL image)."""
    a = assess(img)
    return a['state'], a['detail'], a['header_text'], a['centre_text']


async def session_state(page, out_dir=None, name='session'):
    """One screenshot-only read (CDP Page.captureScreenshot). The frame itself is returned under '_img' / '_png' for the
    caller (the Reality Check click target is taken from this same frame); those keys are never published."""
    from desktop_worker import visual_slip as vs
    img, png = await vs.screenshot(page)
    a = assess(img)
    shot = None
    if out_dir:
        out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
        shot = out_dir / f'{name}.png'
        shot.write_bytes(png)
        extra = ''
        if a['dialog']:
            d = a['dialog']
            extra = (f"DIALOG: {d.get('text', '')}\nTARGET: {d.get('target')}\nREASON: {d.get('reason')}\n")
        (out_dir / f'{name}.ocr.txt').write_text(f"HEADER: {a['header_text']}\nCENTRE: {a['centre_text']}\nSTATE: {a['state']} "
                                                 f"({a['detail']})\nSIGNALS: {json.dumps(a['signals'])}\n{extra}", encoding='utf-8')
    return dict(state=a['state'], detail=a['detail'], url=(page.url or '')[:120], screenshot=str(shot) if shot else None,
                observed_at_ms=int(time.time() * 1000), signals=a['signals'], dialog=a['dialog'], _img=img, _png=png)


def alert_for(state, run_id=None, instruction_id=None):
    """operator_alert for a state that keeps the worker fail-closed (None for LOGGED_IN), through the existing path."""
    if state == 'LOGGED_IN':
        return None
    from desktop_worker.workflow import operator_notice
    code, stage, message = ALERTS.get(state, ALERTS['UNKNOWN'])
    return operator_notice(code, stage, message, instruction_id=instruction_id, run_id=run_id)


# ------------------------------------------------------------------------------------------------ recovery
async def recover(pw, port=chrome.PORT, profile=chrome.PROFILE, out_dir=None, launcher=None, probe=None, wait_s=25):
    """Chrome down -> relaunch the same profile detached; then (always) read the session state on a Bet365 page.
    Returns {chrome_before, relaunched, launch, session, alert, browser, page}."""
    probe = probe or chrome._listening
    before = status(port, probe=probe)
    launch = None
    if not before['cdp_up']:
        launch = (launcher or chrome.launch)(port, profile)
        deadline = time.monotonic() + wait_s
        while not probe(port):
            if time.monotonic() > deadline:
                alert = alert_for('CHROME_DOWN')
                return dict(chrome_before=before, relaunched=False, launch=launch, session=dict(state='UNKNOWN', detail='CDP port did not open'),
                            alert=alert, browser=None, page=None)
            await asyncio.sleep(0.5)
    browser, context, page = await chrome.connect(pw, port)
    if 'bet365.com' not in (page.url or ''):
        await page.goto(HOME, wait_until='domcontentloaded', timeout=30000)     # ordinary navigation, nothing typed
    session = None
    for k in range(8):                              # the top bar renders a few seconds after the shell
        await page.wait_for_timeout(2500 if k == 0 else 1500)
        session = await session_state(page, out_dir, name=f'session_{k + 1:02d}')
        if session['state'] != 'UNKNOWN':
            break
    session = {k: v for k, v in session.items() if not k.startswith('_')}
    return dict(chrome_before=before, relaunched=launch is not None, launch=launch, session=session,
                alert=alert_for(session['state']), browser=browser, page=page)


def main():
    async def go():
        from playwright.async_api import async_playwright
        out = EVIDENCE / datetime.now().strftime('%Y%m%d-%H%M%S')
        async with async_playwright() as pw:
            r = await recover(pw, out_dir=out)
        slim = {k: v for k, v in r.items() if k not in ('browser', 'page')}
        out.mkdir(parents=True, exist_ok=True)
        (out / 'lifecycle.json').write_text(json.dumps(slim, indent=1, default=str), encoding='utf-8')
        print(json.dumps(dict(slim, evidence=str(out)), indent=1, default=str))
    asyncio.run(go())


if __name__ == '__main__':
    main()
