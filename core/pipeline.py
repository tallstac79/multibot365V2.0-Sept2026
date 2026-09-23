"""Unattended pipeline: intake -> classification -> rules -> queue -> device -> result.

The database (core.pipeline_store) is the single source of truth. Every step is a
short transaction; a crash between steps leaves a consistent, resumable record:

* intake is idempotent per (origin, chat, message, edit) and records every message
* an instruction is marked DISPATCHED (committed) *before* anything is sent, so a crash
  can never cause a second send; after restart in-flight work is only polled
* terminal states are final; late/duplicate results are audited and ignored
* SESSION_REQUIRED / DEVICE_OFFLINE / stale checks run immediately before dispatch

No live-site logic lives here: the device gateway sends the proven coordinator request
and the Android adapter owns everything on the phone.
"""
from dataclasses import dataclass, field
from datetime import datetime
import json
import logging

from core import alert_classifier
from core.lifecycle import State, TERMINAL, DEVICE_OWNED, interpret_device_result, CONFIRMATION_MAP
from core.pipeline_store import Store, iso, utcnow, instruction_id_for, selection_key
from core.rules_engine import evaluate, ACCEPT, STALE, selection_name as rules_selection_name
from core.session_contract import parse_report, gate as session_gate, DEFAULT_MAX_AGE_SECONDS

log = logging.getLogger('multibot.pipeline')
HISTORY_SCANS = ('reconcile', 'catch_up', 'backfill')


class _LostRace(Exception):
    """Another delivery of the same message committed between classification and storage."""


@dataclass
class SourceMessage:
    """One message as delivered by a source (Telegram listener, replay, test)."""
    chat_id: str
    message_id: str
    text: str                       # formatting-preserving text (Markdown bold/links)
    received_at: str                # local receipt, ISO-8601 with timezone
    origin: str = 'production'
    source_timestamp: str = None    # Telegram message date, ISO-8601 with timezone
    raw_text: str = None            # plain text exactly as Telegram delivered it
    entities: list = None           # Telegram formatting entities (JSON-serializable)
    edit_date: str = None           # set for edited-message deliveries
    source: str = 'telegram'
    provenance: dict = field(default_factory=dict)


@dataclass
class Settings:
    device_id: str = 'galaxy-a13-5g'
    dispatch_enabled: bool = False
    adapter: str = 'live_bet365'
    device_timeout_ms: int = 120000
    result_timeout_seconds: int = 240
    ready_timeout_seconds: int = 300
    session_max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS

    @classmethod
    def from_dict(cls, values):
        known = {k: v for k, v in (values or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)


class Pipeline:
    def __init__(self, store, config_provider, settings=None, clock=utcnow):
        self.store = store if isinstance(store, Store) else Store(store, clock)
        self.store.clock = clock
        self.config_provider = config_provider   # () -> decision-support config dict
        self.settings = settings or Settings()
        self.clock = clock

    # ================================================================== intake
    def ingest(self, message, delivery='event'):
        """Record one delivered message. Returns a summary dict; never silently drops.

        History scans (delivery 'reconcile', 'catch_up', 'backfill') skip a message that is
        already stored without creating a DUPLICATE row: that is not a new delivery.
        A repeated live 'event' delivery is recorded as DUPLICATE.
        """
        now = self.clock()
        edit_key = message.edit_date or ''
        with self.store.tx() as db:
            original = self.store.find_intake(db, message.origin, message.chat_id, message.message_id, edit_key)
            if original is not None:
                if delivery in HISTORY_SCANS:
                    return dict(intake_id=original['id'], status=original['status'], skipped=True,
                                instruction_id=original['instruction_id'])
                intake_id = self._insert(db, message, now, delivery, status=alert_classifier.DUPLICATE,
                                         reason=f'Duplicate delivery of intake #{original["id"]}',
                                         duplicate_of=original['id'], instruction_id=original['instruction_id'])
                return dict(intake_id=intake_id, status=alert_classifier.DUPLICATE,
                            instruction_id=original['instruction_id'])
            if edit_key:
                return self._ingest_edit(db, message, now, delivery)

        # Classification is pure CPU work outside the write lock.
        try:
            verdict = alert_classifier.classify(message.text, channel_id=str(message.chat_id),
                                                message_id=str(message.message_id),
                                                source_timestamp=message.source_timestamp)
        except Exception as error:  # defensive: parser bugs become INVALID, never a lost message
            verdict = dict(status=alert_classifier.INVALID, reason=f'Parser failure: {type(error).__name__}: {error}',
                           parsed=None, profile=None, parser_version=alert_classifier.PARSER_VERSION)
        parsed = verdict['parsed']
        instruction_id = instruction_id_for(message.origin, message.chat_id, message.message_id)
        try:
            return self._record(message, verdict, parsed, instruction_id, now, delivery)
        except _LostRace:
            # A concurrent delivery stored this message first. Retry only after our write
            # transaction has rolled back, so the retry never waits on its own lock.
            return self.ingest(message, delivery)

    def _record(self, message, verdict, parsed, instruction_id, now, delivery):
        with self.store.tx() as db:
            if self.store.find_intake(db, message.origin, message.chat_id, message.message_id) is not None:
                raise _LostRace()
            status, reason = verdict['status'], verdict['reason']
            superseded = None
            if status == alert_classifier.PARSED:
                status, reason, superseded = self._content_duplicate(db, message.origin, parsed, status, reason)
            intake_id = self._insert(db, message, now, delivery, status=status, reason=reason,
                                     instruction_id=instruction_id if status == alert_classifier.PARSED else None,
                                     parser_profile=verdict.get('profile'), parser_version=verdict.get('parser_version'),
                                     normalized=parsed)
            if status != alert_classifier.PARSED:
                return dict(intake_id=intake_id, status=status, reason=reason, instruction_id=None)
            self.store.create_instruction(
                db, at=iso(now), instruction_id=instruction_id, origin=message.origin, intake_id=intake_id,
                chat_id=str(message.chat_id), message_id=str(message.message_id), selection_key=selection_key(parsed),
                sport=parsed.get('sport'), competition=parsed.get('competition'), fixture=parsed.get('fixture'),
                home=parsed.get('home'), away=parsed.get('away'), event_time=parsed.get('scheduled_at_local'),
                market=parsed.get('market'), selection=parsed.get('target_side'), line=parsed.get('target_line'),
                selection_name=rules_selection_name(parsed),
                alternate_line=int(any((parsed.get('alternate_line') or {}).values())),
                alert_price=parsed.get('alert_price'), displayed_ev=parsed.get('displayed_ev_percent'),
                device_id=self.settings.device_id, raw_alert=message.text, normalized_alert=parsed,
                received_at=message.received_at)
            self.store.transition(db, instruction_id, State.PARSED, actor='parser', at=iso(now),
                                  reason=f'{verdict.get("profile")} / {verdict.get("parser_version")}')
            if superseded:
                self.store.transition(db, superseded, State.STALE, actor='intake', at=iso(now),
                                      reason=f'SUPERSEDED: newer alert {instruction_id} for the same selection')
            state = self._apply_rules(db, instruction_id, parsed, message.received_at, now)
            return dict(intake_id=intake_id, status=status, reason=reason, instruction_id=instruction_id, state=state)

    def _insert(self, db, message, now, delivery, **row):
        return self.store.insert_intake(
            db, origin=message.origin, source=message.source, chat_id=str(message.chat_id),
            message_id=str(message.message_id), edit_key=message.edit_date or '', delivery=delivery,
            raw_text=message.raw_text if message.raw_text is not None else message.text,
            formatted_text=message.text, entities=message.entities, source_timestamp=message.source_timestamp,
            received_at=message.received_at, processed_at=iso(now), provenance=message.provenance or None, **row)

    def _ingest_edit(self, db, message, now, delivery):
        """An edit never creates a second instruction. A pending original is cancelled."""
        first = self.store.find_intake(db, message.origin, message.chat_id, message.message_id)
        reason = 'Edited source message; original identity already processed, edit not executed'
        if first is not None and first['instruction_id']:
            row = self.store.get_instruction(db, first['instruction_id'])
            if row and row['state'] not in {s.value for s in TERMINAL | DEVICE_OWNED}:
                self.store.transition(db, row['instruction_id'], State.STALE, actor='intake', at=iso(now),
                                      reason='SUPERSEDED: source message edited before dispatch')
                reason += '; pending original marked STALE'
        intake_id = self._insert(db, message, now, delivery, status=alert_classifier.IGNORED, reason=reason,
                                 duplicate_of=first['id'] if first else None)
        return dict(intake_id=intake_id, status=alert_classifier.IGNORED, reason=reason, instruction_id=None)

    def _content_duplicate(self, db, origin, parsed, status, reason):
        """Same selection from a different message: duplicate, or supersede a pending one."""
        key = selection_key(parsed)
        superseded = None
        for row in db.execute('SELECT * FROM instructions WHERE origin=? AND selection_key=? ORDER BY received_at DESC',
                              (origin, key)).fetchall():
            state = State(row['state'])
            if state in DEVICE_OWNED or state == State.COMPLETED:
                return (alert_classifier.DUPLICATE,
                        f'Same selection already {state.value} as {row["instruction_id"]}; not processed twice', None)
            if state in TERMINAL:
                continue
            if row['alert_price'] == parsed.get('alert_price'):
                return (alert_classifier.DUPLICATE,
                        f'Same selection and price already pending as {row["instruction_id"]}', None)
            superseded = row['instruction_id']
        return status, reason, superseded

    def _apply_rules(self, db, instruction_id, parsed, received_at, now):
        try:
            decision = evaluate(parsed, self.config_provider(), instruction_id=instruction_id,
                                received_at=received_at, now=now)
        except Exception as error:  # invalid config etc. -> fail closed
            decision = dict(decision='REJECT', reason=f'Rules engine error: {type(error).__name__}: {error}',
                            checks=[], instruction=None, evaluated_at=iso(now))
        self.store.transition(db, instruction_id, State.RULES_APPLIED, actor='rules', at=iso(now),
                              reason=decision['reason'], rules_result=decision,
                              **({'minimum_price': decision['instruction']['minimum_price'],
                                  'stake': decision['instruction']['stake']} if decision.get('instruction') else {}))
        if decision['decision'] == ACCEPT:
            self.store.transition(db, instruction_id, State.QUEUED, actor='rules', at=iso(now), reason='Queued for device')
            return State.QUEUED.value
        target = State.STALE if decision['decision'] == STALE else State.REJECTED
        self.store.transition(db, instruction_id, target, actor='rules', at=iso(now), reason=decision['reason'])
        return target.value

    # ================================================================== device side
    def refresh_device(self, gateway):
        """Poll coordinator health; record device and session state. Returns health or None."""
        device_id, now = self.settings.device_id, self.clock()
        try:
            health = gateway.health()
            if not isinstance(health, dict) or 'healthy' not in health:
                raise ValueError('Malformed health response')
        except Exception as error:
            self.store.record_device(device_id, 'OFFLINE', error=f'{type(error).__name__}: {error}'[:300], at=iso(now))
            return None
        status = 'ONLINE' if health.get('healthy') is True else 'DEGRADED'
        self.store.record_device(device_id, status, health=health, at=iso(now))
        self._record_session(health.get('session'), 'health', now)
        return health

    def _record_session(self, payload, source, now):
        if payload is None:
            return
        try:
            self.store.record_session(parse_report(self.settings.device_id, payload, source), iso(now))
        except (ValueError, TypeError) as error:
            with self.store.tx() as db:
                self.store.audit(db, 'MALFORMED_SESSION_REPORT', dict(error=str(error), payload=payload, source=source),
                                 device_id=self.settings.device_id, at=iso(now))

    def build_payload(self, row):
        """Coordinator request for the existing live adapter. READY-only: never a wager.

        execution_mode is always 'ready' and confirmation is never APPROVED here, so the
        proven adapter stops before its final action. Final action remains out of scope.
        """
        payload = dict(instruction_id=row['instruction_id'], action='ADAPTER_WORKFLOW', adapter=self.settings.adapter,
                       scenario='live', query=row['home'], sport=row['sport'], market=row['market'],
                       side=row['selection'], line=row['line'], minimum_price=row['minimum_price'],
                       stake=row['stake'], timeout_ms=self.settings.device_timeout_ms, execution_mode='ready')
        assert payload['execution_mode'] == 'ready' and 'confirmation_status' not in payload
        return payload

    def tick(self, gateway):
        """One dispatcher cycle. Safe to call repeatedly and after any restart."""
        health = self.refresh_device(gateway)
        self._poll_in_flight(gateway)
        self._expire_ready()
        self._dispatch_queued(gateway, health)

    def _poll_in_flight(self, gateway):
        for row in self.store.instructions_in([State.DISPATCHED, State.DEVICE_ACTIVE]):
            try:
                result = gateway.result(row['instruction_id'])
            except Exception as error:
                result = None
                with self.store.tx() as db:
                    self.store.audit(db, 'RESULT_POLL_FAILED', dict(error=f'{type(error).__name__}: {error}'[:300]),
                                     row['instruction_id'], row['device_id'])
            if result is not None:
                self.apply_result(row['instruction_id'], result)
                continue
            dispatched = datetime.fromisoformat(row['dispatched_at'])
            if (self.clock() - dispatched).total_seconds() > self.settings.result_timeout_seconds:
                with self.store.tx() as db:
                    self.store.transition(db, row['instruction_id'], State.TIMEOUT, actor='dispatcher',
                                          reason=f'No device result within {self.settings.result_timeout_seconds}s; '
                                                 'outcome unknown, never re-dispatched')

    def _expire_ready(self):
        for row in self.store.instructions_in([State.READY]):
            if (self.clock() - datetime.fromisoformat(row['ready_at'])).total_seconds() > self.settings.ready_timeout_seconds:
                with self.store.tx() as db:
                    self.store.transition(db, row['instruction_id'], State.STALE, actor='dispatcher',
                                          reason=f'READY not confirmed within {self.settings.ready_timeout_seconds}s')

    def _dispatch_queued(self, gateway, health):
        queued = self.store.instructions_in([State.QUEUED])
        if not queued:
            return
        in_flight = self.store.instructions_in([State.DISPATCHED, State.DEVICE_ACTIVE])
        for row in queued:
            now = self.clock()
            config = self.config_provider()
            alert = json.loads(row['normalized_alert'])
            recheck = evaluate(alert, config, instruction_id=row['instruction_id'], received_at=row['received_at'], now=now)
            with self.store.tx() as db:
                if recheck['decision'] != ACCEPT:
                    target = State.STALE if recheck['decision'] == STALE else State.REJECTED
                    self.store.transition(db, row['instruction_id'], target, actor='dispatcher',
                                          reason='Pre-dispatch recheck: ' + recheck['reason'], detail=recheck)
                    continue
                if not self.settings.dispatch_enabled:
                    continue  # Remains QUEUED until it ages out as STALE; nothing is sent.
                if health is None:
                    self.store.transition(db, row['instruction_id'], State.DEVICE_OFFLINE, actor='dispatcher',
                                          reason='DEVICE_OFFLINE: coordinator unreachable at dispatch time')
                    continue
                if health.get('healthy') is not True:
                    self.store.transition(db, row['instruction_id'], State.DEVICE_OFFLINE, actor='dispatcher',
                                          reason='DEVICE_OFFLINE: coordinator reports unhealthy')
                    continue
                session = self.store.session(self.settings.device_id)
                permitted, why = session_gate(session, now, self.settings.session_max_age_seconds)
                if not permitted:
                    self.store.transition(db, row['instruction_id'], State.SESSION_REQUIRED, actor='dispatcher',
                                          reason=why, session_state=(session or {}).get('state', 'UNKNOWN'))
                    continue
                if in_flight or health.get('current_instruction'):
                    continue  # One instruction at a time; wait (it may later go STALE).
                payload = self.build_payload(row)
                # Commit DISPATCHED before sending: a crash after this point can never resend.
                if not self.store.transition(db, row['instruction_id'], State.DISPATCHED, actor='dispatcher',
                                             reason='Sent to coordinator', dispatch_payload=payload,
                                             dispatch_attempts=row['dispatch_attempts'] + 1,
                                             session_state=session['state']):
                    continue
            in_flight = [row]
            self._send(gateway, row['instruction_id'], payload)

    def _send(self, gateway, instruction_id, payload):
        try:
            ack = gateway.submit(payload)
        except Exception as error:
            # Uncertain delivery: keep DISPATCHED and poll the same ID; never resend a new ID.
            with self.store.tx() as db:
                self.store.audit(db, 'SUBMIT_UNCERTAIN', dict(error=f'{type(error).__name__}: {error}'[:300]),
                                 instruction_id, self.settings.device_id)
            return
        with self.store.tx() as db:
            self.store.audit(db, 'COORDINATOR_ACK', ack, instruction_id, self.settings.device_id)
            if isinstance(ack, dict) and ack.get('status') == 'FAIL' and ack.get('stage') not in ('DUPLICATE', None):
                self.store.transition(db, instruction_id, State.REJECTED, actor='coordinator',
                                      reason=f"Coordinator refused admission: {ack.get('stage')}: {ack.get('detail')}")
            elif isinstance(ack, dict) and ack.get('state') == 'ACCEPTED':
                self.store.transition(db, instruction_id, State.DEVICE_ACTIVE, actor='coordinator',
                                      reason='Coordinator durably accepted instruction')

    def apply_result(self, instruction_id, result, source='coordinator'):
        """Apply a device result exactly once. Returns the resulting state value."""
        now = self.clock()
        with self.store.tx() as db:
            row = self.store.get_instruction(db, instruction_id)
            if row is None:
                self.store.audit(db, 'RESULT_FOR_UNKNOWN_INSTRUCTION', dict(result=result, source=source), instruction_id)
                return None
            if row['terminal']:
                self.store.audit(db, 'LATE_OR_DUPLICATE_RESULT_IGNORED', dict(result=result, state=row['state'],
                                                                             source=source), instruction_id)
                return row['state']
            try:
                state, reason, observed = interpret_device_result(result)
                if isinstance(result, dict) and result.get('instruction_id') not in (None, instruction_id):
                    raise ValueError('Result instruction_id does not match')
            except ValueError as error:
                self.store.audit(db, 'MALFORMED_RESULT', dict(error=str(error), result=result, source=source), instruction_id)
                self.store.transition(db, instruction_id, State.UNKNOWN, actor=source, at=iso(now),
                                      reason=f'MALFORMED_RESULT: {error}', result_payload=result)
                return State.UNKNOWN.value
            if state is None:
                return row['state']  # DUPLICATE echo of the original; keep waiting for it.
            ready = result.get('ready_state') if isinstance(result.get('ready_state'), dict) else {}
            fields = dict(result_payload=result, device_stage=result.get('stage'), observed_price=observed)
            if isinstance(result.get('evidence'), list):
                fields['evidence'] = result['evidence']
            if ready.get('session'):
                fields['session_state'] = ready['session']
            if state == State.READY and row['state'] == State.READY.value:
                return row['state']
            if state == State.READY and row['state'] == State.DISPATCHED.value:
                self.store.transition(db, instruction_id, State.DEVICE_ACTIVE, actor=source, at=iso(now),
                                      reason='Device result received')
            self.store.transition(db, instruction_id, state, actor=source, at=iso(now), reason=reason, **fields)
            return state.value

    def apply_confirmation(self, instruction_id, decision_status, detail=''):
        """Map an existing confirmation-worker DecisionStatus onto the lifecycle."""
        target = CONFIRMATION_MAP.get(decision_status)
        if target is None:
            return None  # APPROVED/PENDING: the final action is outside this pipeline.
        with self.store.tx() as db:
            self.store.transition(db, instruction_id, target, actor='confirmation',
                                  reason=f'{decision_status}: {detail}'.rstrip(': '))
            return self.store.get_instruction(db, instruction_id)['state']

    def recover(self):
        """Startup reconciliation. Nothing is resent; in-flight work is only polled."""
        with self.store.tx() as db:
            rows = db.execute("SELECT instruction_id, state FROM instructions WHERE terminal=0").fetchall()
            self.store.audit(db, 'PIPELINE_START', dict(open_instructions={r['instruction_id']: r['state'] for r in rows}))
        return len(rows)
