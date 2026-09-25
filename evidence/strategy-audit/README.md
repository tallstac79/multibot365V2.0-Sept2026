# Strategy audit evidence — 25 September 2026

Read `../../docs/STRATEGY_FORENSICS_FULL_SYSTEM_AUDIT.md` for the complete 12-part report.

The replay boundary is 20:12:37 UTC. `baseline.json.gz` preserves the initial frozen
1,475-row database snapshot and old outputs; the SHA-256 manifest verifies its original
uncompressed bytes. The large uncompressed original remains local. Four nonoverlapping
earlier observations are in `supplemental-baseline.json`; 28 later rows and OLD outputs
from archived e1adaa2 core are in `postcutoff-baseline.json`. The combined dataset has
1,507 records: 1,506 alerts and one service notice, including 182 distinct-message-ID
content suppressions. Undated samples are separately preserved and classified.

Primary tables: `strategy-forensics.csv`, `changed-sides.csv`, `manual-review.csv`.
Summary counts: `summary.json`; field checks: `field-consistency.json`.
Initial/subset figures in intermediate logs are superseded by this final full replay.

Reproduce with `python -m tools.strategy_forensics report`. It only reads frozen files
and runs pure parser/rules evaluation. It does not ingest, notify, queue or dispatch.
Both snapshot commands refuse overwrites. No live threshold was changed; diagnostic
zero-minimum-movement results are explicitly unapproved counterfactuals.

`backend-final.txt`: 286 passing tests. `jvm-direct.txt`: freshly compiled 88 passing
JVM tests (Gradle invocation failed; its log is retained). `ocr-hybrid-verified.*`:
68 frames plus two aggregate matches using the corrected missing-result harness.
Earlier OCR/test attempts are retained to expose failures and changed assumptions.

`phone/run-1790366148`: 10/10 successful expected hold/prepare/negative checks.
Initial phone results outside that run show the alias and BUSY failures.
`reboot/run-1790366610`: changed boot ID, coordinator recovery and durable duplicate
rejection, but SESSION_CHECK failed. `reboot.txt` preserves the first failed attempt.
`search/`: post-reboot session/Search failures; the attempted visible-field assistance
did not turn this into a successful automatic recovery. No final betting tap occurred.

`post-restart-state.json` and `final-state.json` distinguish observed state at different
times. Intake remains live, so the latter includes post-corpus arrivals. Credentials
and the diagnostic screen containing the remembered username are excluded from Git.
Compiled classes and machine-specific 68KB classpath argument files remain local.
