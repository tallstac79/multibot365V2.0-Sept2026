"""Configuration, fixture previews, and read-only repository adapters."""
from contextlib import contextmanager
import copy
import json
import math
import sqlite3
import subprocess
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlsplit, quote
from threading import Lock

from core.oddsnotifier_parser import parse_oddsnotifier, AlertFormatError, SYNTHETIC_ORDER_PROFILE
from tools.coordinator_client import Client

ROOT = Path(__file__).resolve().parents[1]
VERSION = '2.0-dashboard.1'
MARKETS = {'football': ['1X2', 'SPREAD', 'TOTALS'], 'basketball': ['MONEYLINE', 'SPREAD', 'TOTALS']}

def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def defaults():
    return {'global': {'enabled': True, 'default_stake': 1.0, 'allowed_slippage': 0.0, 'max_stake': 10.0},
            'sports': {sport: {'markets': {market: {'enabled': True, 'stake': None, 'minimum_ev': None,
                        'allowed_slippage': None} for market in markets}} for sport, markets in MARKETS.items()}}

def number(value, name, low, high, optional=False):
    if value is None and optional:
        return
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{name} must be a finite number between {low} and {high}')

def validate(config):
    if not isinstance(config, dict) or set(config) != {'global', 'sports'}:
        raise ValueError('Expected global and sports configuration')
    g = config['global']
    if not isinstance(g, dict) or set(g) != set(defaults()['global']) or type(g['enabled']) is not bool:
        raise ValueError('Invalid global settings')
    number(g['max_stake'], 'Maximum stake', .01, 100000)
    number(g['default_stake'], 'Default stake', .01, g['max_stake'])
    number(g['allowed_slippage'], 'Slippage (decimal price points)', 0, 1)
    if not isinstance(config['sports'], dict) or set(config['sports']) != set(MARKETS):
        raise ValueError('Expected football and basketball')
    for sport, markets in MARKETS.items():
        s = config['sports'][sport]
        if not isinstance(s, dict) or set(s) != {'markets'} or not isinstance(s['markets'], dict) or set(s['markets']) != set(markets):
            raise ValueError(f'Invalid markets for {sport}')
        for market, rule in s['markets'].items():
            if not isinstance(rule, dict) or set(rule) != {'enabled', 'stake', 'minimum_ev', 'allowed_slippage'} or type(rule['enabled']) is not bool:
                raise ValueError(f'Invalid {market} rule')
            number(rule['stake'], 'Market stake', .01, g['max_stake'], True)
            number(rule['minimum_ev'], 'Minimum displayed EV (%)', 0, 1000, True)
            number(rule['allowed_slippage'], 'Market slippage', 0, 1, True)
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
        return {'config': json.loads(payload), 'updated_at': timestamp}
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

def apply_rules(parsed, side, config, instruction_id, timestamp):
    """Preview only. Explicit synthetic side required; never infer a production target."""
    if not parsed or parsed['sample_provenance'] != 'synthetic' or not side:
        return None, 'Selection and quote ordering are unverified; no instruction produced'
    rule = config['sports'][parsed['sport']]['markets'][parsed['market']]
    g = config['global']
    if not g['enabled'] or not rule['enabled']:
        return None, 'Disabled by configuration'
    if rule['minimum_ev'] is not None and float(parsed['displayed_ev_percent']) < rule['minimum_ev']:
        return None, 'Displayed EV below configured minimum'
    selected = next((q for q in parsed['pinnacle']['quotes'] if q.get('side') == side), None)
    if not selected:
        return None, 'No explicit mapped quote for selection'
    from decimal import Decimal
    slippage = rule['allowed_slippage'] if rule['allowed_slippage'] is not None else g['allowed_slippage']
    minimum = max(Decimal('1.01'), Decimal(selected['price']) - Decimal(str(slippage)))
    return dict(instruction_id=instruction_id, source='OddsNotifier SAMPLE',
                **{k: parsed[k] for k in ('sport', 'competition', 'fixture', 'home', 'away', 'market')},
                side=side, line=parsed['displayed_line'], alert_price=selected['price'], minimum_price=str(minimum),
                stake=rule['stake'] if rule['stake'] is not None else g['default_stake'], created_at=timestamp,
                sample=True, dispatchable=False), None

def sample_alerts(config_snapshot, root=ROOT):
    manifest = json.loads((root / 'tests/fixtures/oddsnotifier_manifest.json').read_text(encoding='utf-8'))
    # Fixed sample receipt time: reload never makes an old message look newly received.
    received = '2026-09-23T08:00:00+00:00'
    cases = []
    for sample in manifest['samples']:
        sides = ['HOME', 'DRAW', 'AWAY'] if sample['file'] == 'oddsnotifier_football_ml.txt' else [
            'OVER' if sample['market'] == 'TOTALS' else 'HOME']
        for side in sides:
            cases.append((sample, side if sample['provenance'] == 'synthetic' else None, 'normal'))
    synthetic_spread = dict(manifest['samples'][0], provenance='synthetic')
    cases.append((synthetic_spread, 'HOME', 'synthetic_spread'))
    base = manifest['samples'][1]
    cases.extend([(base, None, 'malformed'), (base, None, 'ambiguous'), (base, 'HOME', 'duplicate'),
                  (base, 'HOME', 'stale'), (base, None, 'unrelated')])
    rows = []
    seen = set()
    for index, (sample, side, case) in enumerate(cases):
        raw = (root / 'tests/fixtures' / sample['file']).read_text(encoding='utf-8')
        if case == 'synthetic_spread': raw = raw.replace('Welling United', 'Sample United').replace('Cheshunt', 'Example Town')
        if case == 'malformed': raw = raw.replace('1.420', 'broken')
        if case == 'unrelated': raw = 'Service announcement: no odds in this message.'
        message_id = str(index + 1) if case != 'duplicate' else '2'
        identity = 'sample-' + message_id
        source_time = '2026-09-20T08:00:00+00:00' if case == 'stale' else received
        parsed, instruction, reason = None, None, None
        try:
            parsed = parse_oddsnotifier(raw, channel_id='-999', message_id=message_id,
                source_timestamp=source_time, sample_provenance=sample['provenance'],
                ordering_profile=SYNTHETIC_ORDER_PROFILE if side else None)
            status = 'PARSED' if parsed and side else 'AMBIGUOUS' if parsed else 'IGNORED'
            if parsed:
                instruction, reason = apply_rules(parsed, side, config_snapshot['config'], identity, received)
            source_key = ('-999', message_id)
            if source_key in seen:
                status, instruction, reason = 'DUPLICATE', None, 'Same sample channel/message ID as sample-2; no new instruction'
            elif datetime.fromisoformat(received) - datetime.fromisoformat(source_time) > timedelta(hours=24):
                status, instruction, reason = 'IGNORED', None, 'Stale sample (source older than 24 hours at recorded receipt)'
            elif status == 'PARSED' and instruction is None:
                status = 'IGNORED'
        except AlertFormatError as error:
            status, reason = 'INVALID', str(error)
        seen.add(('-999', message_id))
        p = parsed or {}
        row = dict(id=f'row-{index}', instruction_id=identity if instruction or case == 'duplicate' else None,
            received_at=received, source_message_id=message_id, source_timestamp=source_time,
            sport=p.get('sport'), competition=p.get('competition'), fixture=p.get('fixture'), market=p.get('market'),
            side=side, line=p.get('displayed_line'), alert_price=(instruction or {}).get('alert_price'),
            minimum_price=(instruction or {}).get('minimum_price'), displayed_ev=p.get('displayed_ev_percent'),
            status=status, raw_text=raw, parsed=parsed, instruction=instruction,
            warnings=p.get('unresolved', []) + ([reason] if reason else []),
            provenance={'mode': 'SAMPLE DATA', 'fixture': sample['file'], 'original': sample['provenance'],
                        'case': case, 'selection': 'explicit synthetic scenario' if side else 'unresolved'},
            applied_config=config_snapshot, previewed_at=now())
        row['timeline'] = [dict(stage='RECEIVED', timestamp=received),
            dict(stage='PARSED', timestamp=row['previewed_at'], detail='Replayed from fixture' if parsed else status),
            dict(stage='NORMALIZED', timestamp=row['previewed_at'] if parsed else None, detail='Parser schema v3 replay' if parsed else 'Not produced'),
            dict(stage='RULES_APPLIED', timestamp=row['previewed_at'], detail=reason or 'Sample preview using current config'),
            dict(stage='COORDINATOR_RESULT', timestamp=None, detail='Not submitted; sample only')]
        rows.append(row)
    return rows

class Health:
    def __init__(self, root=ROOT, client_factory=Client, network=None):
        self.root, self.client_factory = root, client_factory
        self.network = network or self.tailscale
        self.started = time.monotonic()
        self.last_success = self.reconnected = None
        self.was_online = None
        self.cached, self.cached_at, self.lock = None, 0, Lock()
    def tailscale(self):
        try:
            executable = Path('C:/Program Files/Tailscale/tailscale.exe')
            result = subprocess.run([str(executable) if executable.exists() else 'tailscale', 'status', '--json'],
                                    capture_output=True, text=True, timeout=3, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            return json.loads(result.stdout)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return {}
    def get(self):
        with self.lock:
            if self.cached is not None and time.monotonic() - self.cached_at < 5:
                return self.cached
            data, error, host = {}, None, None
            start = time.monotonic()
            try:
                config = json.loads((self.root / '.local/coordinator.json').read_text(encoding='utf-8-sig'))
                host = urlsplit(config['url']).hostname
                data = self.client_factory(config).health()
                if not isinstance(data, dict) or 'healthy' not in data:
                    raise ValueError('Malformed health response')
                self.last_success = now()
                if self.was_online is False: self.reconnected = now()
                online = True
            except Exception as exc:
                online, error = False, type(exc).__name__ + ': coordinator unavailable'
            latency = round((time.monotonic() - start) * 1000) if online else None
            self.was_online = online
            network = self.network()
            peer = next((p for p in network.get('Peer', {}).values() if p.get('DNSName', '').rstrip('.') == host), {})
            status = 'ONLINE' if online and data.get('healthy') else 'DEGRADED' if online else 'OFFLINE'
            self.cached = dict(dashboard={'version': VERSION, 'uptime_seconds': int(time.monotonic() - self.started), 'online': True},
                coordinator={'status': status, 'error': error, 'health': data},
                phone={'device_id': data.get('device_id'), 'status': status, 'tailscale_hostname': host,
                       'heartbeat_ms': data.get('heartbeat_ms'), 'latency_ms': latency, 'state': data.get('state'),
                       'app_version': data.get('app_version'), 'last_success': self.last_success},
                network={'mini_pc': network.get('BackendState', 'UNKNOWN'),
                         'phone': 'ONLINE' if peer.get('Online') else 'OFFLINE' if peer else 'UNKNOWN',
                         'transport': ('HTTP over Tailscale' if host and (host.endswith('.ts.net') or host.startswith('100.')) else 'Private HTTP') if host else 'UNKNOWN',
                         'last_reconnect': self.reconnected}, checked_at=now())
            self.cached_at = time.monotonic()
            return self.cached

def read_json(path):
    try: return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError): return None

def history(root=ROOT):
    rows = []
    for path in sorted((root / 'evidence').glob('**/*result*.json')):
        if 'dashboard' in path.parts: continue
        payload = read_json(path)
        if not isinstance(payload, dict) or not payload.get('instruction_id') or not payload.get('status'): continue
        selection = payload.get('selection') or {}
        if not isinstance(selection, dict): continue
        final = payload.get('final_state') or {}
        if not isinstance(final, dict): continue
        instruction = read_json(path.parent / 'instruction.json') or {}
        if not isinstance(instruction, dict) or instruction.get('instruction_id') != payload['instruction_id']: instruction = {}
        ready = payload.get('complete_execution_ready') or {}
        if not isinstance(ready, dict): ready = {}
        stamp = payload.get('timestamp_ms') or ready.get('timestamp_ms')
        try:
            timestamp = datetime.fromtimestamp(stamp / 1000, timezone.utc).isoformat() if isinstance(stamp, (int, float)) else None
        except (ValueError, OverflowError, OSError):
            timestamp = None
        links = [p for p in path.parent.iterdir() if p.suffix.lower() in ('.png', '.json', '.txt') and p.is_file()]
        rows.append(dict(instruction_id=payload['instruction_id'], time=timestamp,
            recorded_file_time=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            fixture=payload.get('fixture_name'), market=selection.get('market'), side=selection.get('side'), line=selection.get('line'),
            alert_price=instruction.get('alert_price'), observed_price=selection.get('price'), stake=final.get('stake'),
            status=payload['status'], stage=payload.get('stage'), duration_ms=payload.get('duration_ms'), device_id=payload.get('device_id'),
            failure_reason=payload.get('detail') if payload['status'] != 'PASS' else None,
            payload=payload, source=str(path.relative_to(root)).replace('\\', '/'), origin='RECORDED BACKEND RESULT',
            evidence=[{'name': p.name, 'url': '/api/evidence/' + quote(p.relative_to(root / 'evidence').as_posix(), safe='/')} for p in links]))
    return sorted(rows, key=lambda r: r['time'] or r['recorded_file_time'], reverse=True)

def log_entries(store, root=ROOT):
    entries = store.changes()
    for row in history(root):
        entries.append(dict(timestamp=row['time'] or row['recorded_file_time'], component='coordinator.recorded',
            severity='INFO' if row['status'] == 'PASS' else 'ERROR', instruction_id=row['instruction_id'], device_id=row['device_id'],
            message=f"{row['status']} / {row['stage']}: {row['failure_reason'] or row['instruction_id']}", detail=row['payload']))
    path = root / 'logs/multibot.log'
    if path.exists():
        import re
        with path.open('rb') as stream:
            stream.seek(max(0, path.stat().st_size - 65536))
            lines = stream.read().decode('utf-8', errors='replace').splitlines()[-100:]
        for line in lines:
            match = re.match(r'(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}) \[(.*?)\] (\w+): (.*)', line)
            if match:
                stamp, component, severity, message = match.groups()
                entries.append(dict(timestamp=datetime.strptime(stamp, '%d/%m/%Y %H:%M:%S').isoformat(),
                    component=component, severity=severity, message=message[:240], detail=message))
    return sorted(entries, key=lambda r: r['timestamp'], reverse=True)
