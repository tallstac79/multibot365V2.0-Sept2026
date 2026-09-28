"""The Bet365 desktop betslip (signed in), read from its own elements.

The slip keeps readable class names (bss- / bsf- / bsc-, the same family the old Playwright bot used): one bet item
= title (selection), handicap (line), a price, market label and fixture description; the stake box is a
contenteditable; Place Bet carries its 'To Return' value. Captured live 28 Sep 2026 (Northern Ireland v Hungary,
Asian Handicap HOME 0.0 @1.950, stake 0.10 -> To Return 0.19). Nothing here ever presses Place Bet.
"""

READ_JS = r"""
() => {
  const vis = e => { if (!e) return false; const b = e.getBoundingClientRect(); const s = getComputedStyle(e);
                     return b.width > 0 && b.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const txt = e => e ? e.textContent.replace(/\s+/g, ' ').trim() : null;
  const box = e => { const b = e.getBoundingClientRect(); return [Math.round(b.left), Math.round(b.top), Math.round(b.right), Math.round(b.bottom)]; };
  const slip = [...document.querySelectorAll('.bss-StandardBetslip')].find(vis) || null;
  if (!slip) return {present: false, items: []};
  const items = [...slip.querySelectorAll('.bss-NormalBetItem_Title')].filter(vis).map(title => {
    let item = title; for (let i = 0; i < 6 && item.parentElement && !item.querySelector('.bss-NormalBetItem_Market'); i++) item = item.parentElement;
    const prices = [...item.querySelectorAll('span, div')].filter(e => vis(e) && e.childElementCount === 0 && /^\d+\.\d{2,3}$/.test(txt(e)));
    return {title: txt(title), handicap: txt(item.querySelector('.bss-NormalBetItem_Handicap')), market: txt(item.querySelector('.bss-NormalBetItem_Market')),
            fixture: txt(item.querySelector('.bss-NormalBetItem_FixtureDescription')), price: prices.length ? txt(prices[0]) : null,
            prices: prices.map(txt), text: txt(item).slice(0, 300)};
  });
  const pb = [...slip.querySelectorAll('.bsf-PlaceBetButton')].find(vis);
  const stake = [...slip.querySelectorAll('.bsf-StakeBox_StakeValue-input')].find(vis);
  return {present: true, items,
          stake: stake ? txt(stake) : null,
          place_bet: pb ? {text: txt(pb.querySelector('.bsf-PlaceBetButton_Text')), cls: String(pb.className), bounds: box(pb),
                           disabled: /Disabled|Hidden/.test(String(pb.className))} : null,
          to_return: txt(slip.querySelector('.bsf-PlaceBetButton_ReturnValue')),
          messages: [...slip.querySelectorAll('*')].filter(e => vis(e) && e.childElementCount === 0 && /change|accept|suspend|unavailable|closed|limit|error|sorry/i.test(txt(e) || '')).map(txt).slice(0, 6),
          error: /Sorry, there has been an error/i.test(txt(slip) || ''),
          text: txt(slip).slice(0, 600)};
}
"""

# Slip market labels per wire market (football as captured / as the phone's HeldSlipIdentity.labels; basketball's are the
# phone's labels - a basketball slip is verified against them and fails closed on anything else).
LABELS = {
    ('football', 'SPREAD'): {'asian handicap', 'alternative asian handicap'},
    ('football', 'TOTAL'): {'goal line', 'alternative goal line', 'goals over/under', 'alternative total goals'},
    ('football', 'MONEYLINE'): {'full time result'},
    ('basketball', 'SPREAD'): {'point spread', 'spread'},
    ('basketball', 'TOTAL'): {'game totals', 'total', 'game total'},
    ('basketball', 'MONEYLINE'): {'money line'},
}


async def read(page):
    return await page.evaluate(READ_JS)


async def clear(page, attempts=8):
    """Remove every selection with the slip's own remove buttons; True when the slip holds nothing."""
    for _ in range(attempts):
        state = await read(page)
        if not state['items']:
            return True
        await page.locator('.bss-StandardBetslip .bss-RemoveButton').first.click()
        await page.wait_for_timeout(900)
    return not (await read(page))['items']


async def wait_items(page, count, timeout_ms=6000):
    waited = 0
    while waited < timeout_ms:
        state = await read(page)
        if len(state['items']) == count or state.get('error'):
            return state
        await page.wait_for_timeout(300); waited += 300
    return await read(page)


async def enter_stake(page, stake):
    box = page.locator('.bss-StandardBetslip .bsf-StakeBox_StakeValue-input').first
    await box.click()
    await page.wait_for_timeout(300)
    await page.keyboard.press('Control+A')
    await page.keyboard.press('Backspace')
    await page.keyboard.type(stake, delay=70)
    await page.wait_for_timeout(1200)
    return await read(page)


def money(text):
    try:
        return float(str(text).replace('£', '').replace(',', '').strip())
    except (TypeError, ValueError):
        return None
