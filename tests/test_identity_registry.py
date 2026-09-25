"""Identity registry: strict alias promotion, conflicts, event cache (Milestone B6/B7)."""
import json
import tempfile
import unittest
from pathlib import Path

from tests.pipeline_support import MELBOURNE, Clock, FakeGateway, message, pipeline, ready_result
from tests.test_final_action import placement_result

EVIDENCE = {'event_url': 'https://www.bet365.com/#/AC/B18/C1/D19/E2/F19/I0/', 'kickoff_shown': '25 Sep 18:00'}


class RegistryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.clock = Clock()
        self.p = pipeline(Path(tmp.name) / 'p.sqlite3', self.clock, final_action_enabled=True)
        self.reg = self.p.identity

    def candidate(self, source, book, confidence, day=25):
        evidence = dict(EVIDENCE, identity=dict(kickoff_known=True,kickoff_agrees=True,verdict='HIGH_CONFIDENCE_EVENT_MATCH'),
                        event_context=dict(kickoff_utc=f'2026-09-{day}T17:00',home=book,away='Other Club',competition='test league'))
        with self.p.store.tx() as db:
            return self.reg.record_candidate(db, 'basketball', source, book, evidence, confidence, competition='test league')

    def aliases(self, *names):
        with self.p.store.connection() as db:
            return self.reg.promoted_aliases(db, 'basketball', names, 'test league')

    def test_deterministic_needs_independent_events_and_repeated_delivery_does_not_count(self):
        self.assertEqual(self.candidate('Soproni', 'Sopron KC', 'deterministic'), 'candidate')
        self.assertEqual(self.candidate('Soproni', 'Sopron KC', 'deterministic'), 'candidate')
        self.assertEqual(self.candidate('Soproni', 'Sopron KC', 'deterministic',26), 'promoted')
        self.assertEqual(self.aliases('Soproni'), {'soproni': 'sopron kc'})
        with self.p.store.connection() as db:
            self.assertEqual(self.reg.promoted_aliases(db,'basketball',['Soproni'],'other league'), {})

    def test_high_needs_two_sightings_and_review_never_promotes(self):
        self.assertEqual(self.candidate('Valdeseine', 'Val de Seine', 'high'), 'candidate')
        self.assertEqual(self.aliases('Valdeseine'), {})
        self.assertEqual(self.candidate('Valdeseine', 'Val de Seine', 'high',26), 'promoted')
        self.assertEqual(self.aliases('Valdeseine'), {'valdeseine': 'val de seine'})
        for _ in range(5):
            status = self.candidate('Kyoto Hannaryz', 'Kyoto Hannaryz B', 'review')
        self.assertEqual(status, 'candidate')
        self.assertEqual(self.aliases('Kyoto Hannaryz'), {})

    def test_conflicting_bookmaker_name_demotes(self):
        self.candidate('Soproni', 'Sopron KC', 'deterministic')
        self.candidate('Soproni', 'Sopron KC', 'deterministic',26)
        self.candidate('Soproni', 'Sopron Basket', 'deterministic')   # a different Bet365 name for the same source
        with self.p.store.connection() as db:
            rows = {r['bookmaker_name']: r['status'] for r in db.execute('SELECT * FROM scoped_alias_candidates')}
        self.assertEqual(rows['sopron kc'], 'review')
        with self.p.store.connection() as db:
            self.assertEqual(len([a for a in db.execute("SELECT 1 FROM audit_events WHERE kind='ALIAS_DEMOTED'")]), 1)

    def test_event_cache_only_for_the_same_kickoff_and_not_stale(self):
        with self.p.store.tx() as db:
            self.reg.record_event(db, 'basketball', 'Besancon', 'Val De Seine', '2026-09-25T18:00', EVIDENCE['event_url'], 'Besancon AC', 'Val de Seine','France N1')
        with self.p.store.connection() as db:
            self.assertEqual(self.reg.aliases_for(db, 'basketball', 'Besancon', 'Val De Seine', '2026-09-25T18:00','France N1'),
                             {'besancon': 'Besancon AC'})                                  # only the differing name
            self.assertEqual(self.reg.aliases_for(db, 'basketball', 'Besancon', 'Val De Seine', '2026-10-02T18:00'), {})
        self.clock.advance(5 * 24 * 3600)
        with self.p.store.connection() as db:
            self.assertEqual(self.reg.aliases_for(db, 'basketball', 'Besancon', 'Val De Seine', '2026-09-25T18:00'), {})


class PipelineIntegrationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.clock = Clock()
        self.gateway = FakeGateway(self.clock)
        self.p = pipeline(Path(tmp.name) / 'p.sqlite3', self.clock, instant_verification=False, final_action_enabled=True)

    def row(self, iid):
        with self.p.store.connection() as db:
            return dict(db.execute('SELECT * FROM instructions WHERE instruction_id=?', (iid,)).fetchone())

    def test_candidate_stays_unpromoted_but_exact_event_cache_is_scoped(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.p.tick(self.gateway)
        result = ready_result(iid)
        result['event_context']['kickoff_utc'] = self.gateway.submitted[0]['kickoff_utc']
        result['selection'].update(selection_name='Over', line='190.5')
        result.update(route='event_link', home='SE Melbourne Phoenix', away='Melbourne Utd',
                      event_url='https://www.bet365.com/#/AC/B18/C21167989/D19/E26735656/F19/I0/',
                      alias_candidate={'feed_home': 'SE Melbourne Phoenix', 'feed_away': 'Melbourne United', 'bet365_home': 'SE Melbourne Phoenix',
                                       'bet365_away': 'Melbourne Utd', 'verdict': 'HIGH_CONFIDENCE_EVENT_MATCH', 'confidence': 'deterministic',
                                       'candidates': {'Melbourne United': 'Melbourne Utd'}})
        self.gateway.results[iid] = result
        self.p.tick(self.gateway)
        self.assertEqual(self.row(iid)['state'], 'AWAITING_APPROVAL')
        with self.p.store.connection() as db:
            self.assertEqual(db.execute("SELECT status FROM scoped_alias_candidates WHERE source_name='melbourne united'").fetchone()[0], 'candidate')
            self.assertEqual(db.execute('SELECT bookmaker_away FROM event_cache').fetchone()[0], 'Melbourne Utd')
        self.p.final.reject(iid, 'operator')
        self.p.tick(self.gateway)
        again = self.p.ingest(message(dict(MELBOURNE, message_id="99999")))["instruction_id"]
        self.assertIsNotNone(again)
        self.p.tick(self.gateway)
        payload = [x for x in self.gateway.submitted if x['action'] == 'ADAPTER_WORKFLOW'][-1]
        self.assertEqual(json.loads(payload['aliases']), {'melbourne united': 'Melbourne Utd'})
