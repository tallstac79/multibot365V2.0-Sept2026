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
QUEUED -> AWAITING_APPROVAL --(/approve, dashboard, CLI)--> APPROVED -> DISPATCHED -> outcome
QUEUED -> APPROVED (auto_approve, within limits)
```

The approval notification says exactly what will be placed and gives the command
`/approve on-xxxxxxx`. Commands are only accepted from the configured chat. Commands that
predate the service, or are more than 5 minutes old, are never acted on. Every command
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

5. **Reset:** the betslip is reset by tapping only Done, Continue, Close or Remove All.

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
3. **Shadow capture** of your manual bets. **Next;** needs you.
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
