# MultiBot365 — strategy forensics and full system audit

Date: 25 September 2026. Strategy baseline: `e1adaa2f865ae3123fd6680d16fbd2256404c947`.
Strategy correction: `337b748701911a2d65a4ad02cea6e7c572b323a1`.
Independent OCR harness correction: `b94b385b274adaa6f60ed03f2038a1d471d0f962`.

**Conclusion: the old target-selection rule was conceptually wrong. The corrected
backend follows Pinnacle opening-to-current movement first, then assesses Bet365 for
that same side. It is deployed and disarmed. This audit does not establish profitability
or certify the execution system safe to arm. Automatic reboot/login recovery failed.**

The complete frozen corpus ends at **2026-09-25 20:12:37 UTC**. Intake continues after
that boundary under the corrected code; later arrivals are not silently included in
the fixed replay denominator. No final betting action was dispatched by this audit.

## 1. WHAT THE BETTING STRATEGY ACTUALLY IS

Read Pinnacle's opening and current line in the same team perspective. That movement
identifies the candidate. Then read the Bet365 offer for exactly that candidate.
The opposite team's better handicap never changes what side the strategy wants.

For spreads, the displayed line is the HOME team's signed handicap. Subtract opening
from current: negative selects HOME; positive selects AWAY. This works for favourites,
underdogs and crossing zero. For totals, a higher current total selects OVER and a
lower total selects UNDER.

| Pinnacle opening → current | Candidate | Explanation |
|---|---|---|
| HOME -4 → -7 | HOME | Market requires HOME to concede more points |
| HOME -4 → -1 | AWAY | HOME's expected advantage weakened |
| HOME +4 → +1 | HOME | HOME needs fewer points |
| HOME +4 → +7 | AWAY | HOME needs more points |
| HOME -1 → +2 | AWAY | Net movement is +3 despite crossing zero |
| HOME +1 → -2 | HOME | Net movement is -3 despite crossing zero |
| Total 160 → 165 | OVER | Total increased |
| Total 165 → 160 | UNDER | Total decreased |

For Norrkoping–Umea, -22 → -25 selects Norrkoping HOME. Bet365 -27.5 is 2.5 points
worse for HOME: NO BET under the line criterion. Umea +27.5 is not a replacement.
Real intake #1223 now has HOME/-27.5 and UNFAVOURABLE, rather than AWAY/+27.5.

“Sharp movement” is the operator's reference-market convention. These alerts do not
identify the bettors responsible or establish causal sharp money. They also provide
no outcome sample sufficient to demonstrate expected profit.

## 2. HOW ODDSNOTIFIER SHOULD BE READ

The [official setup guide](https://oddsnotifier.io/en/blog/oddsnotifier-setup-guide)
describes a configurable reference-book price-drop feed. Opening is the sharp opening
quote; bracketed prices are prior quotes. Spread lines use HOME perspective; total
prices run OVER, then UNDER. Feed timezone and filters are configurable. Its EV 110%
convention represents a 10% fair-price edge, not a 110% expected profit.

The account's exact provider settings are not available. The guide establishes intended
format, while the raw stored messages determine what was actually received:

| Field | How the system should use it |
|---|---|
| `New odds update on Pinnacle` | Reference-book identification; no substitution of another book |
| Sport / competition / fixture | Identity and protected team markers; never just a search hint |
| Event date/time | Scheduled fixture time, with configured timezone; it is not receipt time |
| Telegram source and received timestamps | Source provenance and age; retain both |
| Current `Spread` / `Totals` | Current Pinnacle line, in the verified perspective |
| `(previous -> current)` | A recent line transition, separately from the opening baseline |
| Pinnacle price pair | Current outcome prices; keep side ordering fixed |
| Parenthesised prices / arrows | Previous prices and local direction; do not select the net candidate |
| `Opening` line and price pair | Opening baseline; prices are preserved independently of lines |
| Bet365 line and prices | Available-offer snapshot, inspected only after candidate selection |
| Highlighted Bet365 price | Owner of the feed's supplied EV, not necessarily the net-movement side |
| Numeric EV | Supplied value for that same outcome at comparable lines; never transferred |
| `EV: None (not equal lines)` | No supplied comparable-line EV; not zero EV and not a fabricated substitute |
| Alternate-line markers | Preserved per bookmaker group; period/market equivalence remains necessary |
| Bet365 event URL | Navigation hint; it does not prove event identity |
| Opening coloured marker | Retained raw; no trading semantics established |

Contradictions and limits were deliberately sought. In the final corpus, **128
highlights oppose net opening movement**, and **105 latest line transitions oppose
the net move**. These are different movement windows, not permission to switch rules.
There are 29 arrows beside unchanged displayed prices across 15 records, but **zero
arrows numerically opposite the parenthetical-to-current direction** in 3,012 checked
price pairs. Rounding or a line reset could explain the unchanged displays; that is
not proven. No change of opening line was observed within a fixture/market group.

Missing highlighting on unequal lines is established feed behaviour. It does not
justify selecting whichever side has a better Bet365 line. The provider's alert
trigger is a configurable drop signal; this account's generation filters cannot be
reconstructed completely from the delivered subset.

## 3. CURRENT CODE — WHAT WAS WRONG

### Conceptual strategy errors corrected

The recent implied-target implementation around `80d8dda`, `a29f413` and `be13bca`
selected the highlighted Bet365 side, or inferred an unhighlighted side from the
favourable Bet365-versus-current-Pinnacle line. Opening movement was only diagnostic.
Tests faithfully asserted this wrong strategy, so their success was not validation.

That reversed causality: the offer decided what to bet. It also treated a highlight
as authoritative even when it described the opposite side from net movement. A
ten-point cross-book favourite-disagreement rule asserted that large sign differences
were perspective errors but smaller ones were genuine lag, without sufficient proof.

The correction removes favourable-side target inference, separates highlighting from
the candidate, binds EV to its supplied side, and quarantines cross-book sign
disagreement without claiming every such record is truly reversed. Pinnacle itself
crossing zero remains valid direction evidence.

### Ordinary software defects and limitations

The OCR benchmark could silently drop every missing batch response through `zip`,
print “BENCH DONE”, and exit successfully with zero results. This was observed during
the locked-phone attempt. It is fixed in a separate commit: every requested frame
must match a returned identity/class, and failures cause nonzero exit.

The remaining final-slip identity, login, tracking and dashboard problems are distinct
from the strategy error. They are described below, not disguised by strategy tests.

### Why the earlier replay had REJECT = 0

The old parser selected a favourable side and imposed its own 1.0-point inference
floor, equal to the saved rules floor. The saved configuration had no price bounds;
unequal-line EV was inapplicable. Many nonqualifying records were removed as AMBIGUOUS
or INVALID before reaching rules. Consequently the retained targets almost necessarily
passed value rules, leaving ACCEPT or timing-based STALE. REJECT was reachable under
stricter configurations; zero observed rejects was not evidence of correct strategy.

## 4. CORRECTED STRATEGY

The [strategy specification](SHARP_MONEY_STRATEGY_SPEC.md) was written before production
changes. It contains pseudocode, 30 real source examples and adversarial cases.

1. Validate the source, grammar, finite odds, fixture, market and quote mapping.
2. Establish a common opening/current Pinnacle perspective and calculate net movement.
3. Select HOME/AWAY or OVER/UNDER solely from that movement. Missing/zero movement,
   unverified moneyline or changed perspective supplies no executable target.
4. Retrieve Bet365's offer for the selected side. Never choose the opponent instead.
5. Spread advantage is selected-side Bet365 handicap minus Pinnacle handicap. OVER
   advantage is Pinnacle total minus Bet365 total; UNDER is the reverse.
6. A worse line is NO BET. At equal lines require better same-side price and numeric
   supplied EV bound to that same side, above 100 and any configured floor.
7. A better unequal line is an unpriced line opportunity. Apply the inherited line
   advantage floor and configured odds limits; EV stays unavailable.
8. Require an explicit minimum Pinnacle movement policy, enabled market, valid age,
   unstarted event, acceptable stake and remaining configured checks.
9. ACCEPT means eligibility only. Identity/session checks, pause, dispatch, final
   action, approval and durable idempotency are still independent controls.

`min_sharp_movement` is nullable and **unset fails closed**. Zero would explicitly
allow any strictly nonzero move; no such setting was silently approved. The saved
1.0-point line-advantage floor was preserved, not portrayed as optimal. Unchanged-line
price-only movement and moneyline remain AMBIGUOUS. No-line/no-price movement is also
conservatively classified AMBIGUOUS by the current parser, rather than NO BET; both
are nonactionable. This conservative label limitation is explicit in the spec.

The rules independently recompute the target and reject obsolete normalized versions.
After restart, three old queued instructions were rejected, with no replay to the phone.
New interpretation/schema versions are `sharp-money-1`/6; classifier `classifier-3-sharp`;
rules `rules-4-sharp`. Operator notifications and dashboard details expose sharp signal,
highlight and EV ownership separately. Historical records preserve their old versions.

## 5. CORPUS RESULTS

### Coverage and method

The main initial snapshot froze all 1,475 intake rows before changes. Four earlier
archive observations not in that table were added. During the audit, 28 more intake
rows arrived; they were frozen during the disarmed service restart and evaluated by
the **archived baseline core**, not by pretending the edited code was OLD.

Final coverage: **1,507 stored records, 1 service notice, 1,506 alert observations**.
All 140 live-corpus and 23 unequal-line fixture records map to these source IDs. Nine
undated reference samples were examined separately rather than double counted or
assigned invented receipt times. There are 182 content-suppressed deliveries with
distinct Telegram message IDs; they are included because their market evidence can
change. Repeated fixture observations are correlated, not independent bets.

OLD and NEW are both evaluated at each original receipt time under the frozen saved
configuration. This avoids declaring the entire historical corpus stale merely because
the replay runs today. Stored lifecycle state is retained separately from replay decision.
An independent raw-field extractor checks direction against production interpretation.

| Raw evidence dimension | Final count |
|---|---:|
| Spread / totals / labelled moneyline / unlabelled | 915 / 342 / 209 / 40 |
| Clear net line direction | 1,188 |
| Zero net line movement | 69 |
| Unsupported/unlabelled mapping | 249 |
| Old target contradicts net direction | 210 |
| Highlight contradicts net direction | 128 |
| Equal / unequal lines among clear candidates | 441 / 747 |
| Equal-line supplied same-side edge | 307 |
| Favourable unequal line, unpriced | 579 |
| Bet365 moved too far on candidate | 72 |
| No proven same-side value | 134 |
| Cross-book orientation requires review | 96 |

The five offer assessments total 1,188. Direction confidence does not imply parsing,
orientation, freshness or policy eligibility. In particular, the **886 apparent offer
opportunities are not 886 acceptable live bets**. With missing movement policy, actual
eligible count is zero. Raw dimensions and parser outcomes are different axes.

| Outcome at receipt | OLD | NEW, saved policy | NEW, research scenario only |
|---|---:|---:|---:|
| ACCEPT | 1,203 | 0 | 868 |
| REJECT for other policy requirements | 0 | 886 | 0 |
| NO BET, persisted as REJECT | 0 | 194 | 194 |
| AMBIGUOUS | 271 | 416 | 416 |
| INVALID | 10 | 10 | 10 |
| STALE as first failing outcome | 22 | 0 | 18 |
| Total | 1,506 | 1,506 | 1,506 |

Operational NEW rules therefore report **REJECT 1,080**, split above into 886 policy
exclusions and 194 NO BET decisions. All checks are recorded, but the first failing
check supplies the headline. Missing movement policy masks 18 later stale checks.
The research column changes only minimum movement to zero (any nonzero move), retaining
the inherited 1.0-point advantage and absent price bounds. **It is unapproved, is not
saved to live configuration, and is not a recommended trading policy.**

**339 selected-side outputs changed: 194 reversed and 145 removed; zero added.**
This differs from the 210 raw-direction contradictions because ambiguous/malformed
cases can lose executable targets rather than simply reverse. Every old side, new
side, source ID, raw hash and reason is in `changed-sides.csv`.

A deterministic stratified review inspected 208 observations: 60 research ACCEPT,
60 AMBIGUOUS, 60 NO BET, all 18 STALE and all 10 INVALID. All 28 later arrivals were
also reviewed, for **236 reviewed records**. Notes are retained in `manual-review.csv`.
This is broad error review across outcomes, not a statistically independent profitability
study or proof of zero interpretation error.

## 6. QUESTIONABLE CASES

Operator judgement is still required for:

- Minimum acceptable Pinnacle movement, including separate spread/total floors if desired.
- Whether a recent reversal should veto the opening-to-current candidate. Current code
  records it and follows the expressly requested opening baseline.
- Whether price-only movement should ever qualify, and its precise window, margin
  treatment and threshold. It currently does not.
- Appropriate decimal-price bounds and whether the inherited 1.0-point advantage is
  actually intended. The audit did not optimise these to increase acceptance.
- Treatment of main versus alternate markets, very large gaps and cross-book favourite
  disagreements. No unsupported conversion or maximum-gap threshold was invented.
- Confirmation that this account's fixture-time timezone is UTC, as saved locally.
- Whether moneyline should be developed at all; present two-way mapping and a price
  strategy are not sufficiently established to enable it.

Alert #1081 is a useful manual check: Norrkoping -22 → -23.5 selects HOME, while
AWAY is highlighted with 107.59% EV. HOME cannot inherit that EV. Alert #21 crosses
from +11.5 → -2.5 toward HOME but Bet365 -5.5 is already worse. Alert #863 supplies
numeric EV across contradictory signed spreads and stays INVALID. These are intentional
counterexamples, not exceptions chosen to improve acceptance.

## 7. FULL SOFTWARE AUDIT

### Intake, parser and rules

Telegram identifiers, raw/formatted text, source/receipt times and edits are stored.
Durable identity and content suppression exist. Content suppression may discard a later
message with changed movement context while an instruction is pending, so all such
records were included in forensics. The parser retains both outcomes, signed lines,
opening/current/prior prices, highlights, EV and event links. Unsupported mapping fails
closed. Side-labelled football samples do not gain eligibility through this change.

Source age uses the earlier of source and receipt. Explicit future-source inconsistency
is not separately rejected, and local event-time conversion does not validate ambiguous
or nonexistent daylight-saving times. The configured feed timezone has not been
independently confirmed. The existing age checks are necessary but not a complete clock
integrity proof. Every failed rule is retained, even when an earlier failure masks its label.

### Identity

Fresh JVM tests cover canonicalisation, aliases, women's markers, youth markers,
opponent mismatch and HOME/AWAY reversal. A wrong event link failed correctly in the
live held-slip proof. The initial feed-name attempt failed ALIAS_REQUIRED rather than
guessing; the later proof used the exact names observed on the bookmaker page and
did not promote aliases.

Remaining static risks: `EventIdentity` collapses II/III/B/reserves/academy/youth into
one reserve marker. It protects senior versus reserve identity but does not distinguish
all reserve variants. Exact/canonical/alias matches can succeed with unknown kickoff;
only known conflicting kickoffs are rejected. General competition/period is not a
mandatory identity dimension. Alias registry keys omit competition, and repeat sightings
can include correlated repetitions rather than independent verified events.

### Android execution and final verification

Direct event navigation, matching names, hold, price verification, stake/return checks,
duplicate rejection, wrong-link failure and impossible signed-line rejection were
exercised without final tapping. The hold probe used a future event and exact bookmaker
names, at £0.10, in MONEYLINE solely to test worker plumbing; it did not enable a
moneyline trading strategy. The first round encountered BUSY from background
reconciliation; the bounded second round passed all ten planned checks.

**Critical static gap:** `Pipeline.place_held_payload` carries selection name, market,
side, line, price and stake but no full fixture/opponent/event/kickoff identity. Android
`Bet365LiveAdapter.place_held` verifies those slip fields without freshly binding them
to the complete approved event. For totals, a generic “Over” on another fixture could
share the same line/price/stake. This is a plausible wrong-event final-action path,
not a bet performed during the audit. Held-slip locking reduces interference but is
not a complete final identity proof. Fix before arming.

### OCR

Fresh hybrid OCR passes 68 stored frames and two aggregate My Bets matches after the
benchmark accounting correction. This is useful bounded regression evidence, not an
unseen-screen accuracy guarantee. Grid scoring checks supplied targets and observed
cells; missing non-target cells are not comprehensively penalised. Expand independent
truth data before treating “100%” as general reliability.

### Session, login, reboot and credentials

The initial session proof authenticated successfully. Two requested reboots were
attempted; immediate SESSION_CHECK failed both times. The second independently
verified changed boot ID, automatic coordinator recovery and durable duplicate rejection,
but its login failed with unclear session markers. Subsequent session/Search attempts
failed with **“No unique username placeholder on the Bet365 login form.”**

Screen inspection found a remembered non-email username. The existing prefilled-account
branch only recognises OCR words containing `@`; a remembered username without `@`
falls through to placeholder lookup. Clearing the visible field did not restore
reliable automated recovery. This is a concrete unresolved login defect, not a
successful reboot/login regression. Search itself was blocked before navigation.

The backend/JVM suites exercise session gates and the bounded session state machine,
including 2FA and challenge states. Overlay handlers were source-reviewed; comprehensive
live overlay recovery was not established. This audit did not provoke live 2FA or bypass any
challenge. A transient authenticated idle probe after the first failed job did not
justify calling the end-to-end recovery successful. A later probe reported LOGGED_OUT;
the final health snapshot says AUTHENTICATING while the worker is IDLE, after repeated
failed recovery attempts. Successful authentication is not established.

Health reports encrypted credentials, using Android Keystore/EncryptedSharedPreferences;
backup is disabled. Source inspection nevertheless finds a legacy plain-preferences
fallback on encryption/migration failure. That fallback should fail closed before
deployment is considered secure across failure modes. No credential values were
included in committed evidence. The diagnostic screen containing the username was
excluded from the audit commit.

### Persistence, crash behaviour and reconciliation

Backend dispatch state is committed before the HTTP request; service restart polls
open work rather than resending it. Phone instruction IDs are durable and have execution
counts. The pre-reboot hold ID returned 409 DUPLICATE after the reboot. Unknown/crash
outcomes reconcile without blind re-tapping. Backend queue/crash/reconciliation and
JVM ledger tests pass; no live crash in the middle of a final betting action was induced.

The kill switch prevents betting dispatch, but background session and My Bets work can
continue. This explains BUSY during the first phone proof. The authenticated phone API
still trusts its caller's execution mode and approval fields; it does not independently
possess the backend's arming policy. Network/token access therefore remains a trust boundary.

My Bets matching succeeds on the two small historical bet examples, but fuzzy name
normalisation and limited scroll coverage require more adversarial tests. Repeated
absence is not proof of non-placement outside the inspected cards. Unknown outcomes
must remain unresolved without a final re-tap.

### Bet tracking

Two pre-existing bets remain OPEN, both Besancon AWAY spreads at £0.10 and 1.83:

| Requested line | Receipt reference | Stored potential return |
|---|---|---:|
| +3.5 | HT5515901931W | £0.10 |
| +1.5 | YT6334352221W | £0.18 |

The first return conflicts with the stored receipt-frame ground truth of £0.18.
No historical money or settlement row was silently changed. No settled return or
realised P&L is established by this audit; absence is not zero profit or a win/loss.

`FinalAction.record_outcome` persists requested line and falls back from receipt odds/
stake to observed/requested values. The schema therefore does not cleanly distinguish
requested, verified pre-tap and actual receipt terms. Those must become separate
provenanced fields before reliable execution-quality or P&L analysis.

### Dashboard and notifications

The dashboard API was tested against the real local store: status and configuration
GETs returned 200; the new nullable movement field is present. Static JavaScript syntax
validation passes. Strategy details now distinguish candidate, net movement, highlight
and feed EV. No operator message was manually sent by the audit.

Remaining issues: service-heartbeat data is displayed without a strict age-derived
liveness verdict, and the label “Dispatch ENABLED (READY-only)” can be misleading when
final action is enabled. Historical decisions are intentionally not rewritten and need
clear version/context labelling. There is no complete requested-versus-actual terms or
realised-P&L view. Current disarmed flags in the API agree with SQLite/settings. A
static/API check is not a claim that every visual lifecycle display is correct.

## 8. TEST RESULTS

| Check | Result and limit |
|---|---|
| Backend baseline, actual project Python | 268/268 PASS |
| Final complete backend suite | **286/286 PASS**, 53.610s |
| Fresh JVM compilation and complete JUnit suite | **88/88 PASS**, 1.267s test execution |
| Identity corpus inside JVM suite | 19 cases: EXACT 5, CANONICAL 2, ALIAS 3, HIGH_CONFIDENCE 2, AMBIGUOUS 1, MISMATCH 6 |
| Historical replay | 1,506 alerts; OLD/NEW results and side changes saved |
| Real strategy fixture set | 30 unchanged raw alerts; direction/value/EV and ambiguity regressions |
| Hybrid OCR, corrected harness | **68/68 frames + 2/2 aggregate matches PASS** |
| Non-final phone regression, second round | **10/10 planned checks PASS**, including expected negative outcomes |
| Reboot coordinator + persistent duplicate ID | PASS on recorded second reboot |
| Immediate reboot SESSION_CHECK | **FAIL on both reboot attempts** |
| Post-reboot session and Search fallback | **FAIL at login gate**; Search success not established |
| Stale instructions, queue/idempotency, reconciliation | Covered by passing backend/JVM suites; no live final action |
| Dashboard API / JavaScript syntax | 200 status/config GETs; syntax PASS |

The default shell Python was the unrelated Hermes environment and lacked Telethon;
the project Python 3.11 interpreter was used for valid backend runs. Gradle JVM execution
was blocked by local dependency/native-loopback setup. All JVM test sources were freshly
compiled with `javac` against cached dependencies and run directly with JUnit, not
merely inferred from old Gradle XML. No new APK was built or installed. Failed first
attempts and logs are retained rather than converted into passes.

## 9. PERFORMANCE

Current hybrid benchmark, milliseconds:

| Class | Samples | Mean | Median |
|---|---:|---:|---:|
| Grid | 14 | 425 | 428 |
| Header | 14 | 316 | 318 |
| Slip | 14 | 395 | 390 |
| Keypad | 14 | 375 | 372 |
| Receipt | 4 | 378 | 384 |
| My Bets frame | 8 | 408 | 370 |
| Aggregate My Bets run | 2 | 1,630 | 1,630 |

Live wall times from the passing hold round: session 14.125s; direct-link hold 11.203s;
final-slip **prepare only** 1.563s; changed-price rejection 8.703s; wrong-link rejection
9.687s; impossible-line rejection 8.718s; resets 1.532–3.563s; My Bets 31.078s.
Recorded reboot through failed session and duplicate check: 81.328s. Later failed login
checks were roughly 9–11s. These are individual observations, not latency percentiles
or guarantees. No final-action timing was measured during this audit.

## 10. REMAINING RISKS

| Severity | Finding | Required consequence |
|---|---|---|
| Critical before arming | Final held slip lacks complete event identity binding | Require verified event/opponent/kickoff/period through prepare and final action |
| High | Strategy movement/value/price policy remains unapproved; unequal-line EV unmodelled | Keep nullable movement gate closed; approve exact policy, not replay acceptance rate |
| High | Reboot/session recovery fails on remembered non-email username | Repair secure same-account field detection; repeat automatic reboot and Search proofs |
| High | Reserve variants, missing kickoff, competition-insensitive aliases can weaken identity | Require distinct protected markers and complete event context |
| High | Legacy plaintext credential fallback | Fail closed on secure-storage failure; test migration failure paths |
| High for accounting | Requested/observed/actual terms mixed; historical return discrepancy | Add provenance and audit repair before P&L or execution-quality claims |
| Medium | Timestamp/DST/account-timezone uncertainty | Validate source-clock anomalies and confirm timezone settings |
| Medium | My Bets fuzzy matching and incomplete scrolling | Expand wrong-card/name/marker/absence corpus; retain unknown outcomes |
| Medium | Dashboard stale heartbeat and READY-only wording | Derive freshness and display actual final-action capability |
| Medium | Phone trusts caller approval/mode; background jobs continue while betting paused | Document/enforce the boundary and coordinate read-only jobs |
| Medium | Small OCR truth corpus; incomplete non-target grid scoring | Expand labelled coverage and strengthen benchmark scoring |

## 11. CURRENT STATE

Evidence snapshot: `evidence/strategy-audit/final-state.json`, captured at **20:25:50 UTC**.
The earlier 20:13:29 post-restart snapshot is also retained. Status/config GETs confirmed
continued listening. New live intake #1526 independently reports `classifier-3-sharp`,
`sharp-money-1` and the `pinnacle_opening_to_current` target source.

- Baseline `e1adaa2`; strategy `337b748`; separate OCR harness fix `b94b385`.
- Backend PID **23108**, restarted with corrected code; Telegram LISTENING, no service error.
- Phone APK **0.9.17-reset**, versionCode **100**, not the approximate 0.9.14 in the brief.
- Phone coordinator healthy, IDLE, no current instruction; hybrid OCR, encrypted credentials.
- Session health **AUTHENTICATING**, worker IDLE, with repeated LOGIN_FAILED outcomes;
  the inspected form and prior probe were logged out. Recovery remains unverified.
- Queue snapshot: **0 active instructions**; COMPLETED 2, PRICE_CHANGED 1, REJECTED 16,
  SESSION_REQUIRED 8, STALE 387, TARGET_NOT_FOUND 15, TIMEOUT 2, UNKNOWN 4.
  Live intake now has 1,526 rows; 23 arrivals after the final frozen corpus boundary
  are processed by the corrected service. Terminal counts can subsequently increase.
- Two existing bets OPEN; no new bet created by the audit. Historical held-slip control
  is marked released; audit slips were reset.
- **dispatch_enabled=false; final_action_enabled=false; final_action_one_shot=false;
  auto_approve=false; paused=true (kill switch ON).** Movement policy remains unset.
- Pre-existing tracked Gradle/build changes and unrelated evidence were preserved.
  Only explicit audited files were staged. No push or multi-phone development occurred.

## 12. RECOMMENDED NEXT STEPS

**MUST FIX before arming:** bind the final slip to complete approved event identity;
agree the movement/advantage/odds policy and confirm timezone; repair remembered-username
recovery and rerun unassisted login/reboot/Search; strengthen protected identity markers
and kickoff/competition requirements; remove insecure credential fallback; separate
receipt facts from requested terms and resolve the historical return discrepancy with
provenanced evidence. Repeat the affected regressions after each fix, remaining disarmed.

**SHOULD IMPROVE:** validate future timestamps and DST edges; make every lifecycle/version
and heartbeat age explicit in the dashboard; coordinate background jobs with diagnostics;
expand wrong-card My Bets and OCR corpora; prevent correlated repeated sightings from
being treated as independent alias evidence; retain selection-content changes despite
deduplication when their movement context is materially different.

**FUTURE:** develop a properly calibrated probability/value model for unequal lines;
evaluate outcomes on independent events with commission/limits/execution/slippage and
selection bias accounted for; consider price-only or moneyline strategies only as
separately specified work. Multi-phone development remains out of scope.

### Evidence and reproduction

All deliverables are under `evidence/strategy-audit/`: compressed immutable old snapshot
and SHA-256 manifest, supplemental and post-cutoff snapshots, reference samples,
`strategy-forensics.csv`, `changed-sides.csv`, `summary.json`, field-consistency checks,
236 manual-review rows, backend/JVM/OCR logs and phone/reboot/Search result JSON.

Reproduce the pure full-corpus comparison from the repository root:

```powershell
& 'C:\Users\WINDOWS11\AppData\Local\Programs\Python\Python311\python.exe' -m tools.strategy_forensics report
```

`report` reads the frozen JSON or compressed equivalent and never starts a Pipeline or
contacts a phone. `snapshot` and `snapshot_tail` refuse to overwrite existing baselines.
Phone proof tools require explicit invocation, verify all three execution flags are
false and the kill switch is on, and contain no final-dispatch test path. The raw local
snapshot is retained unchanged; the committed gzip decompresses to the manifest hash.
