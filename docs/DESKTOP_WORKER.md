# Desktop Chrome worker (supervised build)

A second execution worker that speaks the phone coordinator's HTTP contract but drives Bet365 in desktop Chrome.
The backend remains the only source of truth. The worker receives the same instruction payloads the phone receives
(`Pipeline.build_payload`) and returns results in the phone's schema.

## Parts

| File | Role |
| --- | --- |
| `desktop_worker/chrome.py` | Installed Google Chrome with a dedicated profile (`.local/desktop-chrome-profile`) and a CDP port on 127.0.0.1:9333. Playwright uses `connect_over_cdp`. There is no Multilogin or antidetect layer. The operator signs in by hand, and the code never types or reads credentials. |
| `desktop_worker/layout.py` | Visible page text plus geometry from the DOM (a TreeWalker over text nodes; it calls none of the page's wrapped query APIs), in the phone's OCR word format. Used on the event / market pages only, before the selection click. Read-only: the page is never tagged or modified. |
| `desktop_worker/bet365_page.py` | Pure functions that turn the page into the phone's header lines and quotes. Group titles are found by font (15px bold) and columns by bold headers. |
| `desktop_worker/jvm/DesktopDecisions.java` + `decisions.py` | Decision bridge. The phone's own Java classes (EventPage / EventIdentity / CompetitionStructure / FootballLineCheck / ExecutionTolerance / FootballMarkets / HeldSlipIdentity) are compiled unchanged from `android/` into `.local/desktop-decisions/decisions.jar`. One JVM answers over stdin/stdout, and the jar is rebuilt whenever a source is newer. Identity, competition, kick-off, the football ±0.25 line band and the price/line tolerances are therefore identical to the phone's. |
| `desktop_worker/ledger.py` | SQLite at-most-once ledger. An ID is committed before it is acknowledged and is never evicted. At restart, PENDING becomes INTERNAL_ERROR and is never replayed. |
| `desktop_worker/server.py` | HTTP on 127.0.0.1:8768 with a bearer token (`.local/desktop_worker.json`). Endpoints: `/health`, `POST /instructions` (202; 409 DUPLICATE; 409 BUSY "ID not consumed"), `GET /instructions/ID` (202 pending / 200), `/evidence`, `/artifacts/NAME`. |
| `desktop_worker/workflow.py` | SESSION_CHECK, and ADAPTER_WORKFLOW hold/ready plus the supervised-only `discover`. The betslip part (empty-slip check to Place Bet check) is visual only. |
| `desktop_worker/visual_slip.py` | The betslip as a person sees it: CDP `Page.captureScreenshot`, Tesseract OCR (`C:\Program Files\Tesseract-OCR`), ordinary mouse clicks / keyboard typing at coordinates read from the screenshot, and Bet365's own `BetsWebAPI/addbet` answer read passively. No script in the page, no DOM query of the slip. It has no function that presses Place Bet. |
| `desktop_worker/betslip.py` | Slip market-label vocabulary (`LABELS`, plus `GROUP_LABELS`: 'Total Goals' only for a quote from the Goals Over/Under group) and `money()`. The old DOM slip reader is removed. |
| `tools/desktop_supervised.py` | Sends one run to the desktop worker: either a payload built by `Pipeline.build_payload` from a private copy of the production row (fresh `sup-` ID), or a manual payload. It then judges the result with `execution_terms.comparisons_for_result`. |

## Safety properties

- `health.phone_final_action_armed` and `local_execution.enabled` are always false, so the automatic policy's `phone_final_action_permission` check can never pass for this worker.
- PLACE_HELD and MY_BETS are refused with `placement {tapped: false, outcome: NOT_TAPPED}`.
- Only the alert's own pre-match `#/AC/` link is used. The Search route is not implemented and fails closed.
- Prices must be decimal. Fractional odds, which a logged-out session shows, are never used as a price.
- Every step saves a text layout (`sNNN_name.txt`, the phone's OCR format) and a screenshot under `.local/desktop-evidence/<run_id>/`.

## Run

```
python -m desktop_worker.server
python -m tools.desktop_supervised --manual evidence/desktop-worker/manual_nir_ah_home.json --mode discover
python -m tools.desktop_supervised --instruction on-xxxxxxxx --mode hold
py -3.11 evidence/desktop-worker-placebet-ready/scripts/run_ready.py LABEL evidence/desktop-worker-placebet-ready/instructions/nir_ah_home_0.json ...
```

## Status, 28 Sep 2026 (supervised trials on a separate account)

- Proven: loopback worker contract, session check, event link opened (a hash-only navigation can show a stale "no
  longer available" page, so the worker reloads once), EXACT identity from the phone's decision code, market discovery
  (Popular, then Goals / Asian Lines, then the market's own alternative group), exact line first, the ±0.25 band via
  the phone's `nearest`, minimum price check, a fresh re-read of the cell before clicking, and slip reading (title,
  handicap, price, market, fixture, stake, To Return, Place Bet). One manual slip capture: AH HOME 0.0 @1.950, stake
  0.10, To Return £0.19, Place Bet enabled, removed again.
- Stopped, cause identified (bisected 28 Sep 2026, every run recording Bet365's own `BetsWebAPI/addbet` exchange):
  the `addbet` request is byte-identical in passing and failing runs. What decides is whether a script has queried
  Bet365's betslip elements beforehand:

  | evaluated in the page before the selection click | `addbet` |
  | --- | --- |
  | nothing, a 300 ms wait, reading the page text (`layout.read_words`) | accepted |
  | `document.querySelectorAll('div')` | accepted |
  | `querySelectorAll('.bss-StandardBetslip')`, even followed by a 3 s wait | `{"cs":2,"sr":-1}`: "Sorry, there has been an error" |
  | `querySelectorAll('.bss-NormalBetItem_Market')` | the same |

  A plain DOM query has no side effects, so this is Bet365 watching for scripts that inspect its betslip and refusing
  the next bet-slip addition: an anti-automation check. Reworking the worker so the check does not fire would be
  designing around Bet365's bot detection, and that is not done. The worker fails closed (`BETSLIP_ERROR`, with the
  `addbet` exchange in its evidence). Everything before the slip (event, identity, market, line, price, the click
  target found by text and geometry without modifying the page) works and stays useful for replay and verification.

### Independent re-check, 28 Sep 2026 13:05-13:40 BST (`evidence/desktop-worker-addbet/`)

Re-tested from scratch with paired runs on the same event and cell (Place Bet never touched). Result: real detection,
now with its mechanism shown.

- Bet365 replaces `document.querySelector/querySelectorAll/getElementsByClassName/getElementsByTagName` and the
  `Element.prototype` equivalents with one obfuscated wrapper that passes every call's selector into its own
  interpreter (`page_dom_api_hooks.json`).
- Plain click: 4/4 accepted. Main-world `querySelectorAll('.bss-StandardBetslip')`: refused every time. Main-world
  `querySelectorAll('.zzq-NotABet365Class')` (no betslip, matches nothing): refused. `querySelectorAll('div')`:
  accepted. The same `.bss-StandardBetslip` read through Playwright's isolated world (does not pass through the page's
  wrappers, same CDP session): accepted.
- addbet URL, POST body, header names, cookie names, slip state, timings, cookies and storage are identical between
  accepted and refused runs; only the per-request `x-net-sync-term` / `x-request-id` values differ (as they do on every
  request).
- So it is not a betslip-init race, focus, stale selection, session or CDP-domain side effect. A worker change that
  avoids the check (isolated-world or CDP-DOM reads) would work only by hiding automation from Bet365 and is not made.
  The worker remains fail-closed at BETSLIP_ERROR. The event / identity / market / line / price stages are unaffected.

## Place Bet-ready without in-page slip scripts, 28 Sep 2026 14:28-15:10 BST (`evidence/desktop-worker-placebet-ready/`)

David approved removing the flagged action instead of hiding it. The slip flow no longer runs any script in the page
and never queries the slip's DOM (no `page.evaluate`, no Playwright locator, no CDP DOM/Runtime read of the slip, no
isolated-world reads). It works the way a person does:

| step | how | verified by |
| --- | --- | --- |
| empty slip | right after the fresh event load: screenshot; if the white slip panel is showing, click its visible remove (X), then load the page afresh and check again | screenshots `slip_check`, `slip_after_remove`, `slip_after_reload`, `slip_before_click` |
| add selection | the existing fresh read of the grid and the existing click on the price cell (unchanged) | Bet365's own `addbet` response to that click (`cs:1 sr:0`, exactly one bet), read passively, plus a screenshot of the slip |
| slip terms | OCR of the slip panel: selection + handicap, price, market, fixture | each checked on the screen AND in the addbet answer (fixture, market label, selection, line, odds within 0.011), one selection on both; the price is then judged by the phone's tolerances (`fresh` / `price_ok` / `line_ok`) |
| stake | click the slip's own stake control ('Set Stake' or the Stake box) found on the screenshot, then Ctrl+A, Backspace and type the stake | OCR: the stake equals the instruction; To Return = stake x price (±0.011) |
| Place Bet | located from the 'Place' 'Bet' words; enabled = the button face is Bet365's active green (grey when disabled) | OCR + pixel colour on two frames (`slip_stake`, `slip_final`), no notice on the slip |
| stop | READY / `COMPLETE_EXECUTION_READY` in the existing result schema; `gesture_dispatched: false`, `wager_submitted: false` | Place Bet is never clicked; the code has no path that clicks it |

A read that does not come out cleanly is retaken (up to 6 frames, 400 ms apart; the stake box's blinking caret can hide
a digit), and nothing is accepted from a frame that does not read cleanly. The term checks use the phone's readback
rule (up to 3 frames). Price and line changes follow MultiBot's existing rules. A slip price or line is judged by the
phone's tolerances. Any change notice fails closed, and a notice asking to accept a change fails `PRICE_CHANGED`,
because MultiBot never presses Accept Change (the phone's `PlaceBetTarget.changeNotice` rule). No change notice came up
in these runs. A Bet365 'Reality Check' dialog fails `SESSION_EXPIRED`: the operator answers it by hand, and the worker
never does.

Before the click, the event / market stages are unchanged: `layout.read_words` (a TreeWalker text read, not a wrapped
API) and `open_tab` / `expand` / `element_for` (Playwright locators on the event grid, not the slip). The paired trials
and every run below had these before the click, and Bet365 accepted every addbet, so nothing there was changed.

Result with the final code (batch `final`: 15 runs, 4 events, AH / Goal Line / Goals Over/Under / Full Time Result,
home / away / over / under): **14/15 reached Place Bet-ready and stopped**. The one miss (`final-11`, Sweden AH 0.0)
failed closed before any click with `LINE_CHANGED`. The existing discovery read the expanded Alternative Asian Handicap
while the page was still laying out (the next group's title still sat over the new rows), so the 0.0 row was assigned
to the wrong group. That is pre-existing discovery behaviour, left unchanged by instruction.

Across all 30 live runs (calibration 3, first proof batch 12, final 15), the worker clicked a selection 26 times and
Bet365 accepted all 26 addbets (`cs:1 sr:0`), with zero `{"cs":2,"sr":-1}`. Stake entry and the Place Bet checks
caused no further BetsWebAPI traffic and no slip notices, so the screenshot / OCR / passive-response verification does
not itself cause refusals. First-batch failures, fixed before `final`:

- 3 runs: Bet365 labels the Goals Over/Under group 'Total Goals' on the slip. That label is now accepted for that group only.
- 1 run: one whole-panel OCR pass missed the footer. The footer band is now read on its own, and the first slip frame must show the stake control and Place Bet.

Also seen and left unchanged (existing event / market logic): Turkiye 1X2 is never found, because the decision bridge
returns the folded name 'Turkiye' while the page shows 'Türkiye', so the Full Time Result row does not match. It fails
closed with `TARGET_NOT_FOUND`, and no click is made.
