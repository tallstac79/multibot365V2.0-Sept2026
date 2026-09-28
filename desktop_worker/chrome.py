"""The desktop worker's own Chrome: the installed Google Chrome with a dedicated profile directory, driven over the
Chrome DevTools Protocol on a loopback port (Playwright connect_over_cdp).

No Multilogin and no antidetect layer: an ordinary Chrome window the operator can see, sign in to by hand and take over at
any time. The profile keeps the Bet365 session between runs. Credentials are never typed, stored or read by this code.

Lifecycle (28 Sep 2026): the dedicated Chrome died at 19:16 BST when the Claude desktop app (an MSIX package) updated.
Chrome had been started at 11:11 by a script run from that app's shell, so it was inside the package's process tree/job
object, and Windows' package servicing ('TerminateApplications') killed it with the app. DETACHED_PROCESS only detaches
the console. Chrome is now started OUTSIDE the caller's process tree and job: through WMI Win32_Process.Create (the
process's parent is the WMI provider host, not the caller), falling back to CREATE_BREAKAWAY_FROM_JOB, then to the old
detached start. The flags and profile are unchanged.
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
DETACHED_PROCESS, CREATE_NEW_PROCESS_GROUP, CREATE_BREAKAWAY_FROM_JOB = 0x00000008, 0x00000200, 0x01000000
LAST_LAUNCH = {}                                   # how Chrome was last started by this process (reported on /health)


def _listening(port=PORT, timeout=1):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/version', timeout=timeout) as r:
            return r.status == 200
    except OSError:
        return False


def launch_args(port=PORT, profile=PROFILE, chrome=CHROME):
    """The dedicated Chrome's command line: the same flags as since the first build (nothing added)."""
    return [str(chrome), f'--remote-debugging-port={port}', '--remote-debugging-address=127.0.0.1',
            f'--user-data-dir={profile}', '--no-first-run', '--no-default-browser-check',
            '--window-size=1400,1000', 'about:blank']


WMI_CREATE = ("$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
              "-Arguments @{CommandLine=$env:MB_CHROME_CMD; CurrentDirectory=$env:MB_CHROME_CWD}; "
              "Write-Output \"$($r.ReturnValue) $($r.ProcessId)\"")


def _wmi_create(cmdline, cwd, run=subprocess.run):
    """Start `cmdline` through WMI Win32_Process.Create: the new process belongs to no caller's tree or job object."""
    env = dict(os.environ, MB_CHROME_CMD=cmdline, MB_CHROME_CWD=str(cwd))
    out = run(['powershell', '-NoProfile', '-NonInteractive', '-Command', WMI_CREATE], capture_output=True, text=True,
              env=env, timeout=30)
    parts = (out.stdout or '').split()
    if out.returncode != 0 or len(parts) < 2 or parts[0] != '0':
        raise OSError(f'Win32_Process.Create failed: rc={out.returncode} out={out.stdout!r} err={(out.stderr or "")[:200]!r}')
    return int(parts[1])


def launch(port=PORT, profile=PROFILE, chrome=CHROME, run=subprocess.run, popen=subprocess.Popen, windows=None):
    """Start the dedicated Chrome detached from this process (it must outlive the script, console or app that asked).
    Returns {method, pid, args, errors}."""
    args = launch_args(port, profile, chrome)
    Path(profile).mkdir(parents=True, exist_ok=True)
    windows = (os.name == 'nt') if windows is None else windows
    errors = []
    quiet = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    if windows:
        try:
            pid = _wmi_create(subprocess.list2cmdline(args), Path(chrome).parent, run=run)
            return _note(dict(method='wmi_win32_process_create', pid=pid, args=args, errors=errors))
        except Exception as e:
            errors.append(f'wmi: {e}')
        for method, flags in (('popen_breakaway', DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB),
                              ('popen_detached', DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)):
            try:
                p = popen(args, creationflags=flags, **quiet)
                return _note(dict(method=method, pid=p.pid, args=args, errors=errors))
            except OSError as e:                   # breakaway is refused inside a job that does not allow it
                errors.append(f'{method}: {e}')
        raise RuntimeError(f'Chrome could not be started: {errors}')
    p = popen(args, start_new_session=True, **quiet)
    return _note(dict(method='popen_new_session', pid=p.pid, args=args, errors=errors))


def _note(info):
    LAST_LAUNCH.clear()
    LAST_LAUNCH.update(info, at_ms=int(time.time() * 1000))
    return info


def ensure_chrome(port=PORT, profile=PROFILE, chrome=CHROME, wait_s=20, launcher=None, probe=None):
    """Start the dedicated Chrome if its debugging port is not answering; returns the CDP endpoint URL."""
    probe = probe or _listening
    if not probe(port):
        (launcher or launch)(port, profile, chrome)
        deadline = time.monotonic() + wait_s
        while not probe(port):
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
