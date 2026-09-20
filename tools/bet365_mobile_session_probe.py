"""bet365_mobile_session_probe.py — Phase 3A session control over Android Chrome CDP.

Sequence:
  detect → (if in) logout → verify out → login → verify in + balance
  → logout → verify out → login again → leave logged in

MUST NOT: enter stake, click Place Bet, wager, bypass CAPTCHA/challenge.
Credentials: config.PROFILES / BET365_USERNAME + BET365_PASSWORD env. Never log password.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import plugins.bet365_mobile_selectors as MS  # noqa: E402

LOG_JSON = ROOT / "logs" / "bet365_mobile_session_probe.json"
CDP = "http://127.0.0.1:9222"
DEFAULT_TIMEOUT_MS = 8000
ACTION_TIMEOUT_S = 25
LOGIN_TIMEOUT_S = 45


def log(msg: str) -> None:
    print(msg, flush=True)


def die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


def ensure_cdp() -> None:
    subprocess.run(["adb", "forward", "--remove", "tcp:9222"], capture_output=True, text=True)
    p = subprocess.run(
        ["adb", "forward", "tcp:9222", "localabstract:chrome_devtools_remote"],
        capture_output=True,
        text=True,
    )
    if p.returncode != 0:
        die(f"adb forward failed: {(p.stderr or p.stdout or '').strip()}")


def http_json(path: str):
    with urllib.request.urlopen(f"{CDP}{path}", timeout=8) as r:
        return json.loads(r.read().decode())


def is_challenge(title: str, url: str, body: str = "") -> bool:
    blob = f"{title}\n{url}\n{body}".lower()
    keys = [
        "just a moment",
        "attention required",
        "checking your browser",
        "verify you are human",
        "human verification",
        "captcha",
        "cloudflare",
        "cf-browser-verification",
        "are you a robot",
        "unusual activity",
        "account restricted",
        "partial authentication",
        "security check",
    ]
    return any(k in blob for k in keys)


def load_credentials() -> tuple[str, str, str]:
    """Return (username, password, source). Password never logged by caller."""
    user = (os.environ.get("BET365_USERNAME") or os.environ.get("BET365_USER") or "").strip()
    pw = (os.environ.get("BET365_PASSWORD") or os.environ.get("BET365_PASS") or "").strip()
    if user and pw:
        return user, pw, "env"
    try:
        import config as cfg  # type: ignore

        profiles = getattr(cfg, "PROFILES", None) or []
        for p in profiles:
            if not isinstance(p, dict) or not p.get("enabled", True):
                continue
            u = (p.get("bet365_username") or "").strip()
            w = (p.get("bet365_password") or "").strip()
            if u and w:
                return u, w, f"config:{p.get('name') or 'profile'}"
    except Exception as e:
        log(f"config load note: {type(e).__name__}")
    return "", "", "none"


def loc(page, selector: str):
    if not selector:
        return None
    if selector.startswith("xpath="):
        return page.locator(selector)
    if selector.startswith("css="):
        return page.locator(selector[4:])
    if selector.startswith("text="):
        return page.locator(selector)
    if selector.startswith("/") or selector.startswith("("):
        return page.locator(f"xpath={selector}")
    return page.locator(selector)


def first_visible(page, candidates: list, timeout_ms: int = 2500):
    failures = []
    for sel in candidates:
        if not sel:
            continue
        try:
            l = loc(page, sel)
            if l is None:
                continue
            n = l.count()
            for i in range(min(n, 6)):
                el = l.nth(i)
                try:
                    if el.is_visible(timeout=timeout_ms):
                        return el, sel
                except Exception:
                    continue
            failures.append(f"{sel}:count={n}")
        except Exception as e:
            failures.append(f"{sel}:{type(e).__name__}")
    return None, failures


def click_first(page, candidates: list, label: str, report: dict, timeout_ms: int = 4000) -> bool:
    el, info = first_visible(page, candidates, timeout_ms=min(timeout_ms, 2500))
    if el is None:
        report.setdefault("selector_failures", []).append({"action": label, "tried": info})
        return False
    try:
        el.click(timeout=timeout_ms)
        log(f"clicked {label} via {info}")
        return True
    except Exception as e:
        report.setdefault("selector_failures", []).append({"action": label, "selector": info, "error": str(e)[:200]})
        return False


def fill_first(page, candidates: list, value: str, label: str, report: dict) -> bool:
    el, info = first_visible(page, candidates)
    if el is None:
        report.setdefault("selector_failures", []).append({"action": f"fill:{label}", "tried": info})
        return False
    try:
        el.click(timeout=3000)
        el.fill("")
        # char-by-char like desktop flow; never log value
        for ch in value:
            el.type(ch, delay=40)
        log(f"filled {label} via {info} (len={len(value)})")
        return True
    except Exception as e:
        report.setdefault("selector_failures", []).append(
            {"action": f"fill:{label}", "selector": info, "error": str(e)[:200]}
        )
        return False


def dismiss_popups(page, report: dict) -> None:
    for sel in MS.POPUP_CLOSE_CANDIDATES:
        try:
            el, info = first_visible(page, [sel], timeout_ms=800)
            if el is not None:
                el.click(timeout=1500)
                log(f"dismissed popup via {info}")
                time.sleep(0.4)
        except Exception:
            pass


def read_balance(page) -> str | None:
    # Prefer live text match from body / candidate nodes
    try:
        text = page.evaluate(
            """() => {
              const body=(document.body&&document.body.innerText)||'';
              const m=body.match(/[£$€]\\s*[\\d,.]+/);
              return m?m[0]:null;
            }"""
        )
        if text:
            return text.strip()
    except Exception:
        pass
    el, _ = first_visible(page, MS.BALANCE_CANDIDATES, timeout_ms=1500)
    if el is not None:
        try:
            t = (el.inner_text(timeout=1500) or "").strip()
            if re.search(r"[£$€]\s*[\d,.]+", t):
                return t
            if re.search(r"[\d,.]+", t):
                return t
        except Exception:
            pass
    return None


def detect_state(page) -> dict:
    return page.evaluate(
        """() => {
          const text=(document.body&&document.body.innerText)||'';
          const hasLogIn=/\\bLog In\\b/i.test(text);
          const hasJoin=/\\bJoin\\b/i.test(text);
          const hasLogOut=/\\bLog Out\\b/i.test(text);
          const hasMyBets=/My Bets/i.test(text);
          const bal=(text.match(/[£$€]\\s*[\\d,.]+/)||[null])[0];
          const membersClass=!!document.querySelector('[class*="Members"],[class*="Balance"],[class*="sln-d0"]');
          const loggedOutClass=!!document.querySelector('[class*="LoggedOut"]');
          const userInput=!!document.querySelector('input[type="password"], input[class*="Username"], input[class*="Password"]');
          // Mobile chrome can show "My Bets" while logged out — Log In wins.
          let logged_in=false;
          if (hasLogIn && !hasLogOut) logged_in=false;
          else if (hasLogOut || bal || (membersClass && !hasLogIn)) logged_in=true;
          else if (hasJoin || loggedOutClass) logged_in=false;
          return {
            logged_in, hasLogIn, hasJoin, hasLogOut, hasMyBets,
            balanceText: bal, membersClass, loggedOutClass, userInput,
            bodySample: text.slice(0, 240)
          };
        }"""
    )


def wait_until(pred, timeout_s: float, interval: float = 0.4) -> bool:
    end = time.time() + timeout_s
    while time.time() < end:
        if pred():
            return True
        time.sleep(interval)
    return False


def do_logout(page, report: dict) -> bool:
    t0 = time.time()
    dismiss_popups(page, report)

    def logout_visible() -> bool:
        try:
            return page.locator("text=Log Out").count() > 0
        except Exception:
            return False

    def click_logout() -> bool:
        try:
            loc = page.locator("div.zsa-d")
            if not loc.count():
                loc = page.locator("xpath=//div[normalize-space()='Log Out']")
            if not loc.count():
                loc = page.locator("text=Log Out")
            if not loc.count():
                return False
            box = loc.last.bounding_box()
            if not box:
                report.setdefault("selector_failures", []).append({"action": "logout_click", "error": "no bbox"})
                return False
            page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            log(f"clicked logout via mouse bbox {box}")
            try:
                page.wait_for_load_state("domcontentloaded", timeout=8000)
            except Exception:
                pass
            time.sleep(1.0)
            return True
        except Exception as e:
            report.setdefault("selector_failures", []).append({"action": "logout_click", "error": str(e)[:200]})
            return False

    # If Log Out already on screen, do NOT toggle the account menu closed
    if logout_visible():
        log("Log Out already visible — skipping menu open")
        ok = click_logout()
    else:
        opened = False
        try:
            btns = page.locator("header button.hrm-6c")
            n = btns.count()
            if n:
                btns.nth(n - 1).click(timeout=4000, force=True)
                opened = True
                log(f"opened account menu via header button.hrm-6c nth=-1 (n={n})")
        except Exception as e:
            report.setdefault("selector_failures", []).append({"action": "members_menu_primary", "error": str(e)[:200]})
        if not opened:
            try:
                page.locator("header .hrm-ff").first.click(timeout=4000, force=True)
                opened = True
                log("opened account menu via header .hrm-ff")
            except Exception as e:
                report.setdefault("selector_failures", []).append({"action": "members_menu_icon", "error": str(e)[:200]})
        if not opened:
            try:
                box = page.evaluate("() => ({w: window.innerWidth})")
                page.mouse.click(max(10, (box or {}).get("w", 360) - 20), 24)
                opened = True
                log("opened account menu via top-right coordinates")
            except Exception as e:
                report.setdefault("selector_failures", []).append({"action": "members_menu_xy", "error": str(e)[:200]})
        time.sleep(1.0)
        if not logout_visible():
            try:
                page.mouse.click(max(10, page.evaluate("() => window.innerWidth") - 20), 24)
                time.sleep(0.8)
            except Exception:
                pass
        ok = click_logout()
        if not ok:
            found = page.evaluate(
                """() => {
                  for (const el of document.querySelectorAll('div,span,a,button')) {
                    const t=(el.innerText||'').trim();
                    if (/^Log Out$/i.test(t) || /^Logout$/i.test(t) || /^Sign Out$/i.test(t)) {
                      el.scrollIntoView({block:'center'});
                      el.click();
                      return t;
                    }
                  }
                  return null;
                }"""
            )
            ok = bool(found)
            log(f"logout discover click={found!r}")
            if not ok:
                report.setdefault("selector_failures", []).append({"action": "logout", "error": "no Log Out control"})

    if ok:
        for sel in ["text=OK", "text=Yes", "text=Confirm"]:
            try:
                loc = page.locator(sel)
                if loc.count() and loc.last.is_visible():
                    loc.last.click(timeout=2000)
                    log(f"post-logout confirm via {sel}")
                    time.sleep(0.5)
            except Exception:
                pass
        wait_until(
            lambda: (not detect_state(page).get("logged_in")) or bool(detect_state(page).get("hasLogIn")),
            ACTION_TIMEOUT_S,
        )
    report.setdefault("timings", {})["logout_s"] = round(time.time() - t0, 2)
    st = detect_state(page)
    success = (st.get("logged_in") is False) or bool(st.get("hasLogIn"))
    log(
        f"logout_state logged_in={st.get('logged_in')} hasLogIn={st.get('hasLogIn')} "
        f"hasMyBets={st.get('hasMyBets')} hasLogOut={st.get('hasLogOut')}"
    )
    return bool(success)


def open_login_form(page, report: dict) -> bool:
    """Header Log In needs a full pointer event sequence; force-show panel if animation stuck."""
    try:
        page.evaluate(
            """() => {
              const b=[...document.querySelectorAll('button')].find(e=>/^\\s*Log In\\s*$/i.test((e.innerText||'').trim()) && (e.className||'').includes('hrm-'))
                || [...document.querySelectorAll('button')].find(e=>/^\\s*Log In\\s*$/i.test((e.innerText||'').trim()));
              if(!b) return false;
              b.focus();
              for (const type of ['pointerdown','mousedown','pointerup','mouseup','click']) {
                b.dispatchEvent(new PointerEvent(type,{bubbles:true,cancelable:true,view:window,pointerId:1,pointerType:'touch'}));
              }
              b.click();
              return true;
            }"""
        )
        time.sleep(0.8)
        page.evaluate(
            """() => {
              const panel=document.querySelector('div.slm2-11');
              if(!panel) return;
              panel.style.setProperty('opacity','1','important');
              panel.style.setProperty('transform','translate(0px, 0px)','important');
              panel.style.setProperty('pointer-events','auto','important');
            }"""
        )
        time.sleep(0.4)
        ok = wait_until(lambda: page.locator("input.slm2-c2, input[type='password']").count() > 0, 8)
        log(f"open_login_form fields={ok}")
        return bool(ok)
    except Exception as e:
        report.setdefault("selector_failures", []).append({"action": "open_login_form", "error": str(e)[:200]})
        return False


def do_login(page, user: str, password: str, report: dict, timing_key: str) -> bool:
    t0 = time.time()
    dismiss_popups(page, report)
    st = detect_state(page)
    if st.get("logged_in"):
        report.setdefault("timings", {})[timing_key] = round(time.time() - t0, 2)
        return True

    if page.locator("input[type='password'], input.slm2-c2").count() == 0:
        if not open_login_form(page, report):
            # fallback candidates
            click_first(page, MS.LOGIN_BUTTON_CANDIDATES, "login_button", report)
            time.sleep(1.0)
            if page.locator("input[type='password'], input.slm2-c2").count() == 0:
                open_login_form(page, report)

    body = page.evaluate("() => (document.body&&document.body.innerText||'').slice(0,1000)")
    if is_challenge(page.title(), page.url, body):
        report["challenge_detected"] = True
        report["challenge_detail"] = {"title": page.title(), "url": page.url, "body_sample": body[:400]}
        report.setdefault("timings", {})[timing_key] = round(time.time() - t0, 2)
        return False

    # Fill even if slightly off-screen
    try:
        user_el = page.locator("input.slm2-8, input[placeholder*='Username' i]").first
        pass_el = page.locator("input.slm2-c2, input[type='password']").first
        if user_el.count() == 0 or pass_el.count() == 0:
            if not fill_first(page, MS.USERNAME_CANDIDATES, user, "username", report):
                report.setdefault("timings", {})[timing_key] = round(time.time() - t0, 2)
                return False
            if not fill_first(page, MS.PASSWORD_CANDIDATES, password, "password", report):
                report.setdefault("timings", {})[timing_key] = round(time.time() - t0, 2)
                return False
        else:
            try:
                user_el.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass
            user_el.fill(user, force=True, timeout=5000)
            log(f"filled username via slm2 (len={len(user)})")
            pass_el.fill(password, force=True, timeout=5000)
            log(f"filled password via slm2 (len={len(password)})")
    except Exception as e:
        report.setdefault("selector_failures", []).append({"action": "fill_login", "error": str(e)[:200]})
        report.setdefault("timings", {})[timing_key] = round(time.time() - t0, 2)
        return False

    # Submit — prefer mouse if on-screen, else JS pointer sequence
    submitted = False
    try:
        # re-force panel visible before submit
        page.evaluate(
            """() => {
              const panel=document.querySelector('div.slm2-11');
              if(!panel) return;
              panel.style.setProperty('opacity','1','important');
              panel.style.setProperty('transform','translate(0px, 0px)','important');
            }"""
        )
        time.sleep(0.2)
        sub = page.locator("button.slm2-f9").first
        box = sub.bounding_box() if sub.count() else None
        if box and box.get("y", -1) >= 0:
            page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            submitted = True
            log("clicked login submit via mouse")
        else:
            page.evaluate(
                """() => {
                  const b=document.querySelector('button.slm2-f9');
                  if(!b) return false;
                  for (const type of ['pointerdown','mousedown','pointerup','mouseup','click']) {
                    b.dispatchEvent(new PointerEvent(type,{bubbles:true,cancelable:true,view:window,pointerId:1,pointerType:'touch'}));
                  }
                  b.click();
                  return true;
                }"""
            )
            submitted = True
            log("clicked login submit via JS events")
    except Exception as e:
        report.setdefault("selector_failures", []).append({"action": "login_submit", "error": str(e)[:200]})
    if not submitted:
        report.setdefault("timings", {})[timing_key] = round(time.time() - t0, 2)
        return False

    def _logged():
        body2 = page.evaluate("() => (document.body&&document.body.innerText||'').slice(0,800)")
        if is_challenge(page.title(), page.url, body2):
            report["challenge_detected"] = True
            report["challenge_detail"] = {"title": page.title(), "url": page.url, "body_sample": body2[:400]}
            return True
        dismiss_popups(page, report)
        return bool(detect_state(page).get("logged_in"))

    wait_until(_logged, LOGIN_TIMEOUT_S)
    report.setdefault("timings", {})[timing_key] = round(time.time() - t0, 2)
    if report.get("challenge_detected"):
        return False
    return bool(detect_state(page).get("logged_in"))



def main() -> None:
    from playwright.sync_api import sync_playwright

    LOG_JSON.parent.mkdir(parents=True, exist_ok=True)
    user, password, cred_source = load_credentials()
    report = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "cred_source": cred_source,
        "cred_username_set": bool(user),
        "cred_password_set": bool(password),
        "initial_state": None,
        "logout_success": None,
        "login_success": None,
        "balance_readable": None,
        "balance_value": None,
        "second_logout_success": None,
        "final_login_success": None,
        "challenge_detected": False,
        "timings": {},
        "selector_failures": [],
        "blocker": None,
        "left_logged_in": None,
    }

    if not user or not password:
        report["blocker"] = "No Bet365 credentials in env (BET365_USERNAME/BET365_PASSWORD) or config.PROFILES"
        LOG_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
        log(json.dumps({k: report[k] for k in report if k != "challenge_detail"}, indent=2))
        die(report["blocker"])

    log("=== ensure CDP ===")
    ensure_cdp()
    version = http_json("/json/version")
    tabs = http_json("/json/list")
    report["cdp_version"] = version.get("Browser")
    bet = next((t for t in tabs if "bet365" in ((t.get("url") or "") + (t.get("title") or "")).lower()), None)
    if not bet:
        report["blocker"] = "Bet365 tab not found in CDP list"
        LOG_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
        die(report["blocker"])

    t_all = time.time()
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        pages = [pg for c in browser.contexts for pg in c.pages]
        page = next((pg for pg in pages if "bet365" in (pg.url or "").lower()), None)
        if not page:
            report["blocker"] = "No Bet365 Playwright page"
            LOG_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
            die(report["blocker"])
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)

        body = page.evaluate("() => (document.body&&document.body.innerText||'').slice(0,1000)")
        if is_challenge(page.title(), page.url, body):
            report["challenge_detected"] = True
            report["challenge_detail"] = {"title": page.title(), "url": page.url, "body_sample": body[:400]}
            report["blocker"] = "Challenge detected before session cycle"
            LOG_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
            log("STOP: challenge detected — not bypassing")
            sys.exit(0)

        dismiss_popups(page, report)
        st0 = detect_state(page)
        report["initial_state"] = "logged_in" if st0.get("logged_in") else "logged_out"
        log(f"initial_state={report['initial_state']} session={ {k:st0[k] for k in st0 if k!='bodySample'} }")

        # A. If logged in → logout
        if st0.get("logged_in"):
            bal = read_balance(page)
            if bal:
                report["balance_value"] = bal
                report["balance_readable"] = True
            report["logout_success"] = do_logout(page, report)
            log(f"logout_success={report['logout_success']}")
            if report.get("challenge_detected"):
                report["blocker"] = "Challenge during/after logout"
                LOG_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
                sys.exit(0)
        else:
            report["logout_success"] = True  # already out
            log("already logged out — skip first logout")

        # B. Login
        report["login_success"] = do_login(page, user, password, report, "login_s")
        log(f"login_success={report['login_success']} login_s={report['timings'].get('login_s')}")
        if report.get("challenge_detected"):
            report["blocker"] = "Challenge during login"
            LOG_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
            sys.exit(0)
        if report["login_success"]:
            bal = read_balance(page)
            report["balance_value"] = bal
            report["balance_readable"] = bool(bal)
            log(f"balance={bal!r}")
        else:
            report["blocker"] = "First login failed"
            report["timings"]["total_s"] = round(time.time() - t_all, 2)
            LOG_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
            die(report["blocker"])

        # C. Logout again
        report["second_logout_success"] = do_logout(page, report)
        # accumulate logout timing
        report["timings"]["second_logout_s"] = report["timings"].get("logout_s")
        log(f"second_logout_success={report['second_logout_success']}")
        if report.get("challenge_detected"):
            report["blocker"] = "Challenge during second logout"
            LOG_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
            sys.exit(0)
        if not report["second_logout_success"]:
            report["blocker"] = "Second logout failed"
            report["timings"]["total_s"] = round(time.time() - t_all, 2)
            LOG_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
            die(report["blocker"])

        # D. Final login — leave logged in
        report["final_login_success"] = do_login(page, user, password, report, "final_login_s")
        log(f"final_login_success={report['final_login_success']} final_login_s={report['timings'].get('final_login_s')}")
        if report.get("challenge_detected"):
            report["blocker"] = "Challenge during final login"
            LOG_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
            sys.exit(0)
        bal = read_balance(page)
        if bal:
            report["balance_value"] = bal
            report["balance_readable"] = True
        report["left_logged_in"] = bool(detect_state(page).get("logged_in"))
        report["timings"]["total_s"] = round(time.time() - t_all, 2)
        report["timings"]["total_login_s"] = round(
            (report["timings"].get("login_s") or 0) + (report["timings"].get("final_login_s") or 0), 2
        )

        LOG_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
        log("=== RESULT ===")
        log(f"LOGIN={'PASS' if report['login_success'] else 'FAIL'}")
        log(f"LOGOUT={'PASS' if report['logout_success'] and report['second_logout_success'] else 'FAIL'}")
        log(f"FINAL_LOGIN={'PASS' if report['final_login_success'] else 'FAIL'}")
        log(f"BALANCE={'PASS' if report['balance_readable'] else 'FAIL'}")
        log(f"challenge={report['challenge_detected']}")
        log(f"total_login_s={report['timings'].get('total_login_s')}")
        log(f"left_logged_in={report['left_logged_in']}")
        if report["selector_failures"]:
            log(f"selector_failures={len(report['selector_failures'])}")
        if not (report["login_success"] and report["second_logout_success"] and report["final_login_success"]):
            sys.exit(1)


if __name__ == "__main__":
    main()
