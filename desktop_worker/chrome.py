"""The desktop worker's own Chrome: the installed Google Chrome with a dedicated profile directory, driven over the
Chrome DevTools Protocol on a loopback port (Playwright connect_over_cdp).

No Multilogin and no antidetect layer: an ordinary Chrome window the operator can see, sign in to by hand and take over at
any time. The profile keeps the Bet365 session between runs. Credentials are never typed, stored or read by this code.
"""
import os
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHROME = Path(os.environ.get('PROGRAMFILES', r'C:\Program Files')) / 'Google' / 'Chrome' / 'Application' / 'chrome.exe'
PROFILE = ROOT / '.local' / 'desktop-chrome-profile'
PORT = 9333


def _listening(port=PORT):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/version', timeout=1) as r:
            return r.status == 200
    except OSError:
        return False


def ensure_chrome(port=PORT, profile=PROFILE, chrome=CHROME, wait_s=20):
    """Start the dedicated Chrome if its debugging port is not answering; returns the CDP endpoint URL."""
    if not _listening(port):
        profile.mkdir(parents=True, exist_ok=True)
        subprocess.Popen([str(chrome), f'--remote-debugging-port={port}', '--remote-debugging-address=127.0.0.1',
                          f'--user-data-dir={profile}', '--no-first-run', '--no-default-browser-check',
                          '--window-size=1400,1000', 'about:blank'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, 'DETACHED_PROCESS', 0))
        deadline = time.monotonic() + wait_s
        while not _listening(port):
            if time.monotonic() > deadline:
                raise RuntimeError(f'Chrome debugging port {port} did not open')
            time.sleep(0.3)
    return f'http://127.0.0.1:{port}'


async def connect(playwright, port=PORT):
    """(browser, context, page): the dedicated Chrome's default context and one Bet365 tab (reused, never duplicated)."""
    browser = await playwright.chromium.connect_over_cdp(ensure_chrome(port))
    context = browser.contexts[0] if browser.contexts else await browser.new_context()
    pages = [p for p in context.pages if 'bet365' in (p.url or '')] or context.pages
    page = pages[0] if pages else await context.new_page()
    return browser, context, page
