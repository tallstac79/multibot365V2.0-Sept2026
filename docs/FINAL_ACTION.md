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
| `approval_mode` | "manual" | `manual`: you approve each device-verified slip (`/approve`); `automatic`: the backend approves it itself when every policy check passes, see [AUTOMATIC_APPROVAL.md](AUTOMATIC_APPROVAL.md) (`auto_approve: true` is the legacy spelling) |
| `expected_worker_id` / `expected_account_fingerprint` | "" | Automatic mode only: must equal the phone's health `worker_id` / `account_fingerprint`; unset refuses every automatic approval |
| `approval_timeout_seconds` | 120 | Manual mode: no approval in time means no bet (STALE) |
| `hold_max_age_seconds` | 115 | A verified hold older than this is never consumed by a final action |
| `max_stake_per_bet` | "1.00" | Per-bet cap (the phone has its own cap too, prefs `max_stake`, default 1.00) |
| `max_bets_per_day` / `max_daily_stake` / `max_daily_loss` | 5 / "5.00" / "5.00" | UTC day; includes uncertain placements |
| `session_warmup` | true | A stale/unknown session triggers one SESSION_CHECK before dispatch |

Kill switch: Telegram `/stop`, the dashboard "STOP" button, or `python -m tools.pipeline_service pause`.
It cancels pending approvals and blocks all dispatch until `/resume`.

Phone-side permission (0.9.22, `LocalExecution`): the phone taps Place Bet only while its persistent local execution
permission is enabled. It is enabled and disabled only on the phone's settings screen, survives app, Chrome and phone
restarts, is revoked automatically when the worker id or the account fingerprint it was granted for changes, and has
no HTTP setter. It never bypasses any verification, limit or backend switch; `/health` reports it as `local_execution`.

Home readiness (0.9.22): `open_home` waits state-driven (1 s polls, up to 30 s, one re-open at 10 s) until Bet365
chrome, a login wall, a cookie wall, the splash or a Chrome prompt is on screen, instead of a fixed 2.8 s. A cold
Chrome after a phone reboot no longer produces "Live Bet365 homepage not visible" from an empty frame.

## Flow

```
QUEUED -> DISPATCHED "hold" run (event link -> verify -> bet on slip, £0.10 + To Return verified,
          Place Bet located, NOT tapped, slip KEPT) -> READY -> AWAITING_APPROVAL (Telegram)
       --(/approve)--> APPROVED -> DISPATCHED "PLACE_HELD" as "<id>-place":
          one-frame pre-tap check of the held slip (login, same selection + exact line, approved price
          >= minimum, stake + To Return, one selection, Place Bet) -> ONE tap -> receipt -> reset -> HOME
READY -> APPROVED by automatic-policy (approval_mode automatic: every check in FinalAction.automatic_checks
         passed; audit AUTO_APPROVED) -> the same PLACE_HELD fresh pre-tap verification -> ONE tap
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
* **Event identity resolver (B).** `EventIdentity` (phone, pure Java) identifies the EVENT: sport, both
  teams, their pairing and the kick-off, anchored on the alert's own Bet365 link. Team layers: EXACT (NFKC,
  case, whitespace) > CANONICAL (diacritics, punctuation, slash/hyphen, safe affixes FC/BC/KC/AC ...) >
  ALIAS (explicit registry `TeamAliases`, or aliases supplied with the instruction) > VARIANT (controlled
  fuzzy score, one signal only). Protected markers (women, reserves/II/B, U21 ...) must agree — with one
  competition-aware exception (2026-09-25): when the backend has established the competition as women's
  (`competition_women` on the wire, from `core/competition_gender.py`), a Bet365 name carrying only the
  women's marker the feed name lacks ("Explosivas de Moca (W)") is compared without it, capped at VARIANT, so
  the event still needs its own link, an agreeing kick-off and the other team at ALIAS or better; markers are
  never stripped globally and the reverse case (feed has (W), page has not) stays a mismatch — or the team is
  a MISMATCH. Verdicts: EXACT / CANONICAL_MATCH / ALIAS_MATCH / HIGH_CONFIDENCE_EVENT_MATCH / AMBIGUOUS
  (-> ALIAS_REQUIRED) / MISMATCH (sport, kick-off, markers, club-family prefix, wrong opponent, reversed
  home/away -> WRONG_EVENT). Reversed pairings are never accepted: a HOME/AWAY selection would land on the
  other team.
  **Event-level evidence (0.9.25-ops, 2026-09-27).** The VARIANT layer is deterministic token evidence
  (`EventIdentity.compareTokens`): every distinctive token of the shorter name must be explained by the longer
  one - same token, plural, split ("Skygunners" / "Sky Gunners"), initials ("TA" / "Tel Aviv"), abbreviation
  ("JLM" / "Jerusalem"), inflected stem ("Soproni" / "Sopron") - or the whole single-token names agree letter
  for letter (>= 0.80). Descriptor words (basket, club, de ...) carry nothing; a club-family prefix present on
  one side only is ignorable ("Atletico Boca Juniors" / "Boca Juniors") but two different ones are two clubs
  (Real / Atletico Madrid, Hapoel / Maccabi Tel Aviv, United / City). A shared nickname next to an unexplained
  token ("Samsung Thunders" / "Seoul Thunders") or a bare prefix ("Lyon" / "LYONSO") is WEAK: AMBIGUOUS,
  never accepted, never a wrong event. HIGH_CONFIDENCE_EVENT_MATCH needs the alert's own event link, an
  agreeing kick-off (exact or within 5 minutes), agreeing markers, a decidable HOME/AWAY orientation (the
  crossed pairing must not also read plausibly) and either one team ALIAS-or-better with the other a strong
  VARIANT, or BOTH teams with deterministic token evidence ("Atletico Boca Juniors v Tigers" against
  "Boca Juniors v RSSB Tigers"). `resolveVerified` still requires a known kick-off and a deterministic
  competition match (equal, country-prefixed, governing-body-prefixed "FIBA ...", or an approved mapping:
  Poland 1 liga, Korea KBL Cup -> Club Friendlies, Japan B League -> B League 1). Every result carries an
  evidence log (`identity.evidence` in the run record: event_id_match, sport_match, competition_match,
  kickoff_match, home/away similarity with level/kind/score, protected_markers, orientation, competing_event,
  policy). A nickname contained in a longer bookmaker name ("Tigers" in "RSSB Tigers") is event-scoped
  evidence and is never proposed as an alias candidate (`Side.aliasSafe`), so no broad alias such as
  Tigers = RSSB Tigers can arise from it; the specific-to-shorter direction ("Rytas Vilnius" -> "Rytas") may
  still be proposed to the competition-scoped registry. Corpus: `identity_corpus.txt` (40 cases, live +
  constructed lookalikes; evidence/identity-corpus/).
* **Alias registry and event cache (B6/B7, backend `core/identity_registry.py`).** Candidates from the
  phone are recorded with evidence (`alias_candidates`). Promotion is strict and audited: "deterministic"
  (score >= 0.85 with full event corroboration) on first sight, "high" after 2 sightings, anything else
  stays for review; a conflicting bookmaker name demotes. Promoted aliases and the names Bet365 used for
  the same fixture and kick-off (`event_cache`, never another kick-off, 36 h after it) travel with each
  instruction as `aliases`.
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

Waits on this path are state-driven (0.8.8-stake): instead of fixed sleeps, the phone
re-captures (250–300 ms apart, bounded) until the state the next check needs is visibly
present — the betslip, the OCR-located keypad, the typed stake reading back — and the
existing `require()` on that frame still decides. The betslip readback after Done and the
pre-tap check re-read a slip that is still rendering with a plain second frame; the third
read is Tesseract's enhanced pass (a different engine). Evidence PNGs are encoded after
the OCR result is handed on, and the single Place Bet tap waits for every pending evidence
write before the gesture. `tools/stake_profile.py` prints the per-step timings of a run.

### Basketball Game Lines

`GameLinesParser` reads the Spread / Total / Money Line grid from word positions. Rows are
found by the team labels (exact, or the team's letters in order when OCR fragments them).
Several captures must agree on a cell. A spread sign is only inferred from the opposite
row, and the betslip must re-show the exact signed line (or Over/Under + line) in large
text before READY.

### OCR engines (Milestone C)

The phone has two on-device OCR engines behind one flag (`ocr_engine`, pref on the phone,
`/health` reports it; debug builds accept `POST /config/ocr_engine {"engine": ...}`):

* `legacy` — Tesseract (tess-two), the engine of every placement so far;
* `fast` — ML Kit Latin text recognition, model bundled in the APK (no network, no download),
  word boxes in the same shape every parser already uses;
* `hybrid` (default since 0.8.5-c5) — `fast` for every pre-tap read including the Game Lines
  grid; Tesseract kept for numeric region reads (price/amount crops with a numeric alphabet),
  for the enhanced second-opinion re-read after a failed readback, and to re-read the
  receipt's "Bet Ref" line after the tap (the fast reading is kept; a disagreement is flagged as
  `bet_reference_disputed` with both readings recorded as `bet_reference_fast` /
  `bet_reference_legacy`, never silently resolved). A fast-engine exception never fails a run:
  that frame falls back to Tesseract and `/health` shows `fast_ocr_error`.

The parsers and every check are engine-independent and unchanged. `OCR_BENCH` (an action that
never touches the screen) runs a named engine over stored frames and the same parsers; the
A/B on 68 real frames (`evidence/ocr-bench/`) is what chose the policy:

| class | legacy | fast |
|---|---|---|
| Game Lines grid | 13/14, 5.2 s (one wrong price on a keyboard-clipped frame) | 14/14, 0.48 s |
| event header | 14/14, 2.1 s | 14/14, 0.36 s |
| betslip readback | 10/14, 2.6 s (`+3.5`→`+315`, `1.83`→`183`, all fail-closed) | 14/14, 0.40 s, stake box digits read |
| stake keypad | 14/14, 3.2 s | 14/14, 0.40 s |
| receipt | 3/4, 2.3 s (read `YT6334352221W` as `W6334352221W`: the reference reported for the second live placement was wrong) | 4/4, 0.36 s |
| My Bets | 2/2 runs, 10.1 s | 2/2 runs, 1.5 s |

Rollback is one call (`legacy`, persisted) or the one-line default in `CoordinatorConfig`.

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
