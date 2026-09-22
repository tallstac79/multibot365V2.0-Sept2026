# OddsNotifier observation parser

This standalone parser handles the exact Spread message grammar supplied by the
user. It has no network, coordinator, Android, recommendation or execution hooks.
The legacy Telegram listener and generic parser are unchanged.

Run from the project root:

```powershell
python tools/parse_oddsnotifier.py tests/fixtures/oddsnotifier_spread.txt
python -m unittest discover -s tests -p test_oddsnotifier_parser.py -v
```

Optional `--channel-id`, `--message-id` and `--source-timestamp` must be supplied
together. Channel and message IDs are numeric strings; the timestamp must include
a timezone. A deterministic observation ID hashes source, channel and message ID.
This supplies a stable identity, not persistent duplicate suppression.

The message's date is the fixture's scheduled local time, not the Telegram send
time. Its timezone is unspecified. Missing Telegram metadata remains null.
All decimal values are strings so their precision and signs survive JSON export.
Current, parenthesized, opening and comparison prices remain distinct. Opening
and comparison lines are preserved independently even when they differ.

The sample does not explicitly identify a target selection or explain the
parenthesized prices. Price entries retain their numbered positions; HOME/AWAY
quote mapping, a target price and a target line are not inferred from EV or price
size. Fixture names follow the displayed first-team/second-team order.

Unrelated text returns IGNORED. Recognized malformed, ambiguous or unsupported
alerts return INVALID_ALERT (CLI exit 2). No generic-parser fallback is used.
The parser permits Football or Basketball in this Spread grammar, but the only
real supplied example is football. Actual 1X2, moneyline, totals and basketball
examples are still needed before claiming those source formats are supported.
