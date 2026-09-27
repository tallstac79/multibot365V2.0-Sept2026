# Offline event identity v2

This component compares saved event records. It has **no production caller** and
does not change Android admission, execution settings, strategy, staking, quote
tolerances, dispatch, approval, OCR, or final actions. No APK was built or installed.

## Root cause

The historical resolver combined separate protected attributes into a flat set;
missing gender and an OCR-damaged Roman numeral could therefore produce a misleading
`[ii] vs [women]` contradiction. Historical builds also required an exact team as
an anchor when both bookmaker names varied. The current Java resolver has more event
context than those builds, but still performs the flat protected-marker rejection
before it can use a complete market fingerprint.

Header extraction also lost wrapped text. In the actual Bydgoszcz capture the away
name continues onto `Torun (W)` and the home name visibly contains **II**. The
stored OCR reads `I|`/`||`. These are extraction errors, not proof of different
gender or a first-team fixture. Three original screenshots were inspected at full
resolution; SHA-256-bound visual reviews are separate from the absent OCR scores.

Competition prefixes, governing-body prefixes and `Div`/`Division` should be
canonicalised. An unknown translated league name is insufficient to claim a
different competition. It remains unresolved without a scoped mapping or other
independent league evidence.

## Contract and evidence

`tools.offline_event_identity.resolve(alert, page, *, kickoff_tolerance_seconds=120,
aliases=(), competition_mappings=())` returns a verdict, per-field evidence,
conflicts, recheck requests and missing fields. It never mutates the inputs or
promotes aliases. Inputs are dictionaries, usable in unit tests without infrastructure.

Both records provide sport, competition, timezone-aware kickoff, home/away and
`market_fingerprint`. The alert supplies `event_id` and optionally `event_url` and
country. The page supplies page type, prematch status, orientation, competitor
count/scope, capture timestamp and evidence provenance. A team may be a string or
`{name, source, confidence, dimensions, reread}`. Missing evidence is unknown.

The direct-link anchor is either an independently observed destination event ID,
or a recorded navigation to the requested event followed by a captured unique
event page. These have different provenance in the output. A copied URL alone is
insufficient. Generic/home/search URLs cannot borrow an event ID. The old captures
preserved the requested navigation URL, **not a destination-ID read-back**. Page
sport extracted from that URL is explicitly correlated evidence, not a second
independent observation. The captured page's header/time/competition/grid supply
the independent corroboration. A single direct event page is the competitor scope;
the replay does not claim to have searched every simultaneous fixture.

Confirmation requires all of the anchor, prematch page, kickoff, sport, competition,
fingerprint, orientation and compatible names, with no protected conflict or
competing candidate. Kickoff tolerance is an identity comparison setting, not an
operating-window or stale-alert setting. Naive timestamps remain unknown.

Names use Unicode/diacritic normalisation, club affixes, token containment, token
splits, initials, distinctive shared tokens and existing approved scoped aliases.
No edit-distance threshold was lowered. Generic nicknames contribute little; a
shared `Tigers` cannot connect `Tokyo Tigers` to `RSSB Tigers`. Containment such as
`Tigers` to `RSSB Tigers` requires the complete event evidence. Completely unrelated
nickname strings need an independently evidenced relationship scoped to this
one event. No new `Tigers = RSSB Tigers` alias exists.

Gender, age group, squad tier, reserve and academy are separate dimensions.
Absence means unknown, not male or first team. A compatible women's competition
can supply missing gender. Explicit opposite gender, U19/U21, independently
confirmed I/II, or explicit first-team/reserve contradictions remain conflicts.
An OCR-only decisive Roman discrepancy requests a reread. A numeric score alone
does not convert the original OCR into independent corroboration. A reread must
have its own provenance; visual reviews preserve null numeric confidence.

Fingerprint fields are market, period, selected outcome, signed line and all
available named prices. States are `MATCHES`, `MOVED_PLAUSIBLY`, `CONFLICT` and
`UNAVAILABLE`. Movement requires a prior independently observed matching snapshot
on the same event before the current capture. No slippage allowance is imported.
A differing quote without corroborating history remains a snapshot conflict; this
does **not** establish that the fixture itself is wrong. A matching fingerprint
alone never confirms identity.

Verdicts:

| Verdict | Meaning |
|---|---|
| DIRECT_URL_CONFIRMED | Complete compatible context; both names exact |
| DIRECT_URL_CONFIRMED_NAME_VARIANT | Complete compatible context; canonical, contextual or scoped naming variant |
| NEEDS_RECHECK | Decisive OCR/marker uncertainty or competing/orientation ambiguity |
| AMBIGUOUS | Incomplete anchor/context or unsupported name/league relationship |
| CONFLICT | Explicit contradictory evidence, including incompatible captured snapshot |

Search candidates cannot receive direct-link confirmation without the same
explicit anchor evidence. This component does not implement a new search policy.

## Replay and tests

`evidence/identity-v2/REPORT.md` gives counts and limitations. `replay.csv` includes
the operational cohort and a separately labelled historical archive cohort.
`snapshot.json` preserves the original failure stages/verdicts; `inputs.json`
preserves the reconstructed observations; `results.json` contains every check.
The before column is the actual historical recorded verdict, not a claim to have
rerun every historical APK version. Archive probes are not counted as real intake.

Run from the repository root:

```powershell
python -m tools.identity_v2_replay
python -m unittest tests.test_offline_event_identity tests.test_identity_v2_replay tests.test_identity_registry
```

Optional reconstruction from the saved OCR artifacts (no phone or network):

```powershell
python -m tools.identity_v2_replay --extract --java-home 'C:\Program Files\Microsoft\jdk-17.0.20.101-hotspot'
python -m tools.identity_v2_replay --inventory-archives
```

The Java CLI wrapper uses the unchanged `GameLinesParser.java`. It supplies saved
words in spatial reading order because OCR serialization order can otherwise mix
full-game and later-section headers. Its compiled classes live only under
`.local/identity-v2-java`. Frozen replay needs Python and timezone data, not Java.

## Proposed later integration point — not connected

`Bet365LiveAdapter.verifyDirectEvent(VisualScreen s, String kickoffUtc)` currently
extracts `EventPage.teams(header)` around line 796, calls
`EventIdentity.resolveVerified(...)` around line 806, and rejects on `!id.accepted()`
around line 833. This is the exact boundary for a **future separately reviewed**
port or adapter of the evidence contract. It would first collect the whole wrapped
header, actual URL provenance, kickoff, competition and grid from the same screen;
then emit the new result in shadow diagnostics. Do not replace `id.accepted()` with
these offline verdicts as part of this task. `requireSearchContext` around line
1231 must continue to distinguish search evidence from direct navigation.

Unresolved data needs are explicit destination-ID read-back, independent sport
provenance, enhanced OCR confidence/crops, translated league mappings, and original
quote history for changed markets. These are not silently filled from the alert.
