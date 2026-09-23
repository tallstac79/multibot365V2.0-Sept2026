"""Generic device session-state contract (site-agnostic).

The Android adapter reports its session into the backend; the backend never drives a
login UI. Only a fresh, explicit AUTHENTICATED report permits instruction progression.
Everything else - including missing, stale, malformed or contradictory reports - fails
closed as SESSION_REQUIRED. See docs/SESSION_CONTRACT.md for the wire format.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class SessionState(str, Enum):
    UNKNOWN = 'UNKNOWN'
    LOGGED_OUT = 'LOGGED_OUT'
    AUTHENTICATING = 'AUTHENTICATING'
    AUTHENTICATED = 'AUTHENTICATED'
    EXPIRED = 'EXPIRED'
    RESTRICTED = 'RESTRICTED'
    ERROR = 'ERROR'


# Legacy values already emitted by the proven live adapter (ready_state.session).
LEGACY_ALIASES = {'LOGGED_IN': SessionState.AUTHENTICATED}
DEFAULT_MAX_AGE_SECONDS = 120


@dataclass(frozen=True)
class SessionReport:
    device_id: str
    state: SessionState
    observed_at: str   # device observation time, ISO-8601 UTC
    source: str        # 'health' | 'result' | 'manual' | 'test'
    detail: str = ''


def _utc(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(value / 1000, timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Session observation time must include a timezone')
    return parsed.astimezone(timezone.utc)


def parse_report(device_id, payload, source):
    """Validate a device session object. Raises ValueError on anything malformed.

    Accepted: {"state": "...", "observed_at_ms": 1790000000000, "detail": "..."} or
    {"state": "...", "observed_at": "2026-09-23T10:00:00Z"}.
    """
    if not isinstance(device_id, str) or not device_id:
        raise ValueError('device_id required')
    if not isinstance(payload, dict):
        raise ValueError('Session payload must be an object')
    raw = payload.get('state')
    if not isinstance(raw, str):
        raise ValueError('Session state must be a string')
    state = LEGACY_ALIASES.get(raw.upper()) or SessionState(raw.upper())
    stamp = payload.get('observed_at_ms', payload.get('observed_at'))
    if stamp is None:
        raise ValueError('Session observation time required')
    observed = _utc(stamp)
    detail = payload.get('detail') or ''
    return SessionReport(device_id, state, observed.isoformat(), source, str(detail)[:500])


def gate(report, now, max_age_seconds=DEFAULT_MAX_AGE_SECONDS):
    """Return (permitted, reason). Uncertain means not permitted."""
    if report is None:
        return False, 'SESSION_REQUIRED: no session report from device'
    try:
        state = SessionState(report['state'] if isinstance(report, dict) else report.state)
        observed = _utc(report['observed_at'] if isinstance(report, dict) else report.observed_at)
    except (KeyError, ValueError, TypeError):
        return False, 'SESSION_REQUIRED: malformed stored session report'
    age = (now - observed).total_seconds()
    if age < -30:
        return False, 'SESSION_REQUIRED: session report timestamp is in the future'
    if age > max_age_seconds:
        return False, f'SESSION_REQUIRED: session report is {int(age)}s old (limit {max_age_seconds}s)'
    if state != SessionState.AUTHENTICATED:
        return False, f'SESSION_REQUIRED: device session {state.value}'
    return True, 'AUTHENTICATED'
