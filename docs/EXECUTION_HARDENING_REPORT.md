# Execution hardening after the strategy audit

This implements the audit's MUST FIX and SHOULD IMPROVE recommendations, with the
operator's subsequent corrections to movement qualification and execution policy.
The original forensic audit and its snapshots remain historical records. No final
betting action was dispatched during this work. No multi-phone development or new
probability/value model was added.

## Strategy and operator policy

The configured OddsNotifier feed qualifies the signal upstream. A genuine nonzero
Pinnacle opening-to-current movement determines the candidate side; MultiBot then
compares only that side at Bet365. An unset optional `min_sharp_movement` no longer
rejects that signal. Zero, invalid and directionally ambiguous signals still stop.

Execution now has two explicit per-market limits: maximum decimal odds
deterioration and maximum line deterioration versus the alert. Improvements cost
zero tolerance. The worker checks the original requested terms again immediately
before a possible tap, avoiding cumulative deterioration across intermediate reads.
Missing limits reject. Existing configured alert-price/EV/value policy is preserved;
no new global price bounds were chosen.

Six complete historical alert/live observations support only a small comparison:
zero odds/line deterioration retains five and rejects one; 0.01 through 0.10 odds
deterioration retain the same five. All observed lines were unchanged. The rejected
spread quote fell from 2.15 to 1.83. Zero limits are recommended for approval, but
remain **unset**. This is not a representative profitability or full-corpus estimate.

Saved `event_timezone="UTC"` remains provisional, with
`feed_timezone_verified=false`. Timing uncertainty affects conversion, event-start
eligibility and time handling, never the strategy side or offer comparison. Execution
eligibility fails closed pending account confirmation. Aware Telegram/receipt
timestamps retain their offsets. DST gaps/folds and future source clocks reject.
Every newly ingested alert whose candidate start verdicts differ emits a durable
warning. The retrospective list contains 258 such alerts, 171 of which change the
otherwise-verified overall decision.

The exact portal setting, supporting UTC/London examples, consequences and tolerance
retention table are in [Feed time and execution policy](FEED_TIME_AND_EXECUTION_POLICY.md).
After the operator confirms the account setting, change only its configuration and
rerun timestamp/stale/event-start checks; no strategy reinterpretation is required.

## Software changes and practical effect

| Area | Implemented behavior |
|---|---|
| Final action | Only `PLACE_HELD` can dispatch; it must consume its own durable successful hold through the canonical `-place` ID within 120 seconds. Approved teams, competition, kickoff, period, selection and terms are bound to that hold. |
| Fresh slip | Both teams and the full-game market must be inside the slip. Its current selection line/price are read from its own row. Fresh kickoff, competition, future start, stake and return must also pass. Background fixture or price text cannot authorize a bet. |
| Phone permission | Final taps also require a locally enabled one-hour permission on the phone. It expires across reboot. The permission remained off throughout these checks. |
| Login | Recognizes an exact remembered non-email account. Otherwise clears its observed control, verifies the empty placeholder and enters the configured account anew. Password entry requires a fresh Chrome password editor. The blur tap stays inside the modal; the observed Chrome password-save bubble is dismissed without saving. A bounded post-login wait requires actual account-header evidence. |
| Credentials | Keystore creation, migration write/readback or legacy cleanup failure makes credentials unavailable. There is no plaintext operational fallback. |
| Identity | Production requires known matching kickoff and competition, plus protected women/age/reserve markers. II, III, B, academy and youth remain distinct. Search receives the same strict event checks as a direct link. |
| Aliases | Scoped to sport and competition. Promotion requires two different corroborated events; repeated deliveries of one event do not count twice. Legacy unscoped aliases are not consumed. Conflicting promoted candidates enter review. |
| Diagnostics | A bounded authenticated diagnostics lease blocks final actions and suppresses self-heal, warmup, reset and My Bets background jobs; existing instruction results may still be polled. |
| Dedupe | Same selection/price with changed movement context is retained and supersedes pending work. Already executed/device-owned selections remain protected from repeated execution. |
| Tracking | Requested, pre-tap observed and receipt-confirmed terms occupy separate columns. Receipt facts are never populated by requested-term fallback. Dashboard displays their provenance. |
| Reconciliation | Stake, selection and both teams must be on a bounded card in one frame. Missing opponent or incomplete account coverage remains unknown; repeated partial reads do not prove absence. |
| Dashboard | Service heartbeat age, rules/parser versions, provisional timezone and phone permission are explicit. A stale service heartbeat cannot display Telegram/dispatch status as current. |
| OCR scoring | Missing any labelled grid cell fails the benchmark, including cells outside the requested target. Existing batch-integrity checks preserve failed/missing frames in the denominator. |

## Historical accounting repair

The original image for `HT5515901931W` visibly shows £0.10 stake, odds 1.83,
Val de Seine +3.5 and £0.18 To Return. Its stored potential return was corrected
from £0.10 to £0.18, with SHA-256 provenance, an audit record and a private SQLite
backup. Actual receipt terms are populated from that image. The bet remains OPEN;
no settlement or realized return was invented. The idempotent repair tool refuses
to run unless execution is disarmed and the original evidence hash agrees.

## Validation and deployment

Validation details and final live state are recorded in
`evidence/execution-hardening/verification-summary.json`.

- Backend: 301 tests passed, including identity, queue/idempotency, reconciliation,
  real-feed strategy and time-boundary tests.
- Android: 102 JVM tests passed; debug APK 0.9.18-hardened, version code 101 built.
- Dashboard JavaScript syntax and scoped Git whitespace checks passed.
- Live phone: 10/10 disarmed checks passed (session, hold, prepare, duplicate,
  changed held event/price, wrong link, excessive line deterioration and cleanup).
  Reboot run: 5/5 passed (new boot, coordinator recovery/local permission off,
  persisted duplicate rejection, unassisted session recovery, Search hold and cleanup,
  with boot/coordinator/permission counted together). No final tap occurred.
- Hybrid OCR: 67/68 individual frames and 2/2 My Bets aggregates passed. Breakdown:
  grid 13/14; header 14/14; slip 14/14; keypad 14/14; receipt 4/4; My Bets 8/8.
  The failed Hapoel/Bayern grid frame read both moneylines but omitted four labelled
  spread/total cells because decimal prices were unreadable (some OCR tokens were
  `183`). It failed closed. The denominator and ground truth were not weakened.
  Full results, including the failure, are preserved in `ocr-hybrid.json`.

Phone proof outcomes are recorded separately, including unsuccessful attempts that
exposed the actual remembered-account, placeholder, focus and header-wait issues.
Only hold/prepare/reset/session/Search and read-only diagnostics were used. No
`execution_mode=dispatch` or Place Bet tap was sent by the audit tools.

At the final recorded check (25 September 2026, 22:08 UTC), backend PID 20264 was
LISTENING with a fresh heartbeat and no service error; dashboard PID 21752 served
version 2.0-dashboard.4. The phone was IDLE and AUTHENTICATED on APK 0.9.18-hardened
(101), with encrypted credentials. The diagnostics lease had ended. There were no
active betting instructions and two historical OPEN bets. Dispatch, final action,
one-shot execution and auto-approval were false; the kill switch was on and local
phone permission was off. The saved feed timezone remained UTC/unverified, and all
execution deterioration limits remained null.

Measured wall times in the successful proofs were 61.7 seconds for session recovery
after reboot, 12.9 seconds for the direct-link hold, 2.0 seconds for pre-tap prepare,
and 46.5 seconds for the Search hold. These are individual observations, not latency
percentiles or guarantees. OCR class mean times ranged from 329 to 456 ms per frame.

## Remaining operational limits

Account timezone confirmation and explicit tolerance selection are still required
before eligibility can pass. Existing line-advantage/EV rules are execution policy,
not a calibrated probability model. The six live quote pairs cannot justify wider
tolerances. Unreadable OCR, unknown event context, incomplete My Bets coverage and
ambiguous aliases remain reasons to stop or request manual review. 2FA and interactive
security challenges require the operator; this work does not bypass them.

The stricter OCR benchmark is not perfect and must not be reported as 100%. Fresh
phone proofs demonstrate their particular fixture/screens and cannot establish
universal bookmaker-layout coverage. Betting remains deliberately disarmed.
