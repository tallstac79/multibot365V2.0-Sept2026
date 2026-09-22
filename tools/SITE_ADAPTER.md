# Generic visual adapter workflow

Milestone 5 extends the local fictional fixture simulator with football and basketball catalogs, DRAW on football 1X2, a simulated stake dry-run readout, minimum-price gating, and a stale-list scenario. It has no account, transaction, wager or external data endpoint. Stake is display-only on the final DRYRUN page. The simulator is served by the phone at `/neutral/simulator.html`; Windows only sends instructions and reads results/evidence.

## Contract and boundaries

`SiteAdapter` defines asynchronous `open_home`, `open_search`, `enter_query(query)`, `discover_fixture`, `select_fixture(fixture)`, `verify_event(fixture)`, `discover_markets`, `read_selection`, `read_line`, `read_price`, `open_selection`, and `verify_final_state(fixture, selection, stake)` methods. Fixture and selection values carry exact observed text and screenshot-derived bounds.

- `AdapterWorkflow` sequences those methods and handles outcomes. After `READ_PRICE`, if the parsed price is strictly below `minimum_price`, it fails with stage `BELOW_MINIMUM`. It contains no page labels, layout rules or fixture names.
- `VisualSession` performs Chrome launches, screenshots, gesture dispatch, verified text-entry steps, deadlines and atomic evidence checkpoints. `VisualScreen` groups OCR words by their measured geometry. Table capture refines separately detected cells with single-line OCR; digit-bearing cells use a numeric character alphabet without expected-value hints. Final line/price fields also receive independent cropped-region OCR. Navigation keeps the existing full-page OCR mode.
- `LocalSimulatorAdapter` owns every simulator label, page precondition, parsing rule and expected layout. It is sport-aware (football vs basketball market headings and quote counts), allows DRAW in quote parsing, verifies Stake on the final dry-run page, and optionally accepts a visible Time line without requiring it for fixture identity. It uses only OCR frames and the generic visual operations.
- `SiteAdapters` is the composition/validation registry. Add another implementation there; the coordinator, OCR, gestures, workflow, ledger and evidence machinery need no site-specific edits.
- The coordinator continues to own authentication, one-active-instruction admission, permanent instruction-ID tombstones, acknowledgements, result polling and restart reconciliation.

The existing `OPEN_AND_TYPE` protocol remains supported. `TextEntryFlow` is reused as a step inside the outer visual session, retaining exact input-connection readback and screenshot OCR. There is no AccessibilityNodeInfo traversal, DOM lookup, injected JavaScript, coordinate table or simulator data fetch in the adapter path. The adapter never reads the HTML or random generator state.

## Instruction

Save this as a JSON file and use the existing paired Windows client:

```json
{
  "instruction_id": "local-workflow-001",
  "action": "ADAPTER_WORKFLOW",
  "adapter": "local_simulator",
  "scenario": "normal",
  "query": "football",
  "market": "SPREAD",
  "side": "AWAY",
  "sport": "football",
  "minimum_price": "1.01",
  "stake": "10.00",
  "timeout_ms": 60000
}
```

```powershell
python tools/coordinator_client.py send instruction.json
python tools/coordinator_client.py result local-workflow-001
```

All eleven ADAPTER_WORKFLOW fields are required; duplicate/extra/mistyped JSON fields are rejected. Existing ID/text bounds apply. Deadline is an integer 100–60000 ms and covers the entire workflow, not each step separately.

| Field | Rules |
| --- | --- |
| `sport` | `football` or `basketball` |
| `minimum_price` | string matching `[0-9]+\.[0-9]{2}` |
| `stake` | same pattern; simulated dry-run only |
| `market` | `MONEYLINE`, `SPREAD`, or `TOTAL` |
| `side` | MONEYLINE: `HOME`\|`AWAY`\|`DRAW`; SPREAD: `HOME`\|`AWAY`; TOTAL: `OVER`\|`UNDER` |

An unknown adapter/scenario is rejected before admission.

### Sports, catalogs and markets

URL params on the simulator: `scenario`, `request`, `sport`, `stake` (default `10.00`).

- **Football** (`query`/`sport` = `football`): three fixtures with similarly named Town/Youth teams, competition names, and visible kickoff `Time` lines. Market headings: `1X2` (HOME/DRAW/AWAY, line NONE), `Handicap` (SPREAD ±1.5), `Total points` (TOTAL 2.5) → **7 quotes**.
- **Basketball** (`query`/`sport` = `basketball`): three basketball fixtures with tip-off `Time` lines. Market headings: `Moneyline` (HOME/AWAY), `Spread` (±5.5), `Totals` (220.5) → **6 quotes**.

Canonical enums remain MONEYLINE/SPREAD/TOTAL. DRAW is allowed only for MONEYLINE (football 1X2). Codes and teams regenerate per page load. Discovery chooses the first complete visible fixture with a unique home/away/competition identity. Time is parsed when present but is not required for identity; Code/Home/Away/League remain required. The adapter captures again before tapping and requires the same code, exact teams and competition.

Visible quotes are read and stored (7 football / 6 basketball). The adapter selects the requested market/side, reads the line and price from fresh frames, checks availability and the exact tuple immediately before tapping, then independently checks the final fixture/market/side/line/price, Stake and REVIEW OK state. A changed quote is not silently accepted or retried.

## Outcomes and evidence

The result keeps `instruction_id`, PASS/FAIL `status`, `stage`, `detail`, `duration_ms`, `execution_count` and `run_id`. It adds `fixture_name`, `home`, `away`, `competition`, `selection`, `final_state` and `verification_detail` when observed. `selection` includes exact market, side, line, price, availability and visual bounds. `final_state` includes stake plus the verified market/side/line/price/state.

Failure stages include NO_FIXTURE_FOUND, AMBIGUOUS_FIXTURE, TARGET_NOT_FOUND, CLICK_FAILED, WRONG_EVENT, EVENT_NOT_VERIFIED, PRICE_CHANGED, LINE_CHANGED, SELECTION_CHANGED, SUSPENDED, UNAVAILABLE, **BELOW_MINIMUM**, TIMEOUT and INTERNAL_ERROR, plus the existing input/admission outcomes. Only a fully verified final dry-run state returns PASS.

`GET /instructions/ID/evidence` returns the durable workflow record with every phase/time, screenshot reference, gesture intent/bounds, discovered fixtures/markets, chosen values and the nested exact query-entry evidence. `GET /instructions/ID/artifacts/FILENAME` returns recorded PNG/OCR artifacts. Five workflow gestures plus one separately recorded query-focus gesture form a successful run. Screenshots of the final result are actual phone captures.

A restart never resumes uncertain effects: pending workflows become INTERNAL_ERROR, retain their last phase and effect count, and the same instruction ID returns DUPLICATE. Already-persisted terminal evidence is reconciled if the process died between evidence and coordinator result commits. A fresh ID starts a fresh workflow. Completion is at-most-once, not guaranteed after interruption. Uninstalling or clearing app data removes the deduplication ledger.

## Simulator cases and acceptance

Scenarios: normal, empty, ambiguous (duplicate exact team/competition identity), wrong_event, click_ignored, changing (price changes when review opens), suspended, unavailable, wrong_line (line movement), wrong_side, and **stale** (after fixtures render, the list clears within ~500ms so selection preflight sees EMPTY → NO_FIXTURE_FOUND). Fixtures, prices and failure modes live only in the local simulator and its adapter registry; the generic state machine does not inspect scenario names.

```powershell
# After one-time build/install/setup, remove forwarding and stop ADB.
python tools/test_site_adapter.py --output evidence/fixture-m5
# Focused case for diagnosis:
python tools/test_site_adapter.py --case fb_1x2_draw --output .local/adapter-check
python tools/test_site_adapter.py --case bb_spread --output .local/adapter-check
python tools/test_site_adapter.py --case below_min --output .local/adapter-check
python tools/test_site_adapter.py --case stale --output .local/adapter-check
```

A failed suite can resume its passed cases with `--resume` only when the saved build hash matches the unchanged APK.

The suite uses only authenticated LAN HTTP and asserts the ADB server is absent before/after. It verifies football and basketball catalogs, DRAW on 1X2, stake dry-run readback, below-minimum gating, stale empty preflight, three market types, positive/negative spread lines, both totals sides, multiple/ambiguous names, empty search, rejection of visually clipped query text, exact duplicates, wrong events, ignored taps, price/line/side changes, suspended/unavailable selections, hard timeout, process kill after the final selection tap, fresh work after restart, and a lost-response retry using the same ID. Restart uses the existing authenticated debug-only process-kill endpoint.

PASS assertions expect 3 fixtures, 7 markets for football / 6 for basketball, and `final_state.stake` matching the instruction stake.

Scope: currently visible simulator layouts, English OCR, one outlined search field and the existing Android API 33+ text mechanism on the physical Samsung. This does not claim scrolling coverage, arbitrary-site compatibility, or OCR reliability for unseen layouts. Unreadable/ambiguous content fails rather than guessing. Pairing/trusted-LAN requirements remain in COORDINATOR.md.
