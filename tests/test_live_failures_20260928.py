"""Codex failure review of the 27-28 Sep 2026 production run, backend side (the phone-side cases - Brujos slip OCR,
SBU initialism, Tesla glued tier letter, Goianesia slip OCR - are in LiveFailures20260928Test / CompetitionReplayTest):

  on-ca9b37ac8 / on-63771575  Goianesia v Mineiros SPREAD AWAY: the first attempt failed the pre-tap check (placement
                              NOT_TAPPED, tapped false; state PRICE_CHANGED) and the fresh alert for the same selection was
                              refused AUTO_APPROVAL_REFUSED no_duplicate_execution. A proven untapped attempt is no duplicate;
                              anything uncertain still blocks.
  on-f91b5ce9                 Shahrdari Gorgan v Sagesse SPREAD HOME: the alert's Bet365 link was an in-play page
                              (#/IP/EV...), the phone cannot open it, the run fell into Search and failed WRONG_EVENT "Search
                              event context not verified" after a full Search run. Now refused before dispatch.
Fake coordinator only: no phone, no bookmaker, no money."""
import json
import tempfile
import unittest
from pathlib import Path

from core.final_action import proven_not_placed
from tests.pipeline_support import MELBOURNE, Clock, FakeGateway, fail_result, message, pipeline, ready_result
from tests.test_final_action import placement_result

# The production placement record of on-ca9b37ac8c4393d01f700a05 (27 Sep 2026 19:26Z), verbatim.
GOIANESIA_PLACEMENT = '{"detail": "Held slip failed the pre-tap check", "outcome": "NOT_TAPPED", "tapped": false}'
IN_PLAY = MELBOURNE['raw_text'].replace('https://www.bet365.com/#/AC/B18/C21167989/D19/E26735656/F19/I0/',
                                        'https://www.bet365.com/#/IP/EV152019038265C18')


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'p.sqlite3'
        self.clock = Clock()
        self.gateway = FakeGateway(self.clock)
        self.p = pipeline(self.path, self.clock, instant_verification=False, final_action_enabled=True, approval_mode='automatic')

    def row(self, iid):
        with self.p.store.connection() as db:
            return dict(db.execute('SELECT * FROM instructions WHERE instruction_id=?', (iid,)).fetchone())

    def placed_attempts(self):
        return [x['instruction_id'] for x in self.gateway.submitted if x.get('action') == 'PLACE_HELD']

    def first_attempt(self, place_result):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.p.tick(self.gateway)
        self.gateway.results[iid] = ready_result(iid)
        self.p.tick(self.gateway)                                    # auto-approved, PLACE_HELD sent
        self.gateway.results[iid + '-place'] = place_result(iid)
        self.p.tick(self.gateway)
        return iid

    def fresh_alert(self, message_id='990001'):
        """The next alert for the same selection (a new Telegram message, same selection key)."""
        self.clock.advance(60)
        later = self.p.ingest(message(MELBOURNE, message_id=message_id, text=MELBOURNE['raw_text'].replace('EV: 113.52%', 'EV: 113.60%')))
        iid = later['instruction_id']
        self.assertIsNotNone(iid, later)
        self.assertEqual(self.row(iid)['selection_key'], self.row(self.first)['selection_key'])
        self.p.tick(self.gateway)
        self.gateway.results[iid] = ready_result(iid)
        self.p.tick(self.gateway)
        return iid


class Goianesia(Base):
    def test_the_production_placement_record_is_proof_of_no_tap(self):
        row = dict(instruction_id='on-ca9b37ac8c4393d01f700a05', state='PRICE_CHANGED', placement=GOIANESIA_PLACEMENT)
        with self.p.store.connection() as db:
            self.assertTrue(proven_not_placed(db, row))
            for uncertain in ('null', '{"tapped": true, "outcome": "NOT_TAPPED"}', '{"tapped": false}', '{"outcome": "NOT_TAPPED"}',
                              '{"tapped": null, "outcome": "PLACEMENT_UNKNOWN"}', 'not json'):
                self.assertFalse(proven_not_placed(db, dict(row, placement=uncertain)), uncertain)
            for tap_state in ('APPROVED', 'DISPATCHED', 'DEVICE_ACTIVE', 'PLACEMENT_UNKNOWN', 'COMPLETED'):
                self.assertFalse(proven_not_placed(db, dict(row, state=tap_state)), tap_state)

    def test_a_fresh_alert_after_a_proven_untapped_attempt_is_executed(self):
        def untapped(iid):
            r = fail_result(iid, 'PRICE_CHANGED', 'Current slip selection line and price unreadable')
            r['placement'] = json.loads(GOIANESIA_PLACEMENT)
            return r
        self.first = self.first_attempt(untapped)
        self.assertEqual(self.row(self.first)['state'], 'PRICE_CHANGED')
        fresh = self.fresh_alert()
        self.assertNotIn('AUTO_APPROVAL_REFUSED', self.row(fresh)['failure_reason'] or '')
        self.assertIn(fresh + '-place', self.placed_attempts())      # the one tap it is allowed

    def test_an_uncertain_attempt_still_blocks_the_same_selection(self):
        self.first = self.first_attempt(lambda iid: fail_result(iid, 'TIMEOUT', 'no answer'))          # no placement evidence
        self.assertEqual(self.row(self.first)['state'], 'PLACEMENT_UNKNOWN')
        self.clock.advance(60)
        later = self.p.ingest(message(MELBOURNE, message_id='990003', text=MELBOURNE['raw_text'].replace('EV: 113.52%', 'EV: 113.60%')))
        self.p.tick(self.gateway)
        self.assertNotIn((later['instruction_id'] or '') + '-place', self.placed_attempts())
        self.assertNotEqual(self.row(later['instruction_id'])['state'] if later['instruction_id'] else 'REJECTED', 'APPROVED')

    def test_a_placed_attempt_still_blocks_the_same_selection(self):
        self.first = self.first_attempt(placement_result)
        self.assertEqual(self.row(self.first)['state'], 'COMPLETED')
        self.clock.advance(60)
        later = self.p.ingest(message(MELBOURNE, message_id='990002', text=MELBOURNE['raw_text'].replace('EV: 113.52%', 'EV: 113.60%')))
        self.p.tick(self.gateway)
        self.assertNotIn((later['instruction_id'] or '') + '-place', self.placed_attempts())


class Shahrdari(Base):
    def test_an_in_play_link_is_refused_before_dispatch(self):
        iid = self.p.ingest(message(MELBOURNE, text=IN_PLAY))['instruction_id']
        row = self.row(iid)
        self.assertEqual(row['state'], 'REJECTED')
        self.assertTrue(row['failure_reason'].startswith('pre_match_link: '), row['failure_reason'])
        self.assertIn('#/IP/', row['failure_reason'])
        self.p.tick(self.gateway)
        self.assertEqual(self.gateway.submitted, [])                # never sent to the phone, never to Search

    def test_the_real_shahrdari_link_is_in_play_and_an_event_link_is_not(self):
        from core.football import in_play_link
        self.assertTrue(in_play_link('https://www.bet365.com/#/IP/EV152019038265C18'))
        self.assertFalse(in_play_link('https://www.bet365.com/#/AC/B18/C21172678/D19/E26837748/F19/I0/'))
        self.assertFalse(in_play_link(None))                        # no link at all: Search stays the route

    def test_the_pre_match_link_is_unchanged(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.assertNotEqual(self.row(iid)['state'], 'REJECTED')
        self.p.tick(self.gateway)
        self.assertTrue(self.gateway.submitted[0].get('event_url', '').startswith('https://www.bet365.com/#/AC/'))


if __name__ == '__main__':
    unittest.main()
