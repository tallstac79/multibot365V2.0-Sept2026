"""Supervised Place Bet-ready runs of the desktop worker's own hold workflow (desktop_worker.workflow.DesktopBet365.hold),
one instruction file per run, in the dedicated signed-in Chrome. The workflow stops at a verified, enabled Place Bet and
never presses it; this runner adds nothing to the page. Each run's evidence directory is copied under runs/.

    py -3.11 evidence/desktop-worker-placebet-ready/scripts/run_ready.py LABEL instructions/a.json [instructions/b.json ...]
"""
import asyncio, json, shutil, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from playwright.async_api import async_playwright
from desktop_worker import chrome
from desktop_worker.decisions import Decisions
from desktop_worker.workflow import DesktopBet365, Failure, Run

OUT = ROOT / 'evidence' / 'desktop-worker-placebet-ready' / 'runs'
KEEP = ('instruction_id', 'run_id', 'status', 'stage', 'detail', 'duration_ms', 'fixture_name', 'selection', 'addbet', 'stake_entry',
        'betslip_clear', 'ready_state', 'complete_execution_ready', 'readback_rereads', 'wager_submitted', 'football_band_choice')


async def main():
    label, files = sys.argv[1], sys.argv[2:]
    d = Decisions()
    summary = []
    async with async_playwright() as p:
        b, ctx, page = await chrome.connect(p)
        for k, f in enumerate(files, 1):
            body = json.loads(Path(f).read_text(encoding='utf-8'))
            body = dict(body, instruction_id=f"{label}-{k:02d}-{body['instruction_id']}"[:64], execution_mode='hold')
            run = Run(body, lambda *a: None)
            site = DesktopBet365(page, d)
            t0 = time.time()
            try:
                stage, detail = await site.hold(run, 'hold')
                rec = run.finish('PASS', 'PASS', detail)
            except Failure as e:
                rec = run.finish('FAIL', e.stage, e.detail)
            except Exception as e:
                rec = run.finish('FAIL', 'INTERNAL_ERROR', repr(e)[:400])
            dest = OUT / body['instruction_id']
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(run.dir, dest)
            (dest / 'instruction.json').write_text(json.dumps(body, indent=1), encoding='utf-8')
            row = {k: rec.get(k) for k in KEEP if k in rec}
            summary.append(row)
            print(json.dumps(dict(run=body['instruction_id'], status=rec['status'], stage=rec['stage'], detail=rec['detail'],
                                  secs=round(time.time() - t0, 1)), ensure_ascii=False), flush=True)
            await page.wait_for_timeout(1500)
    d.close()
    (OUT / f'{label}_summary.json').write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding='utf-8')

asyncio.run(main())
