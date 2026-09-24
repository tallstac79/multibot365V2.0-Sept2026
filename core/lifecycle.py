"""Canonical instruction lifecycle for the unattended MultiBot365 pipeline.

One state machine; every transition is timestamped by the store. Device, coordinator
and confirmation enums are *mapped* onto these states, never replaced: the original
backend stage/status is always kept alongside the canonical state.

Final action (Place Bet) adds an approval step and a placement outcome:

    QUEUED -> AWAITING_APPROVAL -> APPROVED -> DISPATCHED -> ... -> COMPLETED (bet placed)
    QUEUED -> APPROVED (auto-approval within limits)
    QUEUED -> DISPATCHED (READY-only mode, no final action)

Once the Place Bet tap may have happened, an uncertain outcome is PLACEMENT_UNKNOWN (not
terminal): only a My Bets reconciliation may end it, and nothing is ever re-tapped.
"""
from enum import Enum


class State(str, Enum):
    RECEIVED = 'RECEIVED'
    PARSED = 'PARSED'
    RULES_APPLIED = 'RULES_APPLIED'
    QUEUED = 'QUEUED'
    AWAITING_APPROVAL = 'AWAITING_APPROVAL'
    APPROVED = 'APPROVED'
    DISPATCHED = 'DISPATCHED'
    DEVICE_ACTIVE = 'DEVICE_ACTIVE'
    READY = 'READY'
    PLACEMENT_UNKNOWN = 'PLACEMENT_UNKNOWN'
    # Terminal
    COMPLETED = 'COMPLETED'            # final action: bet placed (receipt and/or My Bets)
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
    INSUFFICIENT_FUNDS = 'INSUFFICIENT_FUNDS'
    STAKE_LIMITED = 'STAKE_LIMITED'
    NOT_PLACED = 'NOT_PLACED'          # tap happened; reconciliation proved no bet exists


ACTIVE = frozenset({State.RECEIVED, State.PARSED, State.RULES_APPLIED, State.QUEUED, State.AWAITING_APPROVAL,
                    State.APPROVED, State.DISPATCHED, State.DEVICE_ACTIVE, State.READY, State.PLACEMENT_UNKNOWN})
TERMINAL = frozenset(State) - ACTIVE
# Forward edges between non-terminal states. Any non-terminal state may end in any terminal state.
NEXT = {
    State.RECEIVED: {State.PARSED},
    State.PARSED: {State.RULES_APPLIED},
    State.RULES_APPLIED: {State.QUEUED},
    State.QUEUED: {State.AWAITING_APPROVAL, State.APPROVED, State.DISPATCHED},
    State.AWAITING_APPROVAL: {State.APPROVED},
    State.APPROVED: {State.DISPATCHED},
    State.DISPATCHED: {State.DEVICE_ACTIVE, State.READY, State.PLACEMENT_UNKNOWN},  # DEVICE_ACTIVE is optional
    State.DEVICE_ACTIVE: {State.READY, State.PLACEMENT_UNKNOWN},
    State.READY: set(),
    State.PLACEMENT_UNKNOWN: set(),
}
# Kept for callers that list the READY-only progression.
ACTIVE_ORDER = [State.RECEIVED, State.PARSED, State.RULES_APPLIED, State.QUEUED,
                State.DISPATCHED, State.DEVICE_ACTIVE, State.READY]
# States in which the device may already have acted. Superseding/cancelling these is
# forbidden: only a device result, reconciliation or a timeout may end them.
DEVICE_OWNED = frozenset({State.DISPATCHED, State.DEVICE_ACTIVE, State.READY, State.PLACEMENT_UNKNOWN})


def is_terminal(state):
    return State(state) in TERMINAL


def allowed(current, target):
    current, target = State(current), State(target)
    if current in TERMINAL:
        return False
    if target in TERMINAL:
        return True
    return target in NEXT[current]


# Existing coordinator/live-adapter result stages -> canonical terminal state.
# PASS and DUPLICATE are handled by the result interpreter, not this table.
DEVICE_STAGE_MAP = {
    'PRICE_CHANGED': State.PRICE_CHANGED, 'BELOW_MINIMUM': State.PRICE_CHANGED,
    'LINE_CHANGED': State.PRICE_CHANGED, 'SELECTION_CHANGED': State.PRICE_CHANGED,
    'SUSPENDED': State.SUSPENDED, 'UNAVAILABLE': State.SUSPENDED,
    'MARKET_SUSPENDED': State.SUSPENDED, 'SELECTION_UNAVAILABLE': State.SUSPENDED,
    'TARGET_NOT_FOUND': State.TARGET_NOT_FOUND, 'NO_FIXTURE_FOUND': State.TARGET_NOT_FOUND,
    'WRONG_EVENT': State.TARGET_NOT_FOUND, 'EVENT_NOT_VERIFIED': State.TARGET_NOT_FOUND,
    'SPORTS_RESULTS_NOT_FOUND': State.TARGET_NOT_FOUND, 'WRONG_SPORT': State.TARGET_NOT_FOUND,
    'MY_BETS_UNAVAILABLE': State.UNKNOWN,
    'AMBIGUOUS_FIXTURE': State.AMBIGUOUS_TARGET,
    'INVALID_INSTRUCTION': State.REJECTED, 'STAKE_REJECTED': State.REJECTED,
    'CONFIRMATION_REQUIRED': State.REJECTED, 'STAKE_CAP_EXCEEDED': State.REJECTED,
    'BETSLIP_NOT_SINGLE': State.REJECTED,
    'INSUFFICIENT_BALANCE': State.INSUFFICIENT_FUNDS, 'INSUFFICIENT_FUNDS': State.INSUFFICIENT_FUNDS,
    'STAKE_LIMITED': State.STAKE_LIMITED,
    'LOGIN_FAILED': State.SESSION_REQUIRED, 'SESSION_REQUIRED': State.SESSION_REQUIRED,
    'SESSION_EXPIRED': State.SESSION_REQUIRED,
    'TIMEOUT': State.TIMEOUT,
    # INTERNAL_ERROR, CLICK_FAILED, FOCUS_FAILED, INPUT_FAILED, TEXT_NOT_VERIFIED and any
    # unrecognised stage map to UNKNOWN: the device outcome cannot be trusted.
}

# Phone placement outcomes after a Place Bet tap (placement.outcome).
PLACEMENT_OUTCOME_MAP = {
    'PLACED': State.COMPLETED,
    'INSUFFICIENT_FUNDS': State.INSUFFICIENT_FUNDS,
    'PRICE_CHANGED': State.PRICE_CHANGED, 'LINE_CHANGED': State.PRICE_CHANGED,
    'STAKE_LIMITED': State.STAKE_LIMITED,
    'SUSPENDED': State.SUSPENDED,
    'SESSION_EXPIRED': State.SESSION_REQUIRED,
    'REJECTED': State.REJECTED,
    # PLACEMENT_UNKNOWN and anything unrecognised -> PLACEMENT_UNKNOWN (reconcile)
}
# 0.6.18-0.6.28 phones report place_bet_result instead of a placement object.
LEGACY_PLACE_BET_RESULT = {'PLACE_BET_SUBMITTED': 'PLACED', 'INSUFFICIENT_BALANCE': 'INSUFFICIENT_FUNDS'}

# tools.confirmation.schema.DecisionStatus -> canonical state (APPROVED/PENDING are not terminal).
CONFIRMATION_MAP = {
    'REJECTED': State.REJECTED, 'EXPIRED': State.STALE, 'DUPLICATE': State.DUPLICATE,
    'PRICE_INVALID': State.PRICE_CHANGED, 'STATE_INVALID': State.UNKNOWN,
    'TIMEOUT': State.TIMEOUT, 'INTERNAL_ERROR': State.UNKNOWN,
}


def placement_of(result):
    """Normalised placement dict from a device result, or None if no tap can have happened.

    Returns {'tapped': bool|None, 'outcome': str, ...}. tapped None means the result does
    not say (treated as 'may have tapped' by dispatch-mode callers).
    """
    if not isinstance(result, dict):
        return None
    placement = result.get('placement')
    if isinstance(placement, dict):
        return dict(placement)
    if 'place_bet_tapped' in result or 'place_bet_result' in result:
        legacy = result.get('place_bet_result')
        tapped = result.get('place_bet_tapped')
        return dict(tapped=True if tapped is True else False if tapped is False else None,
                    outcome=LEGACY_PLACE_BET_RESULT.get(legacy, 'PLACEMENT_UNKNOWN') if tapped else 'NOT_TAPPED',
                    legacy_result=legacy, detail=result.get('place_bet_detail'))
    # The PLACE_BET stage is checkpointed before the tap. If the device's own stage record
    # never reached it, no tap can have happened.
    progress = result.get('progress') if isinstance(result.get('progress'), dict) else {}
    stages = progress.get('stages')
    if isinstance(stages, list) and stages and all(isinstance(s, dict) for s in stages):
        reached = {s.get('stage') for s in stages} | {result.get('device_stage'), progress.get('stage')}
        if 'PLACE_BET' not in reached:
            return dict(tapped=False, outcome='NOT_TAPPED', basis='progress stages never reached PLACE_BET')
    return None


def interpret_device_result(result, *, final_action=False):
    """Map a coordinator GET /instructions/ID payload to (state, reason, observed_price).

    Returns (None, reason, None) when the payload is a non-terminal DUPLICATE echo.
    Raises ValueError for a malformed payload; callers fail closed (UNKNOWN, or
    PLACEMENT_UNKNOWN for a final-action instruction).

    final_action=True: the instruction may have tapped Place Bet. Only a result that
    proves no tap happened (placement.tapped is False) may use the ordinary mapping.
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
    placement = placement_of(result) or {}
    observed = placement.get('odds') or selection.get('price') or ready.get('price') or final.get('price')
    if stage == 'DUPLICATE' and status == 'FAIL':
        return None, reason, observed
    if final_action:
        if placement.get('tapped') is False:
            pass  # provably nothing tapped: ordinary mapping below
        elif placement.get('tapped') is True:
            outcome = placement.get('outcome') or 'PLACEMENT_UNKNOWN'
            state = PLACEMENT_OUTCOME_MAP.get(outcome, State.PLACEMENT_UNKNOWN)
            detail_text = placement.get('detail') or detail
            return state, f'{outcome}: {detail_text}' if detail_text else outcome, observed
        else:
            # The tap may or may not have happened: never guess, reconcile.
            return State.PLACEMENT_UNKNOWN, f'Placement not provable from result ({reason})', observed
    if status == 'PASS':
        if result.get('wager_submitted') is True or final.get('wager_submitted') is True:
            return State.COMPLETED, reason, observed
        if ready.get('state') == 'READY' or final.get('state') == 'READY' or \
                result.get('complete_execution_ready') or detail in ('READY_STATE', 'COMPLETE_EXECUTION_READY'):
            return State.READY, reason, observed
        return State.UNKNOWN, 'PASS without READY or wager evidence: ' + reason, observed
    return DEVICE_STAGE_MAP.get(stage, State.UNKNOWN), reason, observed
