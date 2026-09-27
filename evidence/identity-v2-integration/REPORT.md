# Identity v2 integration into the production direct-link path (APK 0.9.27-ops)

Integrated 27 Sep 2026 on top of Codex's offline resolver (commit 2f37095). The phone's `EventIdentity` remains the
production resolver: it is the only component that sees the screen. The offline Python resolver stays offline and is
the acceptance baseline. Strategy, staking, slippage, automatic approval and unrelated execution behaviour are unchanged.

## What changed (smallest robust integration)

| Change | Why (V2 finding) |
|---|---|
| `EventHeader.header(words)` + `EventPage.decide(...)`: one pure header extraction and one identity decision used by the live adapter, the stored-capture replay and the on-device bench | the replay must run the production call path |
| Competition labels: `Div`/`N.div` = `Division`; same words in another order after the country prefix (`same_words_reordered`) | LKS Lodz ("Liga 1 Women" / "Poland 1 Liga Women"), Phantoms ("Division 1 Women" / "Belgium Div 1 Women") |
| Wrapped team title: a short continuation line is joined to the away name | Bydgoszcz "... vs Katarzynki II" / "Torun (W)", Explosivas "(W)", Berck "13" |
| OCR glyph runs with `|` in a team name become `UNREADTIER`; a lone `I` against a feed II/III, or `UNREADTIER`, gives `NEEDS_RECHECK` (never accepted) | the flat `[ii] vs [women]` rejection; "I|"/"||" are extraction errors, not evidence |
| One enhanced reread (live Tesseract `recognizeLines`) patches only the numeral at the same place (`EventPage.patchNumeral`, counted in strokes); everything else keeps the first read | V2's "independent enhanced crop reread of the header tier; preserve both readings" |
| `shared_core` token evidence: a distinctive non-nickname token matched in full with unexplained words on both sides (sponsor/prefix swap); event-scoped, never an alias, only next to a sure opponent | AB Castello / Amics Castello, Energa Torun II / Katarzynki II Torun (W) |
| A name identical apart from the competition-supplied marker counts as a sure team for pairing | KS Basket 25 II Bydgoszcz / ... (W) with Torun shared core |

Not ported, by decision: the market fingerprint is not an identity gate on the phone. Production judges the quote after
identity against the original alert (net payout 10 %, line caps) at READ_SELECTION and again before the tap; making
the quote an identity condition would change slippage behaviour. All 19 V2 snapshot conflicts are rejected by that
quote gate (table below), so none can execute.

## Production-path replay of the 46 operational failures

`EventIdentityV2ReplayTest` (JVM, stored OCR words -> EventHeader -> EventPage.decide) and the same frames re-OCR'd and
decided ON THE PHONE (`OCR_BENCH` class `identity`, engine hybrid, reread with the live routine; `device-replay.json`).
Both agree case by case.

| | before (0.9.26, same path) | after (0.9.27) |
|---|---:|---:|
| accepted identity | 16 | **30** (27 first read + 3 after the device reread) |
| AMBIGUOUS | 21 | 10 |
| MISMATCH | 9 | 6 |
| NEEDS_RECHECK after reread | - | 0 |

Against the V2 baseline (0 violations):

* V2 confirmed 19: production accepts all 19 (16 on the first read; the 3 Bydgoszcz frames after the phone's enhanced
  reread read the numeral as "ll", two strokes, as the first engine's "I|"/"||"). V2 itself confirmed those 3 only with a
  human visual review; on OCR alone V2 says NEEDS_RECHECK, which production also returns before the reread.
* V2 AMBIGUOUS 3: Orchies/LYONSO and Samsung/Seoul Thunders stay AMBIGUOUS. on-25d0bcd6 (Suwon/Goyang) is accepted: the
  stored screenshot shows "Club Friendlies • 27 Sep 06:00" at y=168, which V2's extraction dropped (checked on the PNG).
* V2 NEEDS_RECHECK 5 (UBI Graz / ZKD Ilirija): production MISMATCH. OCR read "lirija (W)" (leading I and ZKD lost) and
  the feed has no country for "Adriatic League 2 Women". Fails closed; not recovered.
* V2 CONFLICT 19 (all market-snapshot only): identity accepted for 10 (all already accepted by 0.9.26), not for 9
  (Poitiers/Denain "Championnat Pro B"/"Ligue B" and Botas "Super League Women"/"TKBSL Women" are translated labels
  without an approved mapping; Graz as above). The quote gate rejects all 19:

| Case | Market | Alert | Page | Quote gate |
|---|---|---|---|---|
| Saga / Hiroshima | TOTALS OVER | 166 @2.00 | 164.5 @1.83 | reject (floor 1.90) |
| Boras / Nassjo | SPREAD AWAY | +14 @2.10 | +14.5 @1.83 | reject (floor 1.99) |
| Rytas / Boca | TOTALS OVER | 167.5 @1.83 | 171.5 @1.80 | reject (line 4.0) |
| Seoul Knights / Wonju | SPREAD AWAY | -5.5 @1.83 | -7.5 @1.83 | reject (line 2.0) |
| Utsunomiya / Yokohama x4 | SPREAD / ML AWAY | +8 @2.22 ... 4.75 | +10.5 @1.74 ... 4.20 | reject (price) |
| Burgos / Baskonia | TOTALS OVER | 184 @2.30 | 182.5 @1.83 | reject (floor 2.17) |
| Elfic / GC Zurich | TOTALS OVER | 144.5 @1.83 | 147.5 @1.80 | reject (line 3.0) |
| others (9) | | | | reject (identity already not accepted) |

## Adversarial corpus

`EventIdentityV2AdversarialTest` runs Codex's 21 controlled cases on the production decision: both positive controls
accept; every negative is rejected (wrong kick-off, wrong opponent, reversed pairing, men/women, U19/U21, first/second
squad, OCR squad uncertainty = NEEDS_RECHECK, reserves, generic nickname, different numbered division, search candidate).
URL/search/period/quote negatives are owned by their production guards (EventPage.validUrl, no header teams on a search
page, FULL_GAME context, ExecutionTolerance) and are asserted there. Destination event-ID read-back and a competing-event
count are not observable on the phone (the same data needs V2 lists).

## Live non-final proofs on 0.9.27-ops (27 Sep 2026, `live/`)

| Fixture | Pattern | Result |
|---|---|---|
| Phantoms Boom v Liege Panthers (Belgium Div 1 Women) | the historical ALIAS_REQUIRED x3 case; Div/Division; nickname containment | HOLD PASS, HIGH_CONFIDENCE, held, reset |
| Pantery Lancut v MUKS Poznan (Poland 1 Liga Women) | LKS-style reordered league words, women's marker | HOLD PASS, HIGH_CONFIDENCE, held, reset |
| Besa Biel/Bienne v Yverdon Sport II | canonical names | identity CANONICAL; BELOW_MINIMUM on price |
| Final Spor Genclik v Fenerbahce II | page "Fenerbahce Gelisim" (development team) | MISMATCH (protected marker), fails closed |
| Viktoria Plzen v Slovacko (1. Liga Women vs Czechia Division 1 Women) | translated league | AMBIGUOUS, fails closed |
| Billericay v Chatham (National League Cup Women vs England FA ...) | governing-body word "FA" not mapped | AMBIGUOUS, fails closed |

Bydgoszcz-style numeral: proved on the device with the three real frames (`reread-bench/`, `device-replay.json`); no
current fixture showed a numeral glyph during the proof window.
