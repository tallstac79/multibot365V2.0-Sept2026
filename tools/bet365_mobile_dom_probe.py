"""bet365_mobile_dom_probe.py — logged-in mobile Chrome CDP selector audit.

MAY: search, open events/markets, click selections, inspect/clear betslip.
MUST NOT: enter stake, Place Bet, wager, bypass challenges.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LOG_JSON = ROOT / "logs" / "bet365_mobile_dom_probe.json"
AUDIT_MD = ROOT / "docs" / "BET365_MOBILE_SELECTOR_AUDIT.md"
CDP = "http://127.0.0.1:9222"


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
        die(f"adb forward failed: {p.stderr}")


def http_json(path: str):
    with urllib.request.urlopen(f"{CDP}{path}", timeout=8) as r:
        return json.loads(r.read().decode())


def is_challenge(title: str, url: str, body: str = "") -> bool:
    blob = f"{title}\n{url}\n{body}".lower()
    keys = [
        "just a moment",
        "attention required",
        "verify you are human",
        "captcha",
        "cloudflare",
        "checking your browser",
    ]
    return any(k in blob for k in keys)


def test_sel(page, selector: str) -> dict:
    out = {"selector": selector, "count": 0, "visible": 0, "ok": False, "error": None, "sample": None}
    if not selector or not isinstance(selector, str):
        out["error"] = "empty"
        return out
    try:
        kind = "xpath" if selector.startswith("/") or selector.startswith("(") else "css"
        loc = page.locator(f"xpath={selector}") if kind == "xpath" else page.locator(selector)
        count = loc.count()
        out["count"] = count
        vis = 0
        sample = None
        for i in range(min(count, 5)):
            el = loc.nth(i)
            try:
                if el.is_visible():
                    vis += 1
                    if sample is None:
                        sample = {
                            "text": (el.inner_text(timeout=1500) or "")[:80],
                            "meta": el.evaluate(
                                """e => ({
                                  id: e.id||null,
                                  className: (e.className&&String(e.className).slice(0,120))||null,
                                  role: e.getAttribute('role'),
                                  aria: e.getAttribute('aria-label'),
                                  data: Object.fromEntries([...e.attributes].filter(a=>a.name.startsWith('data-')).slice(0,6).map(a=>[a.name,a.value.slice(0,60)]))
                                })"""
                            ),
                        }
            except Exception:
                pass
        out["visible"] = vis
        out["ok"] = count > 0
        out["sample"] = sample
    except Exception as e:
        out["error"] = str(e)[:200]
    return out


def discover(page, needles: list[str]) -> list[dict]:
    return page.evaluate(
        """(needles) => {
          const out=[];
          const rx=needles.map(n=>new RegExp(n,'i'));
          for (const el of document.querySelectorAll('a,button,div,span,input,li')) {
            const t=((el.innerText||el.textContent||'')+' '+(el.getAttribute('aria-label')||'')).trim().replace(/\\s+/g,' ');
            if (!t || t.length>80) continue;
            if (!rx.some(r=>r.test(t))) continue;
            const r=el.getBoundingClientRect();
            if (!(r.width&&r.height)) continue;
            out.push({
              text:t.slice(0,80),
              tag:el.tagName.toLowerCase(),
              id:el.id||null,
              className:(el.className&&String(el.className).slice(0,140))||null,
              role:el.getAttribute('role'),
              aria:el.getAttribute('aria-label'),
              data:Object.fromEntries([...el.attributes].filter(a=>a.name.startsWith('data-')).slice(0,6).map(a=>[a.name,a.value.slice(0,60)]))
            });
            if (out.length>=12) break;
          }
          return out;
        }""",
        needles,
    )


def propose_from(disc: list[dict], fallback_text: str | None = None) -> tuple[str, str]:
    if not disc:
        if fallback_text:
            return (f"text={fallback_text}", "low")
        return ("", "none")
    el = disc[0]
    if el.get("id"):
        return (f"#{el['id']}", "high")
    data = el.get("data") or {}
    for k, v in data.items():
        if v and len(str(v)) < 40:
            return (f'[{k}="{v}"]', "high")
    if el.get("aria"):
        return (f'[aria-label="{el["aria"]}"]', "med")
    cls = (el.get("className") or "").split()
    tokens = [
        c
        for c in cls
        if any(
            x in c
            for x in (
                "hm-",
                "lms-",
                "sml-",
                "ssm-",
                "bsf-",
                "sph-",
                "gl-",
                "ipe-",
                "AcceptButton",
                "Balance",
                "Members",
                "Search",
                "Login",
            )
        )
    ]
    if tokens:
        return (f'[class*="{tokens[0]}"]', "med")
    if el.get("text"):
        return (f'text={el["text"]}', "low")
    return ("", "none")


def clear_betslip(page) -> str:
    notes = []
    for sel in [
        'xpath=//div[contains(@class,"-RemoveButton")]',
        'xpath=//div[contains(@class,"RemoveButton")]',
        'xpath=//div[contains(text(),"Remove all")]',
        "text=Remove all",
        "text=Remove",
    ]:
        try:
            loc = page.locator(sel)
            n = loc.count()
            for i in range(min(n, 8)):
                el = loc.nth(i)
                if el.is_visible():
                    el.click(timeout=2000)
                    notes.append(f"clicked {sel}")
                    time.sleep(0.35)
        except Exception as e:
            notes.append(f"skip {sel}: {e}")
    return "; ".join(notes) or "no clear controls found"


def click_first_odds(page):
    return page.evaluate(
        """() => {
          const cands=[...document.querySelectorAll('div,span,button')];
          for (const el of cands) {
            const t=(el.innerText||'').trim();
            if (!/^\\d+(\\.\\d+)?$/.test(t)) continue;
            const n=parseFloat(t); if (!(n>1 && n<100)) continue;
            const r=el.getBoundingClientRect();
            if (r.width>20 && r.height>16 && r.top>120) { el.click(); return t; }
          }
          return null;
        }"""
    )


def main() -> None:
    from playwright.sync_api import sync_playwright
    import plugins.bet365_selectors as S

    LOG_JSON.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_MD.parent.mkdir(parents=True, exist_ok=True)

    log("=== ensure CDP ===")
    ensure_cdp()
    version = http_json("/json/version")
    tabs = http_json("/json/list")
    log(json.dumps(version, indent=2))

    report = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "version": version,
        "tabs": tabs,
        "logged_in": None,
        "challenge": False,
        "results": [],
        "markets": {},
        "summary": {},
    }

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        pages = [pg for c in browser.contexts for pg in c.pages]
        page = next((pg for pg in pages if "bet365" in (pg.url or "").lower()), pages[0] if pages else None)
        if not page:
            die("no Bet365 page")
        page.set_default_timeout(8000)

        body = page.evaluate("() => (document.body && document.body.innerText || '').slice(0, 800)")
        title, url = page.title(), page.url
        if is_challenge(title, url, body):
            report["challenge"] = True
            log("HUMAN_CHALLENGE — stopping")
            LOG_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
            sys.exit(0)

        session = page.evaluate(
            """() => {
              const text=(document.body&&document.body.innerText||'');
              return {
                hasLogIn:/\\bLog In\\b/i.test(text),
                hasJoin:/\\bJoin\\b/i.test(text),
                hasLogOut:/\\bLog Out\\b/i.test(text),
                hasMyBets:/My Bets/i.test(text),
                balanceText:(text.match(/£\\s*[\\d,.]+|\\$\\s*[\\d,.]+|€\\s*[\\d,.]+/)||[null])[0],
                membersClass:!!document.querySelector('[class*="Members"],[class*="Balance"]'),
                loggedOutClass:!!document.querySelector('[class*="LoggedOut"]'),
              };
            }"""
        )
        logged_in = False
        if session.get("hasLogIn") and not session.get("hasLogOut"):
            logged_in = False
        elif session.get("balanceText") or session.get("membersClass") or session.get("hasMyBets") or session.get("hasLogOut"):
            logged_in = True
        report["logged_in"] = logged_in
        report["session"] = session
        log(f"logged_in={logged_in} session={session}")

        mapping = [
            ("SESSION balance", getattr(S, "BALANCE_DISPLAY", None), ["Balance", "£"]),
            ("SESSION members/account menu", getattr(S, "MEMBERS_MENU", None), ["Members"]),
            ("SESSION logout", getattr(S, "LOG_OUT", None), ["Log Out"]),
            ("SESSION logged-out indicator", getattr(S, "LOGIN_BUTTON", None), ["Log In"]),
            ("PUBLIC login button", getattr(S, "LOGIN_BUTTON", None), ["Log In"]),
            ("PUBLIC login container", getattr(S, "LOGIN_CONTAINER", None), ["Login"]),
            ("PUBLIC username", getattr(S, "USERNAME_INPUT", None), ["Username"]),
            ("PUBLIC password", getattr(S, "PASSWORD_INPUT", None), ["Password"]),
            ("PUBLIC login submit", getattr(S, "CONFIRM_LOGIN_BUTTON", None), ["Log In"]),
            ("SEARCH control/bar", getattr(S, "SEARCH_BAR", None), ["Search"]),
            ("SEARCH input", getattr(S, "SEARCH_INPUT", None), ["Search"]),
            ("SEARCH view event text", getattr(S, "VIEW_EVENT_TEXT", None), ["View Event"]),
            ("SEARCH view event bets", getattr(S, "VIEW_EVENT_BETS", None), ["View Event"]),
            ("NAV all sports", getattr(S, "ALL_SPORTS", None), ["All Sports"]),
            ("NAV in-play", getattr(S, "IN_PLAY", None), ["In-Play"]),
            ("BETSLIP stake input", getattr(S, "STAKE_INPUT", None), ["Stake"]),
            ("BETSLIP place bet", getattr(S, "PLACE_BET_BUTTON", None), ["Place Bet"]),
            ("BETSLIP accept changes text", getattr(S, "ACCEPT_CHANGES_TEXT", None), ["Accept"]),
            ("BETSLIP done", getattr(S, "DONE_BUTTON", None), ["Done"]),
            ("BETSLIP remove", getattr(S, "REMOVE_BUTTON", None), ["Remove"]),
            ("BETSLIP remove all", getattr(S, "REMOVE_ALL", None), ["Remove all"]),
            ("MARKET nav buttons", getattr(S, "MARKET_NAV_BUTTONS", None), ["Popular"]),
            ("MARKET asian lines tab", getattr(S, "ASIAN_LINES_TAB", None), ["Asian Lines"]),
            ("MARKET popular tab", getattr(S, "POPULAR_TAB", None), ["Popular"]),
            ("EVENT header label", getattr(S, "EVENT_HEADER_LABEL", None), []),
            ("AH team1", getattr(S, "AH_TEAM1_VALUE", None), ["Asian Handicap"]),
            ("GOAL LINE over", getattr(S, "GOAL_LINE_OVER", None), ["Goal Line"]),
            ("MY BETS tab", getattr(S, "MY_BETS_TAB", None), ["My Bets"]),
            ("MY BETS button", getattr(S, "MY_BETS_BUTTON", None), ["My Bets"]),
            ("FOOTBALL nav", None, ["Football"]),
            ("BASKETBALL nav", None, ["Basketball"]),
        ]

        seen = {m[1] for m in mapping if m[1]}
        for name in dir(S):
            if name.startswith("_"):
                continue
            val = getattr(S, name)
            if isinstance(val, str) and (val.startswith(".") or val.startswith("/")) and val not in seen:
                mapping.append((f"CONST {name}", val, []))

        rows = []
        log("=== static selector tests (home) ===")
        for element, old, needles in mapping:
            old_res = test_sel(page, old) if old else {"ok": False, "count": 0, "visible": 0, "selector": None, "sample": None, "error": "no old selector"}
            disc = discover(page, needles) if needles else []
            prop, conf = propose_from(disc, needles[0] if needles else None)
            works = bool(old_res.get("ok") and old_res.get("count", 0) > 0)
            status = "PASS" if works else "FAIL"
            if works:
                mobile_works, bucket = "YES", "unchanged"
            elif prop:
                mobile_works, bucket = "NO (needs new)", "modify"
            else:
                mobile_works, bucket = "NO", "unusable"
            if logged_in and element.startswith(("PUBLIC ", "SESSION logged-out")) and not works:
                bucket = "expected_fail_logged_in"
                mobile_works = "N/A (logged in)"
            rows.append(
                {
                    "element": element,
                    "old_selector": old,
                    "old_test": old_res,
                    "mobile_works": mobile_works,
                    "proposed": prop,
                    "confidence": conf,
                    "discover": disc[:3],
                    "bucket": bucket,
                    "status": status,
                }
            )
            log(f"{status:4} {element}: old_ok={works} proposed={prop!r}")

        report["results"] = rows

        # Football
        log("=== FOOTBALL path ===")
        foot = {"ok": False, "notes": [], "markets": {}}
        try:
            for sel in ["text=Football", 'xpath=//div[normalize-space()="Football"]']:
                try:
                    loc = page.locator(sel)
                    if loc.count() and loc.first.is_visible():
                        loc.first.click(timeout=3000)
                        foot["notes"].append(f"nav {sel}")
                        time.sleep(1.2)
                        break
                except Exception as e:
                    foot["notes"].append(str(e))
            opened = page.evaluate(
                """() => {
                  for (const name of ['Bournemouth','Liverpool','Man City','Leeds','Fulham','Sunderland']) {
                    const el=[...document.querySelectorAll('div,span')].find(e=>(e.innerText||'').trim()===name);
                    if (el) { const r=el.getBoundingClientRect(); if(r.width&&r.top>80){ el.click(); return name; } }
                  }
                  return null;
                }"""
            )
            foot["notes"].append(f"opened={opened}")
            time.sleep(1.5)
            for label, needles in [
                ("1X2/moneyline", ["1X2", "Full Time Result", "Match Result", "Result"]),
                ("asian_handicap", ["Asian Handicap", "Spread", "Handicap"]),
                ("totals", ["Goal Line", "Total", "Over/Under", "Goals"]),
            ]:
                disc = discover(page, needles)
                old = None
                try:
                    if label == "asian_handicap":
                        old = test_sel(page, S.category_button("Asian Handicap"))
                    elif label == "totals":
                        old = test_sel(page, S.category_button("Goal Line"))
                    else:
                        old = test_sel(page, S.category_button("Full Time Result"))
                        if not old.get("ok"):
                            old = test_sel(page, S.category_button("Match Result"))
                except Exception as e:
                    old = {"error": str(e)}
                foot["markets"][label] = {"discover": disc[:4], "old": old, "proposed": propose_from(disc)[0]}
                log(f"FOOT {label}: disc={len(disc)} prop={foot['markets'][label]['proposed']!r}")
            odds = click_first_odds(page)
            foot["notes"].append(f"selection_odds={odds}")
            time.sleep(1.2)
            slip = {n: test_sel(page, s) for n, s in [
                ("stake", S.STAKE_INPUT), ("place_bet", S.PLACE_BET_BUTTON), ("accept", S.ACCEPT_CHANGES_TEXT),
                ("remove", S.REMOVE_BUTTON), ("remove_all", S.REMOVE_ALL), ("done", S.DONE_BUTTON),
            ]}
            slip["discover"] = discover(page, ["Place Bet", "Stake", "Remove", "Bet Slip", "Singles"])
            slip["clear"] = clear_betslip(page)
            foot["betslip"] = slip
            foot["ok"] = True
        except Exception as e:
            foot["error"] = str(e)
        report["markets"]["football"] = foot

        # Basketball
        log("=== BASKETBALL path ===")
        bask = {"ok": False, "notes": [], "markets": {}}
        try:
            page.goto("https://www.bet365.com/#/HO/", wait_until="domcontentloaded", timeout=20000)
            time.sleep(1.5)
            for sel in ["text=Basketball", 'xpath=//div[normalize-space()="Basketball"]']:
                try:
                    loc = page.locator(sel)
                    if loc.count() and loc.first.is_visible():
                        loc.first.click(timeout=3000)
                        bask["notes"].append(f"nav {sel}")
                        time.sleep(1.5)
                        break
                except Exception as e:
                    bask["notes"].append(str(e))
            opened = page.evaluate(
                """() => {
                  const cands=[...document.querySelectorAll('div,a,span')];
                  for (const el of cands) {
                    const t=(el.innerText||'').trim();
                    if ((/vs|@|\\d{1,2}:\\d{2}/i.test(t) || /NBA|NCAA/i.test(t)) && t.length<70) {
                      const r=el.getBoundingClientRect();
                      if (r.width&&r.height&&r.top>100) { el.click(); return t.slice(0,60); }
                    }
                  }
                  return null;
                }"""
            )
            bask["notes"].append(f"opened={opened}")
            time.sleep(1.5)
            for label, needles in [
                ("moneyline", ["Money Line", "Moneyline", "Match Winner", "Winner", "To Win"]),
                ("spread", ["Spread", "Handicap", "Asian Handicap", "Line"]),
                ("totals", ["Total", "Over/Under", "Points", "O/U"]),
            ]:
                disc = discover(page, needles)
                bask["markets"][label] = {"discover": disc[:4], "proposed": propose_from(disc)[0]}
                log(f"BASK {label}: disc={len(disc)} prop={bask['markets'][label]['proposed']!r}")
            odds = click_first_odds(page)
            bask["notes"].append(f"selection_odds={odds}")
            time.sleep(1.0)
            slip = {n: test_sel(page, s) for n, s in [("stake", S.STAKE_INPUT), ("place_bet", S.PLACE_BET_BUTTON), ("remove", S.REMOVE_BUTTON)]}
            slip["discover"] = discover(page, ["Place Bet", "Stake", "Remove", "Bet Slip"])
            slip["clear"] = clear_betslip(page)
            bask["betslip"] = slip
            bask["ok"] = True
        except Exception as e:
            bask["error"] = str(e)
        report["markets"]["basketball"] = bask

        unchanged = sum(1 for r in rows if r["bucket"] == "unchanged")
        mod = sum(1 for r in rows if r["bucket"] == "modify")
        unusable = sum(1 for r in rows if r["bucket"] == "unusable")
        report["summary"] = {
            "unchanged": unchanged,
            "modify": mod,
            "unusable": unusable,
            "expected_fail_logged_in": sum(1 for r in rows if r["bucket"] == "expected_fail_logged_in"),
            "football_addressable": {
                "1x2": bool(foot.get("markets", {}).get("1X2/moneyline", {}).get("discover")),
                "spread": bool(foot.get("markets", {}).get("asian_handicap", {}).get("discover")),
                "totals": bool(foot.get("markets", {}).get("totals", {}).get("discover")),
            },
            "basketball_addressable": {
                "ml": bool(bask.get("markets", {}).get("moneyline", {}).get("discover")),
                "spread": bool(bask.get("markets", {}).get("spread", {}).get("discover")),
                "totals": bool(bask.get("markets", {}).get("totals", {}).get("discover")),
            },
            "betslip_readable": bool((foot.get("betslip") or {}).get("discover") or (bask.get("betslip") or {}).get("discover")),
            "logged_in": logged_in,
        }

        lines = [
            "# Bet365 Mobile Selector Audit",
            "",
            f"Generated: {report['ts']}",
            f"Surface: Android Chrome via CDP (logged_in={logged_in})",
            f"Browser: {version.get('Browser')}",
            "",
            "## Summary",
            "",
            f"- Reusable unchanged: **{unchanged}**",
            f"- Need modification: **{mod}**",
            f"- Unusable (no proposal yet): **{unusable}**",
            f"- Expected fail while logged-in (login UI): **{report['summary']['expected_fail_logged_in']}**",
            f"- Football 1X2/AH/totals discoverable: `{report['summary']['football_addressable']}`",
            f"- Basketball ML/spread/totals discoverable: `{report['summary']['basketball_addressable']}`",
            f"- Betslip fields discoverable: **{report['summary']['betslip_readable']}**",
            "",
            "## Rules followed",
            "",
            "- No stake entry, no Place Bet, no wager, no challenge bypass.",
            "- Selections clicked only to open betslip; betslip cleared after tests.",
            "",
            "## Table",
            "",
            "| Element | Old Selector | Mobile Works? | Proposed Selector | Confidence | Notes |",
            "|---|---|---|---|---|---|",
        ]
        for r in rows:
            old = (r.get("old_selector") or "").replace("|", "\\|")
            if len(old) > 80:
                old = old[:77] + "..."
            prop = (r.get("proposed") or "").replace("|", "\\|")
            notes = r.get("bucket", "")
            sample = (r.get("old_test") or {}).get("sample") or {}
            if sample.get("text"):
                notes += f"; text={sample['text'][:40]}"
            lines.append(
                f"| {r['element']} | `{old}` | {r['mobile_works']} | `{prop}` | {r.get('confidence')} | {notes} |"
            )
        lines += [
            "",
            "## Football notes",
            "",
            "```json",
            json.dumps(foot, indent=2)[:5000],
            "```",
            "",
            "## Basketball notes",
            "",
            "```json",
            json.dumps(bask, indent=2)[:5000],
            "```",
            "",
        ]
        AUDIT_MD.write_text("\n".join(lines), encoding="utf-8")
        LOG_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
        log(f"WROTE {AUDIT_MD}")
        log(f"WROTE {LOG_JSON}")
        log("SUMMARY " + json.dumps(report["summary"]))
        log("SUCCESS probe complete")


if __name__ == "__main__":
    main()
