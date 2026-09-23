"""Failure/recovery harness for the unattended pipeline. No network, phone or Telegram."""
import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import timedelta
from pathlib import Path

from core import alert_classifier
from core.lifecycle import State, TERMINAL, allowed, interpret_device_result
from core.pipeline_store import Store, instruction_id_for
from core.rules_engine import evaluate
from core.session_contract import parse_report, gate, SessionState
from tests.pipeline_support import (ROOT, SNAPSHOT, MELBOURNE, RYTAS, T0, Clock, FakeGateway, config, message,
                                    pipeline, ready_result, fail_result)

FIXTURES = ROOT / 'tests/fixtures'


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'pipeline.sqlite3'
        self.clock = Clock()
        self.gateway = FakeGateway(self.clock)
        self.p = pipeline(self.path, self.clock)
        self.addCleanup(self.tmp.cleanup)

    def row(self, instruction_id):
        with self.p.store.connection() as db:
            return dict(db.execute('SELECT * FROM instructions WHERE instruction_id=?', (instruction_id,)).fetchone())

    def stages(self, instruction_id):
        with self.p.store.connection() as db:
            return [(r['to_state'], r['at']) for r in db.execute(
                'SELECT to_state, at FROM transitions WHERE instruction_id=? ORDER BY id', (instruction_id,))]

    def intake(self):
        with self.p.store.connection() as db:
            return [dict(r) for r in db.execute('SELECT * FROM intake_messages ORDER BY id')]

    def audits(self, kind=None):
        with self.p.store.connection() as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM audit_events ORDER BY id')]
        return [r for r in rows if kind is None or r['kind'] == kind]

    def queued(self, sample=MELBOURNE, **kw):
        result = self.p.ingest(message(sample, **kw))
        self.assertEqual(result['state'], 'QUEUED', result)
        return result['instruction_id']


# ------------------------------------------------------------------ parser / classification
class ClassificationTests(unittest.TestCase):
    """Regression over every genuine production format plus malformed/unsupported cases."""

    def test_every_genuine_snapshot_message_parses_with_explicit_target(self):
        expected = {'67894': ('TOTALS', 'OVER', '190.5', '2.20', '113.52'),
                    '67895': ('SPREAD', 'HOME', '-18.5', '1.83', '108.47'),
                    '67897': ('TOTALS', 'OVER', '176', '2.20', '116.64'),
                    '67898': ('TOTALS', 'OVER', '190', '2.15', '110.69')}
        for sample in SNAPSHOT:
            verdict = alert_classifier.classify(sample['raw_text'])
            self.assertEqual(verdict['status'], 'PARSED', sample['message_id'])
            p = verdict['parsed']
            self.assertEqual((p['market'], p['target_side'], p['target_line'], p['alert_price'],
                              p['displayed_ev_percent']), expected[sample['message_id']])
            self.assertEqual(p['raw_text'], sample['raw_text'])
            self.assertTrue(p['quote_mapping']['production_verified'])

    def test_rytas_preserves_alternate_line_and_all_fields(self):
        p = alert_classifier.classify(RYTAS['raw_text'])['parsed']
        self.assertEqual(p['alternate_line'], {'current': True, 'opening': False, 'comparison': False})
        for key, value in dict(sport='basketball', competition='Intercontinental Cup', home='Rytas Vilnius',
                               away='Shanghai Sharks', scheduled_at_local='2026-09-24T07:30').items():
            self.assertEqual(p[key], value)
        self.assertEqual(p['pinnacle']['quotes'][0]['price'], '1.591')
        decision = evaluate(p, config(), instruction_id='x', received_at=T0.isoformat(), now=T0)
        self.assertEqual(decision['instruction']['alternate_line'], {'current': True, 'opening': False, 'comparison': False})

    def test_pasted_fixtures_without_bold_are_ambiguous_not_guessed(self):
        for name in ('melbourne_real', 'melbourne_190_5_real', 'prague_real', 'rytas_real'):
            verdict = alert_classifier.classify((FIXTURES / f'oddsnotifier_basketball_{name}.txt').read_text(encoding='utf-8'))
            self.assertEqual(verdict['status'], 'AMBIGUOUS', name)
            self.assertIsNone(verdict['parsed']['target_side'])

    def test_unverified_football_formats_are_ambiguous_with_reason(self):
        for name in ('oddsnotifier_spread.txt', 'oddsnotifier_football_ml_linked.txt'):
            verdict = alert_classifier.classify((FIXTURES / name).read_text(encoding='utf-8'))
            self.assertEqual(verdict['status'], 'AMBIGUOUS', name)
            self.assertIn('UNSUPPORTED_MAPPING: football', verdict['reason'])
            self.assertIsNone(verdict['parsed']['target_side'])

    def test_unsupported_basketball_moneyline_layout_is_ambiguous(self):
        text = MELBOURNE['raw_text'].replace('market=Totals', 'market=ML').replace('Totals (190.5)', 'ML') \
            .replace('Bet365 (Totals 190.5)', 'Bet365 (ML)')
        verdict = alert_classifier.classify(text)
        self.assertEqual(verdict['status'], 'AMBIGUOUS')
        self.assertIn('UNSUPPORTED_MAPPING: basketball MONEYLINE', verdict['reason'])

    def test_malformed_ignored_and_empty(self):
        broken = MELBOURNE['raw_text'].replace('- 1.65', '- **1.65**')
        self.assertEqual(alert_classifier.classify(broken)['status'], 'INVALID')
        self.assertIn('Multiple bold', alert_classifier.classify(broken)['reason'])
        self.assertEqual(alert_classifier.classify('New odds update on Pinnacle\ngarbage')['status'], 'INVALID')
        self.assertEqual(alert_classifier.classify('EV: None layout\nNew odds update on Pinnacle')['status'], 'IGNORED')
        self.assertEqual(alert_classifier.classify('Service notice')['status'], 'IGNORED')
        self.assertEqual(alert_classifier.classify('')['status'], 'IGNORED')
        self.assertEqual(alert_classifier.classify(None)['status'], 'IGNORED')
        line_transition = MELBOURNE['raw_text'].replace('Totals (190.5)', 'Totals (190.5 → 191.5)')
        self.assertEqual(alert_classifier.classify(line_transition)['status'], 'INVALID')


# ------------------------------------------------------------------ intake / dedupe / stale
class IntakeTests(Base):
    def test_parsed_message_full_lifecycle_to_queue_with_timestamps(self):
        result = self.p.ingest(message(MELBOURNE))
        iid = result['instruction_id']
        self.assertEqual(iid, instruction_id_for('production', '-1001475314653', '67894'))
        self.assertEqual([s for s, _ in self.stages(iid)], ['RECEIVED', 'PARSED', 'RULES_APPLIED', 'QUEUED'])
        self.assertTrue(all(at for _, at in self.stages(iid)))
        row = self.row(iid)
        self.assertEqual((row['market'], row['selection'], row['line'], row['alert_price'], row['minimum_price'],
                          row['stake'], row['displayed_ev']), ('TOTALS', 'OVER', '190.5', '2.20', '2.20', '1.00', '113.52'))
        self.assertEqual(row['raw_alert'], MELBOURNE['raw_text'])
        self.assertEqual(row['message_id'], '67894')
        self.assertEqual(json.loads(row['rules_result'])['decision'], 'ACCEPT')
        for key in ('received_at', 'parsed_at', 'rules_applied_at', 'queued_at'):
            self.assertIsNotNone(row[key], key)
        stored = self.intake()[0]
        self.assertEqual((stored['status'], stored['formatted_text']), ('PARSED', MELBOURNE['raw_text']))

    def test_instruction_id_is_deterministic_across_restarts(self):
        first = self.p.ingest(message(MELBOURNE))['instruction_id']
        other = Path(self.tmp.name) / 'other.sqlite3'
        self.assertEqual(pipeline(other, self.clock).ingest(message(MELBOURNE))['instruction_id'], first)
        self.assertNotEqual(instruction_id_for('sample', '-1001475314653', '67894'), first)

    def test_every_message_gets_exactly_one_status(self):
        texts = [MELBOURNE['raw_text'], (FIXTURES / 'oddsnotifier_spread.txt').read_text(encoding='utf-8'),
                 'New odds update on Pinnacle\nbroken', 'Channel notice', MELBOURNE['raw_text']]
        for index, text in enumerate(texts):
            self.p.ingest(message(MELBOURNE, message_id=str(100 + index), text=text))
        self.assertEqual([r['status'] for r in self.intake()], ['PARSED', 'AMBIGUOUS', 'INVALID', 'IGNORED', 'DUPLICATE'])
        self.assertTrue(all(r['reason'] for r in self.intake()))

    def test_duplicate_telegram_delivery_recorded_but_processed_once(self):
        first = self.p.ingest(message(MELBOURNE))
        second = self.p.ingest(message(MELBOURNE))
        self.assertEqual(second['status'], 'DUPLICATE')
        self.assertEqual(second['instruction_id'], first['instruction_id'])
        with self.p.store.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM instructions').fetchone()[0], 1)
        # A history scan is not a new delivery: skipped without another row.
        self.assertTrue(self.p.ingest(message(MELBOURNE), delivery='reconcile')['skipped'])
        self.assertEqual(len(self.intake()), 2)

    def test_concurrent_duplicate_deliveries_create_one_instruction(self):
        barrier = threading.Barrier(4)
        results = []

        def deliver():
            barrier.wait()
            results.append(self.p.ingest(message(MELBOURNE))['status'])
        threads = [threading.Thread(target=deliver) for _ in range(4)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sorted(results), ['DUPLICATE'] * 3 + ['PARSED'])
        with self.p.store.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM instructions').fetchone()[0], 1)

    def test_same_selection_from_new_message_is_duplicate(self):
        self.queued()
        again = self.p.ingest(message(MELBOURNE, message_id='99999'))
        self.assertEqual(again['status'], 'DUPLICATE')
        self.assertIn('already pending', again['reason'])

    def test_price_update_supersedes_pending_instruction(self):
        old = self.queued()
        text = MELBOURNE['raw_text'].replace('**2.20**', '**2.25**')
        new = self.p.ingest(message(MELBOURNE, message_id='99999', text=text))
        self.assertEqual(new['state'], 'QUEUED')
        self.assertEqual(self.row(old)['state'], 'STALE')
        self.assertIn('SUPERSEDED', self.row(old)['failure_reason'])

    def test_update_never_supersedes_dispatched_instruction(self):
        old = self.queued()
        self.p.tick(self.gateway)
        text = MELBOURNE['raw_text'].replace('**2.20**', '**2.25**')
        new = self.p.ingest(message(MELBOURNE, message_id='99999', text=text))
        self.assertEqual(new['status'], 'DUPLICATE')
        self.assertEqual(self.row(old)['state'], 'DEVICE_ACTIVE')

    def test_edit_before_dispatch_cancels_and_is_never_executed(self):
        iid = self.queued()
        edited = self.p.ingest(message(MELBOURNE, edit_date=(T0 + timedelta(seconds=5)).isoformat()))
        self.assertEqual(edited['status'], 'IGNORED')
        self.assertEqual(self.row(iid)['state'], 'STALE')
        self.p.tick(self.gateway)
        self.assertEqual(self.gateway.submitted, [])

    def test_stale_by_age_event_started_and_unknown_timezone(self):
        old = self.p.ingest(message(MELBOURNE, source=T0 - timedelta(seconds=301)))
        self.assertEqual(old['state'], 'STALE')
        self.assertIn('alert_age', self.row(old['instruction_id'])['failure_reason'])
        self.clock.now = T0.replace(day=24, hour=10)
        started = self.p.ingest(message(RYTAS, received=self.clock.now))
        self.assertEqual(started['state'], 'STALE')
        self.assertIn('event started', self.row(started['instruction_id'])['failure_reason'])
        self.clock.now = T0
        unknown = pipeline(Path(self.tmp.name) / 'tz.sqlite3', self.clock, config(event_timezone=None))
        result = unknown.ingest(message(MELBOURNE))
        self.assertEqual(result['state'], 'REJECTED')
        with unknown.store.connection() as db:
            reason = unknown.store.get_instruction(db, result['instruction_id'])['failure_reason']
        self.assertIn('event timezone not configured', reason)

    def test_queued_alert_goes_stale_before_dispatch(self):
        self.p.settings.dispatch_enabled = False
        iid = self.queued()
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'QUEUED')
        self.clock.advance(400)
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'STALE')
        self.assertIn('Pre-dispatch recheck', self.row(iid)['failure_reason'])
        self.assertEqual(self.gateway.submitted, [])


# ------------------------------------------------------------------ rules engine
class RulesTests(unittest.TestCase):
    def setUp(self):
        self.alert = alert_classifier.classify(MELBOURNE['raw_text'])['parsed']

    def run_rules(self, cfg, alert=None):
        return evaluate(alert or self.alert, cfg, instruction_id='x', received_at=T0.isoformat(), now=T0)

    def test_accept_builds_normalized_instruction(self):
        cfg = config(allowed_slippage=0.05)
        cfg['sports']['basketball']['markets']['TOTALS']['stake'] = 2.5
        decision = self.run_rules(cfg)
        self.assertEqual(decision['decision'], 'ACCEPT')
        i = decision['instruction']
        self.assertEqual((i['side'], i['selection_name'], i['line'], i['alert_price'], i['minimum_price'], i['stake']),
                         ('OVER', 'Over', '190.5', '2.20', '2.15', '2.50'))
        self.assertTrue(all(c['passed'] for c in decision['checks']))

    def test_rejections_fail_closed_with_reason(self):
        cases = []
        cfg = config(enabled=False); cases.append((cfg, 'global_enabled'))
        cfg = config(); cfg['sports']['basketball']['markets']['TOTALS']['enabled'] = False; cases.append((cfg, 'market_enabled'))
        cfg = config(); cfg['sports']['basketball']['markets']['TOTALS']['minimum_ev'] = 120; cases.append((cfg, 'minimum_ev'))
        cfg = config(); cfg['sports']['basketball']['markets']['TOTALS']['min_price'] = 2.5; cases.append((cfg, 'min_price'))
        cfg = config(); cfg['sports']['basketball']['markets']['TOTALS']['max_price'] = 2.0; cases.append((cfg, 'max_price'))
        for cfg, check in cases:
            decision = self.run_rules(cfg)
            self.assertEqual(decision['decision'], 'REJECT', check)
            self.assertTrue(decision['reason'].startswith(check), decision['reason'])
            self.assertIsNone(decision['instruction'])

    def test_unverified_or_targetless_alert_rejected(self):
        football = alert_classifier.classify((FIXTURES / 'oddsnotifier_spread.txt').read_text(encoding='utf-8'))['parsed']
        self.assertTrue(self.run_rules(config(), football)['reason'].startswith('verified_mapping'))
        targetless = dict(self.alert, target_side=None, alert_price=None)
        self.assertEqual(self.run_rules(config(), targetless)['decision'], 'REJECT')

    def test_config_validation_and_legacy_upgrade(self):
        from core.decision_support import validate, defaults
        legacy = defaults()
        del legacy['global']['stale_alert_seconds'], legacy['global']['event_timezone']
        for rule in legacy['sports']['football']['markets'].values():
            del rule['min_price'], rule['max_price']
        self.assertEqual(validate(legacy)['global']['stale_alert_seconds'], 300)
        for bad in (dict(event_timezone='Mars/Base'), dict(stale_alert_seconds=0)):
            with self.assertRaises(ValueError):
                validate(config(**bad))
        cfg = config(); cfg['sports']['football']['markets']['1X2'].update(min_price=3, max_price=2)
        with self.assertRaises(ValueError):
            validate(cfg)


# ------------------------------------------------------------------ session contract
class SessionTests(Base):
    def test_contract_parsing_and_gate(self):
        report = parse_report('d', {'state': 'LOGGED_IN', 'observed_at_ms': int(T0.timestamp() * 1000)}, 'result')
        self.assertEqual(report.state, SessionState.AUTHENTICATED)
        self.assertEqual(gate(report, T0), (True, 'AUTHENTICATED'))
        for state in ('UNKNOWN', 'LOGGED_OUT', 'AUTHENTICATING', 'EXPIRED', 'RESTRICTED', 'ERROR'):
            permitted, why = gate(parse_report('d', {'state': state, 'observed_at': T0.isoformat()}, 'health'), T0)
            self.assertFalse(permitted)
            self.assertIn(state, why)
        self.assertFalse(gate(None, T0)[0])
        self.assertFalse(gate(report, T0 + timedelta(seconds=121))[0])
        self.assertFalse(gate(report, T0 - timedelta(seconds=60))[0])
        for bad in ({}, {'state': 'MAYBE', 'observed_at': T0.isoformat()}, {'state': 'AUTHENTICATED'},
                    {'state': 'AUTHENTICATED', 'observed_at': '2026-09-23T12:00:00'}, 'AUTHENTICATED'):
            with self.assertRaises((ValueError, TypeError)):
                parse_report('d', bad, 'health')

    def test_session_required_stops_progression(self):
        for state in ('LOGGED_OUT', 'EXPIRED', 'AUTHENTICATING', 'RESTRICTED', 'ERROR', 'UNKNOWN', None):
            with self.subTest(state=state):
                self.setUp()
                self.gateway.session = state
                iid = self.queued()
                self.p.tick(self.gateway)
                self.assertEqual(self.row(iid)['state'], 'SESSION_REQUIRED')
                self.assertEqual(self.gateway.submitted, [])

    def test_stale_and_malformed_session_reports_fail_closed(self):
        self.gateway.session_age = 600
        iid = self.queued()
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'SESSION_REQUIRED')
        self.assertIn('old', self.row(iid)['failure_reason'])
        self.setUp()
        self.gateway.session = 'NOT_A_STATE'
        iid = self.queued()
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'SESSION_REQUIRED')
        self.assertTrue(self.audits('MALFORMED_SESSION_REPORT'))

    def test_authenticated_permits_progression_and_history_recorded(self):
        self.gateway.session = 'LOGGED_OUT'
        self.p.refresh_device(self.gateway)
        self.gateway.session = 'AUTHENTICATED'
        iid = self.queued()
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'DEVICE_ACTIVE')
        self.assertEqual(self.row(iid)['session_state'], 'AUTHENTICATED')
        with self.p.store.connection() as db:
            self.assertEqual([r[0] for r in db.execute('SELECT state FROM session_history ORDER BY id')],
                             ['LOGGED_OUT', 'AUTHENTICATED'])


# ------------------------------------------------------------------ device, dispatch, results
class DispatchTests(Base):
    def test_ready_path_payload_is_ready_only(self):
        iid = self.queued()
        self.p.tick(self.gateway)
        payload = self.gateway.submitted[0]
        self.assertEqual(payload['instruction_id'], iid)
        self.assertEqual(payload['execution_mode'], 'ready')
        self.assertNotIn('confirmation_status', payload)
        self.assertEqual((payload['market'], payload['side'], payload['line'], payload['minimum_price'], payload['stake']),
                         ('TOTALS', 'OVER', '190.5', '2.20', '1.00'))
        self.gateway.results[iid] = ready_result(iid)
        self.p.tick(self.gateway)
        row = self.row(iid)
        self.assertEqual((row['state'], row['observed_price'], row['device_stage']), ('READY', '2.20', 'PASS'))
        self.assertEqual(json.loads(row['evidence']), ['evidence/example/s019_final.png'])
        self.assertEqual([s for s, _ in self.stages(iid)][-3:], ['DISPATCHED', 'DEVICE_ACTIVE', 'READY'])
        self.clock.advance(301)
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'STALE')
        self.assertEqual(len(self.gateway.submitted), 1)

    def test_completion_requires_wager_evidence(self):
        iid = self.queued()
        self.p.tick(self.gateway)
        result = ready_result(iid)
        result['final_state'] = {'state': 'DONE', 'wager_submitted': True}
        self.assertEqual(self.p.apply_result(iid, result), 'COMPLETED')
        self.assertIsNone(self.row(iid)['failure_reason'])
        self.assertIsNotNone(self.row(iid)['duration_ms'])

    def test_device_offline_and_unhealthy(self):
        self.gateway.health_error = OSError('connection refused')
        iid = self.queued()
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'DEVICE_OFFLINE')
        self.assertEqual(self.p.store.device('galaxy-a13-5g')['status'], 'OFFLINE')
        self.setUp()
        self.gateway.health_extra = {'healthy': False}
        iid = self.queued()
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'DEVICE_OFFLINE')
        self.assertEqual(self.gateway.submitted, [])

    def test_busy_device_waits_one_at_a_time(self):
        first = self.queued()
        second = self.queued(RYTAS)
        self.p.tick(self.gateway)
        self.assertEqual([p['instruction_id'] for p in self.gateway.submitted], [first])
        self.assertEqual(self.row(second)['state'], 'QUEUED')
        self.gateway.results[first] = fail_result(first, 'PRICE_CHANGED', 'live 2.10 < 2.20')
        self.p.tick(self.gateway)
        self.p.tick(self.gateway)
        self.assertEqual([p['instruction_id'] for p in self.gateway.submitted], [first, second])

    def test_coordinator_timeout_never_resubmits(self):
        iid = self.queued()
        self.p.tick(self.gateway)
        for _ in range(5):
            self.clock.advance(60)
            self.p.tick(self.gateway)
        row = self.row(iid)
        self.assertEqual(row['state'], 'TIMEOUT')
        self.assertIn('never re-dispatched', row['failure_reason'])
        self.assertEqual(len(self.gateway.submitted), 1)

    def test_lost_submit_response_polls_same_id(self):
        self.gateway.submit_error = TimeoutError('response lost')
        iid = self.queued()
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'DISPATCHED')
        self.assertTrue(self.audits('SUBMIT_UNCERTAIN'))
        self.gateway.submit_error = None
        self.gateway.results[iid] = ready_result(iid)
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'READY')
        self.assertEqual(len(self.gateway.submitted), 1)

    def test_lost_result_response_retried_by_polling(self):
        iid = self.queued()
        self.p.tick(self.gateway)
        self.gateway.results[iid] = ConnectionResetError('lost')
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'DEVICE_ACTIVE')
        self.assertTrue(self.audits('RESULT_POLL_FAILED'))
        self.gateway.results[iid] = ready_result(iid)
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'READY')

    def test_coordinator_duplicate_echo_keeps_waiting(self):
        iid = self.queued()
        self.p.tick(self.gateway)
        self.gateway.results[iid] = fail_result(iid, 'DUPLICATE', 'already accepted')
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'DEVICE_ACTIVE')

    def test_device_stage_mapping_preserves_original(self):
        cases = {'PRICE_CHANGED': 'PRICE_CHANGED', 'BELOW_MINIMUM': 'PRICE_CHANGED', 'SUSPENDED': 'SUSPENDED',
                 'NO_FIXTURE_FOUND': 'TARGET_NOT_FOUND', 'AMBIGUOUS_FIXTURE': 'AMBIGUOUS_TARGET',
                 'LOGIN_FAILED': 'SESSION_REQUIRED', 'TIMEOUT': 'TIMEOUT', 'INVALID_INSTRUCTION': 'REJECTED',
                 'INTERNAL_ERROR': 'UNKNOWN', 'SOMETHING_NEW': 'UNKNOWN'}
        for stage, expected in cases.items():
            state, reason, _ = interpret_device_result(fail_result('i', stage, 'detail text'))
            self.assertEqual(state.value, expected, stage)
            self.assertEqual(reason, f'{stage}: detail text')
        state, reason, _ = interpret_device_result({'status': 'PASS', 'stage': 'PASS'})
        self.assertEqual(state, State.UNKNOWN)

    def test_malformed_result_payload_fails_closed(self):
        for bad in (['not', 'a', 'dict'], {'status': 'MAYBE'}, {'status': 'PASS'}, {'instruction_id': 'other',
                    'status': 'PASS', 'stage': 'PASS', 'detail': 'READY_STATE'}):
            with self.subTest(bad=bad):
                self.setUp()
                iid = self.queued()
                self.p.tick(self.gateway)
                self.gateway.results[iid] = bad
                self.p.tick(self.gateway)
                self.assertEqual(self.row(iid)['state'], 'UNKNOWN')
                self.assertIn('MALFORMED_RESULT', self.row(iid)['failure_reason'])
                self.assertTrue(self.audits('MALFORMED_RESULT'))
                # A later valid result can no longer change the terminal record.
                self.assertEqual(self.p.apply_result(iid, ready_result(iid)), 'UNKNOWN')

    def test_confirmation_statuses_map_onto_lifecycle(self):
        iid = self.queued()
        self.p.tick(self.gateway)
        self.p.apply_result(iid, ready_result(iid))
        self.assertIsNone(self.p.apply_confirmation(iid, 'APPROVED'))
        self.assertEqual(self.p.apply_confirmation(iid, 'PRICE_INVALID', 'live 2.10'), 'PRICE_CHANGED')


# ------------------------------------------------------------------ idempotency / restart
class IdempotencyTests(Base):
    def test_crash_after_dispatch_commit_never_resends(self):
        iid = self.queued()

        class Crash(BaseException):
            pass

        def crash(payload):
            raise Crash()
        self.gateway.submit = crash
        with self.assertRaises(Crash):
            self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'DISPATCHED')
        restarted = pipeline(self.path, self.clock)
        self.assertEqual(restarted.recover(), 1)
        gateway = FakeGateway(self.clock)
        for _ in range(3):
            restarted.tick(gateway)
        self.assertEqual(gateway.submitted, [])
        self.assertEqual(gateway.polled, [iid] * 3)
        gateway.results[iid] = ready_result(iid)
        restarted.tick(gateway)
        self.assertEqual(self.row(iid)['state'], 'READY')

    def test_duplicate_message_after_restart_and_terminal(self):
        iid = self.queued()
        self.p.tick(self.gateway)
        self.gateway.results[iid] = fail_result(iid, 'PRICE_CHANGED')
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'PRICE_CHANGED')
        restarted = pipeline(self.path, self.clock)
        again = restarted.ingest(message(MELBOURNE))
        self.assertEqual(again['status'], 'DUPLICATE')
        restarted.recover()
        gateway = FakeGateway(self.clock)
        for _ in range(3):
            restarted.tick(gateway)
        self.assertEqual(gateway.submitted, [])
        self.assertEqual(restarted.apply_result(iid, ready_result(iid)), 'PRICE_CHANGED')
        self.assertTrue(self.audits('LATE_OR_DUPLICATE_RESULT_IGNORED'))
        with restarted.store.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM instructions').fetchone()[0], 1)

    def test_terminal_state_is_final_and_refusals_audited(self):
        iid = self.queued()
        with self.p.store.tx() as db:
            self.assertTrue(self.p.store.transition(db, iid, State.REJECTED, reason='test'))
            for target in list(State):
                self.assertFalse(self.p.store.transition(db, iid, target))
        self.assertEqual(len(self.audits('TRANSITION_REFUSED')), len(State))
        self.p.tick(self.gateway)
        self.assertEqual(self.gateway.submitted, [])

    def test_state_machine_is_forward_only(self):
        self.assertTrue(allowed('QUEUED', 'DISPATCHED'))
        self.assertTrue(allowed('DISPATCHED', 'READY'))
        self.assertFalse(allowed('DISPATCHED', 'QUEUED'))
        self.assertFalse(allowed('RECEIVED', 'DISPATCHED'))
        for terminal in TERMINAL:
            self.assertFalse(any(allowed(terminal, s) for s in State))

    def test_database_enforces_unique_identity(self):
        self.p.ingest(message(MELBOURNE))
        with self.assertRaises(sqlite3.IntegrityError):
            with self.p.store.tx() as db:
                db.execute("INSERT INTO intake_messages(origin,source,chat_id,message_id,edit_key,delivery,received_at,"
                           "processed_at,status) VALUES ('production','t','-1001475314653','67894','','x','t','t','PARSED')")


if __name__ == '__main__':
    unittest.main()
