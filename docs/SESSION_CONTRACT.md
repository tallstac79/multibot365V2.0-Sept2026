# Generic session-state contract (backend ⇄ Android adapter)

Code: `core/session_contract.py`. Storage: `session_state` (latest per device) and
`session_history` (each change) in `.local/pipeline.sqlite3`. The backend never drives
a login UI. It only consumes what the device reports.

## States

| State | Meaning (reported by the phone) |
|---|---|
| UNKNOWN | The adapter cannot currently determine the session |
| LOGGED_OUT | The site shows a logged-out session |
| AUTHENTICATING | A login is in progress (manual or adapter-driven) |
| AUTHENTICATED | Logged in and usable. The legacy `LOGGED_IN` value from the proven adapter is accepted as an alias. |
| EXPIRED | The session timed out or was invalidated |
| RESTRICTED | Logged in, but the account is limited or blocked for the action |
| ERROR | The adapter hit an error while determining the session |

## Backend behaviour (fail closed)

The dispatcher reads the latest stored report immediately before each dispatch.

* It proceeds **only** for `AUTHENTICATED` observed within `session_max_age_seconds`
  (default 120 s).
* Anything else ends the instruction as terminal `SESSION_REQUIRED`, with the reason
  stored. That includes any other state, no report at all, a stale report, a timestamp
  more than 30 s in the future, or a malformed stored row.
* A malformed report is not stored as state. It is audited as `MALFORMED_SESSION_REPORT`,
  so the previous state stands and ages out.
* An older observation arriving late never overwrites a newer one.
* A device result stage `LOGIN_FAILED` or `SESSION_REQUIRED` also maps to
  `SESSION_REQUIRED`.

## Wire format the Android adapter must implement (REMAINING_GROK_CONTRACT)

### 1. `GET /health` gains a `session` object (required)

```json
{
  "healthy": true,
  "state": "IDLE",
  "current_instruction": null,
  "device_id": "galaxy-a13-5g",
  "session": {
    "state": "AUTHENTICATED",
    "observed_at_ms": 1790160000000,
    "detail": "header balance visible"
  }
}
```

* `state` must be exactly one of the seven values above. Upper case is preferred;
  `LOGGED_IN` is accepted.
* `observed_at_ms` is the epoch time in milliseconds of the **last actual on-screen check**,
  not the time of the health request. Alternatively, send `observed_at` as ISO-8601 with a
  timezone.
* Refresh it at least every 60 s while idle, because the backend treats reports older than
  120 s as stale.
* Report `UNKNOWN` rather than repeating an old value when the check cannot run (for
  example, screen locked).
* `detail` is optional free text, at most 500 characters, and must contain no
  credentials.
* Include `device_id` (stable, for example `galaxy-a13-5g`) so the backend stops showing
  the Tailscale node ID fallback.

### 2. Instruction results carry the session they observed (recommended)

Keep the existing `ready_state.session` field. The backend records it on the instruction
as `session_state`.

### 3. Instruction request fields the adapter receives

```json
{"instruction_id": "on-…", "action": "ADAPTER_WORKFLOW", "adapter": "live_bet365", "scenario": "live",
 "query": "Rytas Vilnius", "sport": "basketball", "market": "SPREAD", "side": "HOME", "line": "-18.5",
 "minimum_price": "1.83", "stake": "1.00", "timeout_ms": 120000, "execution_mode": "ready"}
```

* `market` is one of `1X2`, `MONEYLINE`, `SPREAD`, `TOTALS`. `side` is one of `HOME`,
  `DRAW`, `AWAY`, `OVER`, `UNDER`. `line` is the signed Bet365 target line, or null for
  1X2/Moneyline.
* The adapter **must** return `INVALID_INSTRUCTION` for any market, side or line
  combination it cannot verify. The backend maps that to REJECTED and never retries it.
* A result must contain `instruction_id`, `status` (PASS or FAIL) and `stage`. It should
  also contain `detail`, `selection.price` (the observed price), `ready_state.state`, and
  `wager_submitted` or `final_state.wager_submitted`. `evidence` is an optional list of
  relative evidence paths.
* Existing failure stages are mapped as listed in
  [INSTRUCTION_LIFECYCLE.md](INSTRUCTION_LIFECYCLE.md). New failure stages are accepted and
  map to UNKNOWN until they are added to the mapping.

## Not implemented here (by design)

Bet365-specific login detection and UI interaction, OCR of the account header, and any
final action. Until the phone reports a `session` object, every dispatch attempt safely
ends as `SESSION_REQUIRED`.
