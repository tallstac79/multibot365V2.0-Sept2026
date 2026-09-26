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
from datetime import datetime, timezone
import hashlib
import json
import logging
import re

from core import alert_classifier
from core.final_action import FinalAction
from core.competition_gender import womens_competition
from core.scoped_identity import IdentityRegistry
from core.lifecycle import State, TERMINAL, DEVICE_OWNED, interpret_device_result, CONFIRMATION_MAP
from core.pipeline_store import Store, iso, utcnow, instruction_id_for, selection_key
from core.rules_engine import evaluate, ACCEPT, STALE, selection_name as rules_selection_name, time_assumptions
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
    device_timeout_ms: int = 300000  # absolute backstop; stage inactivity on device fails closed sooner
    result_timeout_seconds: int = 360
    ready_timeout_seconds: int = 300
    session_max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS
    # Final action (Place Bet). Off unless explicitly enabled; see core/final_action.py.
    final_action_enabled: bool = False
    # approval_mode: 'manual' (a device-verified slip waits for /approve) or 'automatic' (the backend itself
    # approves a device-verified slip once every policy check in FinalAction.automatic_checks passes, then the
    # phone re-verifies the slip immediately before its single tap). auto_approve is the legacy alias.
    approval_mode: str = 'manual'
    auto_approve: bool = False
    # Automatic mode binds the decision to one worker and one bookmaker account: the phone reports both in its
    # health (worker_id, account_fingerprint = sha256 of the configured username, first 12 hex) and they must
    # equal these values. Empty = not checked (manual mode) / refused (automatic mode).
    expected_worker_id: str = ''
    expected_account_fingerprint: str = ''
    approval_timeout_seconds: int = 120
    # A verified hold is consumed by its final action only while fresh (the phone enforces 120 s itself).
    hold_max_age_seconds: int = 115
    max_stake_per_bet: str = '1.00'
    max_bets_per_day: int = 5
    max_daily_stake: str = '5.00'
    max_daily_loss: str = '5.00'
    reconcile_delay_seconds: int = 15
    reconcile_max_attempts: int = 3
    reconcile_timeout_ms: int = 120000
    settlement_poll_minutes: int = 30
    # Supervised arming: after the FIRST result of a Place Bet run (placed, refused, failed before the tap
    # or PLACEMENT_UNKNOWN) dispatch and final action switch off at once and the kill switch engages.
    # My Bets verification and settlement keep running.
    final_action_one_shot: bool = False
    # Stale/unknown session at dispatch time: send one SESSION_CHECK (opens home, logs in if
    # needed) and wait for it instead of failing SESSION_REQUIRED straight away.
    session_warmup: bool = True
    session_warmup_timeout_seconds: int = 120

    APPROVAL_MODES = ('manual', 'automatic')

    def __post_init__(self):
        mode = str(self.approval_mode or 'manual').strip().lower()
        if mode not in self.APPROVAL_MODES:
            raise ValueError(f'approval_mode must be one of {self.APPROVAL_MODES}, not {self.approval_mode!r}')
        if mode == 'manual' and self.auto_approve:
            mode = 'automatic'                     # legacy flag
        self.approval_mode = mode
        self.auto_approve = mode == 'automatic'   # kept in step for older readers (status file, dashboard)

    @property
    def automatic(self):
        return self.approval_mode == 'automatic'

    @classmethod
    def from_dict(cls, values):
        known = {k: v for k, v in (values or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)


EVENT_URL = re.compile(r'^https://www\.bet365\.com/#/AC/B(\d{1,3})(/[A-Z]\d{1,12}){2,8}/?$')
KICKOFF = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$')
SELECTION_NAME = re.compile(r"^[A-Za-z0-9 ./'&()-]{2,64}$")
HELD_KEY = 'held_slip'


BARE_HOST = 'https://bet365.com/#/'


def event_link(row):
    """The alert's Bet365 event link if it is a well-formed #/AC/ link; else None (the phone searches).

    OddsNotifier writes the link with either host ("https://www.bet365.com/#/AC/..." or, since 23 Sep 2026, sometimes
    "https://bet365.com/#/AC/..."; 27 of 212 links on 24-25 Sep). The path is what identifies the event, so the bare
    host is normalised to the www form the phone validates (EventPage.validUrl) instead of losing the primary route.
    Real failure (Milestone B, on-8f79281a, Norrkoping v Umea): a bare-host link was dropped, the run fell back to
    Search and failed closed there.
    """
    try:
        url = (json.loads(row['normalized_alert'] or '{}') or {}).get('comparison_url')
    except (ValueError, TypeError):
        return None
    if not isinstance(url, str):
        return None
    url = url.strip()
    if url.startswith(BARE_HOST):
        url = 'https://www.' + url[len('https://'):]
    return url if EVENT_URL.match(url) else None


def device_instruction_id(instruction_id, execution_mode):
    """Phone-side ID: the verification run uses the instruction ID; the Place Bet run its own ('-place')."""
    return f'{instruction_id}-place' if execution_mode == 'dispatch' else instruction_id


class Pipeline:
    def __init__(self, store, config_provider, settings=None, clock=utcnow):
        self.store = store if isinstance(store, Store) else Store(store, clock)
        self.store.clock = clock
        self.config_provider = config_provider   # () -> decision-support config dict
        self.settings = settings or Settings()
        self.clock = clock
        self.final = FinalAction(self)
        self.identity = IdentityRegistry(self.store)
        self.armed_at = iso(clock())    # one-shot: only Place Bet runs dispatched after this count
        self.disarmed = None            # set when the one-shot fired (the service persists it)

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
            if parsed and parsed.get('scheduled_at_local'):
                try:
                    timing = time_assumptions(parsed, self.config_provider(), now)
                except (ValueError, TypeError, KeyError):
                    timing = {}  # The rules engine below records invalid configuration and rejects.
                if timing.get('timezone_eligibility_uncertain'):
                    timing.update(intake_id=intake_id, source_timestamp=message.source_timestamp,
                                  received_at=message.received_at, fixture=parsed.get('fixture'))
                    self.store.audit(db, 'TIMEZONE_ELIGIBILITY_UNCERTAIN', timing)
                    log.warning('TIMEZONE_ELIGIBILITY_UNCERTAIN feed_timezone_verified=false intake=%s %s',
                                intake_id, json.dumps(timing, sort_keys=True))
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
            previous = json.loads(row['normalized_alert'] or '{}')
            context = ('opening', 'pinnacle', 'market_movement', 'highlighted_side', 'comparison',
                       'displayed_ev_percent', 'quote_mapping')
            if row['alert_price'] == parsed.get('alert_price') and all(previous.get(k) == parsed.get(k) for k in context):
                return (alert_classifier.DUPLICATE,
                        f'Same selection, price and movement context already pending as {row["instruction_id"]}', None)
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
        self.store.audit(db, 'ALERT_TO_LIVE_COMPARISON', dict(
            requested=dict(market=parsed.get('market'), side=parsed.get('target_side'),
                           line=parsed.get('target_line'), price=parsed.get('alert_price')),
            live=None, stage='rules', acceptable=False, reason=decision['reason'],
            observation_status='not sent to phone; live terms unknown'), instruction_id)
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

    def build_payload(self, row, final_action=False):
        """Coordinator request for the live adapter.

        READY-only by default: execution_mode 'ready' stops before Place Bet. A final action
        (execution_mode 'dispatch' + confirmation_status 'APPROVED') is built only for an
        APPROVED instruction while final action is enabled and not paused.
        """
        if final_action:
            if not (self.final.enabled() and row['state'] == State.APPROVED.value and row['approved_by']):
                raise PermissionError('Final action requires an APPROVED instruction with final action enabled')
            return self.place_held_payload(row)
        # Final action enabled: 'hold' = verify everything and leave the bet on the slip with the stake
        # entered and Place Bet located (never tapped) for the approval. Otherwise READY-only.
        mode = 'hold' if self.final.enabled() else 'ready'
        payload = dict(instruction_id=row['instruction_id'], action='ADAPTER_WORKFLOW', adapter=self.settings.adapter,
                       scenario='live', query=(f"{row['home']}||{row['away']}" if row['away'] else row['home']),
                       sport=row['sport'], market=row['market'], side=row['selection'], line=row['line'],
                       minimum_price=row['minimum_price'], stake=row['stake'], timeout_ms=self.settings.device_timeout_ms,
                       execution_mode=mode)
        url = event_link(row)
        if url:
            payload['event_url'] = url                      # primary route: open the exact event
        rules = json.loads(row['rules_result'] or '{}')
        terms = rules.get('instruction') or {}
        if terms.get('max_line_deterioration') is not None:
            payload['max_line_deterioration'] = terms['max_line_deterioration']
        start = (rules.get('instruction') or {}).get('event_start_utc')
        if start and rules.get('feed_timezone_verified') is True:
            payload['kickoff_utc'] = datetime.fromisoformat(start).strftime('%Y-%m-%dT%H:%M')
        if row['competition']:
            payload['competition'] = row['competition']
        try:
            country = (json.loads(row['normalized_alert'] or '{}') or {}).get('country')
        except (ValueError, TypeError):
            country = None
        if country:
            payload['country'] = str(country)      # the phone's deterministic competition gate ("Mexico Liga ABE")
        payload['period'] = 'FULL_GAME'
        # B6/B7: promoted aliases and the names Bet365 used for this same fixture before travel with the run.
        with self.store.connection() as db:
            aliases = self.identity.aliases_for(db, row['sport'], row['home'], row['away'], payload.get('kickoff_utc'), row['competition'])
        if aliases:
            payload['aliases'] = json.dumps(aliases)
        # Competition-aware women's marker: the phone may supply a missing "(W)" only for a women's competition.
        if womens_competition(row['competition']):
            payload['competition_women'] = 'true'
        assert 'confirmation_status' not in payload
        return payload

    def place_held_payload(self, row):
        """PLACE_HELD: tap the bet the phone verified and left on the slip. Expected values come from the
        hold run's own result (the names/line as Bet365 shows them). Its own device ID ('-place')."""
        result = json.loads(row['result_payload'] or '{}')
        selection = result.get('selection') if isinstance(result.get('selection'), dict) else {}
        ready = result.get('ready_state') if isinstance(result.get('ready_state'), dict) else {}
        name = selection.get('selection_name') or ready.get('selection_name')
        if not name and row['market'] == 'TOTALS':
            name = 'Over' if row['selection'] == 'OVER' else 'Under'
        if not name:
            name = row['selection_name']   # feed name; the phone still requires it visible on the slip
        price = selection.get('price') or ready.get('price') or row['observed_price']
        line = selection.get('line') if row['market'] not in ('ML','MONEYLINE') else ''
        if row['market'] in ('SPREAD', 'TOTALS') and not line:
            line = row['line']
        if not (name and SELECTION_NAME.match(str(name)) and price):
            raise PermissionError('Held selection details missing from the verification result')
        context = result.get('event_context') or {}
        if not result.get('held') or any(not context.get(k) for k in ('home','away','competition','kickoff_utc','period')):
            raise PermissionError('Original held event identity missing; verify a new hold')
        return dict(instruction_id=device_instruction_id(row['instruction_id'], 'dispatch'), action='PLACE_HELD',
                    adapter=self.settings.adapter, scenario='live', sport=row['sport'], market=row['market'],
                    side=row['selection'], line=line or '', selection_name=str(name), price=str(price),
                    minimum_price=row['minimum_price'], stake=row['stake'], execution_mode='dispatch',
                    confirmation_status='APPROVED', timeout_ms=90000, held_instruction_id=row['instruction_id'],
                    **{k: context[k] for k in ('home','away','competition','kickoff_utc','period')})

    # ------------------------------------------------------------------ held slip (one bet on the phone)
    HELD_ACTIVE = ('READY', 'AWAITING_APPROVAL', 'APPROVED', 'DISPATCHED', 'DEVICE_ACTIVE')

    def held_instruction(self):
        """Instruction whose verified bet is on the phone's slip awaiting approval/placement, else None."""
        held = self.store.control(HELD_KEY)
        return held.get('instruction_id') if isinstance(held, dict) and not held.get('released') else None

    def _release_hold(self, gateway, health):
        """A held bet that will not be placed (expired, rejected, paused, failed before the tap) is cleared
        from the slip with RESET_BETSLIP (removes it by its own X; never taps Place Bet)."""
        held = self.store.control(HELD_KEY)
        if not isinstance(held, dict) or held.get('released'):
            return
        with self.store.connection() as db:
            row = self.store.get_instruction(db, held['instruction_id'])
        if row is None:
            self.store.set_control(HELD_KEY, dict(held, released='missing'), by='dispatcher')
            return
        if row['state'] in self.HELD_ACTIVE:
            return
        placement = json.loads(row['placement'] or 'null') if row['placement'] else None
        if isinstance(placement, dict) and placement.get('tapped') is not False and row['execution_mode'] == 'dispatch':
            # Place Bet was (or may have been) tapped: that run closed the receipt and returned home itself.
            self.store.set_control(HELD_KEY, dict(held, released='placement run'), by='dispatcher')
            return
        if health is None or health.get('healthy') is not True or health.get('current_instruction'):
            return  # phone busy/offline: retry next tick
        device_id = 'rs-' + hashlib.sha256(row['instruction_id'].encode()).hexdigest()[:24]
        try:
            gateway.submit(dict(instruction_id=device_id, action='RESET_BETSLIP', adapter=self.settings.adapter,
                                scenario='live', timeout_ms=60000))
            outcome = 'reset sent'
        except Exception as error:
            reply = error.args[0] if error.args else None
            if not (isinstance(reply, dict) and reply.get('stage') == 'DUPLICATE'):
                with self.store.tx() as db:
                    self.store.audit(db, 'HELD_SLIP_RESET_FAILED', dict(error=str(error)[:200]), row['instruction_id'])
                return
            outcome = 'reset already sent'
        with self.store.tx() as db:
            self.store.audit(db, 'HELD_SLIP_RELEASED', dict(state=row['state'], reset=device_id, outcome=outcome), row['instruction_id'])
        self.store.set_control(HELD_KEY, dict(held, released=outcome, reset=device_id), by='dispatcher')

    def tick(self, gateway):
        """One dispatcher cycle. Safe to call repeatedly and after any restart."""
        health = self.refresh_device(gateway)
        if health and health.get('diagnostics_active'):
            self._poll_in_flight(gateway)
            return  # lease suppresses reset, warmup, reconciliation and dispatch; polling remains safe
        self._poll_warmup(gateway)
        self._poll_in_flight(gateway)
        self._one_shot()
        self._release_hold(gateway, health)
        self.final.poll(gateway)
        self._expire_ready()
        self.final.expire_approvals()
        # Placement verification outranks new work: an unresolved tap blocks nothing else
        # being learnt, but the phone does one thing at a time.
        device_free = not self.store.instructions_in([State.DISPATCHED, State.DEVICE_ACTIVE])
        held = self.held_instruction()
        # A held bet owns the phone: no My Bets checks (they navigate away) until it is placed or released.
        # A2: live placement work outranks routine My Bets checks; only PLACEMENT_UNKNOWN resolution is urgent.
        if not held and self.final.schedule(gateway, health, device_free and not self.final.device_busy(),
                                            urgent_only=self._live_work_pending()):
            return
        if not self.final.device_busy():
            self._dispatch_queued(gateway, health)

    def _live_work_pending(self):
        """Live placement work that can actually reach the phone (dispatch on, not paused)."""
        if not self.settings.dispatch_enabled or self.final.paused():
            return False
        return bool(self.store.instructions_in([State.QUEUED, State.APPROVED]))

    ONE_SHOT_KEY = 'final_action_one_shot'
    # controls key: ISO timestamp set by the operator when arming; instructions received before it are never dispatched
    ACTIVATION_KEY = 'activation_at'

    def _one_shot(self):
        """Disarm after the first Place Bet run result since arming (see Settings.final_action_one_shot)."""
        if not self.settings.final_action_one_shot or not (self.settings.dispatch_enabled or self.settings.final_action_enabled):
            return
        with self.store.connection() as db:
            row = db.execute("SELECT instruction_id, state FROM instructions WHERE execution_mode='dispatch' "
                             "AND state NOT IN ('APPROVED','DISPATCHED','DEVICE_ACTIVE') AND dispatched_at >= ? "
                             "ORDER BY dispatched_at LIMIT 1", (self.armed_at,)).fetchone()
        if row is None:
            return
        self.settings.dispatch_enabled = False
        self.settings.final_action_enabled = False
        self.final.set_paused(True, 'one-shot')
        self.disarmed = dict(instruction_id=row['instruction_id'], state=row['state'], at=iso(self.clock()))
        with self.store.tx() as db:
            self.store.audit(db, 'FINAL_ACTION_DISARMED', dict(self.disarmed, reason='one-shot: first Place Bet result'),
                             row['instruction_id'])
        self.store.set_control(self.ONE_SHOT_KEY, self.disarmed, by='one-shot')

    def _poll_in_flight(self, gateway):
        for row in self.store.instructions_in([State.DISPATCHED, State.DEVICE_ACTIVE]):
            try:
                result = gateway.result(device_instruction_id(row['instruction_id'], row['execution_mode']))
            except Exception as error:
                result = None
                with self.store.tx() as db:
                    self.store.audit(db, 'RESULT_POLL_FAILED', dict(error=f'{type(error).__name__}: {error}'[:300]),
                                     row['instruction_id'], row['device_id'])
            if result is not None:
                if isinstance(result, dict) and result.get('_pending'):
                    # Mid-flight progress heartbeat from coordinator acknowledgement.
                    progress = result.get('progress') if isinstance(result.get('progress'), dict) else {}
                    stage = result.get('device_stage') or progress.get('stage')
                    if stage and stage != row['device_stage']:
                        with self.store.tx() as db:
                            self.store.update_fields(db, row['instruction_id'], device_stage=stage)
                            self.store.audit(db, 'DEVICE_PROGRESS', dict(progress=progress or result),
                                             row['instruction_id'], row['device_id'] or self.settings.device_id)
                    result = None
                else:
                    self.apply_result(row['instruction_id'], result)
                    continue
            dispatched = datetime.fromisoformat(row['dispatched_at'])
            if (self.clock() - dispatched).total_seconds() > self.settings.result_timeout_seconds:
                with self.store.tx() as db:
                    if row['execution_mode'] == 'dispatch':
                        # The tap may have happened: reconcile via My Bets, never re-dispatch.
                        if self.store.transition(db, row['instruction_id'], State.PLACEMENT_UNKNOWN, actor='dispatcher',
                                                 reason=f'No device result within {self.settings.result_timeout_seconds}s '
                                                        'after a final-action dispatch; reconciling via My Bets'):
                            self.final.record_outcome(db, self.store.get_instruction(db, row['instruction_id']),
                                                      State.PLACEMENT_UNKNOWN, None)
                    else:
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
        candidates = self.store.instructions_in([State.APPROVED, State.QUEUED])
        if not candidates:
            return
        paused = self.final.paused()
        in_flight = self.store.instructions_in([State.DISPATCHED, State.DEVICE_ACTIVE])
        # Approved final actions first: an operator is waiting on them.
        candidates.sort(key=lambda r: 0 if r['state'] == State.APPROVED.value else 1)
        warmup_for = None
        held = self.held_instruction()
        activation = self.store.control(self.ACTIVATION_KEY)
        for row in candidates:
            if held and row['instruction_id'] != held:
                continue  # the phone holds another verified bet on its slip; wait (may age out as STALE)
            now = self.clock()
            if activation and (row['received_at'] or '') < activation:
                # Clean cut-off (2026-09-27): only alerts received after the operator's activation timestamp may
                # execute; anything earlier (queued while disarmed, historical, replayed) ends here, never on the phone.
                with self.store.tx() as db:
                    self.store.transition(db, row['instruction_id'], State.STALE, actor='activation',
                                          reason=f"received {row['received_at']} before activation {activation}; not executed")
                continue
            config = self.config_provider()
            alert = json.loads(row['normalized_alert'])
            received = row['received_at']
            if row['state'] == State.APPROVED.value and row['ready_at']:
                # Verify-first final action: the phone verified the live line and price at ready_at and
                # re-verifies them before the tap, so alert age is measured from that verification.
                alert = {k: v for k, v in alert.items() if k != 'source_timestamp'}
                received = row['ready_at']
            recheck = evaluate(alert, config, instruction_id=row['instruction_id'], received_at=received, now=now)
            with self.store.tx() as db:
                if recheck['decision'] != ACCEPT:
                    target = State.STALE if recheck['decision'] == STALE else State.REJECTED
                    self.store.transition(db, row['instruction_id'], target, actor='dispatcher',
                                          reason='Pre-dispatch recheck: ' + recheck['reason'], detail=recheck)
                    continue
                if not self.settings.dispatch_enabled or paused:
                    if row['state'] == State.APPROVED.value:
                        self.store.transition(db, row['instruction_id'], State.REJECTED, actor='dispatcher',
                                              reason='Dispatch disabled or paused after approval; nothing sent')
                    continue  # QUEUED rows wait and age out as STALE; nothing is sent.
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
                    decision = self._warmup_decision(row, session, health, bool(in_flight))
                    if decision == 'WAIT':
                        continue
                    if decision == 'START':
                        warmup_for = row
                        break
                    self.store.transition(db, row['instruction_id'], State.SESSION_REQUIRED, actor='dispatcher',
                                          reason=why + ('' if decision == 'FAIL' else f' ({decision})'),
                                          session_state=(session or {}).get('state', 'UNKNOWN'))
                    continue
                final_action = self.final.enabled()
                if final_action and row['state'] == State.QUEUED.value:
                    if not self.final.on_queued(db, row):
                        continue  # rejected by a limit
                    # dispatched below as a READY verification run; approval is requested on its result
                if final_action and row['state'] == State.APPROVED.value:
                    breach = self.final.limit_breach(db, row)
                    if breach:
                        self.store.transition(db, row['instruction_id'], State.REJECTED, actor='limits', reason=breach)
                        continue
                    # The final action may only consume the hold on the worker that verified it, and only while
                    # that hold is fresh (the phone refuses an older hold; do not send a doomed final action).
                    if row['device_id'] not in (None, '', self.settings.device_id):
                        self.store.transition(db, row['instruction_id'], State.REJECTED, actor='dispatcher',
                                              reason=f"PRE_TAP_REJECTED: hold verified on worker {row['device_id']}, "
                                                     f"final action bound to {self.settings.device_id}")
                        continue
                    hold_age = (now - datetime.fromisoformat(row['ready_at'])).total_seconds() if row['ready_at'] else None
                    if hold_age is None or hold_age > self.settings.hold_max_age_seconds:
                        self.store.transition(db, row['instruction_id'], State.REJECTED, actor='dispatcher',
                                              reason=f'PRE_TAP_REJECTED: verified hold is {int(hold_age or -1)}s old, '
                                                     f'older than {self.settings.hold_max_age_seconds}s; nothing tapped')
                        continue
                if in_flight or health.get('current_instruction'):
                    continue  # One instruction at a time; wait (it may later go STALE).
                payload = self.build_payload(row, final_action=final_action and row['state'] == State.APPROVED.value)
                # Commit DISPATCHED before sending: a crash after this point can never resend.
                if not self.store.transition(db, row['instruction_id'], State.DISPATCHED, actor='dispatcher',
                                             reason='Sent to coordinator' + (' (FINAL ACTION: Place Bet approved)'
                                                                             if payload['execution_mode'] == 'dispatch' else ''),
                                             dispatch_payload=payload, execution_mode=payload['execution_mode'],
                                             dispatch_attempts=row['dispatch_attempts'] + 1,
                                             session_state=session['state']):
                    continue
            in_flight = [row]
            self._send(gateway, row['instruction_id'], payload)
        if warmup_for is not None:
            self._start_warmup(gateway, warmup_for)

    # ------------------------------------------------------------------ session warm-up
    WARMUP_KEY = 'session_warmup'

    def _warmup_decision(self, row, session, health, busy):
        """START a SESSION_CHECK, WAIT for one, or FAIL (SESSION_REQUIRED) for this row."""
        state = (session or {}).get('state')
        if not self.settings.session_warmup or state in ('RESTRICTED', 'ERROR'):
            return 'FAIL'
        warm = self.store.control(self.WARMUP_KEY)
        if warm and warm.get('instruction_id') == row['instruction_id']:
            if warm.get('done_at'):
                return 'FAIL'  # a SESSION_CHECK already ran for this instruction and did not help
            return 'WAIT'
        if warm and not warm.get('done_at'):
            return 'WAIT'      # another instruction's warm-up is running; the phone is busy
        if busy or health.get('current_instruction'):
            return 'WAIT'
        return 'START'

    def _start_warmup(self, gateway, row):
        digest = hashlib.sha256(row['instruction_id'].encode()).hexdigest()[:20]
        device_id = f'sc-{digest}'
        payload = dict(instruction_id=device_id, action='SESSION_CHECK', adapter=self.settings.adapter, scenario='live',
                       sport=row['sport'], timeout_ms=self.settings.session_warmup_timeout_seconds * 1000)
        self.store.set_control(self.WARMUP_KEY, dict(id=device_id, instruction_id=row['instruction_id'],
                                                     requested_at=iso(self.clock()), done_at=None, outcome=None),
                               by='dispatcher')
        try:
            ack = gateway.submit(payload)
            detail = dict(ack=ack)
        except Exception as error:
            detail = dict(error=f'{type(error).__name__}: {error}'[:300])
        with self.store.tx() as db:
            self.store.audit(db, 'SESSION_WARMUP', dict(payload=payload, **detail), row['instruction_id'],
                             self.settings.device_id)

    def _poll_warmup(self, gateway):
        warm = self.store.control(self.WARMUP_KEY)
        if not warm or warm.get('done_at'):
            return
        outcome = None
        try:
            result = gateway.result(warm['id'])
            if isinstance(result, dict) and not result.get('_pending'):
                outcome = f"{result.get('status')}/{result.get('stage')}: {result.get('detail')}"
        except Exception as error:
            outcome = None if isinstance(error, OSError) else f'poll failed: {type(error).__name__}'
        age = (self.clock() - datetime.fromisoformat(warm['requested_at'])).total_seconds()
        if outcome is None and age > self.settings.session_warmup_timeout_seconds + 30:
            outcome = 'no result before timeout'
        if outcome is not None:
            warm.update(done_at=iso(self.clock()), outcome=outcome[:300])
            self.store.set_control(self.WARMUP_KEY, warm, by='dispatcher')

    def _send(self, gateway, instruction_id, payload):
        try:
            ack = gateway.submit(payload)
        except ValueError as error:
            reply = error.args[0] if error.args else None
            if isinstance(reply, dict) and reply.get('stage') == 'INVALID_INSTRUCTION':
                # The phone refused admission (schema, stake cap, disarmed phone): definitively nothing executed.
                with self.store.tx() as db:
                    self.store.audit(db, 'COORDINATOR_REFUSED', reply, instruction_id, self.settings.device_id)
                    prefix = 'PRE_TAP_REJECTED: ' if payload.get('action') == 'PLACE_HELD' else ''
                    if prefix:
                        self.store.audit(db, 'PRE_TAP_REJECTED', dict(stage='admission', reason=reply.get('detail'),
                                                                     execution_job_id=payload.get('instruction_id')),
                                         instruction_id, self.settings.device_id)
                    self.store.transition(db, instruction_id, State.REJECTED, actor='coordinator',
                                          reason=f"{prefix}Coordinator refused admission: {reply.get('detail')}")
                return
            with self.store.tx() as db:
                self.store.audit(db, 'SUBMIT_UNCERTAIN', dict(error=f'{type(error).__name__}: {error}'[:300]),
                                 instruction_id, self.settings.device_id)
            return
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
            final_action = row['execution_mode'] == 'dispatch'
            try:
                state, reason, observed = interpret_device_result(result, final_action=final_action)
                if isinstance(result, dict) and result.get('instruction_id') not in (
                        None, instruction_id, device_instruction_id(instruction_id, row['execution_mode'])):
                    raise ValueError('Result instruction_id does not match')
            except ValueError as error:
                self.store.audit(db, 'MALFORMED_RESULT', dict(error=str(error), result=result, source=source), instruction_id)
                target = State.PLACEMENT_UNKNOWN if final_action else State.UNKNOWN
                self.store.transition(db, instruction_id, target, actor=source, at=iso(now),
                                      reason=f'MALFORMED_RESULT: {error}', result_payload=result)
                if final_action:
                    self.final.record_outcome(db, self.store.get_instruction(db, instruction_id), target, None)
                return target.value
            if state is None:
                return row['state']  # DUPLICATE echo of the original; keep waiting for it.
            from core.execution_terms import comparisons_for_result
            policy = (json.loads(row['rules_result'] or '{}').get('instruction') or {})
            quotes = comparisons_for_result(dict(market=row['market'],side=row['selection'],line=row['line'],price=row['alert_price']),
                                            result, policy)
            for quote in quotes:
                self.store.audit(db, 'ALERT_TO_LIVE_COMPARISON', quote, instruction_id)
            quote = quotes[-1]
            result = dict(result, execution_comparison=quote, execution_comparisons=quotes)
            if state == State.READY and not final_action:
                if not quote['acceptable']:
                    state, reason = State.PRICE_CHANGED, 'NO BET: ' + quote['reason']
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
            pre_tap_rejected = False
            if final_action:
                placement = result.get('placement') if isinstance(result.get('placement'), dict) else None
                if placement is not None:
                    fields['placement'] = placement
                from core.lifecycle import placement_of
                tapped = (placement_of(result) or {}).get('tapped')
                if tapped is False and state in TERMINAL and state != State.COMPLETED:
                    # The fresh pre-tap verification (or the phone's own guards) refused: nothing was tapped.
                    pre_tap_rejected = True
                    reason = 'PRE_TAP_REJECTED: ' + reason
                if tapped is not False and result.get('t_tap_ms'):
                    fields['intent_at'] = datetime.fromtimestamp(result['t_tap_ms'] / 1000, tz=timezone.utc).isoformat(timespec='milliseconds')
            applied = self.store.transition(db, instruction_id, state, actor=source, at=iso(now), reason=reason, **fields)
            if applied and pre_tap_rejected:
                self.store.audit(db, 'PRE_TAP_REJECTED', dict(stage=result.get('stage'), reason=reason, state=state.value,
                                                             pretap=result.get('pretap'), comparison=quote,
                                                             execution_job_id=device_instruction_id(instruction_id, 'dispatch')),
                                 instruction_id, row['device_id'] or self.settings.device_id)
            if applied and final_action and state == State.COMPLETED:
                placement = result.get('placement') if isinstance(result.get('placement'), dict) else {}
                actual = placement.get('actual_terms') if isinstance(placement.get('actual_terms'), dict) else {}
                self.store.audit(db, 'PLACED', dict(execution_job_id=device_instruction_id(instruction_id, 'dispatch'),
                                                    bet_reference=placement.get('bet_reference'), intent_at=fields.get('intent_at'),
                                                    receipt=dict(line=actual.get('line'), odds=actual.get('odds') or placement.get('odds'),
                                                                 stake=actual.get('stake') or placement.get('stake'),
                                                                 potential_return=placement.get('potential_return')),
                                                    pretap=result.get('pretap'), approved_by=row['approved_by'],
                                                    approval_mode=row['approval_mode']),
                                 instruction_id, row['device_id'] or self.settings.device_id)
            if applied and isinstance(result.get('alias_candidate'), dict):
                # A1/B6: the event link opened the right event but a team name differs: record the sighting
                # (strict promotion policy in IdentityRegistry) and audit the evidence.
                cand = result['alias_candidate']
                self.store.audit(db, 'ALIAS_CANDIDATE', cand, instruction_id)
                for feed_name, book_name in (cand.get('candidates') or {}).items():
                    proof = dict(cand, identity=result.get('identity'), event_context=result.get('event_context'), event_url=result.get('event_url'))
                    self.identity.record_candidate(db, row['sport'], feed_name, book_name, proof, cand.get('confidence'), instruction_id, row['competition'])
            if applied and result.get('route') == 'event_link' and state in (State.READY, State.COMPLETED) \
                    and result.get('home') and result.get('away') and result.get('event_url') and result.get('event_context'):
                # B7: the resolved event for this fixture and kick-off (never reused for another kick-off).
                self.identity.record_event(db, row['sport'], row['home'], row['away'], result['event_context'].get('kickoff_utc'), result['event_url'],
                                           result['home'], result['away'], row['competition'])
            if applied and state == State.READY and row['execution_mode'] == 'hold':
                # The verified bet is now on the phone's slip: it owns the phone until placed or released.
                self.store.set_control(HELD_KEY, dict(instruction_id=instruction_id, since=iso(now)), by='dispatcher', db=db)
            if applied and state == State.READY and not final_action:
                if self.final.enabled():
                    self.final.on_verified(db, self.store.get_instruction(db, instruction_id))
                elif self.settings.final_action_enabled and self.final.paused():
                    # Kill switch engaged while the phone was verifying: nothing is approved and the slip is released.
                    self.store.transition(db, instruction_id, State.REJECTED, actor='dispatcher',
                                          reason='KILL_SWITCH: paused when the device verification arrived; nothing approved')
            if applied and final_action:
                from core.lifecycle import placement_of
                tapped = (placement_of(result) or {}).get('tapped')
                if tapped is not False:  # a tap happened or may have happened: record and verify
                    self.final.record_outcome(db, self.store.get_instruction(db, instruction_id), state, result)
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
