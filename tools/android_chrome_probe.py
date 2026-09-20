"""android_chrome_probe.py - Playwright/CDP to Android Chrome via ADB."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

CDP_HOST, CDP_PORT = "127.0.0.1", 9222
CDP_BASE = f"http://{CDP_HOST}:{CDP_PORT}"
SCREENSHOT_REL = Path("screenshots") / "android_chrome_probe.png"
SHOT_SECS = 5


def log(msg: str) -> None:
    print(msg, flush=True)


def die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    log("$ " + " ".join(cmd))
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def http_json(path: str):
    with urllib.request.urlopen(f"{CDP_BASE}{path}", timeout=8) as resp:
        return json.loads(resp.read().decode("utf-8"))


def is_challenge(title: str, url: str, body: str = "") -> bool:
    blob = f"{title}\n{url}\n{body}".lower()
    keys = [
        "just a moment", "attention required", "checking your browser",
        "verify you are human", "human verification", "captcha", "cloudflare",
        "cf-browser-verification", "are you a robot",
    ]
    return any(k in blob for k in keys)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    shot = root / SCREENSHOT_REL
    shot.parent.mkdir(parents=True, exist_ok=True)

    log("=== 1) adb devices ===")
    cp = run(["adb", "devices"])
    log(((cp.stdout or "") + (cp.stderr or "")).strip())
    lines = [ln.strip() for ln in (cp.stdout or "").splitlines() if ln.strip() and not ln.startswith("List of devices")]
    devices = [ln for ln in lines if ln.split()[-1] == "device"]
    if len(devices) != 1:
        die(f"expected 1 device, got {devices or lines}")
    log(f"OK: {devices[0].split()[0]}")

    log("=== 2) Chrome ===")
    run(["adb", "shell", "am", "start", "-n", "com.android.chrome/com.google.android.apps.chrome.Main"])

    log("=== 3) DevTools socket ===")
    sock = run(["adb", "shell", "cat", "/proc/net/unix"])
    if "chrome_devtools_remote" not in (sock.stdout or ""):
        die("chrome_devtools_remote missing")
    log("OK: chrome_devtools_remote present")

    log("=== 4) forward ===")
    run(["adb", "forward", "--remove", f"tcp:{CDP_PORT}"])
    fw = run(["adb", "forward", f"tcp:{CDP_PORT}", "localabstract:chrome_devtools_remote"])
    if fw.returncode != 0:
        die("forward failed")
    log((run(["adb", "forward", "--list"]).stdout or "").strip())

    log("=== 5) CDP version/list ===")
    version = http_json("/json/version")
    tabs = http_json("/json/list")
    log(json.dumps(version, indent=2))
    for t in tabs:
        log(f"  tab id={t.get('id')!r} title={t.get('title')!r} url={t.get('url')!r}")

    bet = next((t for t in tabs if "bet365" in ((t.get("url") or "") + (t.get("title") or "")).lower()), None)
    if not bet:
        die("Bet365 tab not found in CDP list")

    log("=== 6) Playwright CDP attach ===")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        die(f"playwright missing for {sys.executable}")

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://{CDP_HOST}:{CDP_PORT}")
        pages = [pg for ctx in browser.contexts for pg in ctx.pages]
        log(f"Playwright attached. pages={len(pages)}")
        if not pages:
            die("no pages")
        page = next((pg for pg in pages if "bet365" in (pg.url or "").lower()), pages[0])
        page.set_default_timeout(8000)
        title = page.title()
        url = page.url
        body = page.evaluate("() => (document.body && (document.body.innerText || '')) ? (document.body.innerText || '').slice(0, 500) : ''")
        ready = page.evaluate("() => document.readyState")
        log(f"title={title!r}")
        log(f"url={url!r}")
        log(f"dom_query readyState={ready} body_len={len(body or '')}")
        log(f"body_sample={body!r}")

        challenge = is_challenge(title, url, body or "")
        shot_status = "n/a"
        if challenge:
            log("HUMAN_VERIFICATION_CHALLENGE_DETECTED — not bypassing; skipping screenshot")
        else:
            box: dict = {}

            def _shot() -> None:
                try:
                    import base64
                    session = page.context.new_cdp_session(page)
                    result = session.send("Page.captureScreenshot", {"format": "png", "fromSurface": True})
                    data = result.get("data")
                    if not data:
                        box["err"] = "empty"
                        return
                    shot.write_bytes(base64.b64decode(data))
                    box["ok"] = str(shot)
                except Exception as e:
                    box["err"] = str(e)

            th = threading.Thread(target=_shot, daemon=True)
            th.start()
            th.join(SHOT_SECS)
            if th.is_alive():
                shot_status = f"skipped after {SHOT_SECS}s hard timeout"
            elif box.get("ok"):
                shot_status = f"saved: {box['ok']}"
            else:
                shot_status = f"skipped: {box.get('err')}"

        log("=== RESULT ===")
        log("adb_device=OK")
        log("cdp_forward=OK")
        log("playwright_attached=OK")
        log("bet365_found=OK")
        log(f"title={title!r}")
        log(f"url={url!r}")
        log(f"dom_query=OK")
        log(f"human_challenge={challenge}")
        log(f"screenshot={shot_status}")
        if challenge:
            log("PASS_PARTIAL: control proven; Bet365 shows human verification challenge.")
        else:
            log("SUCCESS: CDP + Playwright attachment proven.")
        sys.exit(0)


if __name__ == "__main__":
    main()