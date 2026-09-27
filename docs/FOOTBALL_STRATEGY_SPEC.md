# Football (Feed 1) strategy specification

Written 27 September 2026 from the real OddsNotifier Feed 1 corpus and Bet365 football event pages captured on the
phone. Basketball (Feed 2) behaviour is unchanged; football enters its own module (`core/football.py`) only when the
alert header says `Football`. Principle preserved from the basketball strategy: **the reference market (Pinnacle
opening -> current) selects WHAT outcome we want; Bet365 then decides whether that SAME outcome is still acceptable.**
No other Bet365 price, highlight or line ever switches the outcome.

## 1. Evidence base

| Source | What it establishes |
|---|---|
| `tests/fixtures/feed1_football/feed1_alerts_20260927.jsonl` | 72 real Feed 1 alerts, 26 Sep 23:50 - 27 Sep 09:07 UTC: 7 1X2, 28 Spread, 37 Totals; every layout variant seen (linked 1X2, two-sided market-first, two-sided opening-first, `(alt. line)`, `EV: None (not equal lines)`, in-play `#/IP/` links) |
| `evidence/football/captures/` | Phone hold runs on 27 Sep 10:25-10:28 UK: Bet365 football event pages read by the worker's own OCR (Farul Constanta (W) v FK Csikszereda, Vihiga Queens FC (W) v Ulinzi Starlets (W), JaPS U21 v PPJ U21, ATSV Salzburg v Union Henndorf) |
| `evidence/football/pages/` | adb screenshots of the Popular, Asian Lines and Goals tabs (Farul, Vihiga) and alert-synchronous captures by `football_watch_capture` |
| `evidence/football/replay-*.txt` | `python -m tools.football_audit` replay of the corpus |
| Provider setup guide (oddsnotifier.io) | HOME / DRAW / AWAY convention, Opening = sharp opening quote, brackets = previous price, spread line = HOME handicap, totals = OVER then UNDER |

## 2. OddsNotifier -> Bet365 mapping (established)

**1X2 (fixture URL `market=ML`, no market label row).**

```
<current>  2.090⬇️ (2.310) - 3.490 (3.490) - 2.880⬆️ (2.560)     HOME - DRAW - AWAY, bracket = previous price
Opening    2.440 - 2.450                                        HOME - AWAY  (the draw's opening price is NOT supplied)
[Bet365](event link)
**2.88** - 3.50 - 2.15                                           HOME - DRAW - AWAY, bold = owner of the displayed EV
EV: 127.07%
```

Proof of ordering: in all 7 real 1X2 alerts the bold Bet365 price sits on the outcome that is the unique
opening-to-current shortener (5 HOME, 2 AWAY, never the draw); the draw price is the middle value in every current and
Bet365 row (3.49-7.82 range, never the favourite); the two opening prices pair with HOME and AWAY under the shortener
rule and would be impossible as a HOME-DRAW or DRAW-AWAY pair (a 1.54 "draw" in Honda v YSCC). On the phone the Full
Time Result columns read *home team | Draw | away team* left to right on every captured page (Farul 1.36 | 5.25 | 5.75,
Salzburg 3.30 | 4.75 | 1.66, JaPS 1.80 | 4.50 | 3.00, Vihiga 3.50 | 3.40 | 1.85), consistent with Pinnacle's favourite.

**Spread = Asian handicap, HOME perspective.**

```
Spread (-1) (alt. line)
1.330⬇️ (1.374) - 2.940⬆️ (2.750)      HOME at -1 - AWAY at +1
Opening (-1)
1.787 - 1.934
[Bet365 (Spread -1)](event link)
**1.80** - 2.00                          HOME -1 - AWAY +1, bold = EV owner
```

The displayed line is the HOME handicap (provider guide; Halcones Negros -1 at 1.33 = favourite; a reversed reading
would give Bet365 AWAY -1 at 1.80 no EV against Pinnacle 2.94). On the phone the Asian Handicap grid shows the two team
columns *home | away* with each team's own signed line under its name (Vihiga Queens FC (W) +0.5 1.850 | Ulinzi
Starlets (W) -0.5 1.950). Lines move in quarter goals; Bet365 displays quarter lines as two values ("2.5,3.0" = 2.75).
The `(alt. line)` marker on the current row means Pinnacle's row is the alternate line matching Bet365's offer, not
Pinnacle's main line.

**Totals = goals, OVER then UNDER.**

```
Totals (2.25)
2.030⬆️ (1.909) - 1.806⬇️ (1.909)      OVER - UNDER
Opening (2.25)
1.917 - 1.826
[Bet365 (Totals 2.25)](...)
1.70 - **2.10**                          OVER - UNDER, bold = EV owner
```

On the phone Goals Over/Under and Goal Line grids read *Over | Under* (Farul 2.5: 1.36 | 3.00, Salzburg 1.28 | 3.50,
JaPS 1.16 | 4.50, Vihiga Goal Line 2.5: 2.025 | 1.775). Alert-synchronous comparisons of the alert's Bet365 row with the
page are collected by `football_watch_capture` in `evidence/football/pages/alert-*`.

## 3. Sharp-side selection (reference market only)

* **1X2:** exactly one of the outcomes the Opening row supplies must shorten from opening to current while the other
  does not shorten. HOME or AWAY. Because the draw's opening price is not in the feed, **DRAW is not selectable**; it
  becomes selectable only if an alert carries a three-price Opening row and the draw is that unique shortener (tested
  synthetically; never seen live). Both shortening, neither shortening or no movement: AMBIGUOUS.
* **Spread / Totals, equal opening and current line** (25 of 28 Spread, 37 of 37 Totals alerts): the unique net PRICE
  shortener at that line selects HOME/AWAY or OVER/UNDER. Both/neither: AMBIGUOUS.
* **Spread / Totals, moved line:** the main-line direction selects (HOME handicap down -> HOME, up -> AWAY; total up ->
  OVER, down -> UNDER) **only if** the current row is not an `(alt. line)` (otherwise the main line is unknown - Vihiga
  Queens 0 vs opening 0.25/0.5) and the price movement does not contradict it. Otherwise AMBIGUOUS.
* Highlights (bold), Bet365 prices and the latest arrows never select. The bracketed previous price is recorded only.

## 4. Same-side Bet365 comparison and verdicts

* Only the selected outcome's Bet365 price/line is compared. The bold price identifies the EV owner; an EV owned by
  another outcome is `SUPPLIED_FOR_OTHER_SIDE` and cannot qualify the target; an EV with no bold owner is
  `SUPPLIED_OWNER_UNKNOWN` (NO BET).
* **1X2:** equal "line" by definition; Bet365 price above Pinnacle current price and same-side EV > 100 ->
  `CLEAR_VALUE_SIGNAL` -> EXECUTABLE_HOME / EXECUTABLE_AWAY (DRAW as above). Bet365 at or below Pinnacle: NO BET.
* **Spread / Totals, equal line:** as 1X2 -> EXECUTABLE_HOME/AWAY/OVER/UNDER or NO BET.
* **Spread / Totals, different Bet365 line** (`EV: None (not equal lines)`): NO BET. A different goal line is a
  different bet; goal-line steps change prices steeply and the feed supplies no EV. (Basketball keeps its
  FAVOURABLE_LINE_SIGNAL policy; for football the offer is retained as POTENTIAL_VALUE, non-actionable.)
* **In-play Bet365 link (`#/IP/EV...`, 10 of 72 alerts):** NO BET - the phone cannot verify a pre-match kick-off or
  identity on a live page.
* INVALID: malformed or contradictory rows (wrong outcome counts, negative totals, EV against unequal lines, a Bet365
  market that conflicts with the alert market).

Verdict names: `EXECUTABLE_HOME`, `EXECUTABLE_DRAW`, `EXECUTABLE_AWAY`, `EXECUTABLE_OVER`, `EXECUTABLE_UNDER`, `NO_BET`,
`AMBIGUOUS`, `INVALID` (`alert['football']['verdict']`, `verdict_reason`, `signal_basis`, `in_play_link`).

## 5. Rules engine and execution terms

`core/rules_engine.py` (ENGINE_VERSION `rules-8-football`) re-derives the football signal from the stored quotes and
requires it to equal the interpreted target (`sharp_target`), binds the requested Bet365 price to the target's own
position at its own line from a pre-match link (`football_same_side_offer`), treats 1X2 as a price market (no line
tolerance, like basketball MONEYLINE) and keeps every other check (bet quality, age, kick-off not started, price bounds,
stake, execution tolerances). Alert-to-live tolerances are the existing policy: 10 % of net payout on the price and an
absolute line cap for handicaps/totals.

**Live configuration is untouched:** the football markets are `enabled` but their `max_net_payout_deterioration_percent`
and `max_line_deterioration` are unset, so every football alert stops at `execution_tolerances` (REJECT) until the
operator sets them. The audit uses 10 % net payout and a 0.25-goal line cap (`tools/football_audit.py:football_config`)
as the proposed football terms; they are not applied.

## 6. Phone (0.9.26-ops)

* Wire market `1X2` is the adapter's three-way `MONEYLINE` (HOME/DRAW/AWAY); `SPREAD`/`TOTALS` unchanged.
* Event identity: the football header parses with the same resolver (competition country-prefixed, kick-off in UK
  time, women's marker from the competition; new: the competition's own age marker, e.g. "U21 League" -> "JaPS U21").
* Markets (`FootballMarkets`): Popular tab Full Time Result and main Goals Over/Under; Goals tab for other total lines;
  Asian Lines tab for Asian Handicap and Goal Line, reached by tapping the tab (the strip is swiped when the tab is
  off-screen). Only the frame that shows the requested market supplies tap targets. Column labels must name the fixture's
  teams / Draw / Over / Under or no cell is produced.
* Everything after the tap (betslip single, selection name and line on the slip, stake, To Return, Place Bet located and
  never tapped in a hold) is the existing flow.

## 7. Corpus replay (27 Sep 2026, 72 alerts)

See `evidence/football/replay-*.txt` (regenerate with `python -m tools.football_audit`): 43 executable (19 HOME,
6 AWAY, 5 OVER, 13 UNDER, 0 DRAW), 24 NO BET (10 in-play links, 14 different Bet365 line), 5 AMBIGUOUS (3 alternate-line
handicap rows with a moved main line, 2 with both sides shortening), 0 INVALID. With the proposed football terms and
alerts evaluated as if received live, the rules engine accepts 38 and rejects 14 (all `bet_quality` POTENTIAL_VALUE on
unequal lines) - none are dispatched because the live terms are unset.
