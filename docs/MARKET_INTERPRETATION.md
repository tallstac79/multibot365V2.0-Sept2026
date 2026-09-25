# Market interpretation and alert normalisation

Code: `core/market_interpretation.py` (grammar, comparisons, movement, bet quality) and
`core/alert_classifier.py` (intake status). The layer is pure parsing. It never contacts a
bookmaker or the phone, and never dispatches.

Tests in `tests/test_market_interpretation.py` cover the whole matrix below. The
regression corpus `tests/fixtures/oddsnotifier_feed2_live_corpus.json` holds 140 genuine
Feed 2 alerts captured by the live listener on 2026-09-23.

## Layouts

| Layout | Seen in production as | Sides |
|---|---|---|
| Two-sided | `Totals (L)` or `Spread (L)`, optionally `(P -> L)` and `(alt. line)`; Pinnacle prices; `Opening (L)` (🟢 or 🔵); `Bet365 (Market L)` prices; `EV: N%` or `EV: None (not equal lines)`. Fixture and Bet365 rows may be links or plain text. | Basketball Totals: first = OVER, second = UNDER. Basketball Spread: first = HOME at the displayed line, second = AWAY at the inverse line, in every bookmaker group. Both are user-confirmed. Other sports get no sides. |
| Side-labelled | `Limit: €200 → €400 (just now)`, `Opening: Away 2.030`, `Spread (-1.5): Away 1.724 ↓ [-11.7%]`, `Fair Odds: 1.850`, `Bet365` | Named in the text. The spread line belongs to the named side, per the user's expected reading of HJK Helsinki vs Brann. |

Whitespace-flattened pastes and Telegram's heading bold are normalised first. Only a
bolded **price** keeps its meaning (the highlighted Bet365 target). Moneyline layouts fall
back to the legacy parser and stay AMBIGUOUS, because their ordering is unverified.

## Output (normalised alert, schema 5)

All legacy fields are kept (`target_side`, `target_line`, `alert_price`, `pinnacle`,
`opening`, `comparison.quotes`, `alternate_line`, `quote_mapping`, ...). The new fields
are:

```
market, selection_side, selection_name, selection_line        (null when no side is identified)
reference:   bookmaker, line, odds, fair_odds
comparison:  bet365_present, bet365_line, bet365_odds, equal_line, line_difference (Bet365 - reference, as displayed),
             line_advantage (selected side; + is better), line_quality, price_quality, ev_status, supplied_ev
movement:    opening_line, previous_line, current_line, line_change, line_direction, opening_line_change,
             opening_price, current_price, previous_price_displayed, price_direction,
             price_change_percent (+ price_change_basis), opening_to_current_price_change_percent
market_movement: the same fields at market level (line perspective TOTAL or HOME)
limit:       previous, current, currency, changed_at_text
sides[]:     one entry per identified side, with its own reference, comparison, movement,
             line_quality, price_quality, bet_quality and is_target
line_quality, price_quality, bet_quality, interpretation_status, interpretation_notes
```

Lines and prices are decimal strings with their source precision. Differences are exact
decimals. The selection is the highlighted Bet365 target (two-sided layout) or the named
side (side-labelled layout). Without a highlight, the target is **implied from the lines**
when exactly one side's Bet365 line is at least 1.0 point better than Pinnacle's current
line and the other side's is worse by the same amount (`target_price_source =
implied_favourable_line`, see "Implied target" below); otherwise no side is chosen. Both
sides are still reported.

## Totals direction

| Selected side | Better line | Example (Pinnacle → Bet365) |
|---|---|---|
| OVER | Lower | 168.5 → 165.5: advantage +3.0, FAVOURABLE. 168.5 → 171.5: UNFAVOURABLE. |
| UNDER | Higher | 168.5 → 171.5: advantage +3.0, FAVOURABLE. 168.5 → 165.5: UNFAVOURABLE. |

A favourable line is not a claim of positive expected value.

## Spread normalisation

Every spread is expressed as the **selected team's signed handicap** before any
comparison. The displayed two-sided line is HOME's; AWAY is its inverse (Spread (12) →
HOME +12, AWAY -12). For the selected team, a **higher** signed handicap is better:
-8.5 → -6.5 is +2 (favourable), -8.5 → -10.5 is -2, +6.5 → +8.5 is +2, and +6.5 → +4.5 is
-2. A line on one team is never compared with the opponent's line.

## Moneyline / 1X2

There is no line component, so line quality is EQUAL (`line_applicable: false`). Prices
are compared only for the exact same outcome (HOME, DRAW, AWAY): a higher decimal price is
FAVOURABLE.

## Equal-line comparison

When both lines are equal for the same side, `price_quality` compares Bet365 with
Pinnacle's current price. OddsNotifier's EV is kept as supplied (`ev_status`
`SUPPLIED_EQUAL_LINE`) and never recalculated. EV belongs to the highlighted target; other
sides report `SUPPLIED_FOR_OTHER_SIDE`. Fair odds are recorded where supplied.

## Unequal-line comparison

Prices at different lines are **not** comparable: `price_quality` = `NOT_COMPARABLE`.
Line quality is evaluated directionally per side, and `ev_status` =
`NOT_AVAILABLE_UNEQUAL_LINES`. No synthetic EV is calculated.

`EV: None (not equal lines)` therefore does **not** mean no value and is **not** INVALID.
It means OddsNotifier's standard equal-line EV is unavailable, and each side still carries a
directional result. With a highlighted verified target, or an implied one, the alert is
`PARSED` and may be a `FAVOURABLE_LINE_SIGNAL` (see below). Otherwise it is `PARSED_PARTIAL`.

## Implied target (unequal lines, nothing highlighted)

OddsNotifier never highlights a Bet365 price on an unequal-line alert (0 of 625 stored ones),
so from 2026-09-25 the target is implied from the lines alone, deterministically:
Pinnacle's current line is the sharp reference; if Bet365 still offers a line that is at least
1.0 point better for exactly one side (and worse by the same amount for the other), that side
is the bet. Totals: a lower Bet365 total favours OVER, a higher one favours UNDER. Spreads:
the higher signed handicap from each team's own perspective favours that team.

* Pinnacle OVER/UNDER 168.5, Bet365 165.5 → OVER 165.5, +3.0 (`FAVOURABLE_LINE_SIGNAL`)
* Pinnacle 159.5, Bet365 165.5 → UNDER 165.5, +6.0
* Pinnacle home −5.5, Bet365 home −1.5 → HOME −1.5, +4.0 (the away side is −4.0: UNFAVOURABLE)
* Pinnacle home −2.5, Bet365 home −5.5 → AWAY +5.5, +3.0

A spread on which Pinnacle and Bet365 favour *different* teams by 10 or more points is the Bet365
line quoted from the other perspective, not a lag (Japan −23 vs "17.5"): the sign reference is
ambiguous and the alert is `AMBIGUOUS`. Smaller favourite flips are genuine moves and stay eligible.

Not implied (stays `PARSED_PARTIAL` / `AMBIGUOUS`): advantage below 1.0, equal lines, both
sides favourable or neither, a missing price, an unverified quote mapping (football two-sided
layouts), the spread whose sign reference cannot be normalised, or any highlight at all (a
highlighted side is always the target, even a worse one, which is then UNFAVOURABLE).
No EV is calculated; prices are never compared across lines. `implied_target` records the
advantage and Pinnacle's own line movement (`pinnacle_movement_agrees`) as evidence only, and
the instruction carries `target_source`. The rules engine still applies `min_line_advantage`
and the price bounds.

## Movement

Line movement and price movement are separate facts, and their cause is never inferred.
`Totals (165.5 -> 166.5)` gives previous 165.5, current 166.5, `line_change` +1.0,
`line_direction` UP. This is consistent with the market moving to a higher expected
total; nothing is said about who bet what. Opening-to-current line change is reported
separately.

Price direction comes from the explicit arrow: ⬇ or ↓ = SHORTENED, ⬆ or ↑ = DRIFTED. A
supplied percentage (for example `[-11.7%]`) is kept as `price_change_percent` with basis
`SUPPLIED_BY_ODDSNOTIFIER_BASE_UNSPECIFIED`, because it does not equal opening → current
(2.030 → 1.724 is -15.07 %, reported as `opening_to_current_price_change_percent`).
Parenthesised Pinnacle prices are kept as `previous_price_displayed`, but their meaning is
unconfirmed: arrows and parentheses disagree in some live messages.

## Line quality, price quality, bet quality

`BET_QUALITY` is deliberately not `LINE_QUALITY`:

| bet_quality | When |
|---|---|
| CLEAR_VALUE_SIGNAL | Equal-line price/EV edge: verified ordering, the highlighted target, equal lines, Bet365 price above Pinnacle, and OddsNotifier-supplied equal-line EV above 100 % |
| FAVOURABLE_LINE_SIGNAL | Verified ordering, the target (highlighted, or implied from the lines), a quantified positive Bet365 line advantage for that exact side, and both prices present. The prices are not comparable across lines, so no EV is implied or calculated. |
| POTENTIAL_VALUE | Non-actionable: a favourable line on a side that is not the target (advantage below 1.0, or the other side is the target), a missing price or an unquantifiable advantage, or an equal line with a better price but no supplied EV for this side |
| NO_ADVANTAGE | Equal line and equal price |
| UNFAVOURABLE | An unfavourable line, or an equal line with a worse price |
| INSUFFICIENT_INFORMATION | Unverified ordering, no Bet365 offer, or unknown qualities |

The rules engine (`rules-3`) queues only `CLEAR_VALUE_SIGNAL` or `FAVOURABLE_LINE_SIGNAL`, and
every configured rule still applies to both. For `FAVOURABLE_LINE_SIGNAL`:

* The line advantage must reach **Min favourable line advantage** (global, default 1.0 point,
  configurable 0.5 to 50). This is how "materially favourable" is defined. The default is 1.0
  because compared lines in this feed differ in minimum 1-point steps, even when the lines
  themselves are half-points.
* The Bet365 price must pass the market's min/max alert-price rules. Slippage sets the
  minimum price as usual.
* `minimum_ev` is recorded as *not applicable*, because OddsNotifier EV is unavailable for
  unequal lines and no synthetic EV is calculated.

The instruction carries `signal_reason`, `line_advantage` and `ev_status`, so downstream
components can tell the two signals apart.

Examples: Pinnacle OVER 168.5 vs Bet365 OVER 165.5 with OVER highlighted gives +3.0,
FAVOURABLE_LINE_SIGNAL. Pinnacle UNDER 168.5 vs Bet365 UNDER 171.5 with UNDER highlighted
gives +3.0, FAVOURABLE_LINE_SIGNAL. A highlighted side whose line is *worse* is
UNFAVOURABLE and is rejected. Kipina (166.5 vs 168.5, nothing highlighted) now implies
UNDER 168.5, +2.0, FAVOURABLE_LINE_SIGNAL; with a Bet365 line only 0.5 better it would stay
PARSED_PARTIAL with UNDER as POTENTIAL_VALUE.

## Intake statuses and fail-closed cases

| Status | Meaning |
|---|---|
| PARSED | Highlighted verified target with Bet365 present, and either equal lines with supplied EV or unequal lines evaluated directionally. Only these reach the rules engine. |
| PARSED_PARTIAL | Valid and interpreted, but no highlighted target, no Bet365 offer, or EV not supplied. It is stored, and no instruction is created. |
| AMBIGUOUS | Over/Under or HOME/AWAY ordering is unverified; the selected side is not labelled; more than one price is highlighted; a price is highlighted outside the Bet365 row; the EV field is unrecognised; no market label or fixture link; a spread line equals Pinnacle as displayed while OddsNotifier reports "not equal lines" (sign reference unsafe) |
| INVALID | Genuinely malformed or contradictory data only: wrong price count, price ≤ 1, a negative total, a Bet365 market that conflicts with the alert market, a fixture URL market that conflicts with the label, a numeric EV with unequal lines, "not equal lines" with equal totals, an opening side that conflicts with the market side, a side impossible for the market, an arrow that conflicts with the supplied percentage, identical teams, an invalid date, or unexpected rows |

The intake store (`.local/pipeline.sqlite3`) is schema v2. It adds `PARSED_PARTIAL` to the
status constraint through a transactional table rebuild when a v1 store is opened. The
rebuild is verified on a copy of the live database, and all rows and foreign keys are
preserved.
