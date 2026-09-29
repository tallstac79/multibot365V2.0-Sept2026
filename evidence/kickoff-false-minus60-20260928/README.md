# False -60 minute kick-off mismatch (28 Sep 2026 BST)

## Incidents
- **Zetech Sparks FC (W) v Kenya Police Bullets (W)** (`on-d3678571`, `on-81633228`) ~11:57 / 11:59 BST.
  Alert UK `28 Sep 13:00` from `kickoff_utc=2026-09-28T12:00`. Page read `28 Sep 12:00`.
  Same event `E201873691` at 12:29 BST read `28 Sep 13:00` and placed (`on-b14751ca`, receipt line
  `Kenya League Women 28 Sep 13:00`).
- **Fomento Los Hornos v Napoli Argentino** (`on-0904d518`, `on-b807a521`) ~19:54 / 19:59 BST.
  Alert UK `28 Sep 21:00` from `kickoff_utc=2026-09-28T20:00`. Page read `28 Sep 20:00`.

## Root cause
The alert path converts stored UTC to Europe/London display via `EventPage.ukDisplay` (BST = UTC+1 in September).
The page kick-off string from header OCR was the **UTC wall-clock** of the same instant. Comparison treated that
as a hard -60 minute mismatch and refused the alert's own Bet365 event link (`event_id_match=true`).

Frames were not on the PC; reconstructed from `result_payload` / `execution_stages` in
`analysis/betswifty-2026-09-28/db-snapshots/pipeline.sqlite3` and the speed-gap report.

## Fix (phone identity path, 0.9.45-ops)
`EventIdentity.kickoffMatch`: when the two UK-format strings are the same day/month, UK is on BST, and the
delta is exactly -60 minutes (page behind), treat as `same_instant_utc_display` (agree). Winter GMT still rejects a real
60-minute difference. Strategy / tolerances / minimum-price rules unchanged.

Regression: `KickoffFalseMinus60Test`.

## Build note
Deployed phone build **0.9.40** (commit a8c9801) does **not** include this fix. Source is on
`claude/final-action` as 0.9.45-ops (versionCode 128). A new APK build + install is required before the
phone worker stops false-refusing this class.
