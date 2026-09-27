"""Compare the requested Bet365 quote with the phone's observed quote on the same side."""
from decimal import Decimal, InvalidOperation, ROUND_CEILING


def number(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError('nonfinite execution term')
    return result


def minimum_price(alert_price, *, net_percent=None, decimal_tolerance=None):
    price = number(alert_price)
    if price <= 1:
        raise ValueError('invalid alert odds')
    if net_percent is not None:
        pct = number(net_percent)
        if not 0 <= pct <= 100 or decimal_tolerance is not None:
            raise ValueError('invalid or competing price policies')
        floor = 1 + (price - 1) * (1 - pct / 100)
    else:
        limit = number(decimal_tolerance)
        if limit < 0:
            raise ValueError('invalid decimal tolerance')
        floor = price - limit
    # The device accepts two-decimal quotes. Never round below the exact floor.
    return max(Decimal('1.01'), floor).quantize(Decimal('.01'), rounding=ROUND_CEILING)


def line_allowance(market, alert_line, absolute, percent=None):
    cap = number(absolute)
    if cap < 0:
        raise ValueError('negative line allowance')
    if percent is not None:
        pct = number(percent)
        if market != 'SPREAD' or not 0 <= pct <= 100:
            raise ValueError('relative line allowance is only valid for spreads')
        cap = min(cap, abs(number(alert_line)) * pct / 100)
    return cap


def compare(request, live, *, odds_tolerance=None, line_tolerance=None,
            net_percent=None, line_percent=None):
    out = dict(acceptable=False, requested=request, live=live)
    try:
        market = request['market'].replace('TOTALS','TOTAL')
        if market != live['market'].replace('TOTALS','TOTAL') or request['side'] != live['side']:
            raise ValueError('market/side changed')
        if request['side'] not in {'SPREAD': ('HOME','AWAY'), 'TOTAL': ('OVER','UNDER'),
                                   'MONEYLINE': ('HOME','AWAY'), '1X2': ('HOME','DRAW','AWAY')}.get(market, ()):
            raise ValueError('invalid selection side')
        rp, lp = number(request['price']), number(live['price'])
        floor = minimum_price(rp, net_percent=net_percent, decimal_tolerance=odds_tolerance)
        if market in ('MONEYLINE', '1X2'):
            if line_percent is not None or any(v not in (None, '', 'NONE', 'null') for v in (request.get('line'), live.get('line'))):
                raise ValueError('Moneyline/1X2 cannot carry a handicap or relative line allowance')
            line_limit = Decimal(0)
        else:
            line_limit = line_allowance(market, request.get('line'), line_tolerance, line_percent)
        if min(rp,lp) <= 1:
            raise ValueError('invalid price/tolerance')
        odds_loss = max(Decimal(0), rp-lp)
        line_loss = Decimal(0)
        if market in ('SPREAD','TOTAL'):
            rl, ll = Decimal(str(request['line'])), Decimal(str(live['line']))
            if not rl.is_finite() or not ll.is_finite(): raise ValueError('invalid line')
            line_loss = max(Decimal(0), ll-rl if market=='TOTAL' and request['side']=='OVER' else rl-ll)
        acceptable = lp >= floor and line_loss <= line_limit
        out.update(acceptable=acceptable, minimum_live_price=str(floor), effective_line_allowance=str(line_limit),
                   net_payout_deterioration_percent=str(100 * odds_loss / (rp-1)),
                   odds_deterioration=str(odds_loss), line_deterioration=str(line_loss),
                   price_acceptable=lp >= floor, line_acceptable=line_loss <= line_limit,
                   reason='within configured tolerances' if acceptable else 'deterioration exceeds tolerance')
    except (KeyError, ValueError, TypeError, AttributeError, InvalidOperation):
        out['reason'] = 'quote identity, terms or configured tolerances missing/invalid'
    return out


def comparisons_for_result(request, result, policy):
    """Retain every observed quote, including failures; missing fresh terms stay unknown.

    Effective cap and minimum are bound to the original alert at evaluation time.
    Never substitute a previous observation for an explicitly unreadable fresh one.
    """
    observations = result.get('execution_observations')
    if not isinstance(observations, list) or not observations:
        observations = []
        for stage, key in [('selection', 'selection'), ('pretap', 'pretap')]:
            quote = result.get(key)
            if isinstance(quote, dict):
                quote = dict(quote)
                quote.setdefault('market', request['market'])
                quote.setdefault('side', request['side'])
                observations.append(dict(stage=stage, observed=quote))
        if not observations:
            observations = [dict(stage=result.get('stage'), observed=None)]
    comparisons = []
    for observation in observations:
        if not isinstance(observation, dict):
            observation = dict(stage='invalid observation', observed=None)
        quote = compare(request, observation.get('observed'),
                        odds_tolerance=policy.get('max_odds_deterioration'),
                        net_percent=policy.get('max_net_payout_deterioration_percent'),
                        line_tolerance=policy.get('max_line_deterioration'))
        quote.update(stage=observation.get('stage'), observed_at_ms=observation.get('observed_at_ms'),
                     device_outcome=result.get('status'), device_reason=result.get('detail'),
                     policy=policy, identity_verified=observation.get('identity_verified'))
        comparisons.append(quote)
    return comparisons
