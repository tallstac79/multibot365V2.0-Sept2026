# Rules engine

The pure `core/rules_engine.py` evaluator is **rules-5-feed-qualified**. Its configuration is
validated in `core/decision_support.py` and stored in `.local/dashboard.sqlite3` with
an audit trail. The service reads it each cycle; code changes require a service restart.

`evaluate(alert, config, instruction_id=..., received_at=..., now=...)` returns ACCEPT,
REJECT or STALE, all check results, the first failure as `reason`, and an instruction
only on ACCEPT. Intake AMBIGUOUS and INVALID do not enter this evaluator.

## Decision order

1. Require a verified quote mapping and current `sharp-money-1` PARSED interpretation.
2. Independently recompute the candidate from Pinnacle opening/current lines. Require
   agreement with stored target and `pinnacle_opening_to_current` source. Old queued
   favourable-side/highlight-only targets fail closed.
3. Require that candidate's Bet365 price and actionable quality: equal-line same-side
   supplied EV/price edge, or favourable unequal line. NO BET persists as REJECT.
4. For a favourable unequal line, require `min_line_advantage` (inherited 1.0 points;
   configurable 0.5 to 50). This is an existing policy, not a proven value model.
5. Require a valid strictly nonzero net move. OddsNotifier qualifies upstream;
   `min_sharp_movement=null` adds no second floor. An explicitly set floor applies.
6. Check supported/enabled sport and market, alert age and event time.
7. Check decimal odds, applicable EV floor, price bounds and capped stake.

All check results are retained even after the first failure. Thus unverified event
timezone can be the top-level REJECT while a later tolerance check also fails. Read all
checks when distinguishing policy exclusion from staleness.

## Configuration

Global defaults: enabled=true; stake=1; max_stake=10; stale window=300s;
event_timezone=null; feed_timezone_verified=false; min_line_advantage=1.0;
min_sharp_movement=null. Market overrides include enabled, stake, minimum_ev,
min_price, max_price and the two nullable execution deterioration limits. Existing
configs acquire the new nullable keys without silently selecting a threshold.
Saved price and EV bounds are unchanged. The movement floor remains optional.

`minimum_price = max(1.01, alert_price - max_odds_deterioration)`. Alert price bounds apply
at eligibility; the worker separately checks available price and the approved slip.
`minimum_ev` is inapplicable to favourable unequal-line signals because there is no
supplied EV at comparable lines. No synthetic EV is calculated.

The earlier of receipt/source time anchors alert age. Event times require a configured
IANA timezone; unknown timezone rejects, started events are STALE. The audit identifies
future timestamp and daylight-saving ambiguity checks; these are now implemented.

The pipeline evaluates at ingest and before dispatch. ACCEPT is eligibility only:
pause/kill switch, dispatch/final-action flags, identity, session, approval and durable
idempotency remain separate controls. Execution stayed disarmed throughout the audit.


Operator clarification: `feed_timezone_verified=false` is the default and the
saved UTC assumption remains provisional. Event eligibility rejects until verified;
aware Telegram age checks still run. Market-specific `max_odds_deterioration` and
`max_line_deterioration` are nullable and require explicit configuration. The legacy
`allowed_slippage` controls sample recommendations only. Improvements are allowed;
excess deterioration is NO BET. See [the evidence and timezone instructions](FEED_TIME_AND_EXECUTION_POLICY.md).
