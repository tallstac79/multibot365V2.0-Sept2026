import asyncio, json, sys
sys.path.insert(0, r'C:\Users\WINDOWS11\Desktop\MultiBotV2.0\MultiBot365')
from playwright.async_api import async_playwright
from desktop_worker import chrome
JS = r"""() => {
 const src = f => { try { return Function.prototype.toString.call(f).slice(0, 1500); } catch(e) { return 'err ' + e; } };
 const d = n => { const x = Object.getOwnPropertyDescriptor(document, n); return x ? {w: x.writable, e: x.enumerable, c: x.configurable, src: src(x.value)} : null; };
 const e = n => src(Element.prototype[n]);
 return {doc_qsa: d('querySelectorAll'), doc_qs: d('querySelector'), doc_gebc: d('getElementsByClassName'), doc_gebt: d('getElementsByTagName'),
   el_qsa: e('querySelectorAll'), el_qs: e('querySelector'), el_gebc: e('getElementsByClassName'), el_gebt: e('getElementsByTagName'),
   same: document.querySelectorAll === Element.prototype.querySelectorAll};
}"""
async def main():
    async with async_playwright() as p:
        b, ctx, page = await chrome.connect(p)
        print(json.dumps(await page.evaluate(JS), indent=1))
asyncio.run(main())
