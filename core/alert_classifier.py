"""Production classification of one source message into exactly one intake status.

PARSED     a production-verified mapping with one explicit Bet365 target
AMBIGUOUS  a recognised alert whose target or quote ordering is not production-verified
INVALID    a recognised alert header whose body is malformed or an unsupported layout
IGNORED    not an OddsNotifier odds alert (service notices, empty/media-only messages)
(DUPLICATE is decided by the store, never by the parser.)

Only mappings confirmed from genuine production samples produce PARSED:
basketball Totals/Spread via `oddsnotifier_basketball_v1`. Everything else is kept,
fully parsed where the grammar allows, but never given a guessed selection.
"""
import re

from core.oddsnotifier_parser import (AlertFormatError, HEADER, parse_oddsnotifier,
                                      PRODUCTION_BASKETBALL_PROFILE)

PARSER_VERSION = 'classifier-1'
PARSED, AMBIGUOUS, INVALID, DUPLICATE, IGNORED = 'PARSED', 'AMBIGUOUS', 'INVALID', 'DUPLICATE', 'IGNORED'
INTAKE_STATUSES = (PARSED, AMBIGUOUS, INVALID, DUPLICATE, IGNORED)
# (sport, market) pairs whose Bet365 target mapping is confirmed from production samples.
VERIFIED = {('basketball', 'TOTALS'): PRODUCTION_BASKETBALL_PROFILE,
            ('basketball', 'SPREAD'): PRODUCTION_BASKETBALL_PROFILE}


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
    # The header must start the message; flattened pastes keep it as a prefix.
    if not text.strip().startswith(HEADER):
        return dict(out, status=IGNORED, reason='Not an OddsNotifier odds-update alert')
    sport, market = detect(text)
    out.update(sport=sport, market=market)
    source = dict(channel_id=channel_id, message_id=message_id, source_timestamp=source_timestamp) \
        if source_timestamp else {}
    profile = VERIFIED.get((sport, market))
    if profile:
        out['profile'] = profile
        try:
            parsed = parse_oddsnotifier(text, ordering_profile=profile, sample_provenance='unspecified', **source)
        except AlertFormatError as error:
            return dict(out, status=INVALID, reason=f'{sport} {market} production layout: {error}')
        out['parsed'] = parsed
        if not parsed.get('target_side') or not parsed.get('alert_price'):
            return dict(out, status=AMBIGUOUS, reason='No explicit (bold) Bet365 target price; target not guessed')
        return dict(out, status=PARSED, reason='Production-verified mapping with explicit Bet365 target')
    try:
        parsed = parse_oddsnotifier(text, sample_provenance='unspecified', **source)
    except AlertFormatError as error:
        if sport and market:
            return dict(out, status=AMBIGUOUS, reason=f'UNSUPPORTED_MAPPING: {sport} {market} has no '
                        f'production-verified layout/ordering ({error})')
        return dict(out, status=INVALID, reason=f'Unsupported or malformed alert: {error}')
    if parsed is None:
        return dict(out, status=INVALID, reason='Alert header present but layout not recognised')
    out['parsed'] = parsed
    return dict(out, status=AMBIGUOUS, reason=f'UNSUPPORTED_MAPPING: {parsed["sport"]} {parsed["market"]} '
                'quote ordering is not production-verified; no selection guessed')
