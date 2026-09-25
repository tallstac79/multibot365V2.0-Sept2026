"""Compare the requested Bet365 quote with the phone's observed quote on the same side."""
from decimal import Decimal, InvalidOperation


def compare(request, live, *, odds_tolerance, line_tolerance):
    out = dict(acceptable=False, requested=request, live=live)
    try:
        market = request['market'].replace('TOTALS','TOTAL')
        if market != live['market'].replace('TOTALS','TOTAL') or request['side'] != live['side']:
            raise ValueError('market/side changed')
        rp, lp = Decimal(str(request['price'])), Decimal(str(live['price']))
        odds_limit, line_limit = Decimal(str(odds_tolerance)), Decimal(str(line_tolerance))
        if not all(v.is_finite() for v in (rp,lp,odds_limit,line_limit)) or min(rp,lp) <= 1 or min(odds_limit,line_limit) < 0:
            raise ValueError('invalid price/tolerance')
        odds_loss = max(Decimal(0), rp-lp)
        line_loss = Decimal(0)
        if market in ('SPREAD','TOTAL'):
            rl, ll = Decimal(str(request['line'])), Decimal(str(live['line']))
            if not rl.is_finite() or not ll.is_finite(): raise ValueError('invalid line')
            line_loss = max(Decimal(0), ll-rl if market=='TOTAL' and request['side']=='OVER' else rl-ll)
        out.update(acceptable=odds_loss <= odds_limit and line_loss <= line_limit,
                   odds_deterioration=str(odds_loss), line_deterioration=str(line_loss),
                   reason='within configured tolerances' if odds_loss<=odds_limit and line_loss<=line_limit else 'deterioration exceeds tolerance')
    except (KeyError, ValueError, TypeError, InvalidOperation):
        out['reason'] = 'quote identity, terms or configured tolerances missing/invalid'
    return out
