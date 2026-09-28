# Desktop Chrome worker (supervised build)

A second execution worker that speaks the phone coordinator's HTTP contract but drives Bet365 in desktop Chrome.
The backend remains the only source of truth. The worker receives the same instruction payloads the phone receives
(`Pipeline.build_payload`) and returns results in the phone's schema.

## Parts

| File | Role |
| --- | --- |
| `desktop_worker/chrome.py` | Installed Google Chrome with a dedicated profile (`.local/desktop-chrome-profile`) and a CDP port on 127.0.0.1:9333. Playwright uses `connect_over_cdp`. There is no Multilogin or antidetect layer. The operator signs in by hand, and the code never types or reads credentials. |
| `desktop_worker/layout.py` | Visible page text plus geometry from the DOM, in the phone's OCR word format. Price elements get a per-read click tag (`data-mbq`). Nothing depends on Bet365's hashed class names. |
| `desktop_worker/bet365_page.py` | Pure functions that turn the page into the phone's header lines and quotes. Group titles are found by font (15px bold) and columns by bold headers. |
| `desktop_worker/jvm/DesktopDecisions.java` + `decisions.py` | Decision bridge. The phone's own Java classes (EventPage / EventIdentity / CompetitionStructure / FootballLineCheck / ExecutionTolerance / FootballMarkets / HeldSlipIdentity) are compiled unchanged from `android/` into `.local/desktop-decisions/decisions.jar`. One JVM answers over stdin/stdout, and the jar is rebuilt whenever a source is newer. Identity, competition, kick-off, the football ±0.25 line band and the price/line tolerances are therefore identical to the phone's. |
| `desktop_worker/ledger.py` | SQLite at-most-once ledger. An ID is committed before it is acknowledged and is never evicted. At restart, PENDING becomes INTERNAL_ERROR and is never replayed. |
| `desktop_worker/server.py` | HTTP on 127.0.0.1:8768 with a bearer token (`.local/desktop_worker.json`). Endpoints: `/health`, `POST /instructions` (202; 409 DUPLICATE; 409 BUSY "ID not consumed"), `GET /instructions/ID` (202 pending / 200), `/evidence`, `/artifacts/NAME`. |
| `desktop_worker/workflow.py` | SESSION_CHECK, and ADAPTER_WORKFLOW hold/ready plus the supervised-only `discover`. |
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
