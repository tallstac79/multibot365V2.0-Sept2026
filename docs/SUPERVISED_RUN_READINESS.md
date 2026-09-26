# Supervised run prepared after the MONEYLINE audit

26 September 2026. **Prepared, not armed. No wager was placed during this ML audit.**
The exact timestamped state is in
[`supervised-run-readiness.json`](../evidence/moneyline-audit/supervised-run-readiness.json).

## Installed and running

- Backend: `classifier-4-moneyline`, `rules-7-moneyline`; Telegram intake connected.
- Dashboard restarted with the ML opening/current price display.
- Phone: `0.9.20-moneyline`, version 103; healthy, authenticated, IDLE, hybrid OCR.
- Fresh session-only phone check: PASS / SESSION_AUTHENTICATED, 6.493 seconds.
- No device-owned instruction, pending approval, owned slip or PLACEMENT_UNKNOWN.
- Two pre-existing OPEN bets remain for normal reconciliation; no additional bet.
- Dispatch, final action, final-action one-shot and auto-approval remain false;
  the kill switch remains ON and the phone final-action switch remains false.

The backend may receive new tips while paused. They are retained and age out under
the existing stale policy; they are not an authorization to dispatch. The prepared
run starts from fresh post-start arrivals, with no pre-run queue carried into it.

## Configuration preserved

The saved rules are byte-for-byte equivalent as parsed JSON to the audit baseline.
Basketball SPREAD, TOTALS and MONEYLINE are all enabled.

| Policy | Current value |
|---|---|
| Event timezone | UTC; `feed_timezone_verified = true` |
| Upstream signal | Valid feed-qualified alert with genuine nonzero Pinnacle movement |
| Separate minimum movement | Unset; no additional ML movement threshold |
| All three markets: maximum net-payout deterioration | 10%; minimum live decimal odds = `ceil_to_cent(1 + (alert_odds - 1) × 0.90)` |
| Basketball spread deterioration | Both caps: 1.0 point AND 10% of absolute original alert handicap |
| Basketball totals deterioration | 1.0 point, one practical full-point market step |
| Basketball moneyline handicap | Inapplicable; no line or line allowance required |
| Improvements | Acceptable; identity, price and other checks still apply |
| Original reference | Qualifying alert; never an intermediate observation |
| Staleness | 300 seconds, plus event-start and dispatch checks |
| Default stake | £0.10 |
| Existing execution caps | £1 per bet; 5 bets / £5 staked / £5 loss per UTC day |
| Approval | Manual, existing 120-second window |

These are execution allowances, not claims of optimal betting value. Pinnacle
selects HOME/AWAY for ML; only that same Bet365 outcome can qualify. An opposing
highlight cannot change the selected side or supply its EV.

## Prepared operating sequence

1. On an explicit operator start, verify the installed versions, fresh session,
   empty device/approval state and absence of unresolved placement. Expire the
   pre-run queue and accept only new production alerts after the start time.
2. Enable one-shot execution with manual approval and all three basketball markets
   still enabled. This audit has not applied those activation switches.
3. For the first qualifying opportunity, verify event, selected side and fresh
   grid/slip terms against the original alert. Record every comparison and any
   rejection. A failed quote never changes the target to the opponent.
4. Present the verified £0.10 slip for approval. Recheck fresh terms immediately
   before the single final action; do not place outside the original tolerance.
5. After one final-action outcome, disarm automatically and reconcile the receipt
   and My Bets. An uncertain outcome is reconciled without repeating the tap.

This is one supervised run accepting opportunities from all three markets, with
at most one final action; it does not schedule three wagers.

## Validation and limits

The full 1,879-record frozen replay includes 319 real ML observations. It yields
292 historically eligible ML records, 22 same-side value rejections, 3 unresolved
directions and 2 stale records. Every non-ML classification and rules decision
matches the pre-ML commit, excluding version labels.

The full backend suite passed **325 tests**; Android passed **109 JVM tests** and
built the installed APK. The **15 ML tests** also passed against the final corpus
supplement. Test logs and APK SHA-256 are in `evidence/moneyline-audit/`.

Real feed fixtures prove interpretation; explicit mutations test absent boundary
cases and fresh-price tolerances. The new phone proof is session-only. This audit
does not claim a newly placed ML bet or a new live ML market-selection test.
See [the ML audit](MONEYLINE_AUDIT.md) for ordering evidence, exact feed examples,
opposing highlights, uncertainty and historical-versus-live limits.
