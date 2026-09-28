"""Desktop worker in the backend (28 Sep 2026), offline: its own durable device/worker/account identity (desktop-chrome),
the supervised desktop target (normal routing OFF), the same automatic approval policy bound to the desktop's identity and
its own final-action arming, placement recorded under the desktop worker/account, and My Bets reconciliation routed to the
worker/account that placed the bet. Phone behaviour is unchanged. Fake gateways only: no device, no bookmaker, no money."""
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from core.pipeline import DESKTOP_TARGET_KEY
from tests.pipeline_support import (ACCOUNT_FINGERPRINT, MELBOURNE, RYTAS, WORKER_ID, Clock, FakeGateway, message, pipeline,
                                    ready_result)
from tests.test_final_action import MELBOURNE_CARD, my_bets, placement_result

DESK_WORKER, DESK_ACCOUNT = 'dw-test-desk', 'fp-test-desk'
DESKTOP = dict(desktop_expected_worker_id=DESK_WORKER, desktop_expected_account_fingerprint=DESK_ACCOUNT)
AUTO = dict(final_action_enabled=True, approval_mode='automatic')


class DesktopGateway(FakeGateway):
    """The desktop worker's /health contract (desktop_worker.server.Worker.health)."""
    def __init__(self, clock):
        super().__init__(clock)
        self.armed = True
        self.blocked = None

    def health(self):
        if self.health_error:
            raise self.health_error
        observed = self.clock() - timedelta(seconds=self.session_age)
        h = dict(healthy=self.blocked is None, ready=self.blocked is None, blocked_reason=self.blocked, state='IDLE',
                 current_instruction=None, kind='desktop_chrome', device_id='desktop-chrome', worker_id=DESK_WORKER,
                 account_fingerprint=DESK_ACCOUNT, phone_final_action_armed=False, final_action_armed=self.armed,
                 session=json.dumps(dict(state='AUTHENTICATED' if self.blocked is None else 'UNKNOWN',
                                         observed_at_ms=int(observed.timestamp() * 1000))))
        h.update(self.health_extra)
        return h


class Base(unittest.TestCase):
    settings = dict(AUTO, **DESKTOP)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'p.sqlite3'
        self.clock = Clock()
        self.phone = FakeGateway(self.clock)
        self.desk = DesktopGateway(self.clock)
        self.p = pipeline(self.path, self.clock, instant_verification=False, **self.settings)
        self.p.desktop = self.desk

    def row(self, iid):
        with self.p.store.connection() as db:
            return dict(db.execute('SELECT * FROM instructions WHERE instruction_id=?', (iid,)).fetchone())

    def bet(self, iid):
        with self.p.store.connection() as db:
            r = db.execute('SELECT * FROM bets WHERE instruction_id=?', (iid,)).fetchone()
        return dict(r) if r else None

    def audits(self, kind, iid=None):
        with self.p.store.connection() as db:
            rows = db.execute('SELECT * FROM audit_events WHERE kind=?' + (' AND instruction_id=?' if iid else ''),
                              (kind, iid) if iid else (kind,)).fetchall()
        return [dict(r, detail=json.loads(r['detail']) if r['detail'] else None) for r in rows]

    def tick(self):
        self.p.tick(self.phone)

    def answer_hold(self, gw, iid):
        row = self.row(iid)
        payload = json.loads(row['dispatch_payload'])
        result = ready_result(iid, row['alert_price'])
        result['selection'].update(market=row['market'], side=row['selection'], line=row['line'], selection_name=row['selection_name'])
        result['event_context'].update(home=row['home'], away=row['away'], competition=row['competition'], kickoff_utc=payload['kickoff_utc'])
        result['ready_state']['stake'] = row['stake']
        gw.results[iid] = result

    def arm(self, sport='basketball'):
        return self.p.arm_desktop_target('test', minutes=30, sport=sport)

    def placed_on_desktop(self, sample=MELBOURNE):
        self.tick()                                        # desktop health/session recorded
        self.arm()
        iid = self.p.ingest(message(sample, received=self.clock()))['instruction_id']
        self.tick()
        self.answer_hold(self.desk, iid)
        self.tick()
        return iid


class Identity(Base):
    def test_desktop_has_its_own_durable_identity_and_the_phone_records_are_untouched(self):
        self.tick()
        ident = self.p.store.device_identity('desktop-chrome')
        self.assertEqual((ident['kind'], ident['worker_id'], ident['account_fingerprint']), ('desktop_chrome', DESK_WORKER, DESK_ACCOUNT))
        self.assertIsNone(self.p.store.device_identity('galaxy-a13-5g'))         # the phone is not re-registered
        phone, desk = self.p.store.device('galaxy-a13-5g'), self.p.store.device('desktop-chrome')
        self.assertEqual(json.loads(phone['health'])['worker_id'], WORKER_ID)
        self.assertEqual(json.loads(desk['health'])['worker_id'], DESK_WORKER)
        self.assertEqual(self.p.store.session('desktop-chrome')['state'], 'AUTHENTICATED')
        self.assertEqual(self.p.store.session('galaxy-a13-5g')['state'], 'AUTHENTICATED')
        # re-registering the same identity is a no-op; a change is audited, never silent
        from core.pipeline import Pipeline, Settings
        Pipeline(self.p.store, lambda: {}, Settings(**dict(DESKTOP, device_id='galaxy-a13-5g')), clock=self.clock)
        self.assertEqual(len(self.audits('DEVICE_REGISTERED')), 1)
        Pipeline(self.p.store, lambda: {}, Settings(desktop_expected_worker_id='dw-other', desktop_expected_account_fingerprint=DESK_ACCOUNT),
                 clock=self.clock)
        self.assertEqual(self.audits('DEVICE_IDENTITY_CHANGED')[0]['detail']['before']['worker_id'], DESK_WORKER)

    def test_unconfigured_desktop_registers_nothing_and_is_never_polled(self):
        p = pipeline(self.path.with_name('q.sqlite3'), self.clock, instant_verification=False, **AUTO)
        p.desktop = self.desk
        p.tick(self.phone)
        self.assertIsNone(p.store.device_identity('desktop-chrome'))
        self.assertIsNone(p.store.device('desktop-chrome'))


class SupervisedTarget(Base):
    def test_without_a_target_new_work_stays_on_the_phone_even_when_the_desktop_is_routable(self):
        self.tick()
        iid = self.p.ingest(message(MELBOURNE, received=self.clock()))['instruction_id']
        self.tick()
        self.assertEqual([x['action'] for x in self.phone.submitted], ['ADAPTER_WORKFLOW'])
        self.assertEqual(self.desk.submitted, [])
        self.assertEqual(self.row(iid)['device_id'], 'galaxy-a13-5g')

    def test_target_sends_exactly_one_instruction_to_the_desktop_under_its_own_identity(self):
        iid = self.placed_on_desktop()
        row = self.row(iid)
        self.assertEqual(row['device_id'], 'desktop-chrome')
        self.assertEqual([x['action'] for x in self.desk.submitted], ['ADAPTER_WORKFLOW', 'PLACE_HELD'])
        self.assertEqual(self.phone.submitted, [])
        self.assertEqual(self.p.store.control(DESKTOP_TARGET_KEY)['consumed_by'], iid)
        self.assertEqual(self.audits('DEVICE_TARGET', iid)[0]['detail']['reason'], 'supervised desktop target')
        # the same automatic policy, bound to the desktop worker/account and its own final-action arming
        record = self.audits('AUTO_APPROVED', iid)[0]
        self.assertEqual(record['device_id'], 'desktop-chrome')
        self.assertEqual((record['detail']['worker'], record['detail']['account']),
                         (dict(device_id='desktop-chrome', worker_id=DESK_WORKER), DESK_ACCOUNT))
        checks = {c['check']: c['ok'] for c in record['detail']['checks']}
        self.assertTrue(all(checks.values()))
        self.assertIn('desktop_final_action_permission', checks)
        self.assertNotIn('phone_final_action_permission', checks)
        place = self.desk.submitted[-1]
        self.assertEqual((place['instruction_id'], place['confirmation_status'], place['held_instruction_id']), (iid + '-place', 'APPROVED', iid))
        # receipt -> COMPLETED; the bet row is bound to the desktop worker/account
        self.desk.results[iid + '-place'] = placement_result(iid)
        self.tick()
        self.assertEqual(self.row(iid)['state'], 'COMPLETED')
        bet = self.bet(iid)
        self.assertEqual((bet['status'], bet['worker_id'], bet['account_fingerprint'], bet['bet_reference']),
                         ('PLACED_UNVERIFIED', DESK_WORKER, DESK_ACCOUNT, 'JL1234567890'))
        self.assertIn('desktop worker desktop-chrome', bet['binding_source'])
        self.assertEqual(self.audits('PLACED', iid)[0]['device_id'], 'desktop-chrome')
        # My Bets verification runs on the desktop (the account that placed it), never on the phone
        self.clock.advance(self.p.settings.reconcile_delay_seconds + 1)
        self.tick()
        checks = [x for x in self.desk.submitted if x['action'] == 'MY_BETS']
        self.assertEqual(len(checks), 1)
        self.assertFalse([x for x in self.phone.submitted if x['action'] == 'MY_BETS'])
        self.desk.results[checks[0]['instruction_id']] = my_bets(checks[0]['instruction_id'], MELBOURNE_CARD)
        self.tick()
        self.assertEqual(self.row(iid)['reconciliation_result'], 'FOUND_IN_MY_BETS')
        self.assertEqual(self.bet(iid)['status'], 'OPEN')
        with self.p.store.connection() as db:
            rec = dict(db.execute('SELECT * FROM reconciliations').fetchone())
        self.assertEqual((rec['worker_id'], rec['account_fingerprint'], rec['outcome']), (DESK_WORKER, DESK_ACCOUNT, 'FOUND'))
        # the target was one instruction: the next alert goes to the phone
        nxt = self.p.ingest(message(RYTAS, received=self.clock()))['instruction_id']
        self.tick()
        self.assertEqual(self.row(nxt)['device_id'], 'galaxy-a13-5g')
        self.assertEqual(self.phone.submitted[-1]['instruction_id'], nxt)

    def test_desktop_not_armed_for_final_action_is_refused_by_the_policy(self):
        self.desk.armed = False
        iid = self.placed_on_desktop()
        self.assertEqual(self.row(iid)['state'], 'REJECTED')
        refused = self.audits('AUTO_APPROVAL_REFUSED', iid)[0]['detail']
        self.assertEqual([c['check'] for c in refused['checks'] if not c['ok']], ['desktop_final_action_permission'])
        self.assertEqual([x['action'] for x in self.desk.submitted if x['action'] == 'PLACE_HELD'], [])

    def test_blocked_or_wrongly_bound_desktop_is_never_targeted(self):
        for change in (dict(blocked='REALITY_CHECK'), dict(extra=dict(account_fingerprint='fp-other')), dict(extra=dict(worker_id='dw-x')),
                       dict(extra=dict(state='EXECUTING', current_instruction='x'))):
            with self.subTest(change=change):
                self.setUp()
                self.desk.blocked = change.get('blocked')
                self.desk.health_extra = change.get('extra', {})
                self.tick(); self.arm()
                iid = self.p.ingest(message(MELBOURNE, received=self.clock()))['instruction_id']
                self.tick()
                self.assertEqual(self.desk.submitted, [])
                self.assertEqual(self.row(iid)['device_id'], 'galaxy-a13-5g')
                self.assertIsNone(self.p.store.control(DESKTOP_TARGET_KEY)['consumed_by'])   # still armed, unconsumed

    def test_expired_cancelled_old_or_other_sport_targets_do_not_apply(self):
        self.tick()
        self.arm(sport='football')                                            # MELBOURNE is basketball
        a = self.p.ingest(message(MELBOURNE, received=self.clock()))['instruction_id']
        self.tick()
        self.assertEqual(self.row(a)['device_id'], 'galaxy-a13-5g')
        self.setUp(); self.tick()
        early = self.p.ingest(message(MELBOURNE, received=self.clock() - timedelta(seconds=5)))['instruction_id']
        self.clock.advance(1); self.arm()                                     # received before arming
        self.tick()
        self.assertEqual(self.row(early)['device_id'], 'galaxy-a13-5g')
        self.setUp(); self.tick(); self.arm(); self.p.cancel_desktop_target('test')
        b = self.p.ingest(message(MELBOURNE, received=self.clock()))['instruction_id']
        self.tick()
        self.assertEqual(self.row(b)['device_id'], 'galaxy-a13-5g')
        self.setUp(); self.tick(); self.arm(); self.clock.advance(31 * 60)
        c = self.p.ingest(message(MELBOURNE, received=self.clock()))['instruction_id']
        self.tick()
        self.assertEqual(self.row(c)['device_id'], 'galaxy-a13-5g')

    def test_routing_flag_on_routes_new_work_to_a_routable_desktop_without_a_target(self):
        self.p.settings.desktop_routing_enabled = True
        self.tick()
        iid = self.p.ingest(message(MELBOURNE, received=self.clock()))['instruction_id']
        self.tick()
        self.assertEqual(self.row(iid)['device_id'], 'desktop-chrome')
        self.assertEqual(self.audits('DEVICE_TARGET', iid)[0]['detail']['reason'], 'normal routing')


class PhoneUnchanged(Base):
    def test_phone_bet_is_reconciled_on_the_phone_with_the_desktop_attached(self):
        self.tick()
        iid = self.p.ingest(message(MELBOURNE, received=self.clock()))['instruction_id']
        self.tick()
        self.answer_hold(self.phone, iid)
        self.tick()
        self.assertEqual(self.phone.submitted[-1]['action'], 'PLACE_HELD')
        self.phone.results[iid + '-place'] = placement_result(iid)
        self.tick()
        bet = self.bet(iid)
        self.assertEqual((bet['worker_id'], bet['account_fingerprint'], bet['binding_source']),
                         (WORKER_ID, ACCOUNT_FINGERPRINT, 'phone health at the placement result'))
        record = self.audits('AUTO_APPROVED', iid)[0]
        self.assertEqual(record['detail']['worker'], dict(device_id='galaxy-a13-5g', worker_id=WORKER_ID))
        self.assertIn('phone_final_action_permission', {c['check'] for c in record['detail']['checks']})
        self.clock.advance(self.p.settings.reconcile_delay_seconds + 1)
        self.tick()
        self.assertEqual([x['action'] for x in self.phone.submitted][-1], 'MY_BETS')
        self.assertFalse([x for x in self.desk.submitted if x['action'] == 'MY_BETS'])

    def test_desktop_hold_on_the_phone_pre_tap_check_still_rejects_a_foreign_worker(self):
        self.tick()
        iid = self.p.ingest(message(MELBOURNE, received=self.clock()))['instruction_id']
        self.tick()
        with self.p.store.tx() as db:
            self.p.store.update_fields(db, iid, device_id='some-other-worker')
        self.answer_hold(self.phone, iid)
        self.tick()
        self.assertNotIn('PLACE_HELD', [x['action'] for x in self.phone.submitted + self.desk.submitted])


if __name__ == '__main__':
    unittest.main()
