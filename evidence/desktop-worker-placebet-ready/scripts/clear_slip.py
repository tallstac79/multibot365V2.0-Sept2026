"""Leave the account's slip empty after the supervised runs: screenshot check + the slip's visible remove (X) (the
worker's RESET_BETSLIP path, DesktopBet365.empty_slip). Evidence copied to runs/cleanup/."""
import asyncio, shutil, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from playwright.async_api import async_playwright
from desktop_worker import chrome
from desktop_worker.workflow import DesktopBet365, Run

async def main():
    async with async_playwright() as p:
        b, ctx, page = await chrome.connect(p)
        run = Run(dict(instruction_id='cleanup'), lambda *a: None)
        removed = await DesktopBet365(page, None).empty_slip(run)
        rec = run.finish('PASS', 'PASS', f'BETSLIP_CLEARED ({removed} removed)')
        dest = ROOT / 'evidence' / 'desktop-worker-placebet-ready' / 'runs' / 'cleanup'
        shutil.rmtree(dest, ignore_errors=True); shutil.copytree(run.dir, dest)
        print(rec['detail'])
asyncio.run(main())
