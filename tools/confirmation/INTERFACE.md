# Confirmation worker - main bot interface

## Main-bot handoff (agreed with Personal Assistant)

Primary ingest: poll coordinator `GET /instructions/{id}` and `GET /instructions/{id}/evidence`.
On PASS, `result.ready_state` and/or `evidence.ready_state` carry the nested adapter shape
(`fixture_home`/`fixture_away`, `price`, `state=READY`, and related fields). Normalize into the
target schema via `normalize.py` - no file-drop required from main bot; no main-automation changes.
Proven example: instruction `live-ready-1790108608` (commit `9a154c4`), evidence under
`evidence/live-bet365-ready-state/`.

Inbox / CLI ingest remains available for fixtures and offline tests.

Companion package under `tools/confirmation/`. **Confirmation never calls Place Bet / wager submit.** The main bot **must not** submit a wager without an `APPROVED` decision in the outbox.

## Ingest (main bot -> confirmation)

Two equivalent paths:

1. **Drop file:** write READY_STATE JSON into `tools/confirmation/inbox/{instruction_id}.json`
2. **CLI:** from repo root:
   ```bash
   python -m tools.confirmation ingest path/to/ready_state.json
   ```
   Or drain the inbox:
   ```bash
   python -m tools.confirmation ingest
   ```

## Target READY_STATE schema

```json
{
  "instruction_id": "...",
  "device_id": "...",
  "fixture": "...",
  "market": "...",
  "selection_role": "...",
  "selection_name": "...",
  "line": null,
  "current_price": 0.0,
  "minimum_price": 0.0,
  "stake": 0.0,
  "validated_at": "2026-09-22T20:00:00Z",
  "validation_hash": "..."
}
```

`line` may be `null` / omitted / `"NONE"` (treated as no line).

## Normalizer (no main-bot code changes)

The main bot / `Bet365LiveAdapter` today may emit nested shapes, for example:

- `ready_state` or `final_state` with `home` / `away` (or `fixture_home` / `fixture_away`) instead of `fixture`
- `price` instead of `current_price`
- `side` instead of `selection_role` / `selection_name`
- `instruction` / `result` / `evidence` wrappers carrying `instruction_id`, `minimum_price`, `stake`

`tools.confirmation.normalize.normalize_payload` maps these **best-effort** into the target schema. **`instruction_id` is required** - without it ingest returns `STATE_INVALID`.

CLI uses the normalizer by default; pass `--no-normalize` only when the file already matches the target schema.

## Outbox (confirmation -> main bot)

Decision JSON is written to:

```text
tools/confirmation/outbox/{instruction_id}.json
```

Example:

```json
{
  "instruction_id": "abc",
  "status": "APPROVED",
  "reason": "human APPROVE",
  "validation_hash": "...",
  "device_id": "...",
  "decided_at": "2026-09-22T20:01:00Z",
  "payload": { "...": "echo of READY_STATE" }
}
```

### Structured statuses

| Status | Meaning |
| --- | --- |
| `APPROVED` | Human approved; main bot may proceed only if its own gates still pass |
| `REJECTED` | Human rejected |
| `EXPIRED` | Stale beyond max age (default 120s from `validated_at`) |
| `DUPLICATE` | Replay / second approval / already decided |
| `PRICE_INVALID` | `current_price` < `minimum_price` |
| `STATE_INVALID` | Missing/malformed fields or line mismatch |
| `TIMEOUT` | Reserved for future wait-timeouts |
| `INTERNAL_ERROR` | Unexpected worker failure |
| `PENDING` | Awaiting human APPROVE/REJECT (also written to outbox as marker) |

## Human CLI (chat UI later)

```bash
python -m tools.confirmation pending
python -m tools.confirmation approve <instruction_id>
python -m tools.confirmation reject <instruction_id>
python -m tools.confirmation expire
python -m tools.confirmation status
```

`--max-age-seconds` overrides the default 120s stale window.

## Persistence

SQLite under `tools/confirmation/data/confirmation.sqlite3` (gitignored). Separate from the phone coordinator DB. Survives worker restart; no duplicate approvals after reload.


## Derived fields (confirmation-side)

Main bot READY_STATE today may omit device_id, alidated_at, and alidation_hash.
The normalizer fills them without main-bot changes:

- device_id defaults to samsung-R5CT61TE14Z when absent
- alidated_at uses payload 	imestamp when present, else ingest UTC now
- alidation_hash is a SHA-256 prefix of canonical instruction/fixture/market/selection/line/price/stake when absent

## Hard rules

1. Confirmation worker does **not** invoke Place Bet, Confirm, Submit, or any wager action.
2. Main bot must treat absence of `APPROVED` as **do not submit**.
3. Do not share mutable state with Android / coordinator DBs beyond this file contract.
