# Rules engine

Code: `core/rules_engine.py` (evaluation) and `core/decision_support.py` (configuration,
validation, persistence). Both run outside the frontend. The configuration is the same one
the dashboard's **Rules & configuration** screen edits: `.local/dashboard.sqlite3`, with
atomic saves and a change audit. The service re-reads it every cycle, so edits apply
without a restart.

`evaluate(alert, config, instruction_id=, received_at=, now=)` is pure. It returns:

```json
{"engine": "rules-1", "evaluated_at": "...", "config_hash": "156d8a05cb270139",
 "decision": "ACCEPT | REJECT | STALE", "reason": "first failing check: detail",
 "checks": [{"name": "verified_mapping", "passed": true, "detail": "..."}, "..."],
 "instruction": {"instruction_id": "...", "sport": "...", "competition": "...", "fixture": "...",
                 "home": "...", "away": "...", "event_time_local": "...", "event_timezone": "...",
                 "event_start_utc": "...", "market": "...", "side": "...", "selection_name": "...",
                 "line": "...", "alternate_line": {"current": true, "opening": false, "comparison": false},
                 "alert_price": "1.83", "minimum_price": "1.83", "stake": "1.00",
                 "displayed_ev_percent": "108.47"}}
```

`instruction` is present only on ACCEPT. The full result is stored as
`instructions.rules_result`, and the dashboard shows every check.

## Configuration

GLOBAL

| Key | Default | Meaning |
|---|---|---|
| enabled | true | Master switch |
| default_stake | 1.0 | Suggested stake when a market has none |
| max_stake | 10.0 | Upper bound; every stake must be ≤ this |
| allowed_slippage | 0.0 | minimum_price = max(1.01, alert price − slippage), in decimal-price points |
| stale_alert_seconds | 300 | Maximum age since the Telegram post (or receipt if earlier) |
| event_timezone | null | IANA zone for OddsNotifier fixture times. Null fails closed (see below). |
| min_line_advantage | 0.5 | Minimum Bet365 line advantage, in points, for a FAVOURABLE_LINE_SIGNAL (0.5 to 50) |

FOOTBALL (`1X2`, `SPREAD`, `TOTALS`) and BASKETBALL (`MONEYLINE`, `SPREAD`, `TOTALS`), per
market:

| Key | Meaning |
|---|---|
| enabled | Market switch |
| stake | Suggested stake for this market (blank inherits default) |
| minimum_ev | Minimum displayed EV % (blank means no threshold) |
| allowed_slippage | Market override of the global slippage |
| min_price / max_price | Allowed alert-price range (blank means no bound) |

Configurations saved before these keys existed are upgraded with the defaults on read.
Unknown keys are still rejected.

## Check order (the first failure decides)

1. `verified_mapping`: production-verified quote mapping (otherwise REJECT; nothing is guessed)
2. `explicit_target`: explicit Bet365 target side and price
   - `bet_quality`: must be `CLEAR_VALUE_SIGNAL` (equal-line price/EV edge) or `FAVOURABLE_LINE_SIGNAL`
     (verified target with a favourable Bet365 line; see
     [MARKET_INTERPRETATION.md](MARKET_INTERPRETATION.md))
   - `line_advantage` (favourable-line signals only): at least `min_line_advantage` points
3. `known_market`, `global_enabled`, `market_enabled`
4. `alert_age`: older than `stale_alert_seconds` → **STALE**
5. `event_not_started`: an event already started → **STALE**. An unconfigured timezone or
   unreadable time → **REJECT** ("cannot prove the event has not started").
6. `valid_price`, `minimum_ev` (not applicable to favourable-line signals, which have no EV),
   `min_price`, `max_price`
7. `stake`, then ACCEPT

The engine runs at ingest and again immediately before dispatch, using the current
configuration and clock. It has no live-site interaction and never dispatches anything.

## Operator action required

OddsNotifier fixture times carry no timezone, so `event_timezone` defaults to null. Until
the operator confirms the feed's timezone and sets it (for example `Europe/London`) in the
Rules & configuration screen, every parsed alert is rejected at `event_not_started`. This
is intentional fail-closed behaviour, not a bug.
