# Mauritania U23 stake hang — forensic recovery (28 Sep 2026)

Instruction: `on-a63fdd616d188e00afe19d87`. Times BST (UTC+1).

## Conclusion

**Not a stake-pad focus failure, OCR stake misread, double entry, or spinning verification loop.**

The keypad typed `0.10` correctly on the first attempt. Both `stake_typed` frames (and the later `stake_retyped` frame) show:

| Reading | Value |
|---|---|
| Stake box | £0.10 (`stake_digits=010`) |
| To Return | £0.41 (`return_digits=041`) |
| Opened / expected price | 4.50 (from selection @ 17:31:15.57) |
| Implied slip price | **4.10** (= 0.41 / 0.10) |
| Accept Change banner | **Absent** (Place Bet still shown) |

`StakePad.check` against opened 4.50 failed because To Return must equal `stake × price` (0.10 × 4.50 = 0.45). The same frame **passes** against 4.10.

Phone `evidence.json` already recorded this:

```json
"stake_check_typed": {"ok": false, "detail": "To Return reads '£0.41' not 0.10 x 4.50", "stake_digits": "010", "return_digits": "041", "stake": "0.10", "price": "4.50"}
"stake_check_retyped": { ... same ... }
```

Those keys never reached `instructions.result_payload` because `CoordinatorAgent.complete` whitelisted `stake_field_state` / `stake_clear` only — not `stake_check_*`. That is why the speed-gap report could not see the mismatch from the DB alone.

## Timeline (phone clock, ENTER_STAKE)

| elapsed_ms | Event |
|---:|---|
| 5861 | ENTER_STAKE start |
| 7463 | stake_ui captured; field EMPTY; keypad located |
| 7543–8331 | type `0 . 1 0` |
| 9019 / 9818 | two `stake_typed` captures — both fail check (stake OK, return 0.41) |
| 9841–12317 | **10 backspaces** (retype clear) |
| 13430 | stake_cleared EMPTY |
| 13536–14342 | type `0 . 1 0` again |
| 15469 | stake_retyped — same failure |
| 15493–17989 | **10 backspaces** erase before fail |
| 21066 | FINISHED STAKE_REJECTED (~15.2 s in stage) |

Normal same-day stake entry: 3.5–4.2 s. Recoverable waste: ~11–12 s of clear/retype/erase that could not change the outcome.

## Root cause (class)

1. **Silent price move on the slip** (4.50 → 4.10) without Bet365's "Accept Change" UI.
2. **`enterStakeOnPad` treated any failed `StakePad.check` as a typing problem** and always cleared+retyped once, even when stake digits already matched.
3. **Accept Change was only inspected after the retype**, so a silent move could never short-circuit.
4. **Forensics gap**: `stake_check_*` on the phone record were stripped from the device result whitelist.

## Fix (this change)

- `StakePad.stakeDigitsMatch` / `StakePad.silentMovedPrice`: when stake digits match and To Return implies another price, classify as silent move.
- `enterStakeOnPad`: if first typed frame already has matching stake digits (silent move, Accept Change, or return mismatch) → erase and fail immediately (`PRICE_CHANGED` or `STAKE_REJECTED`) — **no retype**.
- `CoordinatorAgent` result whitelist: persist `stake_check_typed`, `stake_check_retyped`, `stake_retyped`, `stake_keypad`, `stake_entered`, `stake_silent_price`.
- Regression: `MauritaniaStake20260928Test` against the stored OCR frames.
- APK version **0.9.43-ops** (versionCode 126). New phone build required beyond 0.9.40. Desktop worker untouched.

## Residual unknowns

- Exact wall-clock moment Bet365 moved 4.50 → 4.10 (no intermediate price observation after 17:31:16.148).
- Whether 4.50 was still available for BetSwifty at the would-be normal tap (~17:31:24).
- Why Bet365 omitted the Accept Change banner for this move (product behaviour; not observable beyond the frames).
