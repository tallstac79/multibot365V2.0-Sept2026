import asyncio, json, sys
sys.path.insert(0, r'C:\Users\WINDOWS11\Desktop\MultiBotV2.0\MultiBot365')
from playwright.async_api import async_playwright
from desktop_worker import chrome, bet365_page as bp
from desktop_worker.layout import read_words
JS = r"""() => {
 const nat = f => { try { return /\{\s*\[native code\]\s*\}$/.test(Function.prototype.toString.call(f)); } catch(e) { return 'err ' + e; } };
 const names = ['querySelector','querySelectorAll','getElementsByClassName','getElementById','getElementsByTagName'];
 const out = {fnToStringNative: nat(Function.prototype.toString)};
 for (const n of names) { out['Document.' + n] = nat(Document.prototype[n]); out['Element.' + n] = nat(Element.prototype[n]);
   out['docOwn.' + n] = Object.prototype.hasOwnProperty.call(document, n); }
 out.getComputedStyle = nat(window.getComputedStyle); out.gbcr = nat(Element.prototype.getBoundingClientRect);
 out.MutationObserver = nat(window.MutationObserver);
 out.docOwnProps = Object.getOwnPropertyNames(document).slice(0, 30);
 out.webdriver = navigator.webdriver;
 return out; }"""
async def main():
    async with async_playwright() as p:
        b, ctx, page = await chrome.connect(p)
        print('url', page.url)
        words = await read_words(page)
        print('logged_in', bp.logged_in(words))
        print(json.dumps(await page.evaluate(JS), indent=1))
asyncio.run(main())
