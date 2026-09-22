# MultiBot365 live Bet365 adapter ? PASS

Verified **2026-09-22 ~20:42 Europe/London** on Samsung SM-A136B `R5CT61TE14Z`.

- App: **0.6.14-live (26)**
- Adapter: `live_bet365` / scenario `live`
- Evidence: `evidence/live-bet365/` (`summary.json` status PASS; screenshots s001?s013)
- Fixture: **Arsenal v Leeds** (query Arsenal; live search ? not hardcoded)
- Market: **MONEYLINE** (Full Time Result)
- Side: **HOME**
- Line: **NONE**
- Live price observed (structured): **8.00** (decimal; UK board may show fractional equivalent)
- Final state: `NOSUBMIT`, `wager_submitted: false`, Place Bet chrome may be visible ? **not tapped**
- Duration: ~53s over LAN HTTP with PC ADB server down

## Flow proven

1. Open live Bet365 in Chrome (`#/HO/` ? event `#/AC/B1`)
2. Search ? Recent/typed query Arsenal
3. Discover + select live fixture Arsenal v Leeds
4. Verify event (both teams)
5. Read Full Time Result quotes from live OCR
6. Select HOME quote visually
7. Verify post-tap interface; **STOP before Place Bet / wager submit**

## Notes

- Continues from M5 commit `68dea3e` (simulator 25/25). Live adapter is additive (`Bet365LiveAdapter`, registry, harness).
- Prior blocker was Bet365 login wall while logged out; cleared after David logged in on phone Chrome.
- No LocalSimulator substitution. No unit-test-only PASS.

## Remaining

- Optional follow-up: tighten FTR column bounds when odds OCR as decimals on one row (HOME price/bounds attribution).
- No David blocker for this PASS.
