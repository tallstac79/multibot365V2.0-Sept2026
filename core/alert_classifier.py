"""Production classification of one source message into exactly one intake status.

PARSED          production-verified ordering, one explicit (bold) Bet365 target, equal lines
                and an OddsNotifier-supplied EV: complete and comparable
PARSED_PARTIAL  a valid alert that is interpreted as far as safely possible, but has no
                highlighted target, no Bet365 offer, or no EV because the lines differ
AMBIGUOUS       recognised, but ordering/side/sign cannot be resolved without guessing
INVALID         recognised alert header with malformed or self-contradictory data
IGNORED         not an OddsNotifier odds alert (service notices, empty/media-only messages)
(DUPLICATE is decided by the store, never by the parser.)

Market meaning (sides, line/price quality, movement, EV status) comes from
core.market_interpretation. Layouts it does not handle fall back to the legacy parser,
which never assigns a side to unverified orderings.
"""
import re

from core.market_interpretation import interpret, strip_non_price_bold
from core.oddsnotifier_parser import AlertFormatError, HEADER, parse_oddsnotifier

PARSER_VERSION = 'classifier-3-sharp'
PARSED, PARSED_PARTIAL, AMBIGUOUS, INVALID, DUPLICATE, IGNORED = (
    'PARSED', 'PARSED_PARTIAL', 'AMBIGUOUS', 'INVALID', 'DUPLICATE', 'IGNORED')
INTAKE_STATUSES = (PARSED, PARSED_PARTIAL, AMBIGUOUS, INVALID, DUPLICATE, IGNORED)


def detect(text):
    """Best-effort (sport, market) label detection used only to choose a grammar/reason."""
    sport = re.search(r'(?:^|\s)(Football|Basketball) - ', text)
    sport = sport[1].lower() if sport else None
    if re.search(r'^\s*Totals? \(', text, re.MULTILINE) or 'market=Totals' in text:
        market = 'TOTALS'
    elif re.search(r'^\s*Spread \(', text, re.MULTILINE) or 'market=Spread' in text:
        market = 'SPREAD'
    elif re.search(r'^\s*ML\s*$', text, re.MULTILINE) or 'market=ML' in text:
        market = '1X2' if sport == 'football' else 'MONEYLINE' if sport else None
    else:
        market = None
    return sport, market


def classify(text, *, channel_id=None, message_id=None, source_timestamp=None):
    """Return dict(status, reason, parsed, profile, sport, market). Never raises for text input."""
    out = dict(status=None, reason=None, parsed=None, profile=None, parser_version=PARSER_VERSION)
    if not isinstance(text, str) or not text.strip():
        return dict(out, status=IGNORED, reason='No text content (media-only or empty message)')
    # Telegram bolds headings; only bolded prices carry meaning. The header must start the
    # message; flattened pastes keep it as a prefix.
    normalized = strip_non_price_bold(text.replace(' ', ' '))
    if not normalized.strip().startswith(HEADER):
        return dict(out, status=IGNORED, reason='Not an OddsNotifier odds-update alert')
    sport, market = detect(normalized)
    out.update(sport=sport, market=market)
    source = dict(channel_id=channel_id, message_id=message_id, source_timestamp=source_timestamp)         if source_timestamp else {}
    result = interpret(text, **source)
    if result is not None:
        return dict(out, **result)
    try:
        parsed = parse_oddsnotifier(normalized, sample_provenance='unspecified', **source)
    except AlertFormatError as error:
        if sport and market:
            return dict(out, status=AMBIGUOUS, reason=f'UNSUPPORTED_MAPPING: {sport} {market} has no '
                        f'production-verified layout/ordering ({error})')
        if sport:
            return dict(out, status=AMBIGUOUS, reason=f'MARKET_UNRESOLVED: {sport} alert without a market label or '
                        f'fixture link; market not guessed ({error})')
        return dict(out, status=INVALID, reason=f'Unsupported or malformed alert: {error}')
    if parsed is None:
        return dict(out, status=INVALID, reason='Alert header present but layout not recognised')
    parsed['raw_text'] = text
    out['parsed'] = parsed
    return dict(out, status=AMBIGUOUS, reason=f'UNSUPPORTED_MAPPING: {parsed["sport"]} {parsed["market"]} '
                'quote ordering is not production-verified; no selection guessed')
