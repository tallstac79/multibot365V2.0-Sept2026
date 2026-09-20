# Generic visual adapter workflow

Milestone 4 uses a fully local, fictional fixture simulator. It has no account, stake, transaction, wager or external data endpoint. The simulator is served by the phone at `/neutral/simulator.html`; Windows only sends instructions and reads results/evidence.

## Contract and boundaries

`SiteAdapter` defines asynchronous `open_home`, `open_search`, `enter_query(query)`, `discover_fixture`, `select_fixture(fixture)`, `verify_event(fixture)`, `discover_markets`, `read_selection`, `read_line`, `read_price`, `open_selection`, and `verify_final_state` methods. Fixture and selection values carry exact observed text and screenshot-derived bounds.

- `AdapterWorkflow` sequences those methods and handles outcomes. It contains no page labels, layout rules or fixture names.
- `VisualSession` performs Chrome launches, screenshots, gesture dispatch, verified text-entry steps, deadlines and atomic evidence checkpoints. `VisualScreen` groups OCR words by their measured geometry. Table capture refines separately detected cells with single-line OCR; digit-bearing cells use a numeric character alphabet without expected-value hints. Final line/price fields also receive independent cropped-region OCR. Navigation keeps the existing full-page OCR mode.
- `LocalSimulatorAdapter` owns every simulator label, page precondition, parsing rule and expected layout. It uses only OCR frames and the generic visual operations.
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
  "timeout_ms": 60000
}
```

```powershell
python tools/coordinator_client.py send instruction.json
python tools/coordinator_client.py result local-workflow-001
```

All eight fields are required; duplicate/extra/mistyped JSON fields are rejected. Existing ID/text bounds apply. Deadline is an integer 100–60000 ms and covers the entire workflow, not each step separately. Market is MONEYLINE, SPREAD or TOTAL. Sides are HOME/AWAY for MONEYLINE/SPREAD and OVER/UNDER for TOTAL. An unknown adapter/configuration is rejected before admission.

The simulator generates fictional team combinations, event codes and prices per page load. `football` searches all its football fixtures; a name or league query filters that local catalog. The adapter maps the visible labels Match winner, Handicap and Total points to the canonical market types. Each normal catalog has three fixtures including similarly named Town/Youth teams. Discovery chooses the first complete visible fixture with a unique home/away/competition identity. The adapter captures again before tapping and requires the same code, exact teams and competition. Event verification independently checks all those fields plus event/market navigation markers.

All six visible quotes are read and stored. The adapter selects the requested market/side, reads the line and price from fresh frames, checks availability and the exact tuple immediately before tapping, then independently checks the final fixture/market/side/line/price and REVIEWONLY state. A changed quote is not silently accepted or retried.

## Outcomes and evidence

The result keeps `instruction_id`, PASS/FAIL `status`, `stage`, `detail`, `duration_ms`, `execution_count` and `run_id`. It adds `fixture_name`, `home`, `away`, `competition`, `selection`, `final_state` and `verification_detail` when observed. `selection` includes exact market, side, line, price, availability and visual bounds.

Failure stages include NO_FIXTURE_FOUND, AMBIGUOUS_FIXTURE, TARGET_NOT_FOUND, CLICK_FAILED, WRONG_EVENT, EVENT_NOT_VERIFIED, PRICE_CHANGED, LINE_CHANGED, SELECTION_CHANGED, SUSPENDED, UNAVAILABLE, TIMEOUT and INTERNAL_ERROR, plus the existing input/admission outcomes. Only a fully verified final dry-run state returns PASS.

`GET /instructions/ID/evidence` returns the durable workflow record with every phase/time, screenshot reference, gesture intent/bounds, discovered fixtures/markets, chosen values and the nested exact query-entry evidence. `GET /instructions/ID/artifacts/FILENAME` returns recorded PNG/OCR artifacts. Five workflow gestures plus one separately recorded query-focus gesture form a successful run. Screenshots of the final result are actual phone captures.

A restart never resumes uncertain effects: pending workflows become INTERNAL_ERROR, retain their last phase and effect count, and the same instruction ID returns DUPLICATE. Already-persisted terminal evidence is reconciled if the process died between evidence and coordinator result commits. A fresh ID starts a fresh workflow. Completion is at-most-once, not guaranteed after interruption. Uninstalling or clearing app data removes the deduplication ledger.

## Simulator cases and acceptance

Scenarios: normal, empty, ambiguous (duplicate exact team/competition identity), wrong_event, click_ignored, changing (price changes when review opens), suspended, unavailable, wrong_line and wrong_side. Fixtures, prices and failure modes live only in the local simulator and its adapter registry; the generic state machine does not inspect scenario names.

```powershell
# After one-time build/install/setup, remove forwarding and stop ADB.
python tools/test_site_adapter.py --output evidence/fixture
# Focused case for diagnosis:
python tools/test_site_adapter.py --case spread --output .local/adapter-check
```

A failed suite can resume its passed cases with `--resume` only when the saved build hash matches the unchanged APK.

The suite uses only authenticated LAN HTTP and asserts the ADB server is absent before/after. It verifies three market types, positive/negative spread lines, both totals sides, multiple/ambiguous names, empty search, rejection of visually clipped query text, exact duplicates, wrong events, ignored taps, price/line/side changes, suspended/unavailable selections, hard timeout, process kill after the final selection tap, fresh work after restart, and a lost-response retry using the same ID. Restart uses the existing authenticated debug-only process-kill endpoint.

Scope: currently visible simulator layouts, English OCR, one outlined search field and the existing Android API 33+ text mechanism on the physical Samsung. This does not claim scrolling coverage, arbitrary-site compatibility, or OCR reliability for unseen layouts. Unreadable/ambiguous content fails rather than guessing. Pairing/trusted-LAN requirements remain in COORDINATOR.md.
