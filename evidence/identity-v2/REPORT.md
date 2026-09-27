# Identity v2 offline replay

Completed against a frozen operational snapshot taken **2026-09-27 11:21:23 UTC**.
No production caller, settings change, dispatch, approval, final action, new phone
workflow, strategy, staking or slippage change is included.

## Results

All **46 direct-link terminal failures** in the frozen operational snapshot were
replayed. The before verdict is the recorded historical device result. Different
records came from different APK versions; these are not a rerun of a single old build.

| Recorded failure | Confirmed name variant | Snapshot conflict | Ambiguous | Needs recheck | Total |
|---|---:|---:|---:|---:|---:|
| ALIAS_REQUIRED | 15 | 12 | 2 | 0 | 29 |
| TARGET_NOT_FOUND | 0 | 6 | 0 | 0 | 6 |
| WRONG_EVENT | 4 | 1 | 1 | 5 | 11 |
| Total | **19** | **19** | **3** | **5** | **46** |

The 19 snapshot conflicts are mismatching captured line/price snapshots without
an independently observed earlier matching quote. They are **not 19 proven wrong
fixtures**. The comparison remains unresolved, and the requested/captured terms
are retained. None of the six TARGET_NOT_FOUND records was inflated into a
recovered identity false negative.

An additional **108 deduplicated archived failure records** were replayed in a
separate `archive` cohort: **16 CONFLICT, 86 AMBIGUOUS, 6 NEEDS_RECHECK**. This cohort
contains old diagnostic probes, search cases, deliberately wrong inputs and
incomplete saved results, so it is not counted as real-feed recovery evidence.
Fifteen explicit historical kickoff discrepancies and one reversed pairing remain
conflicts. This demonstrates preservation of contradictory input evidence; it
does not assert that every historical timezone probe represented a wrong fixture.
No incomplete archived record was confirmed. Two malformed/empty archive files
could not be parsed and are listed in `archive-inventory.json`.

`replay.csv` contains **154 rows** with source IDs, both team pairs, URL provenance,
kickoff, sport, competition, fingerprint, each protected dimension, both name
comparisons, OCR/review provenance, old verdict and new offline verdict/reason.
`results.json` retains the complete input/output evidence. Unknown fields remain
unknown, including destination event-ID read-back and numerical OCR confidence.

## Recovered historical cases

| Feed pairing | Captured naming evidence | Recovered records |
|---|---|---:|
| Atletico Boca Juniors / Tigers | Boca Juniors / RSSB Tigers; matching full-game total 184.5 and both prices 1.83 | 2 |
| LKS Lodz / Sparta Ziebice | LKS KK Lodz (W) / Sparta Ziebice (W); independently matching women's competition | 7 |
| KS Basket 25 II Bydgoszcz / Energa Torun II | KS Basket 25 **II** Bydgoszcz (W) / Katarzynki II **Torun (W)** | 3 |
| Suwon KT Sonicboom / Goyang Skygunners | Compatible club/sponsor/token splits with complete context | 2 |
| Phantoms Boom / Liege Panthers | Phantoms Boom (W) / Liege (W); Div/Division normalisation | 3 |
| Explosivas de Moca / Leonas De Ponce | Competition supplies omitted women's marker | 1 |
| AB Castello / Benicarlo | Club-prefix variation with complete context | 1 |

There are **no new permanent aliases**. Specifically, Tigers/RSSB Tigers is an
event-context comparison, not a global identity mapping.

The three Bydgoszcz screenshots were independently inspected at original resolution.
They visibly say **II**, not a proven first team. The wrapped away header supplies
`Torun`, which the previous single-line extraction lost. The original readings and
reviewed readings coexist in the inputs. Removing the independent Roman review
changes these cases to NEEDS_RECHECK in the regression tests. The first two saved
grids show +4.5 at 1.83; the later grid shows +3.0 at 1.83, with the actual earlier
capture providing movement evidence. No execution tolerance is used to explain it.

## Remaining unresolved operational records

- **Three AMBIGUOUS:** Orchies/Lyon versus Orchies/LYONSO lacks a supported club
  relationship; Samsung Thunders/Seoul Thunders has only a generic shared nickname;
  one Suwon/Goyang capture lacks event time/competition context.
- **Five NEEDS_RECHECK:** UBI Graz/ZKD Ilirija records lack adequate competition,
  gender and name context in the captured header. Another record for this pairing
  also has a fingerprint conflict.
- **Nineteen snapshot CONFLICT:** saved requested/captured terms differ without
  qualifying chronological corroboration. These include all six TARGET_NOT_FOUND
  cases, four Utsunomiya records, six Botas/Mersin records, Rytas/Boca,
  Burgos/Baskonia and one Graz/Ilirija record. Full values are in the CSV/JSON.

## Validation

**50 unittest tests passed:** 33 pure resolver tests, 12 frozen replay tests and
5 existing identity-registry tests using temporary databases and a fake gateway.
The corpus test executes **21 controlled cases**: two positive controls plus
19 adversarial negatives. Every expected verdict matched; no negative was confirmed.

Negative cases include wrong kickoff/opponent/event ID, reversed pairing, explicit
men/women, U19/U21, independently proven first/second squad and first/reserve,
OCR-sensitive I/II, generic shared nickname, wrong numbered division, competing
events, generic/search URLs, missing evidence, wrong period and incompatible quotes.
Additional tests cover alias scope, missing markers, DST gaps/folds, visual-review
image hashes, no input mutation and chronological same-event movement evidence.

The unchanged Java grid parser compiled and ran against stored OCR files through
the offline wrapper. The wrapper supplies spatial reading order; it does not edit
OCR text or change the production parser. No Android build/install or live phone
proof was performed in this offline task.

## Files and future integration

- `tools/offline_event_identity.py`: pure evidence resolver.
- `tools/identity_v2_replay.py`: offline extraction, archive inventory and replay CSV.
- `tools/identity_v2_grid/IdentityV2Grid.java`: stored-word adapter for existing parser.
- `tests/test_offline_event_identity.py`, `tests/test_identity_v2_replay.py`: new tests.
- `docs/OFFLINE_EVENT_IDENTITY_V2.md`: design, schema, commands, limitations and exact
  proposed integration boundary.
- `evidence/identity-v2/`: frozen records, original captures, visual reviews, replay
  and adversarial evidence.

The proposed later boundary is `Bet365LiveAdapter.verifyDirectEvent`, immediately
around the existing `EventIdentity.resolveVerified` call, after gathering a complete
same-screen evidence bundle. It is documented for a later reviewed integration.
The current `id.accepted()` admission branch and the stricter search route remain
untouched. This commit improves offline identity diagnosis; it does not deploy new
production admission behaviour.
