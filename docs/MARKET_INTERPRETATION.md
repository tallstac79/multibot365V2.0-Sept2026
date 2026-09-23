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
side (side-labelled layout). Without a highlight, **no side is chosen**. Both sides are
still reported.

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
It means OddsNotifier's standard equal-line EV is unavailable. The alert becomes
`PARSED_PARTIAL`, and each side still carries a directional result. In the live corpus,
90 such alerts that were previously INVALID are now fully interpreted.

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
| CLEAR_VALUE_SIGNAL | Verified ordering, the highlighted target, equal lines, Bet365 price above Pinnacle, and OddsNotifier-supplied equal-line EV above 100 % |
| POTENTIAL_VALUE | A favourable line with prices not comparable, or an equal line with a better price but no supplied EV for this side |
| NO_ADVANTAGE | Equal line and equal price |
| UNFAVOURABLE | An unfavourable line, or an equal line with a worse price |
| INSUFFICIENT_INFORMATION | Unverified ordering, no Bet365 offer, or unknown qualities |

A favourable line at a poor price is at most POTENTIAL_VALUE. The rules engine (`rules-2`)
now also requires `bet_quality == CLEAR_VALUE_SIGNAL` before anything is queued.

## Intake statuses and fail-closed cases

| Status | Meaning |
|---|---|
| PARSED | Complete and comparable: highlighted target, Bet365 present, equal lines, EV supplied. Only these reach the rules engine. |
| PARSED_PARTIAL | Valid and interpreted, but no highlighted target, no Bet365 offer, or no EV (unequal lines or not supplied). It is stored, and no instruction is created. |
| AMBIGUOUS | Over/Under or HOME/AWAY ordering is unverified; the selected side is not labelled; more than one price is highlighted; a price is highlighted outside the Bet365 row; the EV field is unrecognised; no market label or fixture link; a spread line equals Pinnacle as displayed while OddsNotifier reports "not equal lines" (sign reference unsafe) |
| INVALID | Genuinely malformed or contradictory data only: wrong price count, price ≤ 1, a negative total, a Bet365 market that conflicts with the alert market, a fixture URL market that conflicts with the label, a numeric EV with unequal lines, "not equal lines" with equal totals, an opening side that conflicts with the market side, a side impossible for the market, an arrow that conflicts with the supplied percentage, identical teams, an invalid date, or unexpected rows |

The intake store (`.local/pipeline.sqlite3`) is schema v2. It adds `PARSED_PARTIAL` to the
status constraint through a transactional table rebuild when a v1 store is opened. The
rebuild is verified on a copy of the live database, and all rows and foreign keys are
preserved.
