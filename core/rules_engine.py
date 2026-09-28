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
from core.execution_terms import minimum_price, line_allowance
from core.market_interpretation import ACTIONABLE_SIGNALS, SHARP_SOURCE, VERSION, sharp_signal, dec
from core.moneyline import VERSION as ML_VERSION, PROFILE as ML_PROFILE, sharp_signal as moneyline_sharp_signal
from core.football import (VERSION as FOOTBALL_VERSION, PROFILE_1X2 as FOOTBALL_1X2_PROFILE, PROFILE_TWO_SIDED as FOOTBALL_TWO_SIDED_PROFILE,
                           SIDES as FOOTBALL_SIDES, sharp_signal_for_alert as football_sharp_signal, in_play_link)

ENGINE_VERSION = 'rules-9-prematch-link'
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
    zone = ZoneInfo(tz_name)
    if local.tzinfo is not None:
        raise ValueError('Feed event wall time must not contain an offset')
    candidates = set()
    for fold in (0, 1):
        utc = local.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
        if utc.astimezone(zone).replace(tzinfo=None) == local:
            candidates.add(utc)
    if len(candidates) != 1:
        raise ValueError('Ambiguous or nonexistent local event time')
    return candidates.pop()


def selection_name(alert):
    side = alert.get('target_side')
    return {'HOME': alert.get('home'), 'AWAY': alert.get('away'), 'OVER': 'Over', 'UNDER': 'Under',
            'DRAW': 'Draw'}.get(side)


def time_assumptions(alert, config, now):
    """Explain provisional event-time interpretations without altering strategy fields."""
    g = validate(config)['global']
    alternatives = {}
    for zone in dict.fromkeys([g['event_timezone'], 'UTC', 'Europe/London']):
        if not zone:
            continue
        try:
            candidate = event_start(alert, zone)
            alternatives[zone] = dict(event_start_utc=candidate.isoformat() if candidate else None,
                                      event_not_started=now < candidate if candidate else None)
        except (ValueError, KeyError):
            alternatives[zone] = dict(event_start_utc=None, event_not_started=None)
    return dict(feed_timezone_verified=g['feed_timezone_verified'],
                event_timezone=g['event_timezone'], event_time_assumptions=alternatives,
                timezone_eligibility_uncertain=not g['feed_timezone_verified'] and
                len({v['event_not_started'] for v in alternatives.values()}) > 1)


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
    moneyline = alert.get('market') == 'MONEYLINE' and alert.get('sport') == 'basketball'
    # Football (Feed 1): 1X2 / Asian-handicap Spread / Totals under core.football; the signal is re-derived here from the
    # stored quotes and lines and must agree with the interpreted target. Basketball paths are unchanged.
    football = alert.get('sport') == 'football' and alert.get('market') in ('1X2', 'SPREAD', 'TOTALS')
    price_market = moneyline or (football and alert.get('market') == '1X2')
    if moneyline:
        signal = moneyline_sharp_signal((alert.get('opening') or {}).get('quotes'), (alert.get('pinnacle') or {}).get('quotes'),
                                        verified=mapping.get('production_verified') is True)
    elif football:
        signal = football_sharp_signal(alert, verified=mapping.get('production_verified') is True)
    else:
        signal = sharp_signal(alert.get('market'), (alert.get('opening') or {}).get('line'),
                              (alert.get('pinnacle') or {}).get('line'),
                              verified=mapping.get('production_verified') is True,
                              perspective=(alert.get('market_movement') or {}).get('line_perspective'))
    expected_version = ML_VERSION if moneyline else FOOTBALL_VERSION if football else VERSION
    check('sharp_target', alert.get('interpretation_version') == expected_version
          and alert.get('interpretation_status') == 'PARSED'
          and alert.get('target_price_source') == SHARP_SOURCE
          and signal['side'] is not None and signal['side'] == alert.get('target_side'),
          signal['reason'] if signal['side'] == alert.get('target_side') and signal['side']
          else 'No verified opening-to-current sharp target; obsolete or ambiguous interpretation fails closed')
    check('explicit_target', bool(alert.get('target_side') and alert.get('alert_price')),
          f"target {alert.get('target_side')} @ {alert.get('alert_price')} (Pinnacle opening-to-current movement)"
          if alert.get('target_side') else 'no verified sharp side and Bet365 offer')
    if moneyline:
        quotes = (alert.get('comparison') or {}).get('quotes') or []
        ordered = len(quotes) == 2 and all(isinstance(q,dict) and q.get('side') == s and q.get('position') == i+1
                                          for i,(q,s) in enumerate(zip(quotes,('HOME','AWAY'))))
        target_quote = next((q for q in quotes if isinstance(q,dict) and q.get('side') == signal['side']), {})
        check('moneyline_same_side_offer', mapping.get('profile') == ML_PROFILE and ordered
              and dec(alert.get('alert_price')) == dec(target_quote.get('price'))
              and alert.get('target_line') is None,
              'Two-outcome basketball ML; requested Bet365 quote must belong to the independently selected Pinnacle side')
    if football:
        sides = FOOTBALL_SIDES[alert.get('market')]
        quotes = (alert.get('comparison') or {}).get('quotes') or []
        ordered = len(quotes) == len(sides) and all(isinstance(q, dict) and q.get('side') == s and q.get('position') == i + 1
                                                    for i, (q, s) in enumerate(zip(quotes, sides)))
        target_quote = next((q for q in quotes if isinstance(q, dict) and q.get('side') == signal['side']), {})
        expected_profile = FOOTBALL_1X2_PROFILE if alert.get('market') == '1X2' else FOOTBALL_TWO_SIDED_PROFILE
        line_ok = alert.get('target_line') is None if price_market else dec(alert.get('target_line')) == dec(target_quote.get('line'))
        check('football_same_side_offer', mapping.get('profile') == expected_profile and ordered and signal['side'] is not None
              and dec(alert.get('alert_price')) == dec(target_quote.get('price')) and line_ok
              and not (alert.get('football') or {}).get('in_play_link'),
              f"football {alert.get('market')}: requested Bet365 quote must belong to the independently selected Pinnacle side "
              f"({signal['side']}) at its own line, from a pre-match event link")
    # Market interpretation (core.market_interpretation): only an actionable signal on the
    # verified Pinnacle opening-to-current target proceeds. CLEAR_VALUE_SIGNAL = equal-line price/EV edge;
    # FAVOURABLE_LINE_SIGNAL = materially favourable Bet365 line at an acceptable price (no EV).
    quality = alert.get('bet_quality')
    comparison = alert.get('comparison') or {}
    check('bet_quality', quality in ACTIONABLE_SIGNALS,
          f"{quality or 'no market interpretation'} (line {alert.get('line_quality')}, price "
          f"{alert.get('price_quality')}, EV {comparison.get('ev_status')})")
    line_signal = quality == 'FAVOURABLE_LINE_SIGNAL'
    if line_signal:
        advantage = comparison.get('line_advantage')
        try:
            advantage_value = Decimal(str(advantage))
        except (InvalidOperation, TypeError, ValueError):
            advantage_value = None
        check('line_advantage', advantage_value is not None and advantage_value >= Decimal(str(g['min_line_advantage'])),
              f"Bet365 line advantage {advantage} points vs minimum {g['min_line_advantage']}")
    minimum_move = g['min_sharp_movement']
    magnitude = dec(signal.get('magnitude'))
    price_based = moneyline or (football and signal.get('basis') in ('price', 'price_same_line'))
    check('sharp_movement', magnitude is not None and magnitude > 0
          and (price_based or minimum_move is None or magnitude >= Decimal(str(minimum_move))),
          'Feed-qualified signal; genuine nonzero opening-to-current movement required; no duplicate movement floor' if price_based or minimum_move is None
          else f'Pinnacle net movement {magnitude} points vs minimum {minimum_move}')
    sport, market = alert.get('sport'), alert.get('market')
    rule = config['sports'].get(sport, {}).get('markets', {}).get(market)
    check('known_market', rule is not None, f'{sport} {market}' if rule else f'unsupported sport/market {sport} {market}')
    if not football:
        # An in-play Bet365 link (#/IP/EV...) is not an event page the phone can open (only #/AC/ links are), so it used to
        # be dropped and the run fell into Search, which cannot verify a live event (27 Sep 2026 Shahrdari Gorgan v
        # Sagesse, on-f91b5ce9: WRONG_EVENT "Search event context not verified" after a full Search run). Refused here,
        # before dispatch. Football already refuses it in football_same_side_offer. No link at all still uses Search.
        in_play = in_play_link(alert.get('comparison_url'))
        check('pre_match_link', not in_play,
              'Bet365 link is an in-play page (#/IP/): no pre-match event page to open; not sent to Search' if in_play
              else 'no in-play Bet365 link')
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
    check('timestamp_consistency', age is not None and all((v - now).total_seconds() <= 30 for v in anchors),
          'Source/receipt times must not exceed the current clock by more than 30 seconds')
    # Timezone uncertainty is an eligibility gate only: target selection and offer
    # quality above are unchanged. Preserve both candidate conversions for review.
    result.update(time_assumptions(alert, config, now))
    check('feed_timezone_verified', g['feed_timezone_verified'],
          f"Feed timezone {g['event_timezone']} is " + ('operator verified' if g['feed_timezone_verified'] else
          'provisional/unverified; event-start eligibility fails closed'))
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
        if rule['minimum_ev'] is not None and line_signal:
            check('minimum_ev', True, 'not applicable: OddsNotifier EV unavailable for unequal lines '
                  '(favourable-line signal; no synthetic EV)')
        elif rule['minimum_ev'] is not None:
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

    if rule is not None:
        check('execution_tolerances', (rule['max_odds_deterioration'] is not None or rule['max_net_payout_deterioration_percent'] is not None)
              and (price_market or rule['max_line_deterioration'] is not None),
              f"{sport} {market}: net payout tolerance {rule['max_net_payout_deterioration_percent']}%, "
              f"legacy decimal tolerance {rule['max_odds_deterioration']}, absolute line cap {rule['max_line_deterioration']}, "
              f"spread cap {rule['max_line_deterioration_percent']}% of original handicap; price and line policies require explicit configuration")
    if result['decision'] is not None:
        return result
    stake = rule['stake'] if rule['stake'] is not None else g['default_stake']
    stake = min(stake, g['max_stake'])
    slippage = rule['max_odds_deterioration']
    minimum = minimum_price(price, net_percent=rule['max_net_payout_deterioration_percent'], decimal_tolerance=slippage)
    effective_line = None if price_market else line_allowance(market, alert.get('target_line'), rule['max_line_deterioration'], rule['max_line_deterioration_percent'])
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
        max_odds_deterioration=str(slippage) if slippage is not None else None,
        max_net_payout_deterioration_percent=rule['max_net_payout_deterioration_percent'],
        max_line_deterioration=str(effective_line) if effective_line is not None else None,
        configured_line_absolute_cap=rule['max_line_deterioration'],
        max_line_deterioration_percent=rule['max_line_deterioration_percent'],
        displayed_ev_percent=alert.get('displayed_ev_percent'), bet_quality=quality,
        signal_reason=quality, line_advantage=comparison.get('line_advantage'),
        target_source=alert.get('target_price_source'), implied_target=alert.get('implied_target'),
        sharp_signal=signal, highlighted_side=alert.get('highlighted_side'),
        ev_status=comparison.get('ev_status'),
        line_quality=alert.get('line_quality'), price_quality=alert.get('price_quality'),
        reference_odds=(alert.get('reference') or {}).get('odds'))
    return result
