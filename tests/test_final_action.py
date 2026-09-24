"""Final action (Place Bet): approval, limits, kill switch, outcomes, reconciliation, settlement.

Everything runs against a fake coordinator: no phone, no bookmaker, no money.
"""
import json
import tempfile
import unittest
from pathlib import Path

from core import bet_matching
from core.lifecycle import State, interpret_device_result, placement_of
from tests.pipeline_support import MELBOURNE, RYTAS, Clock, FakeGateway, message, pipeline, fail_result


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
    return {'instruction_id': rid, 'status': 'PASS', 'stage': 'PASS', 'detail': 'MY_BETS',
            'my_bets': {'view': view, 'frames': ['s001_my_bets.png'],
                        'lines': [{'text': t, 'top': 100 + 40 * i, 'left': 20, 'frame': 0} for i, t in enumerate(lines)]}}


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
        self.assertEqual(self.gateway.submitted, [])
        self.assertEqual(self.p.final.approve(iid[:10], 'operator'), iid)   # unique prefix, like Telegram
        self.p.tick(self.gateway)
        payload = self.gateway.submitted[0]
        self.assertEqual((payload['execution_mode'], payload['confirmation_status']), ('dispatch', 'APPROVED'))
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
        self.assertEqual(self.gateway.submitted, [])

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
        self.assertEqual(self.gateway.submitted, [])
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
        self.assertEqual(self.gateway.submitted[0]['execution_mode'], 'dispatch')
        self.assertEqual(self.row(first)['approved_by'], 'auto')
        self.gateway.results[first] = placement_result(first)
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
        self.assertEqual(self.gateway.submitted, [])

    def test_refused_and_pre_tap_failures_do_not_count(self):
        self.p.settings.max_bets_per_day = 1
        first = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.p.tick(self.gateway)
        self.gateway.results[first] = fail_result(first, 'TARGET_NOT_FOUND', 'fixture not on board')
        self.gateway.results[first]['placement'] = {'tapped': False, 'outcome': 'NOT_TAPPED'}
        self.p.tick(self.gateway)
        self.assertEqual(self.row(first)['state'], 'TARGET_NOT_FOUND')
        self.assertIsNone(self.bet(first))
        second = self.p.ingest(message(RYTAS))['instruction_id']
        self.p.tick(self.gateway)
        self.assertEqual(self.row(second)['state'], 'DEVICE_ACTIVE')     # the failed one did not use the quota


class OutcomeTests(Base):
    def test_placed_records_receipt_and_verifies_in_my_bets(self):
        iid = self.approved_and_dispatched()
        self.gateway.results[iid] = placement_result(iid)
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
        self.gateway.results[iid] = placement_result(iid, 'INSUFFICIENT_FUNDS')
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
        self.gateway.results[iid] = placement_result(iid, 'PRICE_CHANGED')
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
        self.gateway.results[iid] = result
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
        adapter_sends = [s for s in self.gateway.submitted if s['action'] == 'ADAPTER_WORKFLOW']
        self.assertEqual(len(adapter_sends), 1)
        self.clock.advance(16)
        self.p.tick(self.gateway)                      # reconcile delay elapsed: My Bets check submitted
        rec = self.reconciliations()[0]
        self.gateway.results[rec['device_instruction_id']] = my_bets(rec['device_instruction_id'], MELBOURNE_CARD)
        self.p.tick(self.gateway)
        self.assertEqual((self.row(iid)['state'], self.bet(iid)['status']), ('COMPLETED', 'OPEN'))
        self.assertEqual(len([s for s in self.gateway.submitted if s['action'] == 'ADAPTER_WORKFLOW']), 1)

    def test_unknown_absent_twice_becomes_not_placed(self):
        iid = self.approved_and_dispatched()
        self.gateway.results[iid] = placement_result(iid, 'PLACEMENT_UNKNOWN')
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
        self.gateway.results[iid] = placement_result(iid, 'PLACEMENT_UNKNOWN')
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
        self.gateway.results[iid] = {'status': 'MAYBE'}
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'PLACEMENT_UNKNOWN')

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
        self.gateway.results[iid] = placement_result(iid, 'PLACEMENT_UNKNOWN')
        self.p.tick(self.gateway)
        self.clock.advance(16)
        self.p.tick(self.gateway)                      # MY_BETS submitted, no result yet
        second = self.p.ingest(message(RYTAS))['instruction_id']
        self.p.tick(self.gateway)
        self.assertEqual(self.row(second)['state'], 'QUEUED')


class SettlementTests(Base):
    def test_open_bet_settles_and_counts_towards_loss(self):
        iid = self.approved_and_dispatched()
        self.gateway.results[iid] = placement_result(iid)
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
