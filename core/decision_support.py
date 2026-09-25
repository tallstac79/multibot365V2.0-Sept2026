"""Generic decision-support configuration and human recommendations; no execution."""
from contextlib import contextmanager
import copy
import json
import math
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

MARKETS = {'football': ['1X2', 'SPREAD', 'TOTALS'], 'basketball': ['MONEYLINE', 'SPREAD', 'TOTALS']}

def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def defaults():
    return {'global': {'enabled': True, 'default_stake': 1.0, 'allowed_slippage': 0.0, 'max_stake': 10.0,
                       'stale_alert_seconds': 300, 'event_timezone': None, 'min_line_advantage': 1.0,
                       'min_sharp_movement': None},
            'sports': {sport: {'markets': {market: {'enabled': True, 'stake': None, 'minimum_ev': None,
                        'allowed_slippage': None, 'min_price': None, 'max_price': None}
                        for market in markets}} for sport, markets in MARKETS.items()}}

# Keys added after configurations were first persisted; older stored configs are
# upgraded with these defaults. Unknown keys are still rejected.
GLOBAL_ADDED = ('stale_alert_seconds', 'event_timezone', 'min_line_advantage', 'min_sharp_movement')
MARKET_ADDED = ('min_price', 'max_price')

def upgrade(config):
    if not isinstance(config, dict):
        return config
    config = copy.deepcopy(config)
    base = defaults()
    if isinstance(config.get('global'), dict) and set(base['global']) - set(GLOBAL_ADDED) <= set(config['global']):
        for key in GLOBAL_ADDED:
            config['global'].setdefault(key, base['global'][key])
    for sport in (config.get('sports') if isinstance(config.get('sports'), dict) else {}).values():
        for rule in (sport.get('markets') if isinstance(sport, dict) and isinstance(sport.get('markets'), dict) else {}).values():
            if isinstance(rule, dict):
                for key in MARKET_ADDED:
                    rule.setdefault(key, None)
    return config

def timezone_name(value):
    if value is None:
        return
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        if not isinstance(value, str) or not value:
            raise ValueError
        ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError('Event timezone must be an IANA name such as Europe/London, or blank')

def number(value, name, low, high, optional=False):
    if value is None and optional:
        return
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{name} must be a finite number between {low} and {high}')

def validate(config):
    config = upgrade(config)
    if not isinstance(config, dict) or set(config) != {'global', 'sports'}:
        raise ValueError('Expected global and sports configuration')
    g = config['global']
    if not isinstance(g, dict) or set(g) != set(defaults()['global']) or type(g['enabled']) is not bool:
        raise ValueError('Invalid global settings')
    number(g['max_stake'], 'Maximum stake', .01, 100000)
    number(g['default_stake'], 'Default stake', .01, g['max_stake'])
    number(g['allowed_slippage'], 'Slippage (decimal price points)', 0, 1)
    number(g['stale_alert_seconds'], 'Stale alert limit (seconds)', 5, 86400)
    timezone_name(g['event_timezone'])
    number(g['min_line_advantage'], 'Minimum favourable line advantage (points)', 0.5, 50)
    number(g['min_sharp_movement'], 'Minimum Pinnacle opening movement (points)', 0, 100, optional=True)
    if not isinstance(config['sports'], dict) or set(config['sports']) != set(MARKETS):
        raise ValueError('Expected football and basketball')
    for sport, markets in MARKETS.items():
        s = config['sports'][sport]
        if not isinstance(s, dict) or set(s) != {'markets'} or not isinstance(s['markets'], dict) or set(s['markets']) != set(markets):
            raise ValueError(f'Invalid markets for {sport}')
        for market, rule in s['markets'].items():
            if not isinstance(rule, dict) or set(rule) != set(defaults()['sports'][sport]['markets'][market]) or type(rule['enabled']) is not bool:
                raise ValueError(f'Invalid {market} rule')
            number(rule['stake'], 'Market stake', .01, g['max_stake'], True)
            number(rule['minimum_ev'], 'Minimum displayed EV (%)', 0, 1000, True)
            number(rule['allowed_slippage'], 'Market slippage', 0, 1, True)
            number(rule['min_price'], 'Market minimum alert price', 1.01, 1000, True)
            number(rule['max_price'], 'Market maximum alert price', 1.01, 1000, True)
            if rule['min_price'] is not None and rule['max_price'] is not None and rule['min_price'] > rule['max_price']:
                raise ValueError(f'{sport} {market}: minimum price exceeds maximum price')
    return copy.deepcopy(config)

class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS config (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT, updated_at TEXT);'
                             'CREATE TABLE IF NOT EXISTS changes (id INTEGER PRIMARY KEY, timestamp TEXT, payload TEXT);')
            db.execute('INSERT OR IGNORE INTO config VALUES (1,?,?)', (json.dumps(defaults()), now()))
    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()
    def get(self):
        with self.connect() as db:
            payload, timestamp = db.execute('SELECT payload, updated_at FROM config WHERE id=1').fetchone()
        return {'config': upgrade(json.loads(payload)), 'updated_at': timestamp}
    def save(self, config):
        payload, timestamp = json.dumps(validate(config)), now()
        with self.connect() as db:
            db.execute('UPDATE config SET payload=?, updated_at=? WHERE id=1', (payload, timestamp))
            db.execute('INSERT INTO changes(timestamp,payload) VALUES (?,?)', (timestamp, payload))
        return self.get()
    def changes(self):
        with self.connect() as db:
            return [{'timestamp': t, 'component': 'dashboard.config', 'severity': 'INFO', 'message': 'Configuration saved',
                     'detail': json.loads(p)} for t, p in db.execute('SELECT timestamp,payload FROM changes ORDER BY id DESC LIMIT 100')]

def apply_rules(parsed, side, config, instruction_id, timestamp, *, sample=True):
    """Human recommendation only; never infer a target or dispatch an instruction."""
    config = validate(config)
    if not parsed or not side or (sample and parsed.get('sample_provenance') != 'synthetic'):
        return None, 'Selection and quote ordering are unverified; no instruction produced'
    rule = config['sports'][parsed['sport']]['markets'][parsed['market']]
    g = config['global']
    if not g['enabled'] or not rule['enabled']:
        return None, 'Disabled by configuration'
    if rule['minimum_ev'] is not None and float(parsed['displayed_ev_percent']) < rule['minimum_ev']:
        return None, 'Displayed EV below configured minimum'
    if not sample:
        if parsed.get('target_side') != side or not parsed.get('quote_mapping', {}).get('production_verified'):
            return None, 'Production target/quote mapping is unresolved'
        selected = {'price': parsed.get('alert_price')} if parsed.get('alert_price') else None
    else:
        selected = next((q for q in parsed['pinnacle']['quotes'] if q.get('side') == side), None)
    if not selected:
        return None, 'No explicit mapped quote for selection'
    from decimal import Decimal
    slippage = rule['allowed_slippage'] if rule['allowed_slippage'] is not None else g['allowed_slippage']
    from decimal import InvalidOperation
    try:
        price = Decimal(str(selected['price']))
        if not price.is_finite() or price <= 1: return None, 'Invalid decimal target price'
    except (InvalidOperation, TypeError, ValueError):
        return None, 'Invalid decimal target price'
    minimum = max(Decimal('1.01'), price - Decimal(str(slippage)))
    return dict(instruction_id=instruction_id, source='OddsNotifier SAMPLE' if sample else 'OddsNotifier',
                **{k: parsed[k] for k in ('sport', 'competition', 'fixture', 'home', 'away', 'market')},
                side=side, line=parsed['displayed_line'] if sample else parsed.get('target_line'), alert_price=selected['price'], minimum_price=str(minimum),
                stake=rule['stake'] if rule['stake'] is not None else g['default_stake'], created_at=timestamp,
                sample=sample, dispatchable=False), None
