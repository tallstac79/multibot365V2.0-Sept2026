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

## Current operator policy (26 September 2026)

The operator confirmed the account label `(GMT+00:00) London, Birmingham,
Liverpool, Sheffield, Bristol` and explicitly instructed fixed UTC/GMT+0.
The saved settings are now `event_timezone="UTC"` and
`feed_timezone_verified=true`. This records operator confirmation, not an
independent inference that the UI label determines daylight-saving behavior.
Sharp-side selection and all existing value checks are unchanged.

Basketball odds use configurable `max_net_payout_deterioration_percent=10`:
`minimum_price = ceil_to_cent(max(1.01, 1 + (alert_price - 1) * 0.90))`.
Thus 1.83 requires 1.75, and 2.15 requires 2.04. Rounding up never permits more
than the configured loss. The old `max_odds_deterioration` decimal-point setting
remains a compatibility option; configuring both modes is rejected. No global
alert-price bounds or additional sharp-movement floor have been invented.

Basketball spreads use `max_line_deterioration=1.0` AND
`max_line_deterioration_percent=10`: the effective allowance is
`min(1.0, abs(original_alert_handicap) * 0.10)`. From the selected team's signed
perspective, deterioration is `max(0, original_line - live_line)` for either
HOME or AWAY, favorite or underdog. A larger signed handicap is an improvement.
All five operator examples are covered by regression tests.

Basketball totals retain `max_line_deterioration=null` pending the operator's
choice. Spread percentages are invalid on totals. Proposed allowance: **0.5
point absolute**, with OVER deterioration `max(0, live-original)` and UNDER
`max(0, original-live)`. This proposal is not saved or inferred to be optimal.
Until configured, totals eligibility fails closed. Football policies remain
unchanged; all execution remains disarmed.

Every fresh basketball grid/slip/pre-tap quote is tested against limits derived
once from the qualifying alert. An intermediate quote never becomes a baseline.
Improvements consume no tolerance. Identity, event time, availability and stake
must still verify. The original hold binds the original line allowance and odds
floor; `PLACE_HELD` re-reads the actual slip immediately before any action.

Requested and observed terms, stage, observation time, policy and device outcome
are persisted in instruction results and `ALERT_TO_LIVE_COMPARISON` audit rows,
including price/line failures. Rules rejections explicitly record live terms as
unknown; unreadable observations never borrow a previous price or line.

## Historical comparison and totals recommendation

[Full comparison](../evidence/execution-policy-v2/REPORT.md), with frozen source
and per-quote calculations alongside it. Reproduce with
`python -m tools.scaled_execution_report`; this reads only and never saves policy.

The 26 stored results contain six usable alert/live pairs: five at selection
stage and one at pre-tap. Spreads retain **3/4**; Boras/Nassjo loses 27.83% of net
payout (2.15 to 1.83) and still rejects. Both totals quotes were unchanged, so
candidate allowances of 0, 0.5 and 1 point each retain **2/2** when combined with
10% net-payout tolerance. These totals counts are scenarios, not production
acceptances while its line setting remains null.

No historical line deteriorated in this small comparison set. It cannot measure
full-feed retention, distinguish the totals candidates, or establish an optimum.
The 182 resolved total-line alert records include 141 half-point and 41 whole-point
values, supporting 0.5 point as a provisional operational unit. These are repeated
alert records, not independent events or proof of every bookmaker ladder's steps.
The earlier zero-deterioration recommendation is superseded by this operator policy.

## Exactly what to check in OddsNotifier

Open **OddsNotifier Portal → Configuration → Timezone**:
[account Configuration page](https://app.oddsnotifier.io/configuration).
The provider's [official setup guide](https://oddsnotifier.io/en/blog/oddsnotifier-setup-guide)
locates Timezone in Configuration and states that those preferences affect alerts.
This is the account preference, not the Telegram display clock or phone timezone.

For a future setting change, confirm the **exact selected timezone label/value**,
especially whether it is UTC or Europe/London. If the UI uses GMT/offset labels, provide that exact
label; a fixed +01:00 zone and Europe/London differ outside summer. The operator has now supplied the account label and instructed fixed UTC. Saved
configuration is `event_timezone="UTC"`, `feed_timezone_verified=true`.

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
rule results and the service heartbeat expose the verification flag (now `true`).
While unverified, new alerts with differing candidate start verdicts emit a durable
`TIMEZONE_ELIGIBILITY_UNCERTAIN` audit event and warning, including both assumptions.

The account confirmation changed only the timezone verification setting. Its
focused verification reran only timestamp/stale/event-start tests (`tests.test_feed_time` plus the relevant
pipeline stale/dispatch tests). Strategy and slippage interpretation need no
change or full-suite rerun merely because that timezone confirmation arrives.

The focused confirmation check is:

```text
python -m unittest tests.test_feed_time tests.test_pipeline.IntakeTests.test_stale_by_age_event_started_and_unknown_timezone tests.test_pipeline.IntakeTests.test_queued_alert_goes_stale_before_dispatch -q
```

All 10 focused confirmation tests passed; evidence is in `evidence/execution-policy-v2/time-tests.log`. Additional execution-policy tests cover the separately requested tolerance changes.

## Validation and installed state

The affected backend/dashboard set passed 147 tests; the final malformed-quote
boundary check passed all 8 scaled-policy tests. Android passed 105 JVM tests
and built APK `0.9.19-scaled-execution` (102), installed on the existing phone.
The updated services read back the approved policy. Phone health was IDLE with
local final-action arming false, all four backend execution/auto-approval flags
false, and the kill switch on. No live market workflows or wagers were run for
this amendment. The fresh-quote logic is covered by automated tests; installation
was checked through health/version, not a new live market demonstration.
Test logs, APK hash, configuration before/after and runtime verification are in
`evidence/execution-policy-v2/`. No strategy direction, value, stake, alert-age or
event-start rule changed beyond marking the operator's UTC setting verified.
