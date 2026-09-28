"""Visible page text with geometry, read from the DOM instead of OCR.

Bet365's class names are build hashes (rgl-43895c ...) that change between deploys, so nothing here depends on them.
Every visible text node becomes a word record {text, l, t, r, b} in page (document) coordinates - the same shape as the
phone's OCR words ("text [l,t][r,b]"). Strictly read-only: the page is never modified (an earlier build tagged price
elements with a data attribute while the page was still rendering, and Bet365's slip then answered "Sorry, there has
been an error", 28 Sep 2026). A chosen quote is clicked by finding its element again by exact text and position.
"""

EXTRACT_JS = r"""
(root) => {
  const scope = (root && document.querySelector(root)) || document.body;
  if (!scope) return [];
  const out = [];
  const sx = window.scrollX, sy = window.scrollY;
  const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode;
    const text = node.textContent.replace(/\s+/g, ' ').trim();
    if (!text) continue;
    const el = node.parentElement;
    if (!el) continue;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none' || parseFloat(st.opacity) === 0) continue;
    const range = document.createRange(); range.selectNodeContents(node);
    const rects = range.getClientRects();
    if (!rects.length) continue;
    const r = rects[0], last = rects[rects.length - 1];
    if (r.width === 0 || r.height === 0) continue;
    const id = /^(\d+\/\d+|\d+\.\d{1,3}|EVS)$/.test(text) ? 'price' : null;
    out.push({text, l: Math.round(r.left + sx), t: Math.round(r.top + sy), r: Math.round(last.right + sx), b: Math.round(last.bottom + sy), q: id,
              fs: Math.round(parseFloat(st.fontSize)), fw: parseInt(st.fontWeight) || 400});
  }
  return out;
}
"""


async def read_words(page, root=None):
    return await page.evaluate(EXTRACT_JS, root)


def as_text(words):
    """The phone's OCR text format, for evidence files and offline replay."""
    return '\n'.join(f"{w['text']} [{w['l']},{w['t']}][{w['r']},{w['b']}]" for w in words)


def lines(words, tolerance=4):
    """Group words into visual rows (same top within `tolerance` px), left to right: [(top, [words])]."""
    rows = []
    for w in sorted(words, key=lambda w: (w['t'], w['l'])):
        if rows and abs(rows[-1][0] - w['t']) <= tolerance:
            rows[-1][1].append(w)
        else:
            rows.append((w['t'], [w]))
    return [(t, sorted(ws, key=lambda w: w['l'])) for t, ws in rows]
