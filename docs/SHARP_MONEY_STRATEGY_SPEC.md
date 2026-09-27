# Sharp-money strategy specification — forensic revision 1

Written 2026-09-25 **before production strategy changes**. Baseline: e1adaa2.
Execution remains DISARMED. Evidence: `evidence/strategy-audit/baseline.json` and
`strategy-forensics.csv`. This specifies the operator's opening-to-current strategy;
it does not claim to prove who placed bets, that Pinnacle is infallible, or profitability.

## What has been established

Choose the candidate from Pinnacle opening → current, in one fixed team/market
perspective. Only then inspect Bet365's offer for that candidate. Never switch to
the opponent because its handicap or price looks better. Never copy the opponent's EV.

The stored corpus disproves the proposition that every OddsNotifier highlight follows
net opening movement. The original 1,300 nonduplicate intake alerts contain 186 old
targets against the net line move and 105 highlights against it. The provider's drop
signal and this strategy are different. Target direction can be established under a
verified mapping; satisfactory value thresholds cannot be learned from alerts alone.

## Reading the feed: facts and limits

The [provider's setup guide](https://oddsnotifier.io/en/blog/oddsnotifier-setup-guide)
describes a configurable sharp-price-drop feed. It identifies Opening as the sharp
opening quote, bracketed prices as prior prices, spread lines as HOME handicaps,
and total prices as OVER then UNDER. Its displayed 110% EV convention means 10%
above the fair-price break-even ratio. Feed timezones and filters are configurable.
Those descriptions support field interpretation, not this account's settings or
the correctness of every malformed alert.

Local evidence and interpretation:

* `New odds update on Pinnacle` identifies the reference book for these records.
  Other reference books are not silently accepted by this parser.
* Sport, competition, fixture and event time identify the event; Telegram source
  timestamp and received timestamp identify message age. Event time has no offset.
  The operator confirmed fixed UTC/GMT+0 on 26 September 2026; saved UTC is verified.
* The unlabelled price pair under Spread/Totals is current Pinnacle; Opening carries
  its separate line and prices. `(previous -> current)` is an additional, recent
  line transition, not a substitute for Opening. A previous/current reversal does
  not change the net candidate in this strategy; it is recorded for review.
* Down/up arrows describe the local price change. Parentheses and opening prices
  are retained independently. Prices at different handicaps cannot be compared as
  the same bet, so a drifting price after a line move does not prove a reversal.
* Bet365's line/price pair is an offer snapshot, not a target instruction or proof
  that the offer remains available. Its event URL is a navigation hint; identity
  and kickoff must still be checked on the phone.
* Numeric bold is retained as `highlighted_side`. Across the baseline's 1,059 line
  alerts: 364 have equal displayed lines, one highlighted price and numeric EV;
  672 have unequal displayed lines and no highlight/EV; 13 claim unequal lines
  despite equal displayed spreads; 10 carry EV across opposite-signed spreads.
  These last two groups require quarantine, not sign repair.
* Highlighting identifies the side to which the supplied EV belongs. It does not
  override net movement. Missing highlighting on unequal lines is observed format
  behaviour, consistent with absent equal-line EV, not proof of a particular target.
* `EV: None (not equal lines)` means the feed supplied no comparable equal-line EV.
  It is neither zero EV nor permission to calculate a synthetic EV.
* Opening marker colours are stored but have no verified trading meaning here.
  `(alt. line)` is retained per bookmaker group. Main and alternate prices must not
  be mixed. The account's actual alert filters and drop thresholds are unavailable.

## Decision tree

1. Validate source, complete grammar, finite decimal odds > 1, market and fixture.
   Malformed/contradictory data is INVALID. Unverified mappings are AMBIGUOUS.
2. For line markets, require opening and current Pinnacle line on the same market, period and team
   perspective. A perspective change, missing opening, or unresolved alternate-line
   equivalence fails closed. Preserve the raw facts; do not guess a sign.
3. Compute `delta = current_home_line - opening_home_line` for spreads.
   Negative selects HOME; positive selects AWAY. Invert the signed handicap for
   AWAY only after assigning the side. The rule works for favourites, underdogs,
   zero and favourite flips; absolute handicap size does not select a side.
4. For totals compute `delta = current_total - opening_total`. Positive selects OVER;
   negative selects UNDER. The other side is never a substitute.
5. Zero line movement supplies no target under the established line strategy.
   Price-only selection is AMBIGUOUS pending a separately specified threshold,
   margin treatment and movement window. No movement in line or prices is conceptually
   NO BET; the current parser conservatively returns AMBIGUOUS for all zero-line moves.
6. Basketball MONEYLINE is supported by the separate [ML audit and contract](MONEYLINE_AUDIT.md):
   a unique Pinnacle opening-to-current price shortener selects HOME or AWAY;
   only its Bet365 offer and its own EV can qualify it. That audit supersedes
   the initial ML exclusion. Football (Feed 1: 1X2, Asian-handicap Spread, Totals) has
   its own verified profiles and price-based equal-line rule since 27 Sep 2026:
   [FOOTBALL_STRATEGY_SPEC.md](FOOTBALL_STRATEGY_SPEC.md). Nothing in this
   basketball specification changed for it.
7. Evaluate Bet365 for the selected side only. Spread advantage = Bet365 signed
   handicap − current Pinnacle signed handicap. OVER advantage = Pinnacle total
   − Bet365 total. UNDER advantage = Bet365 total − Pinnacle total.
8. Negative advantage means Bet365 moved too far for the established line criterion:
   NO BET, even if the opponent is favourable. A better price might compensate in
   a separately validated probability model; no such model exists here.
9. At equal lines, require better same-side Bet365 odds and numeric supplied EV
   explicitly attached to that same side, above 100 and any configured EV floor.
   An opposing highlight cannot lend its EV to the sharp side. Without sufficient
   same-side evidence: NO BET (or AMBIGUOUS when orientation is unresolved).
10. Positive line advantage is a favourable-line observation, not measured positive
    EV. Apply the existing configured line-advantage floor and price bounds; record
    EV as unavailable. Do not compare decimal prices across different handicaps.
11. OddsNotifier's configured source supplies upstream movement qualification.
    Require genuine nonzero opening-to-current movement; nullable
    `min_sharp_movement` is optional and unset does not reject. An explicitly
    configured floor is additional operator policy for line markets, not ML prices. Preserve existing value
    checks without inventing global price bounds. Alert-to-live odds and line
    deterioration limits are market-specific: approved basketball odds loss is
    10% of net payout and spreads require both 1-point and 10%-of-handicap caps.
    Totals allow 1.0 point deterioration (one practical market step), as recorded in [FEED_TIME_AND_EXECUTION_POLICY.md](FEED_TIME_AND_EXECUTION_POLICY.md).
12. Apply enabled markets, timestamp age, unstarted event with known timezone,
    decimal odds, configured price/EV bounds and stake cap. Recheck at dispatch.
    An old normalized alert lacking this strategy evidence must be rejected, not
    allowed to replay an obsolete target after a restart.

```text
facts = parse_and_validate(raw)
if malformed: INVALID
if mapping/perspective unknown: AMBIGUOUS
if basketball MONEYLINE:
    signal = unique_net_price_shortener(verified_opening_pair, verified_current_pair)
elif supported spread/totals:
    signal = net_pinnacle_line_movement(facts.opening, facts.current)
else: AMBIGUOUS
if missing baseline or no unique signal: AMBIGUOUS
candidate = signal.side                 # never derived from Bet365/highlight
offer = compare_same_side(candidate, facts.pinnacle, facts.bet365)
if spread orientation uncertain: AMBIGUOUS
if offer.worse_line: NO BET
if (equal_line or MONEYLINE) and no EV bound to candidate: NO BET
if unequal_line: EV = unavailable       # never fabricated
if line_market and configured extra movement floor fails: REJECT  # unset adds no floor
if feed_timezone_verified is false: REJECT  # execution timing only
if odds tolerance unset or (line_market and line tolerance unset): REJECT
if any configured threshold fails: REJECT
if timestamps expired or event started: STALE
otherwise: ACCEPT for eligibility only # dispatch and final action remain OFF
```

## Status contract

`PARSED` describes extraction, not approval. `NO BET` is the strategy's lack of a
qualifying same-side opportunity; the existing lifecycle persists that as REJECTED
with a specific reason. `REJECT` also covers known policy failures. `AMBIGUOUS`
means evidence cannot safely establish a required fact. `FAIL CLOSED` means no
instruction is dispatched for INVALID, AMBIGUOUS, missing policy, stale data,
unverified identity/session, or missing final verification. These terms are not
interchangeable with a placed bet, a verified receipt, or a settled result.

## Adversarial direction cases

| HOME opening → current (unless total) | Candidate | Reason / action limit |
|---|---|---|
| -4 → -7 | HOME | More points demanded of HOME |
| -4 → -1 | AWAY | HOME's advantage weakened |
| +4 → +1 | HOME | HOME needs fewer points |
| +4 → +7 | AWAY | HOME needs more points |
| -1 → +2 | AWAY | Crosses zero; sign of delta still positive |
| +1 → -2 | HOME | Crosses zero; sign of delta still negative |
| total 160 → 165 | OVER | Higher total |
| total 165 → 160 | UNDER | Lower total |
| same line, prices move | None | AMBIGUOUS price-only policy |
| line toward HOME, HOME price drifts | HOME candidate | Different-line prices are not a same-bet comparison |
| latest line move opposes opening move | Net candidate | Record both windows; do not substitute |
| bookmaker HOME/AWAY reversed | None executable | Require named-team remapping; otherwise AMBIGUOUS |
| opening/current team perspective changes | None | AMBIGUOUS; signed subtraction is invalid |
| large line gap | Net candidate only | No claim of priced value; review mapping/market freshness |
| stale alternate offer | None executable | STALE or AMBIGUOUS period/line identity |
| malformed row / impossible odds | None | INVALID |
| misleading opposite highlight | Net candidate only | Opponent's EV never assigned to candidate |
| missing highlight, nonzero net move | Net candidate | Unequal-line assessment allowed; no fabricated EV |

Real examples are appended below from frozen source messages. Direction is separate
from execution eligibility; unverified timezone and unset execution tolerances block otherwise eligible cases.

## Real source examples

| Intake ID / fixture | Market | Opening → current → candidate | Bet365 same-side offer | Highlight / EV | Strategy assessment |
|---|---|---|---|---|---|
| 9: Rytas Vilnius vs Shanghai Sharks | TOTALS | 185.5 → 184 → UNDER | 184 @ 2.00 | UNDER / 109.91% | equal_line_supplied_edge |
| 11: Japan vs Thailand | SPREAD | -49.5 → -56.5 → HOME | -58.5 @ 1.83 | none / None (not equal lines) | moved_too_far |
| 12: Kosice Wolves vs BK Inter Bratislava | SPREAD | 11 → 16.5 → AWAY | -16.5 @ 1.95 | HOME / 106.48% | no_proven_same_side_value; No supplied equal-line EV bound to the sharp side |
| 13: Kosice Wolves vs BK Inter Bratislava | SPREAD | 11 → 11.5 → AWAY | -11.5 @ 1.83 | AWAY / 112.84% | equal_line_supplied_edge |
| 15: Bisons Loimaa vs Salon Vilpas Vikings | TOTALS | 167.5 → 164.5 → UNDER | 166.5 @ 1.83 | none / None (not equal lines) | favourable_line_unpriced |
| 18: Randers Cimbria vs Svendborg Rabbits | SPREAD | -4.5 → -3 → AWAY | 3 @ 1.68 | HOME / 112.66% | no_proven_same_side_value; No supplied equal-line EV bound to the sharp side |
| 19: Neftchi vs KK Parnu | TOTALS | 165.5 → 167.5 → OVER | 167.5 @ 1.83 | UNDER / 107.40% | no_proven_same_side_value; No supplied equal-line EV bound to the sharp side |
| 20: Neftchi vs KK Parnu | TOTALS | 165.5 → 164.5 → UNDER | 167.5 @ 1.83 | none / None (not equal lines) | favourable_line_unpriced |
| 21: Bisons Loimaa vs Salon Vilpas Vikings | SPREAD | 11.5 → -2.5 → HOME | -5.5 @ 1.83 | none / None (not equal lines) | moved_too_far |
| 23: Metapan vs Brujos de Izalco BC | TOTALS | 155.5 → 157.5 → OVER | 155.5 @ 1.83 | none / None (not equal lines) | favourable_line_unpriced |
| 25: Metapan vs Brujos de Izalco BC | TOTALS | 155.5 → 158.5 → OVER | 155.5 @ 1.83 | none / None (not equal lines) | favourable_line_unpriced |
| 28: Bisons Loimaa vs Salon Vilpas Vikings | SPREAD | 11.5 → 2 → HOME | -4 @ 1.83 | none / None (not equal lines) | ambiguous; Cross-book favourite disagreement; Bet365 orientation needs verification |
| 35: KD Ilirija vs KK Nova Gorica Mladi | SPREAD | -24.5 → -25.5 → HOME | -25.5 @ 2.10 | HOME / 106.40% | equal_line_supplied_edge |
| 37: Kipina Basket vs Kauhajoki Karhu Basket | TOTALS | 170.5 → 166.5 → UNDER | 168.5 @ 1.83 | none / None (not equal lines) | favourable_line_unpriced |
| 38: Republic of Korea vs Indonesia | TOTALS | 142 → 148 → OVER | 148 @ 2.25 | OVER / 116.77% | equal_line_supplied_edge |
| 46: Kipina Basket vs Kauhajoki Karhu Basket | TOTALS | 170.5 → 170.5 → none | displayed 168.5; side unresolved | none / None (not equal lines) | insufficient_data; Unchanged opening/current line; price-only strategy not established |
| 48: Atletico Boca Juniors vs NBA G League United | SPREAD | 13 → 12 → HOME | 12 @ 1.83 | AWAY / 110.88% | no_proven_same_side_value; No supplied equal-line EV bound to the sharp side |
| 114: Bisons Loimaa vs Salon Vilpas Vikings | SPREAD | 11.5 → 7.5 → HOME | 9.5 @ 1.83 | none / None (not equal lines) | favourable_line_unpriced |
| 165: BMS Herlev vs Gladsaxe BK | SPREAD | -6.5 → 3 → AWAY | 1.5 @ 1.74 | none / None (not equal lines) | ambiguous; Cross-book favourite disagreement; Bet365 orientation needs verification |
| 275: Apagebask Guarulhos vs Santo Andre | TOTALS | 127.5 → 130 → OVER | 127.5 @ 1.83 | none / None (not equal lines) | favourable_line_unpriced |
| 341: CD Castro vs CSD Colo Colo | SPREAD | 4.5 → -4.5 → HOME | -1.5 @ 1.83 | none / None (not equal lines) | favourable_line_unpriced |
| 349: BC Tartu vs BC Kalev/Cramo | SPREAD | -3 → 3 → AWAY | 1.5 @ 1.83 | none / None (not equal lines) | ambiguous; Cross-book favourite disagreement; Bet365 orientation needs verification |
| 364: Seattle Storm vs Dallas Wings | SPREAD | 9.5 → 7.5 → HOME | -9.5 @ 1.80 | none / None (not equal lines) | ambiguous; Cross-book favourite disagreement; Bet365 orientation needs verification |
| 601: BK Loko Trutnov vs Slovanka MB | SPREAD | -26 → -24 → AWAY | 11.5 @ 1.83 | none / None (not equal lines) | moved_too_far |
| 681: Japan vs Chinese Taipei | SPREAD | -23 → -23 → none | displayed 18.5; side unresolved | none / None (not equal lines) | insufficient_data; Unchanged opening/current line; price-only strategy not established |
| 863: Japan vs Chinese Taipei | SPREAD | -23 → -26.5 → HOME | 26.5 @ 1.83 | AWAY / 106.83% | ambiguous; Cross-book favourite disagreement; Bet365 orientation needs verification |
| 1081: Norrkoping Dolphins vs Umea Basket | SPREAD | -22 → -23.5 → HOME | -23.5 @ 1.66 | AWAY / 107.59% | no_proven_same_side_value; No supplied equal-line EV bound to the sharp side |
| 1223: Norrkoping Dolphins vs Umea Basket | SPREAD | -22 → -25 → HOME | -27.5 @ 1.83 | none / None (not equal lines) | moved_too_far |
| 1317: Norrkoping Dolphins vs Umea Basket | TOTALS | 173 → 174 → OVER | 174 @ 2.00 | OVER / 110.75% | equal_line_supplied_edge |
| 1325: Norrkoping Dolphins vs Umea Basket | SPREAD | -22 → -25.5 → HOME | -25.5 @ 1.74 | AWAY / 108.31% | no_proven_same_side_value; No supplied equal-line EV bound to the sharp side |


## Final corpus reconciliation (after the initial specification)

The exploratory figures above describe the first 1,300 nonduplicate intake alerts,
not the final corpus denominator. The completed audit includes 174 content-suppressed
messages with distinct Telegram IDs and four earlier archive observations. There are
1,479 stored records, one of which is a service notice: **1,478 alert observations**.
All 140 live corpus fixtures and 23 unequal-line fixtures are covered by these source
IDs; nine undated reference samples are retained separately to avoid double counting.
Counts at that first cutoff are 1,168 clear net directions, 69 zero-line movements and 241 unsupported
or unlabelled markets. Old targets oppose net movement in 207 cases; highlights oppose
it in 126. These supersede the exploratory counts for full-corpus reporting.

This is proof of a deterministic interpretation of the requested strategy, not proof
of positive expected profit. Unverified timezone and unset execution tolerances block execution eligibility.
The 30 examples above are independent raw-offer assessments; e.g. alert 863 is also
INVALID in the production grammar because numeric EV accompanies unequal signed lines.

At the final frozen cutoff (20:12:37 UTC), 28 additional live arrivals were captured
and evaluated with the archived e1adaa2 core for the OLD side of the comparison.
The full final dataset has **1,507 stored records / 1,506 alerts**: 1,188 clear net
directions, 69 zero-line moves, 249 unsupported/unlabelled markets, 210 old target
contradictions and 128 highlight contradictions. See `summary.json` for this final
denominator. There are 29 arrows beside unchanged displayed parenthetical/current
prices, but zero arrows numerically pointing the opposite way in 3,012 checked pairs;
rounding or line resets may explain the unchanged displays. They do not select targets.
