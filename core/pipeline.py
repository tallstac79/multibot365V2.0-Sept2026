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
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import re
import threading

from core import alert_classifier
from core.final_action import FinalAction
from core.competition_gender import womens_competition
from core.scoped_identity import IdentityRegistry
from core.lifecycle import State, TERMINAL, DEVICE_OWNED, interpret_device_result, CONFIRMATION_MAP, busy_not_admitted
from core.pipeline_store import Store, iso, utcnow, instruction_id_for, selection_key
from core.rules_engine import evaluate, ACCEPT, STALE, selection_name as rules_selection_name, time_assumptions
from core.session_contract import parse_report, gate as session_gate, DEFAULT_MAX_AGE_SECONDS

log = logging.getLogger('multibot.pipeline')
HISTORY_SCANS = ('reconcile', 'catch_up', 'backfill')


def _epoch(text):
    """Sortable epoch seconds of a stored ISO timestamp (0 when unreadable)."""
    try:
        return datetime.fromisoformat(str(text).replace('Z', '+00:00')).timestamp()
    except (TypeError, ValueError):
        return 0.0


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
    max_bets_per_day: int = None   # no daily bet-count cap (operator, 27 Sep 2026); stake/loss caps still apply
    max_daily_stake: str = None    # no daily total-stake cap (operator, 27 Sep 2026); per-bet and daily-loss caps still apply
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
    # Desktop worker (desktop-chrome) as a routing target: OFF by default; see core/device_routing.py. With it OFF the
    # service uses the phone gateway alone, exactly as before. ON routes new work to the desktop only while it is
    # routable (healthy/ready/IDLE, no blocked_reason) AND bound to both expected values below (empty = never routed).
    desktop_routing_enabled: bool = False
    desktop_device_id: str = 'desktop-chrome'
    desktop_expected_worker_id: str = ''
    desktop_expected_account_fingerprint: str = ''
    # Hot-path latency (29 Sep 2026 speed work; no rule, tolerance, stake or approval value involved):
    #  busy_tick_seconds     dispatcher cadence while work is queued/in flight (idle cadence stays the service's tick_seconds)
    #  health_reuse_seconds  while a job is in flight the phone's health snapshot is reused this long (it is re-read at once
    #                        whenever a result arrives, before approval/dispatch); 0 = read every tick
    #  dispatch_newest_first the freshest queued alert goes first (an approved final action always outranks new work)
    busy_tick_seconds: float = 0.2
    health_reuse_seconds: float = 1.5
    dispatch_newest_first: bool = True
    #  prewarm_enabled       the phone starts loading the event page of the next queued alert at once, in parallel with the dispatcher's
    #                        own intake-to-dispatch work (navigation only; refused by the phone while any job runs or a slip is held)
    prewarm_enabled: bool = True

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
# Supervised desktop target (28 Sep 2026): an operator arms "the next eligible new instruction runs on the desktop worker"
# (tools/desktop_route.py target). One instruction, with an expiry; consumed atomically when that instruction is
# dispatched. Independent of desktop_routing_enabled (normal routing), which stays OFF.
DESKTOP_TARGET_KEY = 'desktop_target_next'


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


def _quote(observed):
    observed = observed if isinstance(observed, dict) else {}
    return dict(market=observed.get('market'), side=observed.get('side') or observed.get('selection_role'),
                line=observed.get('line'), price=observed.get('price'), selection_name=observed.get('selection_name') or observed.get('selection'))


def record_request_stage(store, db, row, payload):
    """hold_request / place_request: what was sent to the phone, before the send (a later dispatch overwrites
    instructions.dispatch_payload, not this). The route the request points the phone to: its own event link or Search.
    requested_price = the alert's price, minimum_price = the minimum acceptable price sent to the phone; `price` is only
    a price the request itself carries (the held price of a PLACE_HELD), never the floor."""
    place = payload.get('action') == 'PLACE_HELD'
    store.record_stage(db, row['instruction_id'], 'place_request' if place else 'hold_request', source='dispatcher',
                       device_instruction_id=payload.get('instruction_id'),
                       route=None if place else ('event_link' if payload.get('event_url') else 'search'),
                       market=payload.get('market'), side=payload.get('side'), line=payload.get('line'),
                       price=payload.get('price') if place else None, requested_price=row['alert_price'],
                       minimum_price=payload.get('minimum_price'), stake=payload.get('stake'),
                       selection_name=payload.get('selection_name'), detail=payload)


PHONE_MARKS = ('t_start_ms', 't_pretap_frame_ms', 't_pretap_done_ms', 't_flush_done_ms', 't_gesture_ms', 't_tap_ms', 't_receipt_seen_ms',
               't_receipt_ms', 't_home_ms', 'event_load_ms',
               'receipt_seen_after_tap_ms', 'receipt_extra_looks', 'event_direct_wait', 'duration_ms')


def phone_timings(result):
    """The phone's own timing record of one job (its stage_timings and wall-clock marks), for latency analysis only."""
    timings = [dict(stage=t.get('stage'), start_elapsed_ms=t.get('start_elapsed_ms'), end_elapsed_ms=t.get('end_elapsed_ms'),
                    duration_ms=t.get('duration_ms'), retries=t.get('retries'), status=t.get('status'))
               for t in (result.get('stage_timings') or []) if isinstance(t, dict)]
    return dict(marks={k: result[k] for k in PHONE_MARKS if result.get(k) is not None}, stage_timings=timings,
                app_version=result.get('app_version'), run_id=result.get('run_id'))


def record_result_stages(store, db, instruction_id, result, final_action, state, at=None):
    """Per-stage evidence from a phone result, written once each (analysis only; nothing here affects execution).
    hold run   -> first_quote (the first live quote the phone read, and the route it actually used) + hold_result;
    place run  -> pretap (the fresh pre-tap quote) + receipt (outcome and receipt terms)."""
    if not isinstance(result, dict):
        return
    observations = [o for o in (result.get('execution_observations') or []) if isinstance(o, dict) and isinstance(o.get('observed'), dict)]
    job = result.get('instruction_id')
    if not final_action:
        route = result.get('route')
        first = observations[0] if observations else None
        if first is None and isinstance(result.get('selection'), dict):
            first = dict(stage='selection', observed=result['selection'])
        if first is not None:
            store.record_stage(db, instruction_id, 'first_quote', source='phone hold result', at=at, device_instruction_id=job,
                               route=route, **_quote(first['observed']),
                               detail=dict(observation_stage=first.get('stage'), observed_at_ms=first.get('observed_at_ms'),
                                           identity_verified=first.get('identity_verified')))
        held = result.get('selection') if isinstance(result.get('selection'), dict) else {}
        store.record_stage(db, instruction_id, 'hold_result', source='phone hold result', at=at, device_instruction_id=job,
                           route=route, outcome=f"{state} ({result.get('status')}/{result.get('stage')})", **_quote(held),
                           stake=(result.get('ready_state') or {}).get('stake') if isinstance(result.get('ready_state'), dict) else None,
                           detail=dict(event_url=result.get('event_url'), identity_verdict=result.get('identity_verdict'),
                                       event_context=result.get('event_context'), fixture_name=result.get('fixture_name'),
                                       detail=result.get('detail'), run_id=result.get('run_id')))
        store.record_stage(db, instruction_id, 'hold_timings', source='phone hold result', at=at, device_instruction_id=job,
                           route=route, outcome=state, detail=phone_timings(result))
        return
    store.record_stage(db, instruction_id, 'place_timings', source='phone place result', at=at, device_instruction_id=job,
                       outcome=state, detail=phone_timings(result))
    pretap = result.get('pretap') if isinstance(result.get('pretap'), dict) else None
    if pretap is None:
        pre = [o for o in observations if o.get('stage') == 'pretap']
        pretap = pre[0]['observed'] if pre else None
    if pretap:
        store.record_stage(db, instruction_id, 'pretap', source='phone place result', at=at, device_instruction_id=job,
                           **_quote(pretap), stake=pretap.get('stake'), detail=pretap)
    placement = result.get('placement') if isinstance(result.get('placement'), dict) else None
    if placement is not None:
        actual = placement.get('actual_terms') if isinstance(placement.get('actual_terms'), dict) else {}
        store.record_stage(db, instruction_id, 'receipt', source='phone place result', at=at, device_instruction_id=job,
                           market=(pretap or {}).get('market'), side=(pretap or {}).get('side'),
                           line=actual.get('line'), price=actual.get('odds') or placement.get('odds'),
                           stake=actual.get('stake') or placement.get('stake'), bet_reference=placement.get('bet_reference'),
                           outcome=f"{placement.get('outcome')} (tapped={placement.get('tapped')})",
                           detail=dict(actual_terms=actual, potential_return=placement.get('potential_return'),
                                       receipt_lines=placement.get('receipt_lines'), frames=placement.get('frames'),
                                       terms_source=placement.get('terms_source')))


class Pipeline:
    def __init__(self, store, config_provider, settings=None, clock=utcnow):
        self.store = store if isinstance(store, Store) else Store(store, clock)
        self.store.clock = clock
        self.config_provider = config_provider   # () -> decision-support config dict
        self.settings = settings or Settings()
        self.clock = clock
        self._wake = threading.Event()          # set after an intake commit / a result: the dispatcher need not wait out its sleep
        self._health_cache = (None, None)       # (clock time, health) of the last phone health read
        self._prewarmed = None                  # (instruction_id, url) last sent to the phone as a prewarm
        self._prewarm_retry_at = None
        self.final = FinalAction(self)
        self.identity = IdentityRegistry(self.store)
        self.armed_at = iso(clock())    # one-shot: only Place Bet runs dispatched after this count
        self.disarmed = None            # set when the one-shot fired (the service persists it)
        # Desktop worker (desktop-chrome): its own device/worker/account identity. The service attaches its gateway
        # (DesktopGateway) only when that identity is configured; phone behaviour is unchanged either way.
        self.desktop = None
        self.desktop_health = None
        if self.desktop_configured():
            self.store.register_device(self.settings.desktop_device_id, 'desktop_chrome', self.settings.desktop_expected_worker_id,
                                       self.settings.desktop_expected_account_fingerprint, source='pipeline settings')

    # ================================================================== devices
    def desktop_configured(self):
        s = self.settings
        return bool(s.desktop_device_id and s.desktop_expected_worker_id and s.desktop_expected_account_fingerprint)

    def is_desktop(self, device_id):
        return bool(device_id) and device_id == self.settings.desktop_device_id and self.desktop_configured()

    def device_of(self, row):
        """The device an instruction is bound to (the phone unless it was dispatched to the desktop)."""
        return self.settings.desktop_device_id if self.is_desktop(row['device_id']) else self.settings.device_id

    def gateway_of(self, device_id, phone_gateway):
        return self.desktop if self.is_desktop(device_id) else phone_gateway

    def health_of(self, device_id, phone_health):
        return self.desktop_health if self.is_desktop(device_id) else phone_health

    def refresh_desktop(self):
        """Desktop health/session into device_state/session_state under desktop-chrome (never the phone's records)."""
        if self.desktop is None or not self.desktop_configured():
            self.desktop_health = None
            return None
        self.desktop_health = self.refresh_device(self.desktop, device_id=self.settings.desktop_device_id)
        return self.desktop_health

    def desktop_target(self):
        t = self.store.control(DESKTOP_TARGET_KEY)
        if not isinstance(t, dict) or t.get('consumed_by') or t.get('cancelled_at'):
            return None
        if (t.get('expires_at') or '') <= iso(self.clock()):
            return None
        return t

    def arm_desktop_target(self, by, minutes=60, sport='football', min_lead_minutes=10):
        now = self.clock()
        from datetime import timedelta
        value = dict(armed_at=iso(now), expires_at=iso(now + timedelta(minutes=minutes)), by=by, sport=sport,
                     pre_match=True, min_lead_minutes=min_lead_minutes, consumed_by=None)
        self.store.set_control(DESKTOP_TARGET_KEY, value, by=by)
        with self.store.tx() as db:
            self.store.audit(db, 'DESKTOP_TARGET_ARMED', value, device_id=self.settings.desktop_device_id)
        return value

    def cancel_desktop_target(self, by):
        t = self.store.control(DESKTOP_TARGET_KEY)
        if isinstance(t, dict) and not t.get('consumed_by'):
            t['cancelled_at'] = iso(self.clock())
            self.store.set_control(DESKTOP_TARGET_KEY, t, by=by)
        return t

    def _target_eligible(self, row, target):
        """A new, pre-match instruction of the armed sport received after arming."""
        from datetime import timedelta
        if target.get('sport') and row['sport'] != target['sport']:
            return False
        try:
            received = datetime.fromisoformat((row['received_at'] or '').replace('Z', '+00:00'))
            if received < datetime.fromisoformat(target['armed_at']):
                return False                  # only alerts received after arming
        except (ValueError, TypeError):
            return False
        start = (json.loads(row['rules_result'] or '{}').get('instruction') or {}).get('event_start_utc')
        if not start:
            return False
        try:
            begins = datetime.fromisoformat(start)
            begins = begins if begins.tzinfo else begins.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return False
        return begins - self.clock() >= timedelta(minutes=target.get('min_lead_minutes') or 0)

    def _choose_target(self, row):
        """(device_id, reason). A row already bound to the desktop stays there (its hold is on the desktop slip). A new
        QUEUED row goes to the desktop only while it is routable AND bound to its expected worker/account AND its backend
        session is authenticated, and only when normal routing is ON or a supervised target is armed; otherwise the phone."""
        s = self.settings
        if self.is_desktop(row['device_id']):
            self.refresh_desktop()            # fresh /health for this row's dispatch checks (not the tick-start snapshot)
            return s.desktop_device_id, 'bound to the desktop'
        if row['state'] != State.QUEUED.value or self.desktop is None or not self.desktop_configured():
            return s.device_id, 'phone'
        armed = self.desktop_target()
        if not s.desktop_routing_enabled and not (armed and self._target_eligible(row, armed)):
            return s.device_id, 'phone'
        from core.device_routing import routable
        # a fresh /health right before the decision: a Reality Check seen by the worker since the tick began is honoured
        # now (the worker's own pre-run gate refuses anything that still slips through, without touching the page)
        ok, why = routable(self.refresh_desktop(), s.desktop_device_id, s.desktop_expected_worker_id, s.desktop_expected_account_fingerprint)
        if not ok:
            return s.device_id, f'desktop not routable: {why}'
        permitted, why = session_gate(self.store.session(s.desktop_device_id), self.clock(), s.session_max_age_seconds)
        if not permitted:
            return s.device_id, f'desktop session: {why}'
        if self.final.device_busy('desktop'):
            return s.device_id, 'desktop My Bets check running'
        return s.desktop_device_id, 'normal routing' if s.desktop_routing_enabled else 'supervised desktop target'

    # ================================================================== intake
    def ingest(self, message, delivery='event'):
        """Record one delivered message (see _ingest), then wake the dispatcher: a newly QUEUED alert is dispatched at once
        instead of at the end of the dispatcher's sleep (the commit has completed by now, so the tick sees the row)."""
        result = self._ingest(message, delivery)
        self._wake.set()
        return result

    def _ingest(self, message, delivery='event'):
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
            return self._ingest(message, delivery)

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
            # One bet per market per game: a later alert for a market already bet on this game is ignored here, before it
            # qualifies (no operator message). Durable: read from the store.
            from core.final_action import market_already_bet
            already = market_already_bet(db, self.store.get_instruction(db, instruction_id))
            if already:
                self.store.transition(db, instruction_id, State.REJECTED, actor='rules', at=iso(now), reason=already)
                return State.REJECTED.value
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
    def refresh_device(self, gateway, device_id=None):
        """Poll coordinator health; record device and session state. Returns health or None."""
        device_id, now = device_id or self.settings.device_id, self.clock()
        try:
            health = gateway.health()
            if not isinstance(health, dict) or 'healthy' not in health:
                raise ValueError('Malformed health response')
        except Exception as error:
            self.store.record_device(device_id, 'OFFLINE', error=f'{type(error).__name__}: {error}'[:300], at=iso(now))
            return None
        status = 'ONLINE' if health.get('healthy') is True else 'DEGRADED'
        self.store.record_device(device_id, status, health=health, at=iso(now))
        self._record_session(health.get('session'), 'health', now, device_id)
        return health

    def _record_session(self, payload, source, now, device_id=None):
        if payload is None:
            return
        device_id = device_id or self.settings.device_id
        try:
            if isinstance(payload, str) and self.is_desktop(device_id):
                payload = json.loads(payload)       # the desktop worker's health carries its session as a JSON string
            self.store.record_session(parse_report(device_id, payload, source), iso(now))
        except (ValueError, TypeError) as error:
            with self.store.tx() as db:
                self.store.audit(db, 'MALFORMED_SESSION_REPORT', dict(error=str(error), payload=payload, source=source),
                                 device_id=device_id, at=iso(now))

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
        line = selection.get('line') if row['market'] not in ('ML', 'MONEYLINE', '1X2') else ''
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
        gateway, health = self.gateway_of(row['device_id'], gateway), self.health_of(row['device_id'], health)
        if gateway is None or health is None or health.get('healthy') is not True or health.get('current_instruction'):
            return  # phone (or the desktop holding it) busy/offline: retry next tick
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
        return outcome == 'reset sent'

    # ---- cadence (latency only)
    BUSY_STATES = (State.QUEUED, State.APPROVED, State.DISPATCHED, State.DEVICE_ACTIVE)

    def next_tick_delay(self, idle_seconds):
        """Seconds the dispatcher may sleep: the short busy cadence while work is queued/approved/in flight, else idle."""
        busy = self.settings.busy_tick_seconds
        if busy and busy < idle_seconds and self.store.instructions_in(self.BUSY_STATES):
            return busy
        return idle_seconds

    def wait_for_work(self, timeout):
        """Sleep up to `timeout` seconds, returning early when an intake commit woke the dispatcher."""
        self._wake.wait(max(0.0, timeout))
        self._wake.clear()

    def _phone_health(self, gateway, job_in_flight):
        """The phone's health for this tick. While a job is in flight the snapshot is reused for health_reuse_seconds
        (each read is an HTTP call to the phone); everything that decides on it re-reads after a result (see tick)."""
        at, health = self._health_cache
        reuse = self.settings.health_reuse_seconds
        if job_in_flight and reuse > 0 and at is not None and health is not None and (self.clock() - at).total_seconds() < reuse \
                and not health.get('diagnostics_active'):
            return health
        health = self.refresh_device(gateway)
        self._health_cache = (self.clock(), health)
        return health

    PREWARM_STATES = ('DISPATCHED', 'DEVICE_ACTIVE', 'READY', 'APPROVED', 'PLACEMENT_UNKNOWN')

    def _prewarm(self, gateway):
        """Start the phone loading the event page of the alert that will be dispatched next. Called at the start of a tick, BEFORE the
        health read and the dispatch checks, so the ~4 s page load overlaps them instead of following them. Best effort: any refusal or
        error changes nothing (the hold navigates itself exactly as before)."""
        if not self.settings.prewarm_enabled or not self.settings.dispatch_enabled or self.final.paused():
            return
        if not hasattr(gateway, 'prewarm') or self.store.instructions_in([State(x) for x in self.PREWARM_STATES]):
            return
        if self.held_instruction() or self.final.device_busy('phone'):
            return
        rows = self.store.instructions_in([State.QUEUED])
        if not rows:
            return
        rows.sort(key=lambda r: -_epoch(r['received_at'])) if self.settings.dispatch_newest_first else rows.sort(key=lambda r: _epoch(r['received_at']))
        row = rows[0]
        try:
            target, _ = self._choose_target(row)
        except Exception:
            return
        url = event_link(row)
        if target != self.settings.device_id or not url or row['sport'] not in ('football', 'basketball'):
            return
        key = (row['instruction_id'], url)
        now = self.clock()
        if self._prewarmed == key or (self._prewarm_retry_at is not None and now < self._prewarm_retry_at):
            return
        try:
            reply = gateway.prewarm(url)
        except Exception as error:
            reply = {'started': False, 'error': type(error).__name__}
        if reply.get('started') or reply.get('hot'):
            self._prewarmed = key
            self._prewarm_retry_at = None
        else:
            self._prewarm_retry_at = now + timedelta(seconds=0.5)   # the phone is finishing something: ask again shortly
            return
        with self.store.tx() as db:
            self.store.audit(db, 'PREWARM', dict(url=url, reply=reply), row['instruction_id'])

    def tick(self, gateway):
        """One dispatcher cycle. Safe to call repeatedly and after any restart."""
        self._prewarm(gateway)
        in_flight = bool(self.store.instructions_in([State.DISPATCHED, State.DEVICE_ACTIVE]))
        health = self._phone_health(gateway, in_flight)
        desktop_health = self.refresh_desktop()
        if health and health.get('diagnostics_active'):
            self._poll_in_flight(gateway)
            return  # lease suppresses reset, warmup, reconciliation and dispatch; polling remains safe
        self._poll_warmup(gateway)

        def phone_state_moved():
            # A terminal result is about to be applied (and, for a READY hold, approved and dispatched on it): read the phone's
            # health NOW, after the result and before the decision - never a snapshot from the start of the tick. A finished
            # hold is then no longer 'current_instruction', so the approved final action is sent in this same tick instead of
            # waiting a whole extra cycle (the ~2 s tail of approved -> place dispatch), and worker/account/permission are
            # checked against the state at the moment of approval.
            nonlocal health
            fresh = self._phone_health(gateway, False)
            health = fresh if fresh is not None else health

        self._poll_in_flight(gateway, before_apply=phone_state_moved)
        self._one_shot()
        if self._release_hold(gateway, health):
            return  # the phone is now running RESET_BETSLIP; this tick's health snapshot is stale (27 Sep 2026 BUSY race)
        self.final.poll(gateway, desktop=self.desktop if self.desktop_configured() else None)
        self._expire_ready()
        self.final.expire_approvals()
        # Placement verification outranks new work: an unresolved tap blocks nothing else
        # being learnt, but the phone does one thing at a time.
        device_free = not self.store.instructions_in([State.DISPATCHED, State.DEVICE_ACTIVE])
        held = self.held_instruction()
        # A held bet owns the phone: no My Bets checks (they navigate away) until it is placed or released.
        # A2: live placement work outranks routine My Bets checks; only PLACEMENT_UNKNOWN resolution is urgent.
        if not held and self.final.schedule(gateway, health, device_free and not self.final.device_busy('phone'),
                                            urgent_only=self._live_work_pending()):
            return
        if not held and self.desktop is not None and self.desktop_configured():
            # My Bets checks for bets placed on the desktop worker/account run on the desktop (never on the phone)
            self.final.schedule(self.desktop, desktop_health, device_free and not self.final.device_busy('desktop'),
                                urgent_only=self._live_work_pending(), scope='desktop')
        if not self.final.device_busy('phone'):
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

    def _poll_in_flight(self, gateway, before_apply=None):
        """Poll every in-flight job; True when at least one terminal result was applied. `before_apply` runs once before each
        terminal result is applied (the tick re-reads the phone's health there)."""
        applied = False
        for row in self.store.instructions_in([State.DISPATCHED, State.DEVICE_ACTIVE]):
            try:
                gw = self.gateway_of(row['device_id'], gateway)
                if gw is None:
                    raise ConnectionError('desktop gateway not attached')
                result = gw.result(device_instruction_id(row['instruction_id'], row['execution_mode']))
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
                    if before_apply is not None:
                        before_apply()
                    self.apply_result(row['instruction_id'], result)
                    applied = True
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
        return applied

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
        # Approved final actions first: an operator is waiting on them. Then (29 Sep 2026, burst handling) the FRESHEST queued
        # alert: its price is the least stale, while older ones keep waiting and age out as STALE exactly as before.
        if self.settings.dispatch_newest_first:
            candidates.sort(key=lambda r: (0 if r['state'] == State.APPROVED.value else 1, -_epoch(r['received_at'])))
        else:
            candidates.sort(key=lambda r: 0 if r['state'] == State.APPROVED.value else 1)
        warmup_for = None
        held = self.held_instruction()
        activation = self.store.control(self.ACTIVATION_KEY)
        phone_gateway, phone_health = gateway, health
        for row in candidates:
            if held and row['instruction_id'] != held:
                continue  # the phone holds another verified bet on its slip; wait (may age out as STALE)
            target, target_reason = self._choose_target(row)
            desktop = target != self.settings.device_id
            gateway, health = (self.desktop, self.desktop_health) if desktop else (phone_gateway, phone_health)
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
                session = self.store.session(target)
                permitted, why = session_gate(session, now, self.settings.session_max_age_seconds)
                if not permitted:
                    # the desktop has no warm-up: a desktop-bound row fails closed (a new row only targets it when authenticated)
                    decision = 'FAIL' if desktop else self._warmup_decision(row, session, health, bool(in_flight))
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
                    if row['device_id'] not in (None, '', self.settings.device_id) and not self.is_desktop(row['device_id']):
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
                if desktop and self.final.device_busy('desktop'):
                    continue  # a desktop My Bets check is running
                payload = self.build_payload(row, final_action=final_action and row['state'] == State.APPROVED.value)
                extra = {}
                if desktop and not self.is_desktop(row['device_id']):
                    # bind the instruction to the desktop device (its own worker/account); consume a supervised target
                    extra['device_id'] = target
                    armed = self.desktop_target()
                    if not self.settings.desktop_routing_enabled:
                        if not armed:
                            continue
                        self.store.set_control(DESKTOP_TARGET_KEY, dict(armed, consumed_by=row['instruction_id'], consumed_at=iso(now)),
                                               by='dispatcher', db=db)
                    self.store.audit(db, 'DEVICE_TARGET', dict(device_id=target, reason=target_reason,
                                                               worker_id=self.settings.desktop_expected_worker_id,
                                                               account_fingerprint=self.settings.desktop_expected_account_fingerprint),
                                     row['instruction_id'], target)
                # Commit DISPATCHED before sending: a crash after this point can never resend.
                if not self.store.transition(db, row['instruction_id'], State.DISPATCHED, actor='dispatcher',
                                             reason='Sent to coordinator' + (' (FINAL ACTION: Place Bet approved)'
                                                                             if payload['execution_mode'] == 'dispatch' else '')
                                                    + (f' [desktop worker {target}]' if desktop else ''),
                                             dispatch_payload=payload, execution_mode=payload['execution_mode'],
                                             dispatch_attempts=row['dispatch_attempts'] + 1,
                                             session_state=session['state'], **extra):
                    continue
            in_flight = [row]
            with self.store.tx() as db:
                record_request_stage(self.store, db, row, payload)
            self._send(gateway, row['instruction_id'], payload, device_id=target)
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

    def _send(self, gateway, instruction_id, payload, device_id=None):
        device_id = device_id or self.settings.device_id
        try:
            ack = gateway.submit(payload)
        except ValueError as error:
            reply = error.args[0] if error.args else None
            if isinstance(reply, dict) and reply.get('stage') == 'INVALID_INSTRUCTION':
                # The phone refused admission (schema, stake cap, disarmed phone): definitively nothing executed.
                with self.store.tx() as db:
                    self.store.audit(db, 'COORDINATOR_REFUSED', reply, instruction_id, device_id)
                    prefix = 'PRE_TAP_REJECTED: ' if payload.get('action') == 'PLACE_HELD' else ''
                    if prefix:
                        self.store.audit(db, 'PRE_TAP_REJECTED', dict(stage='admission', reason=reply.get('detail'),
                                                                     execution_job_id=payload.get('instruction_id')),
                                         instruction_id, device_id)
                    self.store.transition(db, instruction_id, State.REJECTED, actor='coordinator',
                                          reason=f"{prefix}Coordinator refused admission: {reply.get('detail')}")
                return
            if busy_not_admitted(error):
                # The phone was running something else and did not consume this ID: nothing executed. Return the
                # instruction to where it came from; the dispatcher resends the same ID when the phone is free.
                back = State.APPROVED if payload.get('execution_mode') == 'dispatch' else State.QUEUED
                with self.store.tx() as db:
                    self.store.audit(db, 'SUBMIT_NOT_ADMITTED_BUSY', dict(reply=reply if isinstance(reply, dict) else str(reply)[:200]),
                                     instruction_id, device_id)
                    self.store.requeue_not_admitted(db, instruction_id, back,
                                                    reason='Phone busy: ID not consumed, nothing admitted; resent when the phone is free')
                return
            with self.store.tx() as db:
                self.store.audit(db, 'SUBMIT_UNCERTAIN', dict(error=f'{type(error).__name__}: {error}'[:300]),
                                 instruction_id, device_id)
            return
        except Exception as error:
            # Uncertain delivery: keep DISPATCHED and poll the same ID; never resend a new ID.
            with self.store.tx() as db:
                self.store.audit(db, 'SUBMIT_UNCERTAIN', dict(error=f'{type(error).__name__}: {error}'[:300]),
                                 instruction_id, device_id)
            return
        with self.store.tx() as db:
            self.store.audit(db, 'COORDINATOR_ACK', ack, instruction_id, device_id)
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
                                            result, policy, sport=row['sport'])
            for quote in quotes:
                self.store.audit(db, 'ALERT_TO_LIVE_COMPARISON', quote, instruction_id)
            # A verified hold is judged on its fresh final slip verification (the phone records one before every READY),
            # never on an earlier grid/preflight observation that happened to be recorded last (28 Sep 2026, Al Kharaitiyat:
            # the identity-unverified preflight read was judged and the acceptable slip refused). Without a final one: last.
            finals = [q for q in quotes if q.get('stage') == 'final']
            quote = finals[-1] if finals and state == State.READY else quotes[-1]
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
            record_result_stages(self.store, db, instruction_id, result, final_action, state.value, at=iso(now))
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
