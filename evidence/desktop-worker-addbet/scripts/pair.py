"""Paired addbet experiment. Never touches Place Bet: only the selection cell is clicked (to add, then again to remove)."""
import asyncio, hashlib, json, sys, time
from pathlib import Path
sys.path.insert(0, r'C:\Users\WINDOWS11\Desktop\MultiBotV2.0\MultiBot365')
from playwright.async_api import async_playwright
from desktop_worker import chrome, bet365_page as bp
from desktop_worker.decisions import Decisions
from desktop_worker.layout import read_words, as_text
from desktop_worker.workflow import DesktopBet365, Run

OUT = Path(r'C:\Users\WINDOWS11\Desktop\MultiBotV2.0\MultiBot365\.local\addbet-probe\runs'); OUT.mkdir(parents=True, exist_ok=True)
INSTR = json.loads(Path(r'C:\Users\WINDOWS11\Desktop\MultiBotV2.0\MultiBot365\evidence\desktop-worker\manual_nir_ah_home.json').read_text())
SENSITIVE = {'cookie', 'authorization', 'x-net-sync-term', 'x-request-id'}
h = lambda v: hashlib.sha256((v or '').encode()).hexdigest()[:10]

async def variant(page, name):
    if name == 'A_plain': return None
    if name == 'B_eval_bss': return await page.evaluate("document.querySelectorAll('.bss-StandardBetslip').length")
    if name == 'C_eval_other': return await page.evaluate("document.querySelectorAll('.zzq-NotABet365Class').length")
    if name == 'D_locator_bss': return await page.locator('.bss-StandardBetslip').count()
    if name == 'E_eval_div': return await page.evaluate("document.querySelectorAll('div').length")
    raise ValueError(name)

async def trial(page, d, name, idx):
    rec = dict(variant=name, idx=idx)
    run = Run(dict(INSTR, instruction_id=f'probe-{idx}-{name}'), lambda *a: None)
    site = DesktopBet365(page, d)
    t0 = time.monotonic(); ms = lambda: int((time.monotonic() - t0) * 1000)
    words = await site.open_event(run, INSTR['event_url'])
    rec['page_ready_ms'] = ms(); rec['logged_in'] = bp.logged_in(words)
    teams = d.call('teams', bp.header(words))
    pick, _ = await site.discover(run, words, 'football', 'SPREAD', 'HOME', '0.0', '0.25', teams)
    assert pick, 'no AH HOME 0.0'
    rec['pick'] = dict(line=pick['line'], price=pick['raw_price'], name=pick['name'])
    before_words = await read_words(page)
    rec['slip_text_before'] = [w['text'] for w in before_words if w['l'] > 1000][:40]
    rec['cookies_before'] = {c['name']: h(c['value']) for c in await page.context.cookies('https://www.bet365.com')}
    rec['storage_keys_before'] = await page.evaluate('Object.keys(localStorage).sort()')
    cell = await site.element_for(pick)
    assert cell is not None, 'cell not unique'
    console, reqs = [], []
    page.on('console', lambda m: console.append(dict(t=ms(), type=m.type, text=m.text[:300])))
    async def on_resp(resp):
        r = resp.request
        e = dict(t=ms(), method=r.method, url=resp.url.split('?')[0][:140], status=resp.status, type=r.resource_type)
        if 'BetsWebAPI' in resp.url:
            hdr = await r.all_headers()
            e['headers'] = {k: (f'<redacted:{h(v)}>' if k.lower() in SENSITIVE else v) for k, v in hdr.items()}
            e['cookie_names_sent'] = sorted(p.split('=')[0].strip() for p in hdr.get('cookie', '').split(';') if p.strip())
            e['post'] = r.post_data or ''
            try: e['body'] = (await resp.text())[:800]
            except Exception as x: e['body'] = f'<{x}>'
        reqs.append(e)
    handler = lambda r: asyncio.ensure_future(on_resp(r))
    page.on('response', handler)
    rec['query_at_ms'] = ms(); rec['query_result'] = await variant(page, name)
    rec['click_at_ms'] = ms()
    await page.screenshot(path=str(OUT / f'{idx:02d}_{name}_postquery.png'))
    try:
        await cell.click(timeout=8000)
    except Exception as x:
        rec['click_error'] = str(x)[:3000]; print(idx, name, 'CLICK_ERROR', str(x)[:2500], flush=True)
        await page.screenshot(path=str(OUT / f'{idx:02d}_{name}_clickfail.png'))
        rec['words_at_fail'] = as_text(await read_words(page))[:20000]
    for _ in range(40):
        await page.wait_for_timeout(200)
        if any('addbet' in r['url'] and 'body' in r for r in reqs): break
    await page.wait_for_timeout(1500)
    add = [r for r in reqs if 'addbet' in r['url']]
    rec['addbet'] = add
    rec['addbet_ok'] = bool(add) and '"sr":-1' not in add[0].get('body', '') 
    after = await read_words(page)
    rec['slip_error_shown'] = any('Sorry, there has been an error' in w['text'] for w in after)
    rec['slip_text_after'] = [w['text'] for w in after if w['l'] > 1000][:40]
    await page.screenshot(path=str(OUT / f'{idx:02d}_{name}_after.png'))
    # remove again: click the same selection cell (a user's toggle); never the slip's buttons
    cell2 = await site.element_for(pick)
    if cell2 is not None:
        try:
            await cell2.click(timeout=8000); await page.wait_for_timeout(1800)
        except Exception as x:
            rec['remove_error'] = str(x)[:3000]; print(idx, name, 'REMOVE_ERROR', str(x)[:2000], flush=True)
            await page.screenshot(path=str(OUT / f'{idx:02d}_{name}_removefail.png'))
    page.remove_listener('response', handler)
    rec['requests'] = reqs; rec['console'] = console
    rec['cookies_after'] = {c['name']: h(c['value']) for c in await page.context.cookies('https://www.bet365.com')}
    rec['storage_keys_after'] = await page.evaluate('Object.keys(localStorage).sort()')
    fin = await read_words(page)
    rec['slip_text_final'] = [w['text'] for w in fin if w['l'] > 1000][:20]
    (OUT / f'{idx:02d}_{name}.json').write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding='utf-8')
    print(idx, name, 'ready', rec['page_ready_ms'], 'q', rec['query_result'], 'click', rec['click_at_ms'],
          'addbet', [(r['t'], r.get('body')) for r in add], 'err_shown', rec['slip_error_shown'], flush=True)

async def main():
    seq = sys.argv[1].split(',')
    start = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    d = Decisions()
    async with async_playwright() as p:
        b, ctx, page = await chrome.connect(p)
        for k, name in enumerate(seq):
            try: await trial(page, d, name, start + k)
            except Exception as e: print(start + k, name, 'ERROR', repr(e)[:300], flush=True)
    d.close()
asyncio.run(main())

