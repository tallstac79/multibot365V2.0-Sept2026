"""Deterministic fakes for pipeline tests: clock, coordinator gateway, Telegram sender."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.decision_support import defaults
from core.pipeline import Pipeline, Settings, SourceMessage

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = json.loads((ROOT / 'evidence/dashboard/telegram-basketball-observed.json').read_text(encoding='utf-8'))
MELBOURNE = next(m for m in SNAPSHOT if m['message_id'] == '67894')   # OVER 190.5 @ 2.20, EV 113.52
RYTAS = next(m for m in SNAPSHOT if m['message_id'] == '67895')       # HOME -18.5 @ 1.83 (alt. line)
T0 = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
HEALTHY = {'healthy': True, 'state': 'IDLE', 'current_instruction': None}


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


class FakeGateway:
    """Coordinator stand-in. Scripted health/submit/result behaviour; records every call."""

    def __init__(self, clock):
        self.clock = clock
        self.health_error = None           # Exception -> coordinator unreachable
        self.health_extra = {}             # merged into the healthy payload
        self.session = 'AUTHENTICATED'     # None -> no session object reported
        self.session_age = 0               # seconds before "now" the phone observed it
        self.submitted, self.polled = [], []
        self.results = {}                  # instruction_id -> payload (or Exception to raise)
        self.submit_error = None

    def health(self):
        if self.health_error:
            raise self.health_error
        value = dict(HEALTHY, **self.health_extra)
        if self.session is not None:
            observed = self.clock() - timedelta(seconds=self.session_age)
            value['session'] = {'state': self.session, 'observed_at': observed.isoformat()}
        return value

    def submit(self, payload):
        self.submitted.append(payload)
        if self.submit_error:
            raise self.submit_error
        return {'instruction_id': payload['instruction_id'], 'acknowledged': True, 'state': 'ACCEPTED'}

    def result(self, instruction_id):
        self.polled.append(instruction_id)
        value = self.results.get(instruction_id)
        if isinstance(value, Exception):
            raise value
        return value


def ready_result(instruction_id, price='2.20', session_state='LOGGED_IN'):
    return {'instruction_id': instruction_id, 'status': 'PASS', 'stage': 'PASS', 'detail': 'READY_STATE',
            'held': True, 'event_context': {'home':'SE Melbourne Phoenix','away':'Melbourne United',
                'competition':'australia nbl','period':'FULL_GAME','kickoff_utc':'2026-09-24T09:30'},
            'duration_ms': 70000, 'execution_count': 1, 'fixture_name': 'SE Melbourne Phoenix v Melbourne United',
            'selection': {'market': 'TOTALS', 'side': 'OVER', 'line': '190.5', 'price': price, 'selection_name':'Over'},
            'ready_state': {'state': 'READY', 'price': price, 'stake': '1.00', 'session': session_state,
                            'wager_submitted': False},
            'evidence': ['evidence/example/s019_final.png']}


def fail_result(instruction_id, stage, detail='x'):
    return {'instruction_id': instruction_id, 'status': 'FAIL', 'stage': stage, 'detail': detail,
            'duration_ms': 1000, 'execution_count': 1}


def config(**global_changes):
    value = defaults()
    # Explicit TEST policy; the live configuration remains unset and fails closed.
    value['global'].update(event_timezone='UTC', feed_timezone_verified=True, stale_alert_seconds=300, min_sharp_movement=0.5)
    value['global'].update(global_changes)
    for sport in value['sports'].values():
        for rule in sport['markets'].values():
            rule.update(max_odds_deterioration=value['global']['allowed_slippage'], max_line_deterioration=0)
    return value


def message(sample=MELBOURNE, *, message_id=None, received=T0, source=None, text=None, chat_id=None, **extra):
    return SourceMessage(chat_id=chat_id or '-100' + sample['chat_id'], message_id=message_id or sample['message_id'],
                         text=sample['raw_text'] if text is None else text, received_at=received.isoformat(),
                         source_timestamp=(source or received).isoformat(), **extra)


def pipeline(path, clock, cfg=None, instant_verification=True, **settings):
    cfg = cfg or config()
    values = dict(dispatch_enabled=True, device_id='galaxy-a13-5g')
    values.update(settings)
    p = Pipeline(path, lambda: cfg, Settings(**values), clock=clock)
    if values.get('final_action_enabled') and instant_verification:
        _instant_verification(p)
    return p


def _instant_verification(p):
    """Final-action tests: the phone's pre-approval READY verification run answers at once, so one
    tick takes a new alert to AWAITING_APPROVAL. The real sequence is tested in VerifyFirstTests."""
    from core.lifecycle import State
    tick = p.tick

    def run(gateway):
        tick(gateway)
        pending = [r['instruction_id'] for r in p.store.instructions_in([State.DISPATCHED, State.DEVICE_ACTIVE])
                   if r['execution_mode'] in ('ready', 'hold') and r['instruction_id'] not in gateway.results]
        if pending:
            for iid in pending:
                with p.store.connection() as db:
                    row = p.store.get_instruction(db,iid)
                    payload = json.loads(row['dispatch_payload'])
                result = ready_result(iid, row['alert_price'])
                result['selection'].update(market=row['market'],side=row['selection'],line=row['line'],selection_name=row['selection_name'])
                result['event_context'].update(home=row['home'],away=row['away'],competition=row['competition'],kickoff_utc=payload['kickoff_utc'])
                result['ready_state']['stake'] = row['stake']
                gateway.results[iid] = result
            tick(gateway)
    p.tick = run
