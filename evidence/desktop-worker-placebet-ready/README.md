# Desktop worker: supervised Place Bet-ready with a visual slip flow (28 Sep 2026, 14:28-15:10 BST)

Dedicated signed-in Chrome (CDP 127.0.0.1:9333) on DESKTOP-IVUNJ9J, stake 0.10, pre-match UEFA Nations League events
(kick-off 19:45 BST). Every run is the worker's own `DesktopBet365.hold` (via `scripts/run_ready.py`), and every run
stops before Place Bet. **Place Bet was never clicked, and no wager was submitted in any run.**

## Layout

- `instructions/`: the ADAPTER_WORKFLOW payloads (phone schema), one per event/market.
- `runs/<label>-NN-<instruction>/`: one directory per run, copied from `.local/desktop-evidence/<run_id>/`.
  - `result.json`: the worker's result record (existing schema: `ready_state`, `final_state`, `complete_execution_ready`, `selection`, stages). It also holds `addbet` (Bet365's answer to the click, parsed and redacted), `betslip_api` (every BetsWebAPI response from the click to the end, redacted), `betslip` (the last slip state read from the screen), `stake_entry`, `betslip_clear` and `readback_rereads`.
  - `sNNN_<step>.png` + `.txt`: event / market pages (before the click; the existing text-layout read).
  - `sNNN_slip_*.png` + `.ocr.txt` + `.slip.json`: slip steps. The screenshot, the Tesseract words with boxes and confidence, and the slip state read from them. There is no DOM read of the slip.
- `<label>_summary.json`: a per-run table with the pass rate (`scripts/summarise.py LABEL`).
- `scripts/check_redaction.py`: checks that no addbet token field (bg/pc/cc/sa), cookie or x-net-sync-term value is in any run file.

## Batches

| label | code | runs | Place Bet-ready | notes |
| --- | --- | --- | --- | --- |
| `cal1`, `cal2` | first visual build | 3 | 3/3 | cal2 also exercised removing a leftover selection with the slip's X and reloading |
| `proof` | first visual build | 12 | 6/12 | 3x 'Total Goals' slip label not in the vocabulary (Goals Over/Under group); 1x footer missed by the whole-panel OCR pass; 2x Turkiye 1X2 not found by the existing discovery (name folding). All failed closed. |
| `final` | final code | 15 | **14/15** | 1x `LINE_CHANGED` before any click: an existing discovery layout race on the expanded Alternative Asian Handicap |

Across all 30 runs there were 26 selection clicks, and 26/26 addbets came back `cs:1 sr:0` with exactly one bet. There
were 0 `{"cs":2,"sr":-1}` refusals and 0 slip error overlays. Stake typing and the Place Bet checks produced no further
BetsWebAPI requests and no slip notices.

The final batch covered 4 events (Northern Ireland v Hungary, Belgium v France, Sweden v Poland, Turkiye v Italy) and
these markets: Asian Handicap home/away (main and alternative group), Goal Line over, Goals Over/Under over/under, and
Full Time Result home/away.

## Reality Check

When work started, Bet365's 'Reality Check' dialog was open ("Your session has now exceeded 02:54:27", 60-minute
reminder). Before any run, the supervising agent clicked 'Remain Logged In' once (a single mouse click on the button, outside the worker code). The worker itself
never answers it: it fails `SESSION_EXPIRED` and asks for the operator.
