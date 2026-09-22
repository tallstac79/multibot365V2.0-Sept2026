"""Offline, lossless observation parser for the supplied OddsNotifier Spread format.

No selection recommendation, price rule, instruction or execution is produced.
Price positions remain positions: the supplied message does not label their sides
or explain the parenthesized values. Decimal strings preserve source precision.
"""
from datetime import datetime
from decimal import Decimal
import hashlib
import json
import re


class AlertFormatError(ValueError):
    """A recognized alert is malformed, ambiguous or unsupported."""


HEADER = "New odds update on Pinnacle"
NUMBER = r"[0-9]+(?:\.[0-9]+)?"
LINE = r"[+-]?[0-9]+(?:\.[0-9]+)?"


def _match(pattern, value, field):
    match = re.fullmatch(pattern, value)
    if not match:
        raise AlertFormatError(f"Invalid or unsupported {field}: {value!r}")
    return match


def _price(value):
    if Decimal(value) <= 1:
        raise AlertFormatError("Decimal price must exceed 1")
    return value


def _quotes(text, parenthetical=False):
    token = rf"({NUMBER})\s*\(({NUMBER})\)" if parenthetical else rf"({NUMBER})"
    m = _match(rf"{token}\s+-\s+{token}", text, "two-price row")
    if parenthetical:
        return [dict(position=1, price=_price(m[1]), parenthetical_price=_price(m[2])),
                dict(position=2, price=_price(m[3]), parenthetical_price=_price(m[4]))]
    return [dict(position=i + 1, price=_price(value)) for i, value in enumerate(m.groups())]


def _source(channel_id, message_id, source_timestamp):
    # Message IDs are scoped to a Telegram channel. Never hash message text alone.
    if channel_id is None and message_id is None and source_timestamp is None:
        return None, None
    if not isinstance(channel_id, str) or not re.fullmatch(r"-?[1-9][0-9]*", channel_id):
        raise AlertFormatError("Numeric Telegram channel_id string required")
    if not isinstance(message_id, str) or not re.fullmatch(r"[1-9][0-9]*", message_id):
        raise AlertFormatError("Positive Telegram message_id string required")
    if not isinstance(source_timestamp, str):
        raise AlertFormatError("Timezone-aware source timestamp required")
    try:
        timestamp = datetime.fromisoformat(source_timestamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise AlertFormatError("Invalid source timestamp") from error
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise AlertFormatError("Source timestamp must include timezone")
    identity = json.dumps(["OddsNotifier", channel_id, message_id], separators=(",", ":"))
    return "oddsnotifier:" + hashlib.sha256(identity.encode()).hexdigest(), source_timestamp


def parse_oddsnotifier(text, *, channel_id=None, message_id=None, source_timestamp=None):
    """Return an observation; None for unrelated text; raise on invalid alerts.

    Supports only the concrete Spread grammar demonstrated by the supplied sample.
    Raw text, signed lines and all decimal precision are retained. Missing metadata
    stays null for pasted samples. No timestamp timezone or target side is guessed.
    """
    if not isinstance(text, str) or len(text) > 32768:
        raise AlertFormatError("Text must be a string of at most 32768 characters")
    rows = [row.strip() for row in text.splitlines() if row.strip()]
    if not rows or rows[0] != HEADER:
        return None
    if len(rows) != 11:
        raise AlertFormatError("Expected one complete alert with 11 nonempty lines")
    event = _match(r"(Football|Basketball) - ([^\r\n]+?) - ([^\r\n]+)", rows[1], "sport/country/competition")
    teams = re.split(r"\s+vs\s+", rows[2])
    if len(teams) != 2 or not all(teams) or teams[0].casefold() == teams[1].casefold():
        raise AlertFormatError("Expected two distinct, unambiguous teams")
    _match(r"[0-9]{2}\.[0-9]{2}\.[0-9]{4} [0-9]{2}:[0-9]{2}", rows[3], "event date")
    try:
        scheduled = datetime.strptime(rows[3], "%d.%m.%Y %H:%M")
    except ValueError as error:
        raise AlertFormatError("Invalid event date") from error
    current = _match(rf"Spread \(({LINE})\)", rows[4], "current market")
    opening = _match(rf"Opening \(({LINE})\)", rows[6], "opening line")
    comparison = _match(rf"([^()]+) \(Spread ({LINE})\)", rows[8], "comparison market")
    ev = _match(rf"EV: ({NUMBER})%", rows[10], "displayed EV")
    observation_id, source_time = _source(channel_id, message_id, source_timestamp)
    return {
        "schema_version": 1, "source": "OddsNotifier", "observation_id": observation_id,
        "telegram_channel_id": channel_id, "telegram_message_id": message_id,
        "source_timestamp": source_time, "raw_text": text,
        "sport": event[1].lower(), "country": event[2], "competition": event[3],
        "fixture": rows[2], "home": teams[0], "away": teams[1],
        "scheduled_at_local": scheduled.isoformat(timespec="minutes"),
        "scheduled_timezone": None, "market": "SPREAD", "displayed_line": current[1],
        "pinnacle": {"line": current[1], "quotes": _quotes(rows[5], True)},
        "opening": {"line": opening[1], "quotes": _quotes(rows[7])},
        "comparison": {"site": comparison[1].strip(), "line": comparison[2],
                       "quotes": _quotes(rows[9])},
        "displayed_ev_percent": ev[1],
        "target_side": None, "target_line": None, "alert_price": None,
        "unresolved": ["target_selection_not_explicit", "quote_sides_not_labeled",
                       "parenthetical_price_meaning_unspecified", "event_timezone_unspecified"],
    }
