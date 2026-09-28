"""Desktop worker as a coordinator routing target (desktop-chrome), behind a flag that is OFF by default.

Settings.desktop_routing_enabled (pipeline.json -> pipeline.desktop_routing_enabled) = False: tools.pipeline_service
.gateway_for returns the phone's CoordinatorGateway exactly as before and nothing here is constructed. Only with the flag
ON does RoutingGateway exist, and even then new work goes to the desktop only while it is routable (healthy, ready, no
blocked_reason, IDLE, nothing running) AND bound to the expected worker_id and account fingerprint
(desktop_expected_worker_id / desktop_expected_account_fingerprint, both required); otherwise the phone gets it.
A PLACE_HELD always follows its hold's target; results are read from the target that took the instruction.

Tests and supervised runs use the explicit manual path instead (tools/desktop_route.py), which talks to the desktop
directly and never touches the pipeline's routing.
"""
import json
from pathlib import Path

from core.device_gateway import CoordinatorGateway

DESKTOP_CONFIG = Path('.local/desktop_worker.json')
ROUTES = Path('.local/device_routes.json')


def routable(health, device_id='desktop-chrome', expected_worker_id='', expected_account_fingerprint=''):
    """(ok, reason) for sending NEW work to the desktop worker, from its /health."""
    if not isinstance(health, dict):
        return False, 'no health'
    if health.get('healthy') is not True:
        return False, f"not healthy ({health.get('blocked_reason') or 'unknown'})"
    if health.get('ready') is not True:
        return False, f"not ready ({health.get('blocked_reason') or health.get('state')})"
    if health.get('blocked_reason'):
        return False, f"blocked ({health['blocked_reason']})"
    if health.get('state') != 'IDLE' or health.get('current_instruction'):
        return False, f"busy ({health.get('state')}, {health.get('current_instruction')})"
    if health.get('device_id') != device_id:
        return False, f"device_id {health.get('device_id')!r} is not {device_id!r}"
    if not expected_worker_id or health.get('worker_id') != expected_worker_id:
        return False, 'worker_id binding missing or different'
    if not expected_account_fingerprint or health.get('account_fingerprint') != expected_account_fingerprint:
        return False, 'account fingerprint binding missing or different'
    return True, 'routable'


def desktop_config(path=DESKTOP_CONFIG, host='127.0.0.1'):
    """{url, token} for the coordinator client (the token is only passed on, never printed)."""
    cfg = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    return dict(url=f"http://{host}:{cfg.get('port', 8768)}", token=cfg['token'])


class DesktopGateway(CoordinatorGateway):
    """The desktop worker behind the phone coordinator's own HTTP contract (same client, auth, ID rules)."""

    def __init__(self, config=None, config_path=DESKTOP_CONFIG, **kw):
        super().__init__(config=config or desktop_config(config_path), **kw)


class RoutingGateway:
    """Flag ON only: per-tick choice between the phone and the desktop, sticky per instruction."""

    def __init__(self, phone, desktop, settings, routes_path=ROUTES):
        self.phone, self.desktop, self.s = phone, desktop, settings
        self.routes_path = Path(routes_path)
        self.routes = self._load()
        self.target, self.reason = 'phone', 'not selected yet'

    def _load(self):
        try:
            return json.loads(self.routes_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}

    def _save(self):
        try:
            self.routes_path.parent.mkdir(parents=True, exist_ok=True)
            self.routes_path.write_text(json.dumps(self.routes, indent=1), encoding='utf-8')
        except OSError:
            pass

    def select(self):
        if not getattr(self.s, 'desktop_routing_enabled', False):
            self.target, self.reason = 'phone', 'desktop routing disabled'
            return self.target
        try:
            h = self.desktop.health()
        except Exception as e:
            self.target, self.reason = 'phone', f'desktop health failed: {type(e).__name__}'
            return self.target
        ok, why = routable(h, self.s.desktop_device_id, self.s.desktop_expected_worker_id, self.s.desktop_expected_account_fingerprint)
        self.target, self.reason = ('desktop' if ok else 'phone'), why
        return self.target

    def _gw(self, target):
        return self.desktop if target == 'desktop' else self.phone

    def health(self):
        target = self.select()
        h = dict(self._gw(target).health())
        h['routed_to'], h['routing_reason'] = target, self.reason
        return h

    def submit(self, payload):
        held = payload.get('held_instruction_id')
        target = self.routes.get(held) if held else None
        target = target or self.target
        reply = self._gw(target).submit(payload)
        self.routes[payload['instruction_id']] = target
        self._save()
        return reply

    def result(self, instruction_id):
        return self._gw(self.routes.get(instruction_id, 'phone')).result(instruction_id)


def gateway(phone, settings, desktop_factory=DesktopGateway):
    """What the pipeline service uses: the phone gateway itself while the flag is OFF (unchanged behaviour)."""
    if not getattr(settings, 'desktop_routing_enabled', False):
        return phone
    return RoutingGateway(phone, desktop_factory(), settings)
