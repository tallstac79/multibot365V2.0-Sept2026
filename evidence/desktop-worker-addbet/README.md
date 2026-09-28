# Desktop worker: addbet `{"cs":2,"sr":-1}` investigation (28 Sep 2026, 13:05-13:40 BST)

Signed-in dedicated Chrome (CDP 127.0.0.1:9333), Northern Ireland v Hungary (pre-match, UEFA Nations League B),
Asian Handicap HOME 0.0 @ 1.975. Each trial: fresh document load of the event link, the worker's own discovery
(text + geometry), one optional query, one click on the selection cell, Bet365's `BetsWebAPI/addbet` exchange
recorded, then the same cell clicked again to remove it. Place Bet was never touched in any trial; no stake was entered.

## Result

| variant (run just before the click) | where the query runs | trials | addbet |
| --- | --- | --- | --- |
| A: nothing | - | 01, 03, 08, 12 | 4/4 accepted (bet item returned) |
| B: `document.querySelectorAll('.bss-StandardBetslip')` via page.evaluate | page main world | 10, 13 (+02, 07, 09*) | 2/2 recorded `{"cs":2,"sr":-1}` + "Sorry, there has been an error" |
| C: `document.querySelectorAll('.zzq-NotABet365Class')` (not a Bet365 or betslip class; matches nothing) | page main world | 11 (+04*) | 1/1 recorded `{"cs":2,"sr":-1}` |
| D: Playwright `locator('.bss-StandardBetslip').count()` (returned 1) | Playwright's isolated world, same CDP session | 05 | accepted |
| E: `document.querySelectorAll('div')` | page main world | 06 | accepted |

\* 02, 04, 07, 09 ran before the recorder tolerated the slip's error overlay: the removal click timed out because
`bsm-BetslipStandardModule_CondensedOverlayShow` (the error modal) intercepted pointer events, i.e. the same failure,
but their JSON was not written. A plain run after every failure was accepted again (03, 08, 12): the effect lasts one
page load.

What is identical between accepted and refused runs (`summary.json`): addbet URL, method, POST body (byte-identical),
request header names, cookie names sent, slip empty before the click, page-ready and click timings (click->addbet
142-2297 ms in both groups, so timing is not the discriminator), and no cookie value or localStorage key changed in
any trial. Header values that differ per request are only `x-net-sync-term` and `x-request-id`, which differ on every
request, passing or failing.

## Why: the page instruments its own DOM query APIs

`page_dom_api_natives.txt` / `page_dom_api_hooks.json`: on bet365.com, `document.querySelector`,
`document.querySelectorAll`, `document.getElementsByClassName`, `document.getElementsByTagName` are overridden as own
properties of `document`, and `Element.prototype.querySelector/querySelectorAll/getElementsByClassName/
getElementsByTagName` are replaced. All eight are the same obfuscated wrapper (`_0x...` identifiers) that copies
`this` and the call arguments (the selector) into an interpreter (`_0x101677(_0x5ac29f)`) before answering. That is
Bet365's own client-side integrity/anti-automation instrumentation.

Consistent with it: the refusal follows a call into those wrappers with a class selector from injected script (B and
C, including a class that does not exist and is not a betslip class), not the betslip selector itself (D reads the
same betslip element through Playwright's isolated world, which does not pass through the page's wrappers, and is
accepted), not CDP (D, E use the same CDP session and pass; no extra CDP domains differ between B and D), and not app
state (same page, empty slip, same cookies/storage, same request). The server-side verdict must ride on the only
per-request value the page script computes, `x-net-sync-term` (not decodable here, and not attempted).

Conclusion: this is real bot detection by Bet365, not a race, focus, stale-selection, session or CDP side effect.

## Not done, deliberately

Reading the slip in a way the page cannot see (isolated-world locators, CDP DOM domain, text walkers) would make the
error go away (variant D shows it), but only because it hides the automation from Bet365's check. That is evasion of
the site's anti-automation control and is outside the project rules, so no fix was implemented and nothing was
committed. The committed worker still calls the hooked `querySelectorAll` in `betslip.read` (clear / wait_items) and
fails closed with BETSLIP_ERROR.

`scripts/` holds the probe scripts (run with the system Python 3.11, Playwright 1.56). Values of cookies, tokens and
account identifiers are redacted; cookie names are kept.
