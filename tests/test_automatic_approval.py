"""Automatic approval (approval_mode=automatic): the backend approves a device-verified slip itself, persists the
decision, and the phone's fresh pre-tap verification decides whether the single final action happens.

Fake coordinator only: no phone, no bookmaker, no money. Real alerts: MELBOURNE (basketball TOTALS OVER 190.5,
equal lines + EV), RYTAS (SPREAD HOME -18.5) and moneyline_real.json 67969 (ML HOME, Pinnacle 2.200 -> 1.613).
"""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from core.pipeline import Settings
from core.status_notifier import AUTOMATIC_STATES, Notifier, format_instruction
from tests.pipeline_support import (ACCOUNT_FINGERPRINT, MELBOURNE, RYTAS, WORKER_ID, Clock, FakeGateway, fail_result,
                                    message, pipeline, ready_result)
from tests.test_final_action import MELBOURNE_CARD, my_bets, placement_result
from tests.test_moneyline import ROWS as ML_ROWS, cfg as ml_cfg, msg as ml_msg

AUTO = dict(final_action_enabled=True, approval_mode='automatic')


class Base(unittest.TestCase):
    settings = AUTO
    instant = True

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'p.sqlite3'
        self.clock = Clock()
        self.gateway = FakeGateway(self.clock)
        self.p = pipeline(self.path, self.clock, instant_verification=self.instant, **self.settings)

    def row(self, iid):
        with self.p.store.connection() as db:
            return dict(db.execute('SELECT * FROM instructions WHERE instruction_id=?', (iid,)).fetchone())

    def bet(self, iid):
        with self.p.store.connection() as db:
            row = db.execute('SELECT * FROM bets WHERE instruction_id=?', (iid,)).fetchone()
        return dict(row) if row else None

    def audits(self, kind, iid=None):
        with self.p.store.connection() as db:
            rows = db.execute('SELECT * FROM audit_events WHERE kind=?' + (' AND instruction_id=?' if iid else ''),
                              (kind, iid) if iid else (kind,)).fetchall()
        return [dict(r, detail=json.loads(r['detail']) if r['detail'] else None) for r in rows]

    def transitions(self, iid):
        with self.p.store.connection() as db:
            return [r[0] for r in db.execute('SELECT to_state FROM transitions WHERE instruction_id=? ORDER BY id', (iid,))]

    def sent(self, action):
        return [x for x in self.gateway.submitted if x['action'] == action]

    def outbox(self):
        notifier = Notifier(self.p.store, sender=None, states=AUTOMATIC_STATES, clock=self.clock)
        notifier.enqueue()
        with self.p.store.connection() as db:
            return [dict(r) for r in db.execute('SELECT * FROM notifications ORDER BY id')]

    def verified(self, sample=MELBOURNE, **result_changes):
        """Ingest and run the hold; the fake phone answers READY (hold verified) with optional changes."""
        iid = self.p.ingest(message(sample))['instruction_id']
        self.p.tick(self.gateway)
        return iid


class AutomaticFlow(Base):
    def test_valid_totals_progresses_past_slip_ready_without_telegram(self):
        iid = self.verified(MELBOURNE)
        row = self.row(iid)
        self.assertIn(row['state'], ('DISPATCHED', 'DEVICE_ACTIVE'))                    # PLACE_HELD already sent
        self.assertNotIn('AWAITING_APPROVAL', self.transitions(iid))
        self.assertIsNone(row['approval_requested_at'])
        self.assertEqual((row['approved_by'], row['approval_mode'], row['execution_job_id']), ('automatic-policy', 'automatic', iid + '-place'))
        self.assertTrue(row['auto_approved_at'] and row['approved_at'] and row['strategy_version'] and row['rules_version'])
        place = self.sent('PLACE_HELD')
        self.assertEqual(len(place), 1)
        self.assertEqual((place[0]['instruction_id'], place[0]['market'], place[0]['side'], place[0]['line'], place[0]['execution_mode'],
                          place[0]['confirmation_status']), (iid + '-place', 'TOTALS', 'OVER', '190.5', 'dispatch', 'APPROVED'))
        # the decision came from policy, not a human: every check recorded, all passed
        record = self.audits('AUTO_APPROVED', iid)[0]['detail']
        self.assertEqual((record['approval_mode'], record['decided_by'], record['execution_job_id']), ('automatic', 'automatic-policy', iid + '-place'))
        self.assertEqual(record['worker'], dict(device_id='galaxy-a13-5g', worker_id=WORKER_ID))
        self.assertEqual(record['account'], ACCOUNT_FINGERPRINT)
        self.assertEqual(record['requested'], dict(line='190.5', odds='2.20', minimum_price=row['minimum_price']))
        self.assertEqual(record['device_verified']['odds'], '2.20')
        self.assertTrue(all(c['ok'] for c in record['checks']))
        self.assertGreaterEqual(len(record['checks']), 18)
        self.assertIn('rules-', record['rules_version'])
        # then the tap, receipt, bets row and My Bets verification
        self.gateway.results[iid + '-place'] = dict(placement_result(iid), t_tap_ms=int(self.clock().timestamp() * 1000))
        self.p.tick(self.gateway)
        row = self.row(iid)
        self.assertEqual(row['state'], 'COMPLETED')
        self.assertTrue(row['intent_at'])
        placed = self.audits('PLACED', iid)[0]['detail']
        self.assertEqual((placed['bet_reference'], placed['approved_by'], placed['approval_mode']), ('JL1234567890', 'automatic-policy', 'automatic'))
        self.assertEqual(self.bet(iid)['status'], 'PLACED_UNVERIFIED')
        # Telegram was informational only
        texts = [n['text'] for n in self.outbox()]
        self.assertTrue(any(t.startswith('MultiBot365 - QUALIFIED') for t in texts))
        self.assertTrue(any(t.startswith('MultiBot365 - AUTO APPROVED') and 'automatic policy' in t for t in texts))
        self.assertTrue(any(t.startswith('MultiBot365 - BET PLACED') and 'JL1234567890' in t for t in texts))
        self.assertFalse(any('/approve' in t for t in texts))

    def test_valid_spread_progresses_past_slip_ready(self):
        iid = self.verified(RYTAS)
        place = self.sent('PLACE_HELD')
        self.assertEqual(self.row(iid)['approved_by'], 'automatic-policy')
        self.assertEqual((place[0]['market'], place[0]['side'], place[0]['line']), ('SPREAD', 'HOME', '-18.5'))

    def test_valid_moneyline_progresses_after_its_interpretation_is_proven(self):
        r = ML_ROWS['67969']
        clock = Clock(datetime.fromisoformat(r['received_at']))
        gateway = FakeGateway(clock)
        p = pipeline(self.path.with_name('ml.sqlite3'), clock, cfg=ml_cfg(), **AUTO)
        iid = p.ingest(ml_msg('67969'))['instruction_id']
        p.tick(gateway)
        with p.store.connection() as db:
            row = dict(p.store.get_instruction(db, iid))
        self.assertIn(row['state'], ('DISPATCHED', 'DEVICE_ACTIVE'))
        self.assertEqual((row['approved_by'], row['market'], row['selection']), ('automatic-policy', 'MONEYLINE', 'HOME'))
        place = [x for x in gateway.submitted if x['action'] == 'PLACE_HELD'][0]
        self.assertEqual((place['market'], place['side'], place['line'], place['selection_name'], place['minimum_price']),
                         ('MONEYLINE', 'HOME', '', 'San Salvador', '2.13'))
        with p.store.connection() as db:
            detail = json.loads(db.execute("SELECT detail FROM audit_events WHERE kind='AUTO_APPROVED' AND instruction_id=?", (iid,)).fetchone()[0])
        self.assertEqual(detail['strategy_version'], 'sharp-money-ml-1')
        signal = [c for c in detail['checks'] if c['check'] == 'sharp_signal'][0]
        self.assertTrue(signal['ok'])

    def test_continuous_operation_places_successive_bets_without_disarming(self):
        first = self.verified(MELBOURNE)
        self.gateway.results[first + '-place'] = placement_result(first)
        self.p.tick(self.gateway)
        self.assertEqual(self.row(first)['state'], 'COMPLETED')
        second = self.verified(RYTAS)
        self.gateway.results[second + '-place'] = placement_result(second, bet_reference='JL0000000002')
        self.p.tick(self.gateway)
        self.assertEqual(self.row(second)['state'], 'COMPLETED')
        self.assertEqual((self.p.settings.dispatch_enabled, self.p.settings.final_action_enabled, self.p.final.paused()), (True, True, False))
        self.assertEqual(len(self.sent('PLACE_HELD')), 2)
        self.assertEqual(self.audits('FINAL_ACTION_DISARMED'), [])


class ManualModeStillWorks(Base):
    settings = dict(final_action_enabled=True, approval_mode='manual')

    def test_manual_waits_for_the_operator_and_never_auto_approves(self):
        iid = self.verified(MELBOURNE)
        row = self.row(iid)
        self.assertEqual((row['state'], row['approval_mode']), ('AWAITING_APPROVAL', None))
        self.assertEqual(self.sent('PLACE_HELD'), [])
        self.assertEqual(self.audits('AUTO_APPROVED'), [])
        texts = [n['text'] for n in self.outbox()]
        self.assertTrue(any(t.startswith('MultiBot365 - APPROVAL NEEDED') and 'Reply /approve' in t for t in texts))
        self.p.final.approve(iid, 'telegram:operator')
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['approved_by'], 'telegram:operator')
        self.assertEqual(len(self.sent('PLACE_HELD')), 1)

    def test_settings_map_the_mode_and_the_legacy_flag(self):
        self.assertEqual(Settings.from_dict({'auto_approve': True}).approval_mode, 'automatic')
        self.assertEqual(Settings.from_dict({'approval_mode': 'automatic'}).auto_approve, True)
        self.assertEqual(Settings.from_dict({}).approval_mode, 'manual')
        self.assertEqual(Settings.from_dict({'approval_mode': 'AUTOMATIC'}).approval_mode, 'automatic')
        with self.assertRaises(ValueError):
            Settings.from_dict({'approval_mode': 'sometimes'})


class ChecksThatBlock(Base):
    instant = False

    def hold(self, sample=MELBOURNE):
        iid = self.p.ingest(message(sample))['instruction_id']
        self.p.tick(self.gateway)
        self.assertEqual(self.gateway.submitted[-1]['execution_mode'], 'hold')
        return iid

    def refused(self, iid, check):
        row = self.row(iid)
        self.assertEqual(row['state'], 'REJECTED')
        self.assertIn('AUTO_APPROVAL_REFUSED', row['failure_reason'])
        self.assertIn(check, row['failure_reason'])
        detail = self.audits('AUTO_APPROVAL_REFUSED', iid)[0]['detail']
        self.assertFalse([c for c in detail['checks'] if c['check'] == check][0]['ok'])
        self.assertEqual(self.sent('PLACE_HELD'), [])
        self.assertEqual(self.audits('AUTO_APPROVED', iid), [])

    def test_wrong_fixture_blocks(self):
        iid = self.hold()
        self.gateway.results[iid] = fail_result(iid, 'WRONG_EVENT', 'Kick-off differs from the alert')
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'TARGET_NOT_FOUND')
        self.assertEqual(self.sent('PLACE_HELD'), [])

    def test_wrong_team_blocks(self):
        iid = self.hold()
        self.gateway.results[iid] = fail_result(iid, 'ALIAS_REQUIRED', 'both teams only resemble the page names')
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'TARGET_NOT_FOUND')
        # and a READY whose identity the phone could not settle is refused by the policy
        other = self.hold(RYTAS)
        result = ready_result(other, price='1.83')
        result['selection'].update(market='SPREAD', side='HOME', line='-18.5', selection_name='Rytas Vilnius')
        result['identity_verdict'] = 'AMBIGUOUS'
        self.gateway.results[other] = result
        self.p.tick(self.gateway)
        self.refused(other, 'event_identity')

    def test_wrong_market_blocks(self):
        iid = self.hold()
        result = ready_result(iid)
        result['selection'].update(market='SPREAD', side='HOME', line='-2.5')
        self.gateway.results[iid] = result
        self.p.tick(self.gateway)
        self.assertNotEqual(self.row(iid)['state'], 'DISPATCHED')
        self.assertEqual(self.sent('PLACE_HELD'), [])

    def test_line_outside_tolerance_blocks(self):
        iid = self.hold()
        result = ready_result(iid)
        result['selection']['line'] = '191.5'          # OVER 190.5 requested; a higher total is a worse line
        self.gateway.results[iid] = result
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'PRICE_CHANGED')
        self.assertEqual(self.sent('PLACE_HELD'), [])

    def test_odds_outside_tolerance_blocks(self):
        iid = self.hold()
        self.gateway.results[iid] = ready_result(iid, price='2.10')   # 2.20 requested, zero tolerance in the test config
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'PRICE_CHANGED')
        self.assertEqual(self.sent('PLACE_HELD'), [])

    def test_stale_alert_blocks(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.clock.advance(400)
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'STALE')
        self.assertEqual(self.gateway.submitted, [])

    def test_session_failure_blocks(self):
        iid = self.hold()
        self.gateway.session = 'LOGGED_OUT'
        self.p.refresh_device(self.gateway)                            # the phone reports the session lost
        self.gateway.results[iid] = ready_result(iid)
        self.p.tick(self.gateway)
        self.refused(iid, 'session_authenticated')

    def test_kill_switch_blocks(self):
        iid = self.hold()
        self.gateway.results[iid] = ready_result(iid)
        self.p.final.set_paused(True, 'operator')                    # /stop while the phone is verifying
        self.p.tick(self.gateway)
        row = self.row(iid)
        self.assertEqual(row['state'], 'REJECTED')
        self.assertIn('KILL_SWITCH', row['failure_reason'])
        self.assertEqual(self.audits('AUTO_APPROVED'), [])
        self.assertEqual(self.sent('PLACE_HELD'), [])
        for _ in range(2):
            self.p.tick(self.gateway)
        self.assertTrue(any(x['action'] == 'RESET_BETSLIP' for x in self.gateway.submitted))   # held slip released
        # and a kill switch engaged after approval stops the final action too
        self.p.final.set_paused(False, 'operator')
        other = self.hold(RYTAS)
        self.gateway.health_extra = dict(current_instruction={'instruction_id': other})
        result = ready_result(other, price='1.83')
        result['selection'].update(market='SPREAD', side='HOME', line='-18.5', selection_name='Rytas Vilnius')
        self.gateway.results[other] = result
        self.p.tick(self.gateway)
        self.assertEqual(self.row(other)['state'], 'APPROVED')
        self.p.final.set_paused(True, 'operator')
        self.gateway.health_extra = {}
        self.p.tick(self.gateway)
        self.assertEqual(self.row(other)['state'], 'REJECTED')
        self.assertEqual(self.sent('PLACE_HELD'), [])

    def test_worker_account_and_phone_permission_are_bound(self):
        cases = [('worker_identity', dict(worker_id='someone-elses-phone')),
                 ('account_identity', dict(account_fingerprint='other-account')),
                 ('phone_final_action_permission', dict(phone_final_action_armed=False))]
        for check, extra in cases:
            with self.subTest(check=check):
                self.setUp()
                iid = self.hold()
                self.gateway.health_extra = extra
                self.gateway.results[iid] = ready_result(iid)
                self.p.tick(self.gateway)
                self.refused(iid, check)

    def test_unconfigured_worker_or_account_never_auto_approves(self):
        p = pipeline(self.path.with_name('u.sqlite3'), self.clock, instant_verification=False, final_action_enabled=True,
                     approval_mode='automatic', expected_worker_id='', expected_account_fingerprint='')
        iid = p.ingest(message(MELBOURNE))['instruction_id']
        p.tick(self.gateway)
        self.gateway.results[iid] = ready_result(iid)
        p.tick(self.gateway)
        with p.store.connection() as db:
            row = dict(p.store.get_instruction(db, iid))
        self.assertEqual(row['state'], 'REJECTED')
        self.assertIn('worker_identity', row['failure_reason'])
        self.assertIn('account_identity', row['failure_reason'])

    def test_duplicate_blocks(self):
        iid = self.hold()
        self.gateway.results[iid] = ready_result(iid)
        self.p.tick(self.gateway)
        self.assertIn(self.row(iid)['state'], ('DISPATCHED', 'DEVICE_ACTIVE'))
        again = self.p.ingest(message(MELBOURNE))                                    # duplicate Telegram delivery
        self.assertEqual(again['status'], 'DUPLICATE')
        same_bet = self.p.ingest(message(MELBOURNE, message_id='999999'))           # same selection, new message id
        self.assertEqual(same_bet['status'], 'DUPLICATE')
        self.gateway.results[iid + '-place'] = placement_result(iid)
        for _ in range(3):
            self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'COMPLETED')
        self.assertEqual(len(self.sent('PLACE_HELD')), 1)

    def test_unresolved_prior_placement_blocks(self):
        first = self.hold()
        self.gateway.results[first] = ready_result(first)
        self.p.tick(self.gateway)
        self.gateway.results[first + '-place'] = placement_result(first, outcome='PLACEMENT_UNKNOWN')
        self.p.tick(self.gateway)
        self.assertEqual(self.row(first)['state'], 'PLACEMENT_UNKNOWN')
        second = self.p.ingest(message(RYTAS))['instruction_id']
        for _ in range(3):
            self.p.tick(self.gateway)
        self.assertNotIn(self.row(second)['state'], ('APPROVED', 'DISPATCHED', 'COMPLETED'))
        self.assertEqual(len(self.sent('PLACE_HELD')), 1)


class AfterSlipReady(Base):
    """AUTO_APPROVED never means blindly tapping: the phone's fresh pre-tap verification decides."""

    def pre_tap(self, stage, detail):
        iid = self.verified(MELBOURNE)
        self.gateway.results[iid + '-place'] = placement_result(iid, outcome=stage, tapped=False, detail=detail)
        self.p.tick(self.gateway)
        return iid

    def test_line_change_after_slip_ready_blocks(self):
        iid = self.pre_tap('LINE_CHANGED', 'Alert-to-live line deterioration exceeds tolerance')
        row = self.row(iid)
        self.assertEqual(row['state'], 'PRICE_CHANGED')
        self.assertTrue(row['failure_reason'].startswith('PRE_TAP_REJECTED: LINE_CHANGED'))
        self.assertEqual(self.audits('PRE_TAP_REJECTED', iid)[0]['detail']['execution_job_id'], iid + '-place')
        self.assertIsNone(self.bet(iid))                                             # nothing staked
        self.assertEqual(len(self.sent('PLACE_HELD')), 1)                             # never a second attempt
        for _ in range(2):
            self.p.tick(self.gateway)
        self.assertTrue(any(x['action'] == 'RESET_BETSLIP' for x in self.gateway.submitted))   # slip released
        texts = [n['text'] for n in self.outbox()]
        self.assertTrue(any(t.startswith('MultiBot365 - PRE-TAP REJECTED') and 'LINE_CHANGED' in t for t in texts))

    def test_odds_change_after_slip_ready_blocks(self):
        iid = self.pre_tap('BELOW_MINIMUM', 'Current slip price below alert-to-live minimum')
        row = self.row(iid)
        self.assertEqual(row['state'], 'PRICE_CHANGED')
        self.assertTrue(row['failure_reason'].startswith('PRE_TAP_REJECTED'))
        self.assertIsNone(self.bet(iid))

class Idempotency(Base):
    instant = False

    def approved(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.p.tick(self.gateway)
        self.gateway.health_extra = dict(current_instruction={'instruction_id': iid})   # phone still busy finishing
        self.gateway.results[iid] = ready_result(iid)
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'APPROVED')                          # approved, final action not yet sent
        self.assertEqual(self.sent('PLACE_HELD'), [])
        return iid

    def restarted(self):
        p2 = pipeline(self.path, self.clock, instant_verification=False, **self.settings)
        p2.recover()
        return p2

    def test_backend_restart_between_approval_and_action_sends_exactly_one_final_action(self):
        iid = self.approved()
        p2 = self.restarted()
        self.gateway.health_extra = {}
        p2.tick(self.gateway)
        self.assertEqual(len(self.sent('PLACE_HELD')), 1)
        p3 = self.restarted()
        for _ in range(3):
            p3.tick(self.gateway)
        self.assertEqual(len(self.sent('PLACE_HELD')), 1)                             # DISPATCHED is only polled
        self.gateway.results[iid + '-place'] = placement_result(iid)
        p3.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'COMPLETED')

    def test_duplicated_http_request_and_phone_restart_cannot_place_twice(self):
        iid = self.approved()
        self.gateway.health_extra = {}
        self.p.tick(self.gateway)
        job = iid + '-place'
        # the phone (restarted or not) echoes DUPLICATE for the same job id: the backend keeps waiting, never resends
        self.gateway.results[job] = {'instruction_id': job, 'status': 'FAIL', 'stage': 'DUPLICATE',
                                     'detail': 'Instruction ID has already been accepted; no action repeated'}
        for _ in range(3):
            self.clock.advance(5)
            self.p.tick(self.gateway)
        self.assertIn(self.row(iid)['state'], ('DISPATCHED', 'DEVICE_ACTIVE'))
        self.assertEqual(len(self.sent('PLACE_HELD')), 1)
        self.gateway.results[job] = placement_result(iid)
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'COMPLETED')
        self.assertEqual(len(self.sent('PLACE_HELD')), 1)

    def test_lost_result_after_the_action_reconciles_instead_of_executing_again(self):
        iid = self.approved()
        self.gateway.health_extra = {}
        self.p.tick(self.gateway)
        self.clock.advance(self.p.settings.result_timeout_seconds + 1)                # reconnect after a timeout
        self.p.tick(self.gateway)
        row = self.row(iid)
        self.assertEqual((row['state'], self.bet(iid)['status']), ('PLACEMENT_UNKNOWN', 'UNKNOWN'))
        self.clock.advance(20)
        self.p.tick(self.gateway)
        checks = [x for x in self.gateway.submitted if x['action'] == 'MY_BETS']
        self.assertEqual(len(checks), 1)
        self.gateway.results[checks[0]['instruction_id']] = my_bets(checks[0]['instruction_id'], MELBOURNE_CARD)
        self.p.tick(self.gateway)
        row = self.row(iid)
        self.assertEqual((row['state'], row['reconciliation_result']), ('COMPLETED', 'FOUND_IN_MY_BETS'))
        self.assertEqual(self.audits('RECONCILED', iid)[0]['detail']['result'], 'FOUND_IN_MY_BETS')
        self.assertEqual(len(self.sent('PLACE_HELD')), 1)
        record = self.p.final.decision_record(iid)
        self.assertEqual((record['approval_mode'], record['approved_by'], record['reconciliation_result']),
                         ('automatic', 'automatic-policy', 'FOUND_IN_MY_BETS'))
        self.assertEqual(record['execution_job_id'], iid + '-place')
        texts = [n['text'] for n in self.outbox()]
        self.assertTrue(any(t.startswith('MultiBot365 - RECONCILED') for t in texts))

    def test_uncertain_post_action_state_reconciles_rather_than_re_executes(self):
        iid = self.approved()
        self.gateway.health_extra = {}
        self.p.tick(self.gateway)
        self.gateway.results[iid + '-place'] = placement_result(iid, outcome='PLACEMENT_UNKNOWN', detail='No definitive outcome')
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'PLACEMENT_UNKNOWN')
        for _ in range(3):
            self.clock.advance(20)
            self.p.tick(self.gateway)
        self.assertEqual(len(self.sent('PLACE_HELD')), 1)
        self.assertTrue(any(x['action'] == 'MY_BETS' for x in self.gateway.submitted))

    def test_stale_hold_is_never_consumed(self):
        iid = self.approved()
        self.clock.advance(self.p.settings.hold_max_age_seconds + 5)
        self.gateway.health_extra = {}
        self.p.tick(self.gateway)
        row = self.row(iid)
        self.assertEqual(row['state'], 'REJECTED')
        self.assertIn('PRE_TAP_REJECTED: verified hold', row['failure_reason'])
        self.assertEqual(self.sent('PLACE_HELD'), [])


class TransientHistoryBaseline(Base):
    def test_history_before_the_first_run_is_never_announced(self):
        old = self.verified(MELBOURNE)                                   # queued, verified, approved, dispatched at T0
        self.gateway.results[old + '-place'] = placement_result(old)
        self.p.tick(self.gateway)
        self.clock.advance(10)
        notifier = Notifier(self.p.store, sender=None, states=AUTOMATIC_STATES, clock=self.clock)
        notifier.enqueue()                                               # first run over an existing database
        with self.p.store.connection() as db:
            states = [r[0] for r in db.execute('SELECT state FROM notifications WHERE instruction_id=?', (old,))]
        self.assertNotIn('QUEUED', states)
        self.assertNotIn('APPROVED', states)
        self.assertIn('COMPLETED', states)
        new = self.verified(RYTAS)                                       # after the baseline: announced
        notifier.enqueue()
        with self.p.store.connection() as db:
            states = [r[0] for r in db.execute('SELECT state FROM notifications WHERE instruction_id=?', (new,))]
        self.assertIn('QUEUED', states)
        self.assertIn('APPROVED', states)


class Messages(unittest.TestCase):
    def test_headlines_are_concise_and_name_the_decision_source(self):
        base = dict(instruction_id='on-abcdef1234567890', fixture='A v B', market='TOTALS', selection='OVER', selection_name='Over',
                    line='190.5', alert_price='2.20', minimum_price='2.20', stake='0.10', observed_price='2.20')
        auto = format_instruction(dict(base, state='APPROVED', approved_by='automatic-policy', approval_mode='automatic',
                                       auto_approved_at='2026-09-26T15:00:00+00:00', strategy_version='sharp-money-1',
                                       rules_version='rules-7-moneyline', execution_job_id='on-abcdef1234567890-place'))
        self.assertTrue(auto.startswith('MultiBot365 - AUTO APPROVED'))
        self.assertIn('automatic policy', auto)
        self.assertNotIn('/approve', auto)
        manual = format_instruction(dict(base, state='AWAITING_APPROVAL', ready_at='x'))
        self.assertIn('Reply /approve', manual)
        rejected = format_instruction(dict(base, state='PRICE_CHANGED', execution_mode='dispatch',
                                           failure_reason='PRE_TAP_REJECTED: LINE_CHANGED: slip shows 191.5'))
        self.assertTrue(rejected.startswith('MultiBot365 - PRE-TAP REJECTED'))
        self.assertIn('Reason: PRE_TAP_REJECTED', rejected)
        placed = format_instruction(dict(base, state='COMPLETED', execution_mode='dispatch', approved_by='automatic-policy',
                                         approval_mode='automatic', bet_reference='JL1'),
                                    bet=dict(actual_line='190.5', actual_odds='2.20', actual_stake='0.10'))
        self.assertTrue(placed.startswith('MultiBot365 - BET PLACED'))
        self.assertIn('Bet ref: JL1; receipt line 190.5 odds 2.20 stake £0.10', placed)
        self.assertIn('approved by automatic-policy (automatic)', placed)
        self.assertLessEqual(len(placed.splitlines()), 7)


if __name__ == '__main__':
    unittest.main()
