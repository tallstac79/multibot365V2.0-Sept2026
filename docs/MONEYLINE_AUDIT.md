# Basketball MONEYLINE audit and execution contract

Audited 26 September 2026, before any supervised wager. Frozen source:
`evidence/moneyline-audit/baseline.json.gz`, 1,873 stored intake records, including
318 basketball ML alerts across 62 fixtures. Raw messages, Telegram IDs, timestamps,
old classification and configuration are preserved. Repeated alerts are not
independent betting opportunities. Reproduce with `python -m tools.moneyline_audit`.
The immutable supplement `postcutoff-baseline.json` adds six arrivals through
08:43:52 UTC: the final replay covers **1,879 records / 319 ML alerts / 63 ML fixtures**.
The raw-field and cross-market ordering research describes the initial 318 ML rows;
the final replay includes every row from both snapshots. Later live arrivals remain
in normal intake and are outside this explicitly frozen audit cutoff.

## Ordering and fields established from the feed

The [provider's ML guide](https://oddsnotifier.io/en/blog/oddsnotifier-setup-guide)
states the HOME / DRAW / AWAY convention and distinguishes current, previous
bracketed and opening prices. The audited basketball format has two outcomes:
HOME first, AWAY second, with no draw slot. This two-outcome application is supported
by the real paired basketball corpus; it is a fixed format contract, never a
per-alert guess from which price is shorter or which team is favourite.

For this verified profile:

| Field | Meaning |
|---|---|
| First fixture name | HOME team |
| Second fixture name | AWAY team |
| Price row after event time | Current Pinnacle HOME, AWAY |
| Parenthetical prices | Previous price snapshot, not opening |
| Price row after `Opening` | Opening Pinnacle HOME, AWAY |
| Price row after Bet365 link | Bet365 HOME, AWAY in the same order |
| One bold Bet365 price | Owner of the feed's displayed EV |
| Recent arrow | Recent direction only; never replaces opening-to-current movement |

Independent corroboration compared 227 near-simultaneous, same-fixture Bet365 ML
and HOME-perspective spread observations: 212 favourite signs agree and 15 do not.
All matches, including disagreements, are in `order-corroboration.json`. This is
corroboration, not a second ordering rule or proof that all markets update together.
Spread signs/alternate lines can disagree; they never flip an ML mapping.
Actual phone grid fixtures also bind ML cells to named team rows (for example,
Hapoel Tel Aviv 1.23 and Bayern Munich 3.75 in the stored Game Lines OCR fixture).

A silent provider reversal of otherwise identical unlabelled pairs cannot be
deduced from prices alone. Unknown formats, wrong outcome counts, duplicated or
inconsistent named ordering, mixed markets and malformed prices fail closed.
This profile does not infer a two-way mapping for football three-way 1X2. Football
1X2 has its own verified profile since 27 Sep 2026 (`core/football.py`,
[FOOTBALL_STRATEGY_SPEC.md](FOOTBALL_STRATEGY_SPEC.md)).

## Minimum evidence and side selection

The alert must identify basketball ML by its fixture URL or explicit ML label,
two distinct teams, complete opening/current Pinnacle pairs and a complete Bet365
pair in this profile. Pinnacle odds must be finite and greater than 1.
Exactly one side must shorten from opening while the other stays unchanged or
drifts. That unique side is the candidate. Any genuine nonzero shortening suffices;
the upstream feed supplies signal qualification. The optional extra line-movement
floor does not apply to decimal-price movement.

Equal prices/no net movement, both sides shortening, or neither side shortening
cannot establish a unique target without adding a margin model. They remain
AMBIGUOUS, visible and auditable. No de-vig model or synthetic EV is introduced.

Only the candidate's Bet365 price is assessed. Existing same-price-market value
checks require Bet365 above current Pinnacle and feed EV above 100% belonging to
that same side. Opposing highlights retain the opening-to-current candidate but
cannot lend EV to it, select the opponent or authorize execution. Missing or
ambiguous EV ownership also cannot qualify a price-only opportunity.

Three actual alerts show the nonselected Bet365 HOME price as 1.00. Its position
is retained as a non-executable displayed quote; it does not invalidate a valid
AWAY offer. A requested price of 1.00 itself can never execute.

## Real examples (unaltered feed values)

Every price pair below is HOME / AWAY. The test fixture preserves the raw text
and message provenance; these are observations, not invented betting examples.

| Message | Fixture | Opening Pinnacle | Current Pinnacle | Candidate | Bet365 | EV owner | Assessment |
|---|---|---|---|---|---|---|---|
| 67969 | San Salvador / Aguila San Miguel | 2.200 / 1.510 | 1.613 / 2.030 | HOME | 2.25 / 1.57 | HOME 127.72% | HOME shortened from underdog to favourite; same-side value |
| 68122 | BMS Herlev / Gladsaxe BK | 1.295 / 3.190 | 2.370 / 1.531 | AWAY | 1.83 / 1.83 | AWAY 113.49% | AWAY shortened from underdog to favourite; same-side value |
| 68111 | Randers Cimbria / Svendborg Rabbits | 1.460 / 2.550 | 1.342 / 2.960 | HOME | 1.57 / 2.25 | HOME 111.93% | Favourite shortened; same-side value |
| 68169 | BC Beroe / Ferrol | 3.100 / 1.268 | 3.680 / 1.181 | AWAY | 2.85 / 1.37 | AWAY 110.87% | Favourite shortened; same-side value |
| 68001 | CD Campinho / Illiabum Clube | 8.410 / 1.012 | 4.890 / 1.123 | HOME | 10.50 / 1.02 | HOME 142.57% | Remains underdog after shortening; same-side value |
| 67974 | Bisons Loimaa / Salon Vilpas Vikings | 4.790 / 1.062 | 1.699 / 1.990 | HOME | 1.41 / 2.70 | AWAY 122.82% | NO BET: HOME offer worse; AWAY highlight cannot switch target |
| 69212 | Tryhoop Okayama / Koshigaya Alphas | 3.100 / 1.268 | 3.210 / 1.291 | None | 5.00 / 1.14 | HOME 128.61% | Both drifted from opening despite recent HOME down arrow |
| 68743 | Japan / Chinese Taipei | 1.024 / 13.370 | 1.060 / 8.470 | AWAY | 1.00 / 18.00 | AWAY 125.94% | AWAY qualifies; opposite 1.00 quote is not executable |

## Execution tolerance and storage

ML uses the unchanged 10% net-payout rule:
`minimum = ceil_to_cent(max(1.01, 1 + (original_alert_odds - 1) * 0.90))`.
For message 67969, 2.25 implies minimum 2.13: live 2.13 passes, 2.12 rejects.
For 68122, 1.83 implies 1.75; for 68169, 1.37 implies 1.34. Improvements pass.
These boundary observations are explicit test mutations, not claimed historical
executions. ML has no line: null/empty/NONE are absence, and numeric zero is not
an invented ML handicap. No line-tolerance setting is required.

Grid, slip, prepare and pre-tap observations compare with the original alert's
floor; intermediate movement never compounds. Event identity, HOME/AWAY,
full-game market, kickoff, session, stake, approval and one-tap protections remain.
Actual receipt odds must come from the selected team's receipt row; unknown
receipt terms never borrow pre-tap values. All observed comparisons, including
rejections, remain in instruction results and `ALERT_TO_LIVE_COMPARISON` audit rows.

## Full replay and regression results

The final 1,879-row corpus replays to 1,623 PARSED, 244 AMBIGUOUS, 11 INVALID and
1 IGNORED. The one ignored row is not an ML alert. ML results:

| Result | Records |
|---|---:|
| Parsed with verified opening-to-current target | 316 |
| HOME / AWAY targets | 157 / 159 |
| Same-side value signals before time checks | 294 |
| Eligible at historical receipt time | 292 |
| Same-side value rejected (opposing highlight) | 22 |
| No unique net shortener | 3 |
| Stale among otherwise qualifying ML signals | 2 |

Historical eligibility is not placement, profitability or fresh-live retention.
The replay compares **every non-ML classification and every corresponding rules
result** with commit `8b39fed`: zero differences excluding parser/engine version
labels. Spread/Totals strategy and their configured tolerances are unchanged.

Tests use real feed examples for both sides, favourites/underdogs and agreeing /
opposing highlights. The corpus contains no fully unchanged opening/current ML
pair; equal/no-movement, both-shortening, missing/reversed ordering, malformed
prices and live tolerance boundaries are explicitly labelled mutations of real
rows. They are never described as observed feed behavior.

The full backend suite passed 325 tests; Android passed 109 JVM tests and built
APK 0.9.20-moneyline (103). The 15 focused ML tests were rerun with the final corpus
supplement. Logs, APK hash and runtime readiness are in `evidence/moneyline-audit/`.
The installed phone also passed a session-only check; this is not a live ML wager
or a new live market-selection proof. See [supervised-run readiness](SUPERVISED_RUN_READINESS.md).
Old intake statuses remain historical; this offline replay never queues old tips.
