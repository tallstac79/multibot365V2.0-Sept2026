# Continuous Telegram / OddsNotifier ingestion

Code: `core/telegram_intake.py` (listener), `core/pipeline.py` (`Pipeline.ingest`),
`core/alert_classifier.py` (classification), `tools/pipeline_service.py` (service).

## Setup (one time, on the mini PC)

1. Create an API ID/hash at https://my.telegram.org for the Telegram **user** account that
   is already a member of the OddsNotifier feeds (bots cannot read other people's channels).
2. Create the untracked `.local/pipeline.json`:

```json
{
  "pipeline": {"device_id": "galaxy-a13-5g", "dispatch_enabled": false},
  "telegram_intake": {
    "api_id": 1234567,
    "api_hash": "FROM_MY_TELEGRAM_ORG",
    "session": ".local/telegram/oddsnotifier",
    "chats": [-1001475314653],
    "backfill_on_first_start": 0,
    "reconcile_seconds": 30,
    "reconcile_limit": 50
  },
  "notifications": {"enabled": false, "bot_token": "", "chat_id": ""}
}
```

   `chats` are Telegram marked peer IDs. Feed 2 in the browser URL `#1475314653` is the
   channel `-1001475314653`. `telegram-login` prints each chat's title so you can check them.
3. Log in once, typing the phone number and login code yourself:

```powershell
python -m tools.pipeline_service telegram-login
```

   The session file is stored under `.local/telegram/`, which is untracked. Treat it like a
   password.
4. Start the service:

```powershell
python -m tools.pipeline_service run
```

   To resume after a mini-PC restart, create a Task Scheduler task with the trigger "At log
   on" and the action `python -m tools.pipeline_service run`, started in this directory.
   Nothing is installed automatically.

## What is stored for every message

Every message delivered from a configured chat becomes exactly one row in
`intake_messages` in `.local/pipeline.sqlite3`. Nothing is dropped silently, and parser
exceptions become `INVALID`.

| Field | Meaning |
|---|---|
| `chat_id`, `message_id` | Telegram identity (marked chat ID, message ID) |
| `raw_text` | The plain text exactly as Telegram delivered it |
| `entities` | All Telegram formatting entities as JSON (bold, text_url, underline, ...) |
| `formatted_text` | `**bold**` and `[text](url)` rebuilt from the entities using UTF-16 offsets. This is the form the production parser was verified against, and it round-trips all four genuine snapshot messages exactly. |
| `source_timestamp` | Telegram message date (UTC) |
| `received_at` | Local receipt time (UTC) |
| `status` | `PARSED`, `AMBIGUOUS`, `INVALID`, `DUPLICATE` or `IGNORED` |
| `reason` | Why it got that status |
| `instruction_id` | Deterministic: `on-` + sha256(origin, chat, message)[:24]. Assigned for `PARSED` rows only. |
| `delivery` | `event`, `catch_up`, `reconcile` or `backfill` |
| `parser_profile`, `parser_version`, `normalized` | The parser output, unaltered |

## Status rules (parser hardening)

| Status | When |
|---|---|
| PARSED | Basketball Totals/Spread (`oddsnotifier_basketball_v1`, production-verified) with exactly one bold Bet365 target |
| AMBIGUOUS | A recognised alert whose target is not bold, or a sport/market with no production-verified ordering (all football, basketball Moneyline). The reason starts with `UNSUPPORTED_MAPPING` where applicable. |
| INVALID | The alert header is present but the body is malformed or uses an unsupported layout (for example several bold targets, line transitions, `EV: None`) |
| DUPLICATE | Repeated live delivery of a stored message, or a different message for a selection that is already pending, dispatched or completed |
| IGNORED | Not an OddsNotifier alert, media-only or empty, or an edit of an already-processed message |

No selection is ever guessed. Regression tests cover all four genuine Feed 2 messages, the
genuine pasted fixtures (no bold, so AMBIGUOUS), the genuine football Spread and linked-ML
samples (AMBIGUOUS), and malformed, unrelated and empty input.

## Reliability

* **Reconnects:** Telethon auto-reconnects. The outer loop also rebuilds the client with
  capped exponential backoff (1 s up to 60 s) after any failure: network, authorization,
  flood-wait or storage.
* **Restart / resume:** on start, every message after the highest stored message ID is
  fetched (`catch_up`). On the very first start there is no history, so only a mark is
  recorded (`intake_checkpoint`). Older history is never back-processed unless
  `backfill_on_first_start` is set.
* **Missed events:** every `reconcile_seconds`, the latest `reconcile_limit` messages are
  compared with the store. Any message above the first-start mark that is not yet stored
  is ingested (`reconcile`).
* **Duplicate delivery:** the unique index `(origin, chat_id, message_id, edit_key)`
  enforces the identity. A repeated live delivery is recorded as `DUPLICATE` and linked
  with `duplicate_of`. History scans skip known messages without adding rows. Concurrent
  deliveries of the same message are tested and create one instruction.
* **Edits:** an edited message is recorded (`IGNORED`) and never executed. If the original
  instruction had not yet been dispatched, it is ended as `STALE` with reason `SUPERSEDED`.
* **Stale protection:** see [RULES_ENGINE.md](RULES_ENGINE.md). Checks run at ingest and
  again immediately before dispatch.

## Replay and inspection

```powershell
python -m tools.pipeline_service replay tests/fixtures/oddsnotifier_basketball_rytas_real.txt --message-id 1
python -m tools.pipeline_service status
```

Replays are stored with origin `sample` and appear only in the dashboard's SAMPLE DATA mode.

## Live status

**Live on DESKTOP-IVUNJ9J:** Telethon user session authorized; listening to OddsNotifier Feed 2 via username `oddsnotifierfeed2bot` (peer `1475314653`; the Web hash `#1475314653` is **not** channel-form `-1001475314653`). `render_oddsnotifier` keeps production Markdown (links + Bet365 `**price**` only).
reconnect paths are covered by deterministic tests with a fake Telegram client. Running it
against the real feed needs the one-time `telegram-login` above, which requires the
account owner's phone code.

