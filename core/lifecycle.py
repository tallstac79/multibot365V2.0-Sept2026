"""Canonical instruction lifecycle for the unattended MultiBot365 pipeline.

One state machine; every transition is timestamped by the store. Device, coordinator
and confirmation enums are *mapped* onto these states, never replaced: the original
backend stage/status is always kept alongside the canonical state.
"""
from enum import Enum


class State(str, Enum):
    RECEIVED = 'RECEIVED'
    PARSED = 'PARSED'
    RULES_APPLIED = 'RULES_APPLIED'
    QUEUED = 'QUEUED'
    DISPATCHED = 'DISPATCHED'
    DEVICE_ACTIVE = 'DEVICE_ACTIVE'
    READY = 'READY'
    # Terminal
    COMPLETED = 'COMPLETED'
    REJECTED = 'REJECTED'
    PRICE_CHANGED = 'PRICE_CHANGED'
    SUSPENDED = 'SUSPENDED'
    STALE = 'STALE'
    TARGET_NOT_FOUND = 'TARGET_NOT_FOUND'
    AMBIGUOUS_TARGET = 'AMBIGUOUS_TARGET'
    SESSION_REQUIRED = 'SESSION_REQUIRED'
    DEVICE_OFFLINE = 'DEVICE_OFFLINE'
    TIMEOUT = 'TIMEOUT'
    DUPLICATE = 'DUPLICATE'
    UNKNOWN = 'UNKNOWN'


ACTIVE_ORDER = [State.RECEIVED, State.PARSED, State.RULES_APPLIED, State.QUEUED,
                State.DISPATCHED, State.DEVICE_ACTIVE, State.READY]
TERMINAL = frozenset(State) - frozenset(ACTIVE_ORDER)
# States in which the device may already have acted. Superseding/cancelling these is
# forbidden: only a device result or a timeout may end them.
DEVICE_OWNED = frozenset({State.DISPATCHED, State.DEVICE_ACTIVE, State.READY})


def is_terminal(state):
    return State(state) in TERMINAL


def allowed(current, target):
    """Forward-only progression; any non-terminal state may end in any terminal state."""
    current, target = State(current), State(target)
    if current in TERMINAL:
        return False
    if target in TERMINAL:
        return True
    if current == State.DISPATCHED and target == State.READY:
        return True  # DEVICE_ACTIVE is optional: not every adapter reports it.
    return ACTIVE_ORDER.index(target) == ACTIVE_ORDER.index(current) + 1


# Existing coordinator/live-adapter result stages -> canonical terminal state.
# PASS and DUPLICATE are handled by the result interpreter, not this table.
DEVICE_STAGE_MAP = {
    'PRICE_CHANGED': State.PRICE_CHANGED, 'BELOW_MINIMUM': State.PRICE_CHANGED,
    'LINE_CHANGED': State.PRICE_CHANGED, 'SELECTION_CHANGED': State.PRICE_CHANGED,
    'SUSPENDED': State.SUSPENDED, 'UNAVAILABLE': State.SUSPENDED,
    'TARGET_NOT_FOUND': State.TARGET_NOT_FOUND, 'NO_FIXTURE_FOUND': State.TARGET_NOT_FOUND,
    'WRONG_EVENT': State.TARGET_NOT_FOUND, 'EVENT_NOT_VERIFIED': State.TARGET_NOT_FOUND,
    'AMBIGUOUS_FIXTURE': State.AMBIGUOUS_TARGET,
    'INVALID_INSTRUCTION': State.REJECTED, 'STAKE_REJECTED': State.REJECTED,
    'INSUFFICIENT_BALANCE': State.REJECTED,
    'LOGIN_FAILED': State.SESSION_REQUIRED, 'SESSION_REQUIRED': State.SESSION_REQUIRED,
    'TIMEOUT': State.TIMEOUT,
    # INTERNAL_ERROR, CLICK_FAILED, FOCUS_FAILED, INPUT_FAILED, TEXT_NOT_VERIFIED and any
    # unrecognised stage map to UNKNOWN: the device outcome cannot be trusted.
}

# tools.confirmation.schema.DecisionStatus -> canonical state (APPROVED/PENDING are not terminal).
CONFIRMATION_MAP = {
    'REJECTED': State.REJECTED, 'EXPIRED': State.STALE, 'DUPLICATE': State.DUPLICATE,
    'PRICE_INVALID': State.PRICE_CHANGED, 'STATE_INVALID': State.UNKNOWN,
    'TIMEOUT': State.TIMEOUT, 'INTERNAL_ERROR': State.UNKNOWN,
}


def interpret_device_result(result):
    """Map a coordinator GET /instructions/ID payload to (state, reason, observed_price).

    Returns (None, reason, None) when the payload is a non-terminal DUPLICATE echo.
    Raises ValueError for a malformed payload; callers fail closed to UNKNOWN.
    """
    if not isinstance(result, dict):
        raise ValueError('Result payload is not an object')
    status, stage = result.get('status'), result.get('stage')
    if status not in ('PASS', 'FAIL') or not isinstance(stage, str) or not stage:
        raise ValueError('Result payload lacks PASS/FAIL status and stage')
    detail = result.get('detail')
    reason = f'{stage}: {detail}' if detail else stage
    ready = result.get('ready_state') if isinstance(result.get('ready_state'), dict) else {}
    final = result.get('final_state') if isinstance(result.get('final_state'), dict) else {}
    selection = result.get('selection') if isinstance(result.get('selection'), dict) else {}
    observed = selection.get('price') or ready.get('price') or final.get('price')
    if status == 'PASS':
        if result.get('wager_submitted') is True or final.get('wager_submitted') is True:
            return State.COMPLETED, reason, observed
        if ready.get('state') == 'READY' or final.get('state') == 'READY' or \
                result.get('complete_execution_ready') or detail in ('READY_STATE', 'COMPLETE_EXECUTION_READY'):
            return State.READY, reason, observed
        return State.UNKNOWN, 'PASS without READY or wager evidence: ' + reason, observed
    if stage == 'DUPLICATE':
        return None, reason, observed
    return DEVICE_STAGE_MAP.get(stage, State.UNKNOWN), reason, observed
