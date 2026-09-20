import json, urllib.request
from playwright.sync_api import sync_playwright

adb_fwd_ok = True
tabs = json.loads(urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=8).read())
print("TABS", json.dumps([{k: t.get(k) for k in ("id", "title", "url")} for t in tabs], indent=2))

with sync_playwright() as p:
    b = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    pages = [pg for c in b.contexts for pg in c.pages]
    page = next((pg for pg in pages if "bet365" in (pg.url or "").lower()), pages[0] if pages else None)
    if not page:
        raise SystemExit("no page")
    page.set_default_timeout(8000)
    info = page.evaluate(
        """() => {
          const text = (document.body && document.body.innerText || '').slice(0, 1500);
          return {
            url: location.href,
            title: document.title,
            hasLogIn: /\\bLog In\\b/i.test(text),
            hasJoin: /\\bJoin\\b/i.test(text),
            hasLogOut: /\\bLog Out\\b/i.test(text),
            hasMyBets: /My Bets/i.test(text),
            hasBalanceWord: /Balance/i.test(text),
            currencyLike: /£\\s*\\d|\\$\\s*\\d|€\\s*\\d/.test(text),
            loggedOutClass: !!document.querySelector('[class*=\"LoggedOut\"]'),
            loggedInClass: !!document.querySelector('[class*=\"Members\"], [class*=\"Balance\"]'),
            sample: text.slice(0, 600)
          };
        }"""
    )
    logged_in = bool(
        (info.get("hasLogOut") or info.get("hasMyBets") or info.get("currencyLike") or info.get("loggedInClass"))
        and not info.get("hasLogIn")
    )
    # Heuristic: logged out if Log In visible and no Log Out
    if info.get("hasLogIn") and not info.get("hasLogOut"):
        logged_in = False
    if info.get("hasLogOut") or (info.get("currencyLike") and info.get("loggedInClass")):
        logged_in = True
    info["logged_in_guess"] = logged_in
    print(json.dumps(info, indent=2))
