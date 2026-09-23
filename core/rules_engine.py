"""Production rules engine: normalized alert + configuration -> normalized decision.

Pure and deterministic given (alert, config, received_at, now). No live-site interaction,
no dispatch. Uses the decision-support configuration (core.decision_support) so the
dashboard's existing Rules & configuration screen edits the same values.

Every check is recorded, so the stored rules result explains exactly why an instruction
was queued, rejected or marked stale. Anything unverifiable fails closed.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json

from core.decision_support import validate

ENGINE_VERSION = 'rules-2'
ACCEPT, REJECT, STALE = 'ACCEPT', 'REJECT', 'STALE'


def _utc(value):
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timezone required')
    return parsed.astimezone(timezone.utc)


def config_hash(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:16]


def event_start(alert, tz_name):
    """Scheduled start as an aware UTC datetime, or None when it cannot be established."""
    if not tz_name or not alert.get('scheduled_at_local'):
        return None
    from zoneinfo import ZoneInfo
    local = datetime.fromisoformat(alert['scheduled_at_local'])
    return local.replace(tzinfo=ZoneInfo(tz_name)).astimezone(timezone.utc)


def selection_name(alert):
    side = alert.get('target_side')
    return {'HOME': alert.get('home'), 'AWAY': alert.get('away'), 'OVER': 'Over', 'UNDER': 'Under',
            'DRAW': 'Draw'}.get(side)


def evaluate(alert, config, *, instruction_id, received_at, now=None):
    """Return a JSON-serializable decision dict.

    decision: ACCEPT (instruction attached) | REJECT | STALE, with `reason` naming the
    first failing check. `checks` lists every check evaluated, in order.
    """
    now = now or datetime.now(timezone.utc)
    config = validate(config)
    g = config['global']
    checks = []
    result = dict(engine=ENGINE_VERSION, evaluated_at=now.isoformat(), config_hash=config_hash(config),
                  decision=None, reason=None, checks=checks, instruction=None)

    def check(name, passed, detail, outcome=REJECT):
        checks.append(dict(name=name, passed=bool(passed), detail=detail))
        if not passed and result['decision'] is None:
            result['decision'], result['reason'] = outcome, f'{name}: {detail}'
        return passed

    mapping = alert.get('quote_mapping') or {}
    check('verified_mapping', mapping.get('production_verified') is True,
          'production-verified quote mapping' if mapping.get('production_verified') else
          'quote ordering is not production-verified; no selection is guessed')
    check('explicit_target', bool(alert.get('target_side') and alert.get('alert_price')),
          f"target {alert.get('target_side')} @ {alert.get('alert_price')}" if alert.get('target_side')
          else 'no explicit Bet365 target in source message')
    # Market interpretation (core.market_interpretation): only a clear equal-line value signal on
    # the highlighted target proceeds. A favourable line alone is not a bet.
    quality = alert.get('bet_quality')
    check('bet_quality', quality == 'CLEAR_VALUE_SIGNAL',
          f"{quality or 'no market interpretation'} (line {alert.get('line_quality')}, price "
          f"{alert.get('price_quality')}, EV {(alert.get('comparison') or {}).get('ev_status')})")
    sport, market = alert.get('sport'), alert.get('market')
    rule = config['sports'].get(sport, {}).get('markets', {}).get(market)
    check('known_market', rule is not None, f'{sport} {market}' if rule else f'unsupported sport/market {sport} {market}')
    check('global_enabled', g['enabled'], 'global rules enabled' if g['enabled'] else 'global rules disabled')
    if rule is not None:
        check('market_enabled', rule['enabled'], f'{sport} {market} ' + ('enabled' if rule['enabled'] else 'disabled'))

    # Staleness: age since the Telegram message was posted (source) or, if the source
    # time is unknown, since local receipt. The later check uses the older of the two.
    try:
        anchors = [_utc(v) for v in (alert.get('source_timestamp'), received_at) if v]
        age = (now - min(anchors)).total_seconds() if anchors else None
    except ValueError:
        age = None
    limit = g['stale_alert_seconds']
    check('alert_age', age is not None and age <= limit,
          f'{int(age)}s old (limit {limit}s)' if age is not None else 'alert receipt time unknown', STALE)
    try:
        start = event_start(alert, g['event_timezone'])
    except (ValueError, KeyError):
        start = None
    if start is None:
        check('event_not_started', False, 'event timezone not configured or event time unreadable; '
              'cannot prove the event has not started')
    else:
        check('event_not_started', now < start, f'event starts {start.isoformat()}' if now < start
              else f'event started at {start.isoformat()}', STALE)

    try:
        price = Decimal(str(alert.get('alert_price')))
        valid_price = price.is_finite() and price > 1
    except (InvalidOperation, TypeError, ValueError):
        price, valid_price = None, False
    check('valid_price', valid_price, f'alert price {alert.get("alert_price")}')
    if rule is not None:
        if rule['minimum_ev'] is not None:
            try:
                ev = Decimal(str(alert.get('displayed_ev_percent')))
            except (InvalidOperation, TypeError, ValueError):
                ev = None
            check('minimum_ev', ev is not None and ev >= Decimal(str(rule['minimum_ev'])),
                  f"displayed EV {alert.get('displayed_ev_percent')} vs minimum {rule['minimum_ev']}")
        if valid_price and rule['min_price'] is not None:
            check('min_price', price >= Decimal(str(rule['min_price'])), f"price {price} vs minimum {rule['min_price']}")
        if valid_price and rule['max_price'] is not None:
            check('max_price', price <= Decimal(str(rule['max_price'])), f"price {price} vs maximum {rule['max_price']}")

    if result['decision'] is not None:
        return result
    stake = rule['stake'] if rule['stake'] is not None else g['default_stake']
    stake = min(stake, g['max_stake'])
    slippage = rule['allowed_slippage'] if rule['allowed_slippage'] is not None else g['allowed_slippage']
    minimum = max(Decimal('1.01'), price - Decimal(str(slippage)))
    check('stake', 0 < stake <= g['max_stake'], f'stake {stake:.2f} (max {g["max_stake"]:.2f})')
    alternate = alert.get('alternate_line') or {}
    result['decision'], result['reason'] = ACCEPT, 'All rules passed'
    result['instruction'] = dict(
        instruction_id=instruction_id, sport=sport, competition=alert.get('competition'),
        fixture=alert.get('fixture'), home=alert.get('home'), away=alert.get('away'),
        event_time_local=alert.get('scheduled_at_local'), event_timezone=g['event_timezone'],
        event_start_utc=start.isoformat() if start else None,
        market=market, side=alert.get('target_side'), selection_name=selection_name(alert),
        line=alert.get('target_line'),
        # Per-group "(alt. line)" markers exactly as parsed: current (Pinnacle), opening, comparison (Bet365).
        alternate_line={k: bool(alternate.get(k)) for k in ('current', 'opening', 'comparison')},
        alert_price=str(alert.get('alert_price')), minimum_price=str(minimum), stake=f'{stake:.2f}',
        displayed_ev_percent=alert.get('displayed_ev_percent'), bet_quality=quality,
        line_quality=alert.get('line_quality'), price_quality=alert.get('price_quality'),
        reference_odds=(alert.get('reference') or {}).get('odds'))
    return result
