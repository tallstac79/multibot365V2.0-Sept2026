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
VERSION = '2.0-dashboard.4'
MARKETS = {'football': ['1X2', 'SPREAD', 'TOTALS'], 'basketball': ['MONEYLINE', 'SPREAD', 'TOTALS']}

def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

from core.decision_support import Store, defaults, validate, apply_rules

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
                ordering_profile=SYNTHETIC_ORDER_PROFILE if side else sample.get('profile'), target_position=sample.get('target_position'))
            status = 'PARSED' if parsed and (side or parsed.get('target_side')) else 'AMBIGUOUS' if parsed else 'IGNORED'
            if parsed:
                instruction, reason = apply_rules(parsed, side or parsed.get('target_side'), config_snapshot['config'], identity, received, sample=not bool(sample.get('profile')))
                if instruction: instruction['sample'] = True; instruction['source'] = 'OddsNotifier fixture replay'
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
            side=side or p.get('target_side'), line=p.get('target_line') or p.get('displayed_line'), alert_price=(instruction or {}).get('alert_price'),
            minimum_price=(instruction or {}).get('minimum_price'), displayed_ev=p.get('displayed_ev_percent'),
            status=status, raw_text=raw, parsed=parsed, instruction=instruction,
            warnings=p.get('unresolved', []) + ([reason] if reason else []),
            provenance={'mode': 'SAMPLE DATA', 'fixture': sample['file'], 'original': sample['provenance'],
                        'case': case, 'selection': 'explicit synthetic scenario' if side else sample.get('target_confirmation', 'unresolved')},
            applied_config=config_snapshot, previewed_at=now())
        row['timeline'] = [dict(stage='RECEIVED', timestamp=received, detail='Sample receipt')]
        if parsed:
            row['timeline'] += [dict(stage='PARSED', timestamp=row['previewed_at'], detail='Fixture parser replay'),
                                dict(stage='NORMALIZED', timestamp=row['previewed_at'], detail=f"Parser schema v{parsed.get('schema_version')}")]
        if parsed and case not in ('duplicate', 'stale'):
            row['timeline'].append(dict(stage='RULES_APPLIED', timestamp=row['previewed_at'], detail=reason or 'Sample preview'))
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
                data = {}
                online, error = False, type(exc).__name__ + ': coordinator unavailable'
            latency = round((time.monotonic() - start) * 1000) if online else None
            self.was_online = online
            try:
                network = self.network()
                if not isinstance(network, dict): network = {}
            except Exception:
                network = {}
            peer = next((p for p in network.get('Peer', {}).values() if p.get('DNSName', '').rstrip('.') == host), {})
            status = 'ONLINE' if online and data.get('healthy') is True else 'DEGRADED' if online else 'OFFLINE'
            phone_status = status if online else 'DEGRADED' if peer.get('Online') else 'OFFLINE'
            self.cached = dict(dashboard={'version': VERSION, 'uptime_seconds': int(time.monotonic() - self.started), 'online': True},
                coordinator={'status': status, 'error': error, 'health': data},
                phone={'device_id': data.get('device_id') or peer.get('ID'),
                       'device_id_source': 'coordinator' if data.get('device_id') else 'Tailscale node ID' if peer.get('ID') else None,
                       'status': phone_status, 'tailscale_hostname': peer.get('DNSName', host),
                       'heartbeat_ms': data.get('heartbeat_ms'), 'latency_ms': latency, 'state': data.get('state'),
                       'app_version': data.get('app_version'), 'last_success': self.last_success},
                network={'mini_pc': network.get('BackendState', 'UNKNOWN'),
                         'mini_pc_hostname': network.get('Self', {}).get('DNSName'),
                         'phone_last_seen': peer.get('LastSeen'),
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
