"""Final action (Place Bet): approval, limits, kill switch, outcomes, reconciliation, settlement.

Everything runs against a fake coordinator: no phone, no bookmaker, no money.
"""
import json
import tempfile
import unittest
from pathlib import Path

from core import bet_matching
from core.lifecycle import State, interpret_device_result, placement_of
from tests.pipeline_support import MELBOURNE, RYTAS, Clock, FakeGateway, message, pipeline, fail_result, ready_result


def placement_result(iid, outcome='PLACED', tapped=True, **extra):
    placement = dict(tapped=tapped, outcome=outcome, bet_reference='JL1234567890' if outcome == 'PLACED' else None,
                     stake='1.00', odds='2.20', potential_return='2.20', frames=['s030_place_bet_after.png'],
                     detail='receipt visible' if outcome == 'PLACED' else outcome)
    placement.update(extra)
    placed = outcome == 'PLACED' and tapped
    return {'instruction_id': iid, 'status': 'PASS' if placed else 'FAIL', 'stage': 'PASS' if placed else outcome,
            'detail': 'PLACED' if placed else outcome, 'placement': placement, 'wager_submitted': placed}


MELBOURNE_CARD = ['Single', 'Over 190.5', 'Total Points - Game', 'SE Melbourne Phoenix v Melbourne United',
                  'Stake £1.00', '6/5', 'To Return £2.20', 'Bet Ref JL1234567890']


def my_bets(rid, lines, view='OPEN'):
    address = 'bet365.com/#/MB/U' if view == 'OPEN' else 'bet365.com/#/MB/S'
    return {'instruction_id': rid, 'status': 'PASS', 'stage': 'PASS', 'detail': 'MY_BETS',
            'my_bets': {'view': view, 'frames': ['s001_my_bets.png'],
                        'lines': [{'text': t, 'top': 100 + 40 * i, 'left': 20, 'frame': 0}
                                  for i, t in enumerate(['10:03', address] + list(lines))]}}


class Base(unittest.TestCase):
    settings = dict(final_action_enabled=True)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.clock = Clock()
        self.gateway = FakeGateway(self.clock)
        self.p = pipeline(Path(tmp.name) / 'p.sqlite3', self.clock, **self.settings)

    def row(self, iid):
        with self.p.store.connection() as db:
            return dict(db.execute('SELECT * FROM instructions WHERE instruction_id=?', (iid,)).fetchone())

    def bet(self, iid):
        with self.p.store.connection() as db:
            row = db.execute('SELECT * FROM bets WHERE instruction_id=?', (iid,)).fetchone()
        return dict(row) if row else None

    def reconciliations(self):
        with self.p.store.connection() as db:
            return [dict(r) for r in db.execute('SELECT * FROM reconciliations ORDER BY id')]

    def audits(self, kind):
        with self.p.store.connection() as db:
            return [dict(r) for r in db.execute('SELECT * FROM audit_events WHERE kind=?', (kind,))]

    def approved_and_dispatched(self, sample=MELBOURNE):
        iid = self.p.ingest(message(sample))['instruction_id']
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'AWAITING_APPROVAL')
        self.p.final.approve(iid[:10], 'operator')
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'DEVICE_ACTIVE')
        return iid


class SwitchTests(Base):
    settings = dict(final_action_enabled=False)

    def test_default_is_ready_only(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.p.tick(self.gateway)
        payload = self.gateway.submitted[0]
        self.assertEqual(payload['execution_mode'], 'ready')
        self.assertNotIn('confirmation_status', payload)
        self.assertEqual(self.row(iid)['execution_mode'], 'ready')
        with self.assertRaises(PermissionError):
            self.p.build_payload(self.row(iid), final_action=True)


class ApprovalTests(Base):
    def test_manual_approval_then_final_action_payload(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'AWAITING_APPROVAL')
        self.assertEqual([x for x in self.gateway.submitted if x.get('execution_mode') == 'dispatch'], [])
        self.assertEqual(self.p.final.approve(iid[:10], 'operator'), iid)   # unique prefix, like Telegram
        self.p.tick(self.gateway)
        payload = self.gateway.submitted[-1]
        self.assertEqual((payload['execution_mode'], payload['confirmation_status']), ('dispatch', 'APPROVED'))
        self.assertEqual(payload['instruction_id'], iid + '-place')      # never the verification run's ID
        row = self.row(iid)
        self.assertEqual((row['state'], row['approved_by'], row['execution_mode']), ('DEVICE_ACTIVE', 'operator', 'dispatch'))
        for key in ('approval_requested_at', 'approved_at', 'dispatched_at'):
            self.assertIsNotNone(row[key], key)

    def test_approval_window_expires(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.p.tick(self.gateway)
        self.clock.advance(121)
        with self.assertRaises(PermissionError):
            self.p.final.approve(iid, 'operator')
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'STALE')
        self.assertEqual([x for x in self.gateway.submitted if x.get('execution_mode') == 'dispatch'], [])

    def test_reject_and_ambiguous_prefix(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.p.ingest(message(RYTAS))
        self.p.tick(self.gateway)
        with self.assertRaises(LookupError):
            self.p.final.approve('on-', 'operator')          # matches two instructions: refuse to guess
        self.p.final.reject(iid, 'operator')
        self.assertEqual(self.row(iid)['state'], 'REJECTED')
        with self.assertRaises(PermissionError):
            self.p.final.approve(iid, 'operator')

    def test_kill_switch_cancels_and_blocks(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.p.tick(self.gateway)
        self.p.final.set_paused(True, 'operator')
        self.assertEqual(self.row(iid)['state'], 'REJECTED')
        self.assertIn('KILL_SWITCH', self.row(iid)['failure_reason'])
        second = self.p.ingest(message(RYTAS))['instruction_id']
        self.p.tick(self.gateway)
        self.assertEqual(self.row(second)['state'], 'QUEUED')      # nothing dispatched while paused
        self.assertEqual([x for x in self.gateway.submitted if x.get('execution_mode') == 'dispatch'], [])
        with self.assertRaises(PermissionError):
            self.p.final.approve(second, 'operator')
        self.p.final.set_paused(False, 'operator')
        self.p.tick(self.gateway)
        self.assertEqual(self.row(second)['state'], 'AWAITING_APPROVAL')


class LimitTests(Base):
    settings = dict(final_action_enabled=True, auto_approve=True, max_stake_per_bet='1.00', max_bets_per_day=1,
                    max_daily_stake='5.00', max_daily_loss='5.00')

    def test_auto_approve_within_limits_then_bets_per_day(self):
        first = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.p.tick(self.gateway)
        self.assertEqual([(x['action'], x['execution_mode']) for x in self.gateway.submitted if x['action'] in ('ADAPTER_WORKFLOW', 'PLACE_HELD')][:2],
                         [('ADAPTER_WORKFLOW', 'hold'), ('PLACE_HELD', 'dispatch')])
        self.assertEqual(self.row(first)['approved_by'], 'auto')
        self.gateway.results[first + "-place"] = placement_result(first)
        self.p.tick(self.gateway)
        self.assertEqual(self.row(first)['state'], 'COMPLETED')
        second = self.p.ingest(message(RYTAS))['instruction_id']
        for _ in range(3):
            self.p.tick(self.gateway)
        self.assertEqual(self.row(second)['state'], 'REJECTED')
        self.assertIn('bets already today', self.row(second)['failure_reason'])

    def test_stake_cap(self):
        self.p.settings.max_stake_per_bet = '0.50'
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'REJECTED')
        self.assertIn('per-bet cap', self.row(iid)['failure_reason'])
        self.assertEqual([x for x in self.gateway.submitted if x.get('execution_mode') == 'dispatch'], [])

    def test_refused_and_pre_tap_failures_do_not_count(self):
        self.p.settings.max_bets_per_day = 1
        first = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.p.tick(self.gateway)
        self.gateway.results[first + "-place"] = fail_result(first, 'TARGET_NOT_FOUND', 'fixture not on board')
        self.gateway.results[first + "-place"]['placement'] = {'tapped': False, 'outcome': 'NOT_TAPPED'}
        self.p.tick(self.gateway)
        self.assertEqual(self.row(first)['state'], 'TARGET_NOT_FOUND')
        self.assertIsNone(self.bet(first))
        second = self.p.ingest(message(RYTAS))['instruction_id']
        self.p.tick(self.gateway)
        self.assertEqual(self.row(second)['state'], 'DEVICE_ACTIVE')     # the failed one did not use the quota


class OutcomeTests(Base):
    def test_placed_records_receipt_and_verifies_in_my_bets(self):
        iid = self.approved_and_dispatched()
        self.gateway.results[iid + "-place"] = placement_result(iid)
        self.p.tick(self.gateway)
        row, bet = self.row(iid), self.bet(iid)
        self.assertEqual((row['state'], row['bet_reference'], row['observed_price']), ('COMPLETED', 'JL1234567890', '2.20'))
        self.assertEqual((bet['status'], bet['bet_reference'], bet['stake'], bet['odds']),
                         ('PLACED_UNVERIFIED', 'JL1234567890', '1.00', '2.20'))
        self.clock.advance(16)
        self.p.tick(self.gateway)
        rec = self.reconciliations()[0]
        self.assertEqual((rec['purpose'], rec['view'], self.gateway.submitted[-1]['action']), ('VERIFY_PLACEMENT', 'OPEN', 'MY_BETS'))
        self.gateway.results[rec['device_instruction_id']] = my_bets(rec['device_instruction_id'], MELBOURNE_CARD)
        self.p.tick(self.gateway)
        self.assertEqual(self.bet(iid)['status'], 'OPEN')
        self.assertIsNotNone(self.bet(iid)['verified_at'])

    def test_every_refusal_outcome_is_explicit_and_claimed_not_placed(self):
        expected = {'INSUFFICIENT_FUNDS': 'INSUFFICIENT_FUNDS', 'STAKE_LIMITED': 'STAKE_LIMITED',
                    'PRICE_CHANGED': 'PRICE_CHANGED', 'LINE_CHANGED': 'PRICE_CHANGED', 'SUSPENDED': 'SUSPENDED',
                    'SESSION_EXPIRED': 'SESSION_REQUIRED', 'REJECTED': 'REJECTED', 'PLACEMENT_UNKNOWN': 'PLACEMENT_UNKNOWN',
                    'SOMETHING_NEW': 'PLACEMENT_UNKNOWN'}
        for outcome, state in expected.items():
            with self.subTest(outcome=outcome):
                result, reason, _ = interpret_device_result(placement_result('x', outcome), final_action=True)
                self.assertEqual(result.value, state)
                self.assertTrue(reason.startswith(outcome))

    def test_insufficient_funds_is_verified_absent(self):
        iid = self.approved_and_dispatched()
        self.gateway.results[iid + "-place"] = placement_result(iid, 'INSUFFICIENT_FUNDS')
        self.p.tick(self.gateway)
        self.assertEqual((self.row(iid)['state'], self.bet(iid)['status']), ('INSUFFICIENT_FUNDS', 'NOT_PLACED_CLAIMED'))
        self.clock.advance(16)
        self.p.tick(self.gateway)
        rec = self.reconciliations()[0]
        self.gateway.results[rec['device_instruction_id']] = my_bets(rec['device_instruction_id'], ['You have no open bets'])
        self.p.tick(self.gateway)
        self.assertEqual(self.bet(iid)['status'], 'NOT_PLACED')

    def test_claimed_refusal_found_in_my_bets_is_a_discrepancy(self):
        iid = self.approved_and_dispatched()
        self.gateway.results[iid + "-place"] = placement_result(iid, 'PRICE_CHANGED')
        self.p.tick(self.gateway)
        self.clock.advance(16)
        self.p.tick(self.gateway)
        rec = self.reconciliations()[0]
        self.gateway.results[rec['device_instruction_id']] = my_bets(rec['device_instruction_id'], MELBOURNE_CARD)
        self.p.tick(self.gateway)
        self.assertEqual(self.bet(iid)['status'], 'DISCREPANCY')
        self.assertTrue(self.audits('PLACEMENT_DISCREPANCY'))

    def test_pre_tap_failure_is_ordinary(self):
        iid = self.approved_and_dispatched()
        result = fail_result(iid, 'WRONG_EVENT', 'fixture pairing not found')
        result['placement'] = {'tapped': False, 'outcome': 'NOT_TAPPED'}
        self.gateway.results[iid + "-place"] = result
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'TARGET_NOT_FOUND')
        self.assertIsNone(self.bet(iid))

    def test_legacy_phone_results(self):
        progress = {'stages': [{'stage': 'SEARCH'}, {'stage': 'ENTER_QUERY'}], 'stage': 'ENTER_QUERY'}
        pre_tap = dict(fail_result('x', 'TARGET_NOT_FOUND'), progress=progress, device_stage='ENTER_QUERY')
        self.assertEqual(interpret_device_result(pre_tap, final_action=True)[0], State.TARGET_NOT_FOUND)
        legacy = dict(fail_result('x', 'INTERNAL_ERROR'), place_bet_tapped=True, place_bet_result='INSUFFICIENT_BALANCE')
        self.assertEqual(interpret_device_result(legacy, final_action=True)[0], State.INSUFFICIENT_FUNDS)
        unknown = dict(fail_result('x', 'TIMEOUT'))                 # no evidence either way
        self.assertEqual(interpret_device_result(unknown, final_action=True)[0], State.PLACEMENT_UNKNOWN)
        self.assertEqual(placement_of(unknown), None)


class UncertaintyTests(Base):
    def test_lost_result_after_final_dispatch_is_reconciled_never_retapped(self):
        iid = self.approved_and_dispatched()
        for _ in range(7):
            self.clock.advance(60)
            self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'PLACEMENT_UNKNOWN')
        self.assertEqual(self.bet(iid)['status'], 'UNKNOWN')
        adapter_sends = [s for s in self.gateway.submitted if s['action'] == 'PLACE_HELD']
        self.assertEqual(len(adapter_sends), 1)
        self.clock.advance(16)
        self.p.tick(self.gateway)                      # reconcile delay elapsed: My Bets check submitted
        rec = self.reconciliations()[0]
        self.gateway.results[rec['device_instruction_id']] = my_bets(rec['device_instruction_id'], MELBOURNE_CARD)
        self.p.tick(self.gateway)
        self.assertEqual((self.row(iid)['state'], self.bet(iid)['status']), ('COMPLETED', 'OPEN'))
        self.assertEqual(len([s for s in self.gateway.submitted if s['action'] == 'PLACE_HELD']), 1)   # never re-tapped

    def test_unknown_absent_twice_becomes_not_placed(self):
        iid = self.approved_and_dispatched()
        self.gateway.results[iid + "-place"] = placement_result(iid, 'PLACEMENT_UNKNOWN')
        self.p.tick(self.gateway)
        for _ in range(2):
            self.clock.advance(31)
            self.p.tick(self.gateway)
            rec = self.reconciliations()[-1]
            self.gateway.results[rec['device_instruction_id']] = my_bets(rec['device_instruction_id'], ['No open bets'])
            self.p.tick(self.gateway)
        self.assertEqual((self.row(iid)['state'], self.bet(iid)['status']), ('NOT_PLACED', 'NOT_PLACED'))

    def test_unreadable_my_bets_escalates_to_manual_check(self):
        iid = self.approved_and_dispatched()
        self.gateway.results[iid + "-place"] = placement_result(iid, 'PLACEMENT_UNKNOWN')
        self.p.tick(self.gateway)
        for _ in range(3):
            self.clock.advance(31)
            self.p.tick(self.gateway)
            rec = self.reconciliations()[-1]
            self.gateway.results[rec['device_instruction_id']] = fail_result(rec['device_instruction_id'], 'INVALID_INSTRUCTION')
            self.p.tick(self.gateway)
        row = self.row(iid)
        self.assertEqual(row['state'], 'UNKNOWN')
        self.assertIn('MANUAL_CHECK_REQUIRED', row['failure_reason'])
        self.assertTrue(self.audits('MANUAL_CHECK_REQUIRED'))

    def test_malformed_final_result_is_placement_unknown(self):
        iid = self.approved_and_dispatched()
        self.gateway.results[iid + "-place"] = {'status': 'MAYBE'}
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'PLACEMENT_UNKNOWN')

    def test_phone_refusing_admission_is_definitive(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.p.tick(self.gateway)
        self.p.final.approve(iid, 'operator')

        def refuse(payload):
            raise ValueError({'instruction_id': iid, 'status': 'FAIL', 'stage': 'INVALID_INSTRUCTION',
                              'detail': 'STAKE_CAP_EXCEEDED: stake 1.00 above phone cap 0.50'})
        self.gateway.submit = refuse
        self.p.tick(self.gateway)
        row = self.row(iid)
        self.assertEqual(row['state'], 'REJECTED')
        self.assertIn('STAKE_CAP_EXCEEDED', row['failure_reason'])
        self.assertIsNone(self.bet(iid))

    def test_new_phone_stages(self):
        self.assertEqual(interpret_device_result(dict(fail_result('x', 'BETSLIP_NOT_SINGLE'),
                                                      placement={'tapped': False}), final_action=True)[0], State.REJECTED)
        self.assertEqual(interpret_device_result(fail_result('x', 'WRONG_SPORT'))[0], State.TARGET_NOT_FOUND)

    def test_crash_after_final_dispatch_commit_never_resends(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.p.tick(self.gateway)
        self.p.final.approve(iid, 'operator')

        class Crash(BaseException):
            pass

        def crash(payload):
            raise Crash()
        self.gateway.submit = crash
        with self.assertRaises(Crash):
            self.p.tick(self.gateway)
        self.assertEqual((self.row(iid)['state'], self.row(iid)['execution_mode']), ('DISPATCHED', 'dispatch'))
        restarted = pipeline(self.p.store.path, self.clock, final_action_enabled=True)
        gateway = FakeGateway(self.clock)
        for _ in range(3):
            restarted.tick(gateway)
        self.assertEqual(gateway.submitted, [])

    def test_reconciliation_blocks_new_dispatch(self):
        iid = self.approved_and_dispatched()
        self.gateway.results[iid + "-place"] = placement_result(iid, 'PLACEMENT_UNKNOWN')
        self.p.tick(self.gateway)
        self.clock.advance(16)
        self.p.tick(self.gateway)                      # MY_BETS submitted, no result yet
        second = self.p.ingest(message(RYTAS))['instruction_id']
        self.p.tick(self.gateway)
        self.assertEqual(self.row(second)['state'], 'QUEUED')


class PriorityTests(Base):
    """A2: live placement work outranks routine My Bets checks; PLACEMENT_UNKNOWN resolution stays urgent."""

    def test_routine_verification_yields_to_queued_live_work(self):
        iid = self.approved_and_dispatched()
        self.gateway.results[iid + '-place'] = placement_result(iid)
        self.p.tick(self.gateway)                                   # PLACED -> PLACED_UNVERIFIED (routine check due in 15 s)
        self.clock.advance(16)
        second = self.p.ingest(message(RYTAS))['instruction_id']
        self.p.tick(self.gateway)
        self.assertFalse(any(x['action'] == 'MY_BETS' for x in self.gateway.submitted))
        self.assertIn(self.row(second)['state'], ('DISPATCHED', 'DEVICE_ACTIVE', 'AWAITING_APPROVAL'))
        self.p.final.reject(second, 'operator')                     # phone free again: the routine check now runs
        self.p.tick(self.gateway)
        self.p.tick(self.gateway)
        self.assertTrue(any(x['action'] == 'MY_BETS' for x in self.gateway.submitted))

    def test_placement_unknown_resolution_outranks_live_work(self):
        iid = self.approved_and_dispatched()
        self.gateway.results[iid + '-place'] = placement_result(iid, 'PLACEMENT_UNKNOWN')
        self.p.tick(self.gateway)
        self.clock.advance(16)
        second = self.p.ingest(message(RYTAS))['instruction_id']
        self.p.tick(self.gateway)
        self.assertTrue(any(x['action'] == 'MY_BETS' for x in self.gateway.submitted))
        self.assertEqual(self.row(second)['state'], 'QUEUED')

    def test_alias_candidate_from_the_phone_is_audited(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        refused = fail_result(iid, 'ALIAS_REQUIRED', "Event link shows 'Sopron KC v DEAC Debreceni'")
        refused['alias_candidate'] = {'feed_home': 'Soproni KC', 'bet365_home': 'Sopron KC', 'home_verified': False}
        self.gateway.results[iid] = refused                         # the phone's answer to the hold run
        self.p.tick(self.gateway)
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'TARGET_NOT_FOUND')
        self.assertEqual(len(self.audits('ALIAS_CANDIDATE')), 1)


class SettlementTests(Base):
    def test_open_bet_settles_and_counts_towards_loss(self):
        iid = self.approved_and_dispatched()
        self.gateway.results[iid + "-place"] = placement_result(iid)
        self.p.tick(self.gateway)
        self.clock.advance(16)
        self.p.tick(self.gateway)
        rec = self.reconciliations()[0]
        self.gateway.results[rec['device_instruction_id']] = my_bets(rec['device_instruction_id'], MELBOURNE_CARD)
        self.p.tick(self.gateway)
        self.p.tick(self.gateway)                      # settlement check submitted immediately (first ever)
        rec = self.reconciliations()[-1]
        self.assertEqual((rec['purpose'], rec['view']), ('SETTLEMENT', 'SETTLED'))
        settled = MELBOURNE_CARD[:-2] + ['Lost', 'Returned £0.00']
        self.gateway.results[rec['device_instruction_id']] = my_bets(rec['device_instruction_id'], settled, 'SETTLED')
        self.p.tick(self.gateway)
        self.assertEqual(self.bet(iid)['status'], 'LOST')
        with self.p.store.connection() as db:
            self.assertEqual(self.p.final.exposure_today(db)['loss'], 1)


REAL = json.loads((Path(__file__).parent / 'fixtures/mybets_real_20260924.json').read_text(encoding='utf-8'))['frames']


def real(key, view):
    return {'view': view, 'lines': [dict(line, frame=0) for line in REAL[key]['lines']]}


class VerifyFirstTests(Base):
    """Real sequence: READY verification on the phone -> APPROVAL NEEDED -> approve -> dispatch."""

    def setUp(self):
        super().setUp()
        self.p = pipeline(self.p.store.path, self.clock, instant_verification=False, **self.settings)

    def test_approval_is_requested_only_after_device_verification(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.p.tick(self.gateway)
        self.assertIn(self.row(iid)['state'], ('DISPATCHED', 'DEVICE_ACTIVE'))
        self.assertEqual(self.gateway.submitted[-1]['execution_mode'], 'hold')   # verify + keep the bet on the slip
        self.assertNotIn('confirmation_status', self.gateway.submitted[-1])
        with self.assertRaises(PermissionError):
            self.p.final.approve(iid, 'operator')               # nothing verified yet: nothing to approve
        self.gateway.results[iid] = ready_result(iid)
        self.clock.advance(250)                                  # the phone's verification run takes minutes
        self.p.tick(self.gateway)
        row = self.row(iid)
        self.assertEqual(row['state'], 'AWAITING_APPROVAL')
        self.assertTrue(row['ready_at'] and row['approval_requested_at'])
        # Operator approves more than 300 s after the alert was posted: age counts from the device
        # verification, which the phone repeats right before the tap.
        self.clock.advance(100)
        self.p.final.approve(iid, 'operator')
        self.p.tick(self.gateway)
        self.assertIn(self.row(iid)['state'], ('DISPATCHED', 'DEVICE_ACTIVE'))
        self.assertEqual(self.gateway.submitted[-1]['execution_mode'], 'dispatch')
        self.assertEqual(self.gateway.submitted[-1]['confirmation_status'], 'APPROVED')

    def test_failed_verification_never_asks_for_approval(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.p.tick(self.gateway)
        self.gateway.results[iid] = fail_result(iid, 'STAKE_REJECTED', 'Typed stake did not read back')
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'REJECTED')
        self.assertIsNone(self.row(iid)['approval_requested_at'])


class OneShotTests(Base):
    settings = dict(final_action_enabled=True, final_action_one_shot=True)

    def test_first_place_bet_result_disarms_everything_but_verification_continues(self):
        first = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.p.tick(self.gateway)
        self.p.final.approve(first, 'operator')
        second = self.p.ingest(message(RYTAS))['instruction_id']
        self.p.tick(self.gateway)                                   # first: Place Bet run sent
        self.gateway.results[first + '-place'] = placement_result(first)
        self.p.tick(self.gateway)
        s = self.p.settings
        self.assertEqual((s.dispatch_enabled, s.final_action_enabled, self.p.final.paused()), (False, False, True))
        self.assertEqual(self.p.disarmed['instruction_id'], first)
        self.assertEqual(len(self.audits('FINAL_ACTION_DISARMED')), 1)
        sends = len(self.gateway.submitted)
        for _ in range(3):
            self.clock.advance(20)
            self.p.tick(self.gateway)
        adapter = [x for x in self.gateway.submitted[sends:] if x['action'] == 'ADAPTER_WORKFLOW']
        self.assertEqual(adapter, [])                               # nothing else goes to the phone...
        self.assertTrue(any(x['action'] == 'MY_BETS' for x in self.gateway.submitted[sends:]))  # ...but verification
        self.assertNotIn(self.row(second)['state'], ('APPROVED', 'DISPATCHED'))

    def test_failure_before_the_tap_also_disarms(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.p.tick(self.gateway)
        self.p.final.approve(iid, 'operator')
        self.p.tick(self.gateway)
        self.gateway.results[iid + '-place'] = fail_result(iid, 'PRICE_CHANGED')
        self.p.tick(self.gateway)
        self.assertEqual((self.p.settings.dispatch_enabled, self.p.settings.final_action_enabled), (False, False))


class SettlementViewTests(Base):
    def test_unconfirmed_settled_view_fails_the_check_and_never_blocks(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.p.tick(self.gateway)
        self.p.final.approve(iid, 'operator')
        self.p.tick(self.gateway)
        self.gateway.results[iid + '-place'] = placement_result(iid)
        self.p.tick(self.gateway)
        self.clock.advance(20)
        self.p.tick(self.gateway)
        rec = self.reconciliations()[-1]
        self.gateway.results[rec['device_instruction_id']] = my_bets(rec['device_instruction_id'], MELBOURNE_CARD)
        self.p.tick(self.gateway)                                   # verified -> OPEN
        self.clock.advance(1)
        self.p.tick(self.gateway)                                   # first settlement check submitted
        settle = [r for r in self.reconciliations() if r['purpose'] == 'SETTLEMENT'][-1]
        wrong_view = {'instruction_id': settle['device_instruction_id'], 'status': 'PASS', 'stage': 'PASS',
                      'my_bets': {'view': 'SETTLED', 'lines': [{'text': 'bet365.com/#/HO/', 'top': 80, 'frame': 0}]}}
        self.gateway.results[settle['device_instruction_id']] = wrong_view
        self.p.tick(self.gateway)                                   # must not raise
        settle = [r for r in self.reconciliations() if r['purpose'] == 'SETTLEMENT'][-1]
        self.assertEqual(settle['outcome'], 'FAILED')
        self.assertFalse(self.p.final.device_busy())


class HeldSlipTests(Base):
    """Verified bet held on the slip for approval; /approve taps it (PLACE_HELD), never rebuilds it."""

    def setUp(self):
        super().setUp()
        self.p = pipeline(self.p.store.path, self.clock, instant_verification=False, **self.settings)

    def held(self, sample=MELBOURNE):
        iid = self.p.ingest(message(sample))['instruction_id']
        self.p.tick(self.gateway)
        result = ready_result(iid)
        result['selection'].update(selection_name='Over', line='190.5')
        self.gateway.results[iid] = result
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'AWAITING_APPROVAL')
        return iid

    def test_hold_run_uses_the_event_link_and_kickoff(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.p.tick(self.gateway)
        payload = self.gateway.submitted[-1]
        self.assertEqual((payload['action'], payload['execution_mode']), ('ADAPTER_WORKFLOW', 'hold'))
        self.assertEqual(payload['event_url'], 'https://www.bet365.com/#/AC/B18/C21167989/D19/E26735656/F19/I0/')
        self.assertEqual(payload['kickoff_utc'], '2026-09-24T09:30')
        self.assertNotIn('confirmation_status', payload)

    def test_approve_taps_the_held_slip_without_rebuilding(self):
        iid = self.held()
        self.p.final.approve(iid, 'operator')
        self.p.tick(self.gateway)
        payload = self.gateway.submitted[-1]
        self.assertEqual(payload['action'], 'PLACE_HELD')
        self.assertEqual(payload['instruction_id'], iid + '-place')
        self.assertEqual((payload['selection_name'], payload['line'], payload['price'], payload['stake']),
                         ('Over', '190.5', '2.20', self.row(iid)['stake']))
        self.assertEqual((payload['execution_mode'], payload['confirmation_status']), ('dispatch', 'APPROVED'))
        self.assertEqual(len([x for x in self.gateway.submitted if x['action'] == 'ADAPTER_WORKFLOW']), 1)  # no rebuild
        self.gateway.results[iid + '-place'] = placement_result(iid)
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'COMPLETED')
        self.p.tick(self.gateway)
        self.assertFalse(any(x['action'] == 'RESET_BETSLIP' for x in self.gateway.submitted))  # the run reset itself
        self.assertIsNone(self.p.held_instruction())

    def test_queue_and_device_timings_are_persisted(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.clock.advance(7)
        self.p.tick(self.gateway)
        self.clock.advance(30)
        result = ready_result(iid)
        result['selection'].update(selection_name='Over', line='190.5')
        self.gateway.results[iid] = result
        self.p.tick(self.gateway)
        row = self.row(iid)
        self.assertEqual(row['queue_wait_ms'], 7000)
        self.assertEqual(row['device_execution_ms'], 30000)
        self.assertIsNotNone(row['device_started_at'])
        self.p.final.approve(iid, 'operator')
        self.p.tick(self.gateway)
        self.clock.advance(6)
        self.gateway.results[iid + '-place'] = placement_result(iid)
        self.p.tick(self.gateway)
        row = self.row(iid)
        self.assertEqual(row['device_execution_ms'], 36000)          # both device runs
        self.assertEqual(row['queue_wait_ms'], 7000)                 # first device start only
        self.assertEqual(row['terminal_at'], row['completed_at'])

    def test_malformed_event_link_is_omitted_so_the_phone_searches(self):
        from core.pipeline import event_link
        bad = dict(normalized_alert=json.dumps({'comparison_url': 'https://www.bet365.com/#/AX/K9'}))
        self.assertIsNone(event_link(bad))
        self.assertIsNone(event_link(dict(normalized_alert='not json')))
        good = dict(normalized_alert=json.dumps({'comparison_url': 'https://www.bet365.com/#/AC/B18/C1/D19/E2/F19/I0/'}))
        self.assertTrue(event_link(good).startswith('https://www.bet365.com/#/AC/B18/'))

    def test_held_slip_owns_the_phone(self):
        iid = self.held()
        other = self.p.ingest(message(RYTAS))['instruction_id']
        for _ in range(3):
            self.clock.advance(10)
            self.p.tick(self.gateway)
        self.assertEqual(self.row(other)['state'], 'QUEUED')         # waits; the held bet is on the slip
        self.assertEqual(self.p.held_instruction(), iid)

    def test_expired_approval_clears_the_held_slip_then_frees_the_phone(self):
        iid = self.held()
        self.clock.advance(121)
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'STALE')
        self.p.tick(self.gateway)
        resets = [x for x in self.gateway.submitted if x['action'] == 'RESET_BETSLIP']
        self.assertEqual(len(resets), 1)
        self.assertIsNone(self.p.held_instruction())
        self.assertFalse(any(x['action'] == 'PLACE_HELD' for x in self.gateway.submitted))

    def test_pre_tap_refusal_clears_the_slip_and_is_not_a_bet(self):
        iid = self.held()
        self.p.final.approve(iid, 'operator')
        self.p.tick(self.gateway)
        refused = fail_result(iid, 'PRICE_CHANGED', 'Approved price 2.20 not on the slip')
        refused['placement'] = {'tapped': False, 'outcome': 'NOT_TAPPED'}
        self.gateway.results[iid + '-place'] = refused
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'PRICE_CHANGED')
        self.p.tick(self.gateway)
        self.assertEqual(len([x for x in self.gateway.submitted if x['action'] == 'RESET_BETSLIP']), 1)
        self.assertIsNone(self.bet(iid))


class RealMyBetsTests(unittest.TestCase):
    def test_live_unsettled_with_several_singles(self):
        live = json.loads((Path(__file__).parent / 'fixtures/mybets_live_20260924.json').read_text(encoding='utf-8'))
        placed = [dict(home='Austria', away='Israel', market='1X2', selection='HOME', stake='0.10', odds='1.44'),
                  dict(home='Hapoel Tel Aviv', away='Bayern Munich', market='MONEYLINE', selection='HOME', stake='0.10', odds='1.23'),
                  dict(home='Panathinaikos', away='Paris', market='MONEYLINE', selection='HOME', stake='0.10', odds='1.17')]
        for bet in placed:
            self.assertTrue(bet_matching.match(bet, live)['found'], bet['home'])
        never = [dict(home='Hapoel Tel Aviv', away='Bayern Munich', market='MONEYLINE', selection='AWAY', stake='0.10', odds='3.75'),
                 dict(home='Austria', away='Israel', market='1X2', selection='HOME', stake='1.00', odds='1.44')]
        for bet in never:
            self.assertFalse(bet_matching.match(bet, live)['found'], bet)

    def test_real_spread_bet_matches_only_its_own_side_and_line(self):
        # Receipt capture 2026-09-24: £0.10 Hapoel Tel Aviv -8.0 @ 1.83 (Bet Ref BT4964411281W).
        live = json.loads((Path(__file__).parent / 'fixtures/mybets_spread_20260924.json').read_text(encoding='utf-8'))
        base = dict(home='Hapoel Tel Aviv', away='Bayern Munich', market='SPREAD', stake='0.10', odds='1.83')
        self.assertTrue(bet_matching.match(dict(base, selection='HOME', line='-8.0'), live)['found'])
        for other in (dict(selection='AWAY', line='8.0'), dict(selection='HOME', line='-7.5'),
                      dict(market='TOTALS', selection='OVER', line='173.5'), dict(selection='HOME', line='-8.0', stake='1.00')):
            self.assertFalse(bet_matching.match(dict(base, **other), live)['found'], other)

    """Real My Bets screens from shadow capture (operator placed £0.10 singles by hand)."""
    austria = dict(home='Austria', away='Israel', market='1X2', selection='HOME', line=None, stake='0.10', odds='1.44')

    def test_newest_expanded_card_is_an_exact_match_despite_ocr_noise(self):
        found = bet_matching.match(self.austria, real('unsettled', 'OPEN'))       # stake OCR'd as "£O.1 0"
        self.assertEqual((found['found'], found['confidence']), (True, 'EXACT'))

    def test_collapsed_card_is_inconclusive_never_absent(self):
        portugal = dict(home='Portugal', away='Wales', market='1X2', selection='HOME', stake='0.10', odds='1.16')
        self.assertEqual(bet_matching.match(portugal, real('unsettled', 'OPEN'))['confidence'], 'INCONCLUSIVE')

    def test_stake_is_read_from_the_same_card_only(self):
        wrong_stake = dict(self.austria, stake='1.00')                          # "£1.00 Single Arsenal" is another card
        self.assertFalse(bet_matching.match(wrong_stake, real('unsettled', 'OPEN'))['found'])

    def test_bet_not_placed_is_not_found(self):
        norway = dict(home='Norway', away='Denmark', market='1X2', selection='HOME', stake='0.10', odds='1.85')
        self.assertFalse(bet_matching.match(norway, real('unsettled', 'OPEN'))['found'])

    def test_live_tab_or_unconfirmed_view_never_proves_absence(self):
        with self.assertRaises(ValueError):
            bet_matching.match(self.austria, real('live_empty', 'OPEN'))           # "There are currently no bets"
        with self.assertRaises(ValueError):
            bet_matching.match(self.austria, real('unsettled', 'SETTLED'))

    def test_settled_cards(self):
        gremio = dict(home='Gremio', away='Vasco da Gama', market='1X2', selection='HOME', stake='300.00')
        found = bet_matching.match(gremio, real('settled_expanded', 'SETTLED'))
        # A Bet Builder card has no 'Gremio <odds>' selection line: not a 1X2 single, so not our bet,
        # but its settlement is still read correctly.
        self.assertEqual((found['found'], found['status'], found['returns']), (False, 'RETURNED', '514.29'))
        psv = dict(home='PSV', away='Shakhtar', market='1X2', selection='HOME', stake='250.00')
        self.assertEqual(bet_matching.match(psv, real('settled_list', 'SETTLED'))['status'], 'LOST')


class MatchingTests(unittest.TestCase):
    base = dict(home='SE Melbourne Phoenix', away='Melbourne United', market='TOTALS', selection='OVER', line='190.5',
                stake='1.00', odds='2.20')

    def lines(self, texts):
        return {'lines': [{'text': t, 'top': i * 40, 'frame': 0} for i, t in enumerate(texts)]}

    def test_exact_match_with_fractional_odds_and_reference(self):
        found = bet_matching.match(self.base, self.lines(MELBOURNE_CARD))
        self.assertEqual((found['found'], found['confidence'], found['bet_reference']), (True, 'EXACT', 'JL1234567890'))

    def test_weak_evidence_is_not_a_match(self):
        for broken in (['Over 190.5', 'SE Melbourne Phoenix v Melbourne United', 'Stake £2.00'],      # wrong stake
                       ['Under 190.5', 'SE Melbourne Phoenix v Melbourne United', 'Stake £1.00'],     # wrong side
                       ['Over 191.5', 'SE Melbourne Phoenix v Melbourne United', 'Stake £1.00'],      # wrong line
                       ['Over 190.5', 'Perth Wildcats v Melbourne United', 'Stake £1.00']):           # wrong fixture
            self.assertFalse(bet_matching.match(self.base, self.lines(broken))['found'], broken)

    def test_spread_signed_line_and_settled_status(self):
        rytas = dict(home='Rytas Vilnius', away='Shanghai Sharks', market='SPREAD', selection='HOME', line='-18.5',
                     stake='0.10', odds='1.83')
        card = ['Rytas Vilnius -18.5', 'Handicap', 'Rytas Vilnius v Shanghai Sharks', 'Stake £0.10', '1.83', 'Won',
                'Returned £0.18']
        found = bet_matching.match(rytas, self.lines(card))
        self.assertEqual((found['found'], found['status'], found['returns']), (True, 'WON', '0.18'))
        self.assertFalse(bet_matching.match(dict(rytas, line='+18.5'), self.lines(card))['found'])

    def test_no_lines_is_an_error(self):
        with self.assertRaises(ValueError):
            bet_matching.match(self.base, {'view': 'OPEN'})


if __name__ == '__main__':
    unittest.main()
