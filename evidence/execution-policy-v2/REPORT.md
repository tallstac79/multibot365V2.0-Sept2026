# Scaled execution tolerance comparison

Frozen at 2026-09-26T06:55:04.513109+00:00. Each row compares the original alert with the latest available stored quote; selection-stage observations are not pre-action guarantees.

| Fixture | Side | Alert → observed line | Alert → observed odds | Stage | Result |
|---|---|---|---|---|---|
| Berck Fliers Range vs Pays Salonais Basket 13 | SPREAD AWAY | +3.5 → +3.5 | 1.83 → 1.83 | selection | Retain |
| Seoul SK Knights vs Wonju Dongbu Promy | TOTALS OVER | 165.5 → 165.5 | 1.83 → 1.83 | selection | Retain at 0, 0.5 or 1 point (scenarios only) |
| Explosivas de Moca vs Leonas De Ponce | TOTALS UNDER | 145.5 → 145.5 | 1.83 → 1.83 | selection | Retain at 0, 0.5 or 1 point (scenarios only) |
| Besancon vs Val De Seine | SPREAD AWAY | +3.5 → +3.5 | 1.83 → 1.83 | selection | Retain |
| Besancon vs Val De Seine | SPREAD AWAY | +1.5 → +1.5 | 1.83 → 1.83 | pretap | Retain |
| Boras Basket vs Nassjo Basket | SPREAD AWAY | +13.5 → +13.5 | 2.15 → 1.83 | selection | Reject: net payout loss 27.83% |

Basketball spreads: **3 retained / 1 rejected**. Boras/Nassjo needs at least 2.04 under the 10% net-payout rule; the observed 1.83 rejects.

Totals: **2 retained / 0 rejected** for each candidate allowance of 0, 0.5 and 1 point, with 10% net-payout tolerance. Both observed totals were unchanged. These are scenario results; configured totals line tolerance remains null and fails closed.

**Proposal for operator choice: 0.5 point absolute deterioration for basketball totals.** OVER can rise by 0.5; UNDER can fall by 0.5. Improvements always pass. The stored alerts contain whole- and half-point values; that supports a half-point unit, but does not prove every live ladder advances in half-point steps or that this limit is optimal.

The snapshot has 314 totals feed rows, including 182 with a resolved target line, spanning ['139.5', '194.5']. Fraction counts: {'0.5': 141, '0': 41}. Rows include repeated alerts/edits and are not independent opportunities.

Six selected historical attempts, not independent opportunities or placements. Five selection-stage quotes and one pre-tap quote. No observed line deterioration, so retention cannot distinguish candidate totals caps or quantify full-feed effect.

Compared with the earlier zero-deterioration scenario, this small set gains no retained observations: 3/4 spreads and 2/2 totals under each candidate totals policy. This is a lack of informative moving-quote data, not evidence that zero tolerance is preferable.

Synthetic spread examples (separate from historical counts): -25.5→-26.5, -15.5→-16.5 and -10.5→-11.5 pass; -5.5→-6.5 and -1.5→-2.5 fail. The same signed arithmetic applies to either selected team.
