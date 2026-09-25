# Feed qualification, timezone and execution tolerances

This amendment supersedes the audit's proposed mandatory second movement floor.
It follows the operator's clarification on 25 September 2026. The original audit
and its evidence remain historical records.

## Qualification and execution

OddsNotifier's configured feed supplies upstream movement qualification. MultiBot
requires a genuine, valid, nonzero Pinnacle opening-to-current movement and a
verified direction. `min_sharp_movement=null` imposes no additional floor and is
not a rejection reason. An explicitly configured optional floor remains supported.
Flat or ambiguous movement still cannot produce a bet. The candidate, same-side
Bet365 comparison and existing value checks remain separate from event timing.

Two nullable settings exist per sport/market: `max_odds_deterioration` in decimal
odds points and `max_line_deterioration` in handicap/total points. They require an
operator decision; neither is silently selected or inherited from the legacy
sample `allowed_slippage` field. No new global price bounds are imposed.

For requested odds R and live odds L, deterioration is max(0, R-L). For a selected
spread or UNDER, line deterioration is max(0, requested line-live line); for OVER
it is max(0, live line-requested line). A larger signed handicap benefits either
selected spread team; a lower total benefits OVER, a higher total benefits UNDER.
Improvements consume zero tolerance. Both limits must pass on the same side.
Final checks compare against the original alert, avoiding cumulative slippage
through several reads. Missing terms or ambiguous alternate choices fail closed.

## What the stored observations support

Reproduce with `python -m tools.execution_policy_report`. It reads the immutable
forensic corpus and a frozen set of 26 historical instruction results. Only six
results have a complete selected alert/live line-and-odds pair. All six selected
sides agree with the corrected sharp-side interpretation, but they were attempted
under the previous strategy; they are not an unbiased sample of opportunities.

| Maximum odds deterioration | Line tolerance tested | Spread retain/reject | Totals retain/reject | All retain/reject |
|---:|---:|---:|---:|---:|
| 0.00 | 0, 0.5, 1.0 | 3 / 1 | 2 / 0 | 5 / 1 |
| 0.01 | 0, 0.5, 1.0 | 3 / 1 | 2 / 0 | 5 / 1 |
| 0.02 | 0, 0.5, 1.0 | 3 / 1 | 2 / 0 | 5 / 1 |
| 0.05 | 0, 0.5, 1.0 | 3 / 1 | 2 / 0 | 5 / 1 |
| 0.10 | 0, 0.5, 1.0 | 3 / 1 | 2 / 0 | 5 / 1 |
| 0.32 (diagnostic only) | 0, 0.5, 1.0 | 4 / 0 | 2 / 0 | 6 / 0 |

Five quotes were unchanged. Boras/Nassjo's selected AWAY +13.5 fell from 2.15 to
1.83: 0.32 decimal points (14.88% of requested decimal odds). All six observed
lines were unchanged. Recommendation for approval: initially zero deterioration
for both spreads and totals; the stored data supplies no retention benefit or
empirical justification for widening either limit. A 0.02 odds alternative makes
no difference here. Zero is a proposed execution baseline, not a profitability
claim. Full-corpus retention cannot be estimated without live quotes for the
other alerts. The CSV lists every pair and every tested scenario.

## Exactly what to check in OddsNotifier

Open **OddsNotifier Portal → Configuration → Timezone**:
[account Configuration page](https://app.oddsnotifier.io/configuration).
The provider's [official setup guide](https://oddsnotifier.io/en/blog/oddsnotifier-setup-guide)
locates Timezone in Configuration and states that those preferences affect alerts.
This is the account preference, not the Telegram display clock or phone timezone.

Confirm the **exact currently selected timezone label/value**, especially whether
it is UTC or Europe/London. If the UI uses GMT/offset labels, provide that exact
label; a fixed +01:00 zone and Europe/London differ outside summer. The account
itself has not been inspected. Saved configuration is `event_timezone="UTC"`,
`feed_timezone_verified=false` until the operator confirms it.

## Stored evidence: UTC versus Europe/London

September UK local time is BST (UTC+1). These stored phone header observations
agree with interpreting the feed wall time as UTC and converting to UK time:

| Fixture | Feed event wall time | Observed phone header time |
|---|---|---|
| Berck/Rang du Fliers — Pays Salonais | 25 Sep 18:00 | 25 Sep 19:00 |
| Boras Basket — Nassjo Basket | 25 Sep 17:04 | 25 Sep 18:04 |
| Seoul SK Knights — Wonju Dongbu Promy | 26 Sep 05:00 | 26 Sep 06:00 |
| Explosivas de Moca — Leonas de Ponce | 26 Sep 00:00 | 26 Sep 01:00 |
| Poitiers — Evreux | 25 Sep 18:00 | 25 Sep 19:00 |
| ASC Denain — Blois | 25 Sep 18:00 | 25 Sep 19:00 |

These examples support UTC **assuming the bookmaker display is UK local time**.
They do not prove the account setting. Europe/London would predict the same
displayed clock time as the feed in September, not the observed +1 hour. No
equally strong same-clock example in these stored verified header observations
supports Europe/London. Missing or garbled kickoff OCR is not contrary evidence;
winter examples would not distinguish these two zones. Full provenance is in
`evidence/execution-policy/timezone-phone-evidence.json`.

At each alert's historical receipt time, 258 of 1,506 alerts change their
event-not-started verdict under UTC versus Europe/London; 171 change their overall
otherwise-verified eligibility decision after the other rules. Every affected
record is in `timezone-sensitive-alerts.csv`, including both conversions, the
sharp side, classification and both otherwise-verified decisions. That comparison
uses explicitly labelled zero-slippage research settings, never saved live.

## Consequences and fail-closed behaviour

If a Europe/London feed is treated as UTC in summer, the interpreted start is one
hour too late. An already started event could appear eligible for up to an hour,
and the phone could search for the wrong kickoff. Treating an actual UTC feed as
Europe/London instead makes events appear to start an hour early, rejecting valid
pre-match work. Midnight/day boundaries, queue expiry and identity kickoff checks
can also be wrong. Ambiguous/nonexistent DST wall times reject rather than guess.

**Unverified event-time eligibility fails closed.** Even where the two candidate
zones currently agree, no execution is authorized until the account setting is
confirmed. The original aware Telegram source timestamp and aware local receipt
timestamp still drive age checks independently; timezone uncertainty is not a
reason to reinterpret their offsets. Future source/receipt clocks beyond 30 seconds
reject, and stale messages remain stale. The phone payload uses the rules engine's
verified UTC conversion, never relabels a raw feed wall time as UTC.

None of this changes sharp-side selection, Pinnacle movement direction, supplied
EV attribution or same-side Bet365 line/price comparison. Logs, saved config,
rule results and the service heartbeat expose `feed_timezone_verified=false`.
New alerts with differing candidate start verdicts emit a durable
`TIMEZONE_ELIGIBILITY_UNCERTAIN` audit event and warning, including both assumptions.

After account confirmation, update the timezone and verification flag, then rerun
only timestamp/stale/event-start tests (`tests.test_feed_time` plus the relevant
pipeline stale/dispatch tests). Strategy and slippage interpretation need no
change or full-suite rerun merely because that timezone confirmation arrives.

The focused confirmation check is:

```text
python -m unittest tests.test_feed_time tests.test_pipeline.IntakeTests.test_stale_by_age_event_started_and_unknown_timezone tests.test_pipeline.IntakeTests.test_queued_alert_goes_stale_before_dispatch -q
```
