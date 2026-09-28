# Desktop worker: supervised one-shot final action (28 Sep 2026)

- STEP 1 (`../desktop-worker-placebet-ready/runs/recheck3-*`, 18:24-18:26 BST): Turkiye v Italy 1X2 Draw @3.50 and
  Sweden v Poland AH home 0.0 @1.475 both reached `COMPLETE_EXECUTION_READY` (Place Bet not clicked).
  `recheck2-*` (18:11) stopped at `SESSION_EXPIRED` (Reality Check open, not answered).
- STEP 2 (`d_9b2dbdeb76e94924a752/`): `py -3.11 -m desktop_worker.final_action evidence/desktop-worker-placebet-ready/instructions/tur_1x2_draw.json --confirm-one-live-bet`
  - `s001`-`s013`: the worker's hold (slip cleared, selection added, stake 0.10, verified).
  - `s014_preclick_prompt_scan`: no stop prompt. `s015_preclick_verify`: the fresh pre-click frame (one selection, Draw
    3.50, Full Time Result, Turkiye v Italy, stake 0.10, To Return 0.35 on the Place Bet button, Jackpot 365 OFF).
  - One click at 18:31:58 BST (805,741). `s016`/`s017_receipt_*`: 'Bet Placed', Bet Ref BT7071586031I, Draw 3.50,
    Stake GBP 0.10, To Return GBP 0.35.
  - `final_action.json`: the pre-click checks, click, receipt OCR text, and the passive placebet response (redacted:
    sr 0, br BT7071586031I, od 5/2, ts 0.1, re 0.35). Outcome PLACED.
