# Rules engine

The pure `core/rules_engine.py` evaluator is **rules-4-sharp**. Its configuration is
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
5. Require configured `min_sharp_movement`, a strictly nonzero net move and magnitude
   at least that floor. The new default is null: **missing policy rejects**. Zero
   explicitly permits any nonzero move; it never permits an unchanged line.
6. Check supported/enabled sport and market, alert age and event time.
7. Check decimal odds, applicable EV floor, price bounds and capped stake.

All check results are retained even after the first failure. Thus missing movement
policy can be the top-level REJECT while a later timing check also fails. Read all
checks when distinguishing policy exclusion from staleness.

## Configuration

Global defaults: enabled=true; stake=1; max_stake=10; slippage=0; stale window=300s;
event_timezone=null; min_line_advantage=1.0; min_sharp_movement=null. Market overrides
include enabled, stake, minimum_ev, slippage, min_price and max_price. Existing configs
acquire the nullable movement key on validation without silently selecting a threshold.
The audit did not change the saved movement, price or EV policy.

`minimum_price = max(1.01, alert_price - allowed_slippage)`. Alert price bounds apply
at eligibility; the worker separately checks available price and the approved slip.
`minimum_ev` is inapplicable to favourable unequal-line signals because there is no
supplied EV at comparable lines. No synthetic EV is calculated.

The earlier of receipt/source time anchors alert age. Event times require a configured
IANA timezone; unknown timezone rejects, started events are STALE. The audit identifies
future timestamp and daylight-saving ambiguity checks as remaining improvements.

The pipeline evaluates at ingest and before dispatch. ACCEPT is eligibility only:
pause/kill switch, dispatch/final-action flags, identity, session, approval and durable
idempotency remain separate controls. Execution stayed disarmed throughout the audit.
