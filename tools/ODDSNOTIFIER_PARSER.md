# OddsNotifier offline observation parser

Parses saved alerts to descriptive JSON. No network, coordinator, recommendation
or execution hooks. The legacy Telegram listener, Android and database are unchanged.

## Samples and supported grammar

`tests/fixtures/oddsnotifier_manifest.json` records the user-reported provenance:
one real football Spread alert and five synthetic examples modelled on its layout.
Synthetic tests demonstrate grammar handling, not exact production formatting.

Supported labels are exactly `ML`, `Spread (line)` and `Total (line)`.
Football ML requires three prices and normalizes to `1X2`; basketball ML requires
two and normalizes to `MONEYLINE`. Spread and Total require two, normalizing to
`SPREAD` and `TOTALS`. The same count is required in current, opening and comparison
rows. Pinnacle rows may have parenthesized values for every price or none.
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

Schema version 2 adds sample provenance, explicit quote-mapping metadata and original
market label. Unrelated text returns IGNORED. Malformed/unsupported recognized alerts
return INVALID_ALERT (CLI exit 2). Real examples are still required before asserting
production support for the synthetic formats or enabling any verified side profile.
