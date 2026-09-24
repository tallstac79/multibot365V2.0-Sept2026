# Final action (Place Bet)

Code: `core/final_action.py`, `core/bet_matching.py`, `core/telegram_commands.py`,
`core/lifecycle.py`, `core/pipeline.py` (backend); `PlacementClassifier.java`,
`Bet365LiveAdapter.place_bet/read_my_bets`, `MyBetsWorkflow.java`, `ObserveWorkflow.java`
(phone, 0.6.29-final). Tests: `tests/test_final_action.py`, `tests/test_operator_commands.py`,
`tests/test_dashboard_final_action.py`, `app/src/test/.../PlacementClassifierTest.java`.

## Switches (all off by default)

| Setting (`.local/pipeline.json` → `pipeline`) | Default | Meaning |
|---|---|---|
| `dispatch_enabled` | false | Anything is sent to the phone |
| `final_action_enabled` | false | The phone may tap Place Bet (otherwise READY-only) |
| `auto_approve` | false | Approve automatically within limits (otherwise you approve each bet) |
| `approval_timeout_seconds` | 120 | No approval in time means no bet (STALE) |
| `max_stake_per_bet` | "1.00" | Per-bet cap (the phone has its own cap too, prefs `max_stake`, default 1.00) |
| `max_bets_per_day` / `max_daily_stake` / `max_daily_loss` | 5 / "5.00" / "5.00" | UTC day; includes uncertain placements |
| `session_warmup` | true | A stale/unknown session triggers one SESSION_CHECK before dispatch |

Kill switch: Telegram `/stop`, the dashboard "STOP" button, or `python -m tools.pipeline_service pause`.
It cancels pending approvals and blocks all dispatch until `/resume`.

## Flow

```
QUEUED -> DISPATCHED "hold" run (event link -> verify -> bet on slip, £0.10 + To Return verified,
          Place Bet located, NOT tapped, slip KEPT) -> READY -> AWAITING_APPROVAL (Telegram)
       --(/approve)--> APPROVED -> DISPATCHED "PLACE_HELD" as "<id>-place":
          one-frame pre-tap check of the held slip (login, same selection + exact line, approved price
          >= minimum, stake + To Return, one selection, Place Bet) -> ONE tap -> receipt -> reset -> HOME
READY -> APPROVED (auto_approve, within limits)
```

* **Event link first.** The alert's Bet365 link (`comparison_url`, `#/AC/B18/...`) is opened
  directly. The page must verify: sport from the link (B18 basketball, B1 football), both teams from
  the header (explicit aliases only), kick-off in UK time = the alert's UTC time (mismatch = WRONG_EVENT).
  Search is only the fallback (no link, invalid link, teams not verified).
* **Event-link identity is authoritative (A1).** If the link opens a genuine event page and the strict
  team check fails, the run stops at once: `ALIAS_REQUIRED` when the kick-off agrees, one team verified
  and the other name looks like a variant (Soproni KC / Sopron KC; Bet365's names are audited as an
  `ALIAS_CANDIDATE`), otherwise `WRONG_EVENT`. No Search fallback: Search uses the same names. Search
  runs only with no link, or when the link does not open an event page. Bet365's "no longer available /
  betting has closed" page stops as `SUSPENDED` (a dead link shows the same page; a stale feed link has
  never been observed, a closed event has, so the fast stop wins).
* **My Bets never keeps the phone (A2).** Every My Bets read ends with a verified return to Bet365 HOME.
  Live placement work outranks routine checks (claimed-placement verification, settlement); only a
  PLACEMENT_UNKNOWN resolution takes the phone ahead of queued live work.
* **Stake field (A5).** The field is read first: EMPTY (no To Return on the button) is typed into directly;
  FILLED is cleared by its own character count and re-read; UNKNOWN gets a bounded clear and re-read.
  Nothing is typed into an unverified field; the exact stake + To Return readback is unchanged.
* **Timings (A4).** Each instruction records `queue_wait_ms`, `device_started_at`, `device_execution_ms`
  (summed over its phone runs) and `terminal_at`, with `device_stage` / `failure_reason` for refusals.
* **Held slip.** Nothing is rebuilt after approval: if the held slip changed or disappeared the
  pre-tap check fails closed (e.g. PRICE_CHANGED, LINE_CHANGED) and the slip is cleared. While a bet
  is held the phone does nothing else (no other alerts, no My Bets checks). Expiry, rejection, pause
  or a pre-tap refusal sends RESET_BETSLIP (removes it by its own X).
* **OCR re-reads.** A slip check that fails on one frame is re-read (targeted price box, then the
  enhanced per-word OCR), max 3 frames; one frame must pass every check.
* Alert age for the post-approval recheck is measured from the phone verification (`ready_at`).

`final_action_one_shot: true` is supervised arming. The first result of a Place Bet run
switches dispatch and final action off (in memory and in `.local/pipeline.json`) and engages
the kill switch; it doesn't matter whether the bet was placed, refused, failed before the tap
or ended PLACEMENT_UNKNOWN. My Bets verification and settlement keep running.

The approval notification says exactly what will be placed and gives the command
`/approve on-xxxxxxx`. A command is obeyed only if it comes from the configured group chat
AND from an operator user ID in `notifications.allowed_user_ids` (currently only the group
creator). Other group members, other chats and anonymous-admin posts are audited
(`UNAUTHORISED_COMMAND`) and ignored. With no operator configured, every command is refused.
Commands that predate the service, or are more than 5 minutes old, are never acted on. Every command
goes through the same checks: approval window, limits and kill switch.

On the phone (execution_mode `dispatch` + confirmation `APPROVED`), the normal READY path
runs first: fixture, market, line, price, stake and betslip verification. Then:

1. **Guards:** the betslip must be a single selection (else `BETSLIP_NOT_SINGLE`). The
   price must be at or above the minimum, and the stake must be visible.
2. **Record intent:** the placement intent is written to disk before the gesture. Any
   failure from that point on is reported as "the tap may have happened".
3. **Tap:** one Place Bet tap, never repeated.
4. **Classify:** up to five screens over about 12 s are classified:

| Outcome | Canonical state |
|---|---|
| PLACED (receipt: bet ref, stake, to-return) | COMPLETED |
| PRICE_CHANGED / LINE_CHANGED (odds-change prompt is never accepted) | PRICE_CHANGED |
| STAKE_LIMITED | STAKE_LIMITED |
| INSUFFICIENT_FUNDS | INSUFFICIENT_FUNDS |
| SUSPENDED | SUSPENDED |
| SESSION_EXPIRED | SESSION_REQUIRED |
| REJECTED | REJECTED |
| anything unclear | PLACEMENT_UNKNOWN (not terminal) |

5. **Reset:** the receipt banner is closed by its X (right of "Share"; never "Reuse
   Selections"). A selection left on the slip is removed by its own X. Otherwise only Done,
   Continue, Close or Remove All are tapped. READY/prepare runs also remove their selection,
   so the next run is still a single. `RESET_BETSLIP` does the same on demand, on the current
   screen.

Real receipt (calibrated 2026-09-24): green banner "Bet Placed" + "Bet Ref BT…", then the
selection, then a "Stake / To Return" row. OCR splits the reference and mangles amounts
("£O.1 0"); the reference is informational, since My Bets identifies the bet by fixture,
selection and stake.

### Stake entry (after a real incident)

In a READY proof the keypad OCR'd as one line and the old code guessed key positions,
typing £8,718 instead of £0.10. Nothing was placed (READY never taps). Now:

* key positions come only from OCR'd digit words on a validated 3×4 grid, with no guessing;
* the field is cleared first. The typed stake must read back before Done: the stake digits AND
  "To Return" = stake × price. If not, the field is erased and the run fails;
* the same strict check runs after Done, at READY, before preparing and just before the tap.
  If OCR drops the stake box, only an exact return at price ≥ 1.10 is accepted, since it
  uniquely fixes the stake. A "Place Bet visible" screen is never evidence of the stake.

### Basketball Game Lines

`GameLinesParser` reads the Spread / Total / Money Line grid from word positions. Rows are
found by the team labels (exact, or the team's letters in order when OCR fragments them).
Several captures must agree on a cell. A spread sign is only inferred from the opposite
row, and the betslip must re-show the exact signed line (or Over/Under + line) in large
text before READY.

## Knowing the outcome: My Bets reconciliation

After every tap, the backend verifies the claimed outcome in My Bets (read-only `MY_BETS`
instruction):

| Claimed | My Bets | Result |
|---|---|---|
| PLACED receipt | found | bet OPEN, verified |
| PLACED receipt | missing after 3 checks | DISCREPANCY alert |
| refused (funds, price, ...) | missing | NOT_PLACED, verified |
| refused | found | DISCREPANCY alert |
| PLACEMENT_UNKNOWN | found | COMPLETED |
| PLACEMENT_UNKNOWN | missing twice | NOT_PLACED |
| PLACEMENT_UNKNOWN | unreadable 3 times | UNKNOWN + MANUAL CHECK REQUIRED alert |

A lost device result, a pipeline timeout or a malformed result after a final-action
dispatch also becomes PLACEMENT_UNKNOWN. **Nothing is ever re-tapped.**

Settlement: every 30 minutes, while bets are open, My Bets → Settled is read. WON, LOST,
VOID, CASHED_OUT and the returns are stored, count towards the daily loss limit, and are
notified.

Matching (`core/bet_matching.py`) needs the fixture (a distinguishing word for each team),
the selection (side plus signed line) and the stake inside one card-sized window. Odds may
be decimal or fractional. Anything weaker is not a match.

## Calibration from real screens (shadow capture)

The outcome phrases and My Bets layout are calibrated from real screens:

```powershell
python -m tools.shadow_capture --minutes 5 --label manual-bet-1
```

Place one or more small bets by hand while it records. It only screenshots and OCRs,
never touches the phone. Frames are saved to `evidence/shadow-capture/…`, then turned into
classifier and matcher test cases.

## Proof ladder

1. **Offline:** the backend and phone unit tests above. **Done.**
2. **Read-only live:** OBSERVE and MY_BETS on the phone. **Done** (`evidence/final-action-0629`).
3. **Shadow capture** of your manual bets. **Done** (receipt + My Bets calibrated).
3b. **Watched betslip proof, basketball spread/totals (READY, 0.6.41):** **Done**. Covered
   Hapoel v Bayern spread ±8.0 and O/U 173.5, and Zvezda v Zalgiris -2.5 and O 168.5. Each run
   ended READY with £0.10 verified and the slip cleared (`evidence/betslip-proof-0631`).
4. **Zero-balance live tap:** with final action enabled, one approved alert. Expected
   INSUFFICIENT_FUNDS, reset, then verified absent in My Bets. You arm and approve it.
5. **First real placement:** £0.10, approved by you. Receipt, My Bets verification,
   notification.
6. **Settlement observed:** later.

## Other safety rules

* Bet365 security checks (Cloudflare) are only waited on passively. An interactive or
  persistent check stops with `BOT_CHECK` and needs you.
* An idle phone's session report comes from a real on-screen check every 60 s. A header
  "Log In" means logged out, even when OCR merges it into a longer line.
