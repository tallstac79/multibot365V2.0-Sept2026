"""Offline observation parser for supplied real/synthetic OddsNotifier formats.

No price rule or execution is produced. Legacy observations keep quote positions
unmapped; the opt-in, user-confirmed basketball profile can extract an explicit
Bet365 target. Parenthetical semantics remain unresolved. Decimal strings retain
source precision.
"""
from datetime import datetime
from decimal import Decimal
import hashlib
import json
import re
from urllib.parse import parse_qs, urlsplit


class AlertFormatError(ValueError):
    """A recognized alert is malformed, ambiguous or unsupported."""


from core.oddsnotifier_basketball import PROFILE as PRODUCTION_BASKETBALL_PROFILE, parse_basketball

HEADER = "New odds update on Pinnacle"
NUMBER = r"[0-9]+(?:\.[0-9]+)?"
LINE = r"[+-]?[0-9]+(?:\.[0-9]+)?"
# An opt-in hypothesis for synthetic tests, NOT a verified production convention.
SYNTHETIC_ORDER_PROFILE = "synthetic_order_v1"
_ORDERS = {
    ("football", "1X2"): ("HOME", "DRAW", "AWAY"),
    ("basketball", "MONEYLINE"): ("HOME", "AWAY"),
    ("football", "SPREAD"): ("HOME", "AWAY"),
    ("basketball", "SPREAD"): ("HOME", "AWAY"),
    ("football", "TOTALS"): ("OVER", "UNDER"),
    ("basketball", "TOTALS"): ("OVER", "UNDER"),
}


def _match(pattern, value, field):
    match = re.fullmatch(pattern, value)
    if not match:
        raise AlertFormatError(f"Invalid or unsupported {field}: {value!r}")
    return match


def _price(value):
    if Decimal(value) <= 1:
        raise AlertFormatError("Decimal price must exceed 1")
    return value


def _quotes(text, count, allow_parenthetical=False, sides=None):
    cells = re.split(r"\s+-\s+", text)
    if len(cells) != count:
        raise AlertFormatError(f"Expected exactly {count} prices")
    quotes = []
    for index, cell in enumerate(cells):
        pattern = (rf"({NUMBER})([⬇⬆]\ufe0f?)?(?:\s*\(({NUMBER})\))?"
                   if allow_parenthetical else rf"({NUMBER})")
        m = _match(pattern, cell, "price cell")
        quote = dict(position=index + 1, price=_price(m[1]))
        if allow_parenthetical:
            if m[2] is not None:
                quote['movement'] = 'DOWN' if m[2].startswith('⬇') else 'UP'
                quote['movement_marker'] = m[2]
            if m[3] is not None:
                quote['parenthetical_price'] = _price(m[3])
        if sides is not None:
            quote['side'] = sides[index]
        quotes.append(quote)
    if 0 < sum('parenthetical_price' in q for q in quotes) < count:
        raise AlertFormatError("Mixed parenthetical and plain price cells")
    return quotes


def _linked_label(row):
    """Read a parenthesized bare/Markdown URL as data, never fetch it."""
    m = _match(r'(.+?) \((https://[^\s()]+|\[https://[^\s\[\]]+\]\(https://[^\s()]+\))\)',
               row, 'linked label')
    label, link = m[1], m[2]
    if link.startswith('['):
        markdown = _match(r'\[(https://[^\s\[\]]+)\]\((https://[^\s()]+)\)', link, 'Markdown link')
        if markdown[1] != markdown[2]:
            raise AlertFormatError('Conflicting displayed and destination URLs')
        link = markdown[2]
    try:
        parsed = urlsplit(link)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.port:
            raise ValueError('Unexpected URL authority')
    except ValueError as error:
        raise AlertFormatError('Invalid source URL') from error
    return label, link, parsed


def _linked_ml_rows(rows):
    """Normalize only the observed linked football-ML layout; no broad fallback."""
    fixture, fixture_url, parsed = _linked_label(rows[2])
    if parsed.hostname != 'oddshub.io' or not parsed.path.startswith('/football/'):
        raise AlertFormatError('Unsupported fixture URL')
    if parse_qs(parsed.query, keep_blank_values=True).get('market') != ['ML']:
        raise AlertFormatError('Fixture URL must identify exactly one ML market')
    if not rows[1].startswith('Football - '):
        raise AlertFormatError('Linked football URL conflicts with sport')
    site, comparison_url, comparison = _linked_label(rows[7])
    if site != 'Bet365' or comparison.hostname not in ('bet365.com', 'www.bet365.com'):
        raise AlertFormatError('Unsupported comparison link')
    _match(r'(?:🟢\s+)?Opening', rows[5], 'linked opening header')
    _match(rf'(?:🎯\s+)?EV: {NUMBER}%', rows[9], 'linked EV')
    normalized = [rows[0], rows[1], fixture, rows[3], 'ML', rows[4],
                  'Opening', rows[6], 'Bet365 (ML)', rows[8],
                  re.sub(r'^🎯\s+', '', rows[9])]
    return normalized, fixture_url, comparison_url


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


def parse_oddsnotifier(text, *, channel_id=None, message_id=None, source_timestamp=None,
                      ordering_profile=None, sample_provenance="unspecified", target_position=None):
    """Return an observation; None for unrelated text; raise on invalid alerts.

    Supports Spread, ML and Total grammars demonstrated by supplied samples.
    Raw text, signed lines and all decimal precision are retained. Missing metadata
    stays null for pasted samples. No timestamp timezone or target side is guessed.
    """
    if ordering_profile not in (None, SYNTHETIC_ORDER_PROFILE, PRODUCTION_BASKETBALL_PROFILE):
        raise AlertFormatError("Unknown ordering profile")
    if sample_provenance not in ("unspecified", "user_reported_real", "synthetic"):
        raise AlertFormatError("Unknown sample provenance")
    if not isinstance(text, str) or len(text) > 32768:
        raise AlertFormatError("Text must be a string of at most 32768 characters")
    if ordering_profile == PRODUCTION_BASKETBALL_PROFILE:
        return parse_basketball(text, channel_id=channel_id, message_id=message_id,
                               source_timestamp=source_timestamp, sample_provenance=sample_provenance, target_position=target_position)
    if target_position is not None:
        raise AlertFormatError('Target confirmation requires the production basketball profile')
    rows = [row.strip() for row in text.splitlines() if row.strip()]
    if not rows or rows[0] != HEADER:
        return None
    linked = len(rows) == 10
    fixture_url = comparison_url = None
    if linked:
        rows, fixture_url, comparison_url = _linked_ml_rows(rows)
    elif len(rows) != 11:
        raise AlertFormatError("Expected one complete supported alert")
    event = _match(r"(Football|Basketball) - ([^\r\n]+?) - ([^\r\n]+)", rows[1], "sport/country/competition")
    teams = re.split(r"\s+vs\s+", rows[2])
    if len(teams) != 2 or not all(teams) or teams[0].casefold() == teams[1].casefold():
        raise AlertFormatError("Expected two distinct, unambiguous teams")
    _match(r"[0-9]{2}\.[0-9]{2}\.[0-9]{4} [0-9]{2}:[0-9]{2}", rows[3], "event date")
    try:
        scheduled = datetime.strptime(rows[3], "%d.%m.%Y %H:%M")
    except ValueError as error:
        raise AlertFormatError("Invalid event date") from error
    sport = event[1].lower()
    if rows[4] == 'ML':
        label, market = 'ML', '1X2' if sport == 'football' else 'MONEYLINE'
        count = 3 if sport == 'football' else 2
        _match('Opening', rows[6], 'opening market')
        comparison = _match(r'([^()]+) \(ML\)', rows[8], 'comparison market')
        current_line = opening_line = comparison_line = None
    else:
        current = _match(rf'(Spread|Total) \(({LINE})\)', rows[4], 'current market')
        label = current[1]
        market, count = ('SPREAD' if label == 'Spread' else 'TOTALS'), 2
        opening = _match(rf'Opening \(({LINE})\)', rows[6], 'opening line')
        comparison = _match(rf'([^()]+) \({label} ({LINE})\)', rows[8], 'comparison market')
        current_line, opening_line, comparison_line = current[2], opening[1], comparison[2]
        if market == 'TOTALS' and any(Decimal(n) < 0 for n in (current_line, opening_line, comparison_line)):
            raise AlertFormatError('Total lines cannot be negative')
    sides = _ORDERS[(sport, market)] if ordering_profile else None
    pinnacle_quotes = _quotes(rows[5], count, True, sides)
    opening_count = len(re.split(r'\s+-\s+', rows[7]))
    incomplete_opening = linked and market == '1X2' and opening_count == 2
    # The real linked sample omits an unidentified opening outcome. Never map its
    # two values onto any subset of the three current outcomes or invent a value.
    opening_sides = None if incomplete_opening else sides
    opening_quotes = _quotes(rows[7], 2 if incomplete_opening else count, sides=opening_sides)
    comparison_quotes = _quotes(rows[9], count, sides=sides)
    unresolved = ['target_selection_not_explicit', 'event_timezone_unspecified']
    unresolved.append('quote_mapping_is_unverified_assumption' if sides else 'quote_sides_not_labeled')
    if any('parenthetical_price' in q for q in pinnacle_quotes):
        unresolved.append('parenthetical_price_meaning_unspecified')
    if incomplete_opening:
        unresolved.append('opening_outcome_count_mismatch_unmapped')
    ev = _match(rf"EV: ({NUMBER})%", rows[10], "displayed EV")
    observation_id, source_time = _source(channel_id, message_id, source_timestamp)
    return {
        "schema_version": 3, "source": "OddsNotifier", "observation_id": observation_id,
        "format_variant": 'linked_football_ml' if linked else 'labeled_market',
        "fixture_url": fixture_url, "comparison_url": comparison_url,
        "market_label_source": 'fixture_url_query' if linked else 'standalone_label',
        "sample_provenance": sample_provenance,
        "quote_mapping": {"profile": ordering_profile, "production_verified": False,
                          "sides_by_position": list(sides) if sides else None,
                          "group_sides_by_position": {
                              'pinnacle': list(sides) if sides else None,
                              'opening': list(opening_sides) if opening_sides else None,
                              'comparison': list(sides) if sides else None}},
        "telegram_channel_id": channel_id, "telegram_message_id": message_id,
        "source_timestamp": source_time, "raw_text": text,
        "sport": sport, "country": event[2], "competition": event[3],
        "fixture": rows[2], "home": teams[0], "away": teams[1],
        "scheduled_at_local": scheduled.isoformat(timespec="minutes"),
        "scheduled_timezone": None, "market": market, "market_label": label,
        "displayed_line": current_line,
        "pinnacle": {"line": current_line, "quotes": pinnacle_quotes},
        "opening": {"line": opening_line, "quotes": opening_quotes,
                    "outcome_count_matches_market": not incomplete_opening},
        "comparison": {"site": comparison[1].strip(), "line": comparison_line,
                       "quotes": comparison_quotes},
        "displayed_ev_percent": ev[1],
        "target_side": None, "target_line": None, "alert_price": None,
        "unresolved": unresolved,
    }
