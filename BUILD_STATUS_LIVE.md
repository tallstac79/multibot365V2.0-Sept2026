# MultiBot365 live Bet365 adapter ? PASS (1X2 identity fixed)

Verified **2026-09-22 ~20:52 Europe/London** on Samsung SM-A136B `R5CT61TE14Z`.

- App: **0.6.15-live (27)**
- Commit parent of prior false PASS: `565b132` (HOME wrongly @ 8.00). This fix supersedes that acceptance.
- Evidence: `evidence/live-bet365/` (`summary.json` PASS + `moneyline_map`)

## 1X2 map (Arsenal v Leeds)

| Role | selection_name | price |
| --- | --- | --- |
| HOME | Arsenal | 1.33 |
| DRAW | Draw | 5.00 |
| AWAY | Leeds | 8.00 |

Selected for workflow: HOME / Arsenal / 1.33. Final: NOSUBMIT, wager_submitted false (Place Bet not tapped).

## Fix

- Bind Full Time Result columns by X proximity (label ? price box), not leftover single-token OCR order.
- Emit `fixture_home`, `fixture_away`, `selection_role`, `selection_name`, `price`.
- Fail if HOME/AWAY names disagree with fixture teams, DRAW is a team name, or columns/prices ambiguous.

No LocalSimulator substitute. No David blocker remaining for this fix.
