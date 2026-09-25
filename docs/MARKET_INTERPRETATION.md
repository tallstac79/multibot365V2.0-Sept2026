# Market interpretation and alert normalisation

**Current strategy: sharp-money-1, normalized schema 6.** The authoritative strategy,
30 real examples and adversarial cases are in [SHARP_MONEY_STRATEGY_SPEC.md](SHARP_MONEY_STRATEGY_SPEC.md).
This supersedes the favourable-side inference introduced around 80d8dda/a29f413/be13bca.

`core/market_interpretation.py` is pure: it parses evidence and assesses offers, without
contacting a bookmaker, calculating synthetic EV, or dispatching instructions.

## Candidate selection

Only verified basketball two-sided mappings are actionable: spread lines are HOME
handicaps (AWAY is the inverse); total prices are OVER then UNDER. Both opening and
current Pinnacle quotes must share this perspective. Let delta = current - opening.

| Market | Negative delta | Positive delta |
|---|---|---|
| Spread, HOME perspective | HOME | AWAY |
| Total | UNDER | OVER |

Zero movement, missing opening, unverified mapping, moneyline and price-only signals
cannot supply an executable target. Price highlighting is evidence about the feed's
price/EV signal, not candidate selection. Bet365 line advantage never selects a side.
Pinnacle crossing zero is supported. Opposite signs between the current Pinnacle and
Bet365 HOME lines are quarantined until the bookmaker perspective is verified; there
is no arbitrary ten-point exception.

## Same-side offer comparison

After selecting the candidate, compare its signed Bet365 handicap with its signed
Pinnacle handicap. A larger signed spread is better. A lower total is better for OVER;
a higher total is better for UNDER. An unfavourable offer never causes a side switch.

At equal lines, same-side better odds and supplied EV above 100 establish the existing
`CLEAR_VALUE_SIGNAL` criterion. EV must belong to the candidate: an opposing highlight
retains `SUPPLIED_FOR_OTHER_SIDE`, not an EV reassigned to the candidate. Unequal-line
prices are `NOT_COMPARABLE`; a better line is `FAVOURABLE_LINE_SIGNAL`, with EV unavailable.
Rules still apply policy thresholds. Neither label proves positive expected profit.

## Preserved evidence and states

Schema 6 retains current/opening/previous quotes, alternative-line flags, per-side
comparisons, raw source identity and time. `sharp_signal` contains the source, delta,
magnitude, candidate, highlight agreement and recent-line reversal. `target_price_source`
is `pinnacle_opening_to_current`. `highlighted_side` and `feed_displayed_ev_percent` preserve
the original feed evidence separately from candidate-bound `displayed_ev_percent`.
`implied_target` remains null for compatibility with historical records.

`PARSED` means a verified candidate and usable offer were extracted, even when the offer
is unfavourable. `AMBIGUOUS`/`PARSED_PARTIAL` cannot queue. Malformed contradictory fields
are `INVALID`. Rules persist strategy NO BET as REJECT with an explicit quality reason.
Historical records keep their original interpretation version; they are not silently
rewritten. The rules reject old normalized targets at the `sharp_target` gate.

See [RULES_ENGINE.md](RULES_ENGINE.md) for eligibility and missing-policy behaviour.
