# OddsNotifier offline observation parser

Parses saved alerts to descriptive JSON. No network, coordinator, recommendation
or execution hooks. The legacy Telegram listener, Android and database are unchanged.

## Samples and supported grammar

`tests/fixtures/oddsnotifier_manifest.json` records the user-reported provenance:
two user-reported real alerts (football Spread and linked football ML), plus five
synthetic examples modelled on the first layout.
Synthetic tests demonstrate grammar handling, not exact production formatting.

Supported labels are exactly `ML`, `Spread (line)` and `Total (line)`.
Football ML requires three prices and normalizes to `1X2`; basketball ML requires
two and normalizes to `MONEYLINE`. Spread and Total require two, normalizing to
`SPREAD` and `TOTALS`. In the labeled layout, the same count is required in current, opening and comparison
rows. The linked-layout opening exception is documented below. Pinnacle rows may have parenthesized values for every price or none.
Mixed rows, incomplete alerts, unrecognized labels and inconsistent market headers
are rejected. There is no generic-parser fallback. One call accepts one alert;
concatenated alerts fail closed rather than sharing metadata accidentally.

## Explicit quote ordering

Default output preserves numbered quote positions without assigning sides.
An optional `synthetic_order_v1` profile applies the following TEST ASSUMPTIONS
uniformly to Pinnacle, opening and comparison rows:

| Sport | Market | Positions in order |
| --- | --- | --- |
| Football | 1X2 | HOME, DRAW, AWAY |
| Basketball | MONEYLINE | HOME, AWAY |
| Either | SPREAD | HOME, AWAY |
| Either | TOTALS | OVER, UNDER |

Every output records the chosen profile, sides by position and
`production_verified: false`. Even the real Spread sample does not establish
quote-side ordering. Unknown profiles fail; no profile is auto-selected based on
sport, prices or EV. A side label annotates a quote, never selects a target.
Target side, target line and alert price stay null. Spread lines are not inverted
or attached to a side; the signed displayed line is preserved per price group.

Fixture `home` and `away` reflect first and second team in the supplied `vs` row.
The fixture date remains local with unknown timezone, separate from Telegram time.
Parenthesized price meanings are unspecified. EV is copied as displayed percent,
not recalculated or interpreted as a choice. Decimal strings retain precision.

## Usage

```powershell
python tools/parse_oddsnotifier.py tests/fixtures/oddsnotifier_spread.txt --sample-provenance user_reported_real
python tools/parse_oddsnotifier.py tests/fixtures/oddsnotifier_football_ml.txt --sample-provenance synthetic --ordering-profile synthetic_order_v1
python -m unittest discover -s tests -p test_oddsnotifier_parser.py -v
```

`--sample-provenance` defaults to `unspecified`; it records caller-supplied metadata,
not provenance detected or verified by the parser. Optional `--channel-id`,
`--message-id` and `--source-timestamp` must be supplied together. IDs are numeric
strings; the timestamp includes a timezone. A stable observation ID hashes source,
channel and message ID, remaining unchanged for message edits. It is not persistent
duplicate suppression. Missing Telegram metadata stays null for pasted examples.

Schema version 3 additionally records format variant, source links, market-label
source, per-group mapping and opening-count consistency. Unrelated text returns IGNORED. Malformed/unsupported recognized alerts
return INVALID_ALERT (CLI exit 2). Additional real examples are still required for the synthetic formats or any
verified side profile.

## Observed linked football ML format

The real Banks O´Dee / Aberdeen B sample has ten nonempty lines, no standalone
market heading, and `market=ML` in an Oddshub football URL. That explicit URL
parameter supplies the market label; no market is inferred from price size.
The linked layout is supported only for this observed football ML structure.
The fixture and Bet365 source URLs are preserved without fetching them. Bare
parenthesized HTTPS URLs and the supplied Markdown URL form are accepted;
conflicting display/destination links, unsupported hosts, duplicate/missing market
parameters and sport conflicts are rejected.

Unicode team punctuation is retained. Up/down arrows and their original markers
are stored per current quote; absence of an arrow is not called unchanged. The
parenthesized prices retain their unspecified meaning. Opening/EV emoji headers
are recognized, while unrelated symbols are not stripped indiscriminately.

This sample contains three current and comparison quotes but only two opening
quotes. Both opening values are retained positionally with
`outcome_count_matches_market: false` and
`opening_outcome_count_mismatch_unmapped` in unresolved issues. They are never
assigned HOME/DRAW/AWAY, even under the opt-in test profile. Per-group mapping
metadata records null for opening. No missing value or relationship to the
current outcomes is invented. One or four opening quotes are rejected, and this
exception does not relax count checks in the older labeled layouts. A PARSED
observation can contain unresolved information; it is not an executable instruction.

## Production basketball profile (2026-09-23)

Use `--ordering-profile oddsnotifier_basketball_v1` for the genuine linked Totals/Spread
layout. Four user-supplied raw fixtures and provenance live in the manifest. Verified
Telegram rendering (including numeric bold) is captured in
`evidence/dashboard/telegram-basketball-observed.json`. This profile returns schema v4;
legacy profiles retain schema v3. Basketball Moneyline mappings remain unchanged.

Totals quote order: OVER, UNDER. Spread: HOME at displayed line, AWAY at inverse,
separately for Pinnacle/Opening/Bet365. Alternate-line metadata is retained. The sole
bold Bet365 price identifies the target; its current Bet365 line is used. Missing bold
means unresolved selection, never choose the larger price. For pasted text with lost
formatting, `--target-position 1` records explicit user confirmation; it is not inferred.
Conflicting/multiple target markers fail. The original user-pasted fixtures are not
rewritten to manufacture bold formatting. Exact raw-fixture and browser-format tests:
`tests/test_oddsnotifier_basketball_production.py`.
