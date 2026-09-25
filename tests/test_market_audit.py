"""Milestone A (2026-09-25) market audit regressions, on real stored alerts (tests/fixtures/unequal_line_corpus_20260925.json).

* the production rules engine CAN reject an implied target: materiality, price bounds, market/global switches, a
  highlighted worse side (the replay's REJECT = 0 was the live configuration, not an inability to reject)
* orientation guard: Pinnacle and Bet365 favouring different teams by 10+ points is AMBIGUOUS (no side implied)
* NO mirror guard: an opposite-sign spread of equal magnitude WITHOUT supplied EV is a coincidence inside a genuine
  lag run and stays eligible; WITH supplied EV it is a contradictory alert and stays INVALID
* favourite flips below 10 points stay eligible
"""
import json
import unittest
from datetime import datetime

from core import alert_classifier
from core.rules_engine import evaluate
from tests.pipeline_support import ROOT, T0, config

CORPUS = json.loads((ROOT / 'tests/fixtures/unequal_line_corpus_20260925.json').read_text(encoding='utf-8'))
BY_ID = {m['id']: m for m in CORPUS['messages']}


def alert(mid):
    return BY_ID[mid]['text']


def received(mid):
    return datetime.fromisoformat(BY_ID[mid]['received_at'].replace('Z', '+00:00'))


def decide(parsed, cfg, now):
    return evaluate(parsed, cfg, instruction_id='audit', received_at=now.isoformat(), now=now)


class RulesCanRejectImpliedTargets(unittest.TestCase):
    def setUp(self):
        self.p = alert_classifier.classify(alert(341))['parsed']     # CD Castro HOME -1.5, +3.0, implied
        self.now = received(341)
        self.assertEqual((self.p['selection_side'], self.p['comparison']['line_advantage'], self.p['target_price_source']),
                         ('HOME', '3.0', 'implied_favourable_line'))
        self.assertEqual(decide(self.p, config(), self.now)['decision'], 'ACCEPT')

    def test_materiality(self):
        d = decide(self.p, config(min_line_advantage=5), self.now)
        self.assertEqual((d['decision'], d['reason'].split(':')[0]), ('REJECT', 'line_advantage'))

    def test_price_bounds(self):
        cfg = config(); cfg['sports']['basketball']['markets']['SPREAD']['min_price'] = 1.9
        d = decide(self.p, cfg, self.now)
        self.assertEqual((d['decision'], d['reason'].split(':')[0]), ('REJECT', 'min_price'))
        cfg = config(); cfg['sports']['basketball']['markets']['SPREAD']['max_price'] = 1.5
        self.assertEqual(decide(self.p, cfg, self.now)['reason'].split(':')[0], 'max_price')

    def test_switches(self):
        cfg = config(); cfg['sports']['basketball']['markets']['SPREAD']['enabled'] = False
        self.assertEqual(decide(self.p, cfg, self.now)['reason'].split(':')[0], 'market_enabled')
        self.assertEqual(decide(self.p, config(enabled=False), self.now)['reason'].split(':')[0], 'global_enabled')

    def test_highlighted_worse_side_is_rejected_on_quality(self):
        worse = alert(341).replace('1.83 - 1.83', '1.83 - **1.83**')   # AWAY highlighted where HOME has the better line
        p = alert_classifier.classify(worse)['parsed']
        self.assertEqual((p['selection_side'], p['bet_quality']), ('AWAY', 'UNFAVOURABLE'))
        d = decide(p, config(), self.now)
        self.assertEqual((d['decision'], d['reason'].split(':')[0]), ('REJECT', 'bet_quality'))

    def test_live_configuration_explains_reject_zero(self):
        # with no price bounds, no minimum EV for line signals and an inference threshold equal to min_line_advantage,
        # the only rule outcomes for an implied target are ACCEPT or STALE (timing)
        d = decide(self.p, config(), self.now)
        self.assertEqual({c['name'] for c in d['checks'] if not c['passed']}, set())
        late = decide(self.p, config(), self.now.replace(year=self.now.year + 1))
        self.assertEqual(late['decision'], 'STALE')


class OrientationAndMirrorEvidence(unittest.TestCase):
    def test_reversed_listing_by_ten_or_more_is_ambiguous(self):
        for mid in (681, 364):
            v = alert_classifier.classify(alert(mid))
            self.assertEqual((v['status'], v['parsed']['selection_side']), ('AMBIGUOUS', None), mid)

    def test_mirror_without_ev_is_a_lag_coincidence_and_stays_eligible(self):
        # Orchies v Lyon 2026-09-25 00:06: Pinnacle home +3.5, Bet365 home -3.5. Bet365 sat at -3.5 while Pinnacle moved
        # 1 -> 4.5 across ten alerts; the phone later opened the same Bet365 event. AWAY +3.5 is 7.0 better than -3.5.
        v = alert_classifier.classify(alert(1034))
        self.assertEqual(v['status'], 'PARSED', v['reason'])
        p = v['parsed']
        self.assertEqual((p['selection_side'], p['selection_line'], p['comparison']['line_advantage']), ('AWAY', '+3.5', '7.0'))
        self.assertEqual(decide(p, config(), received(1034))['decision'], 'ACCEPT')

    def test_mirror_with_supplied_ev_is_contradictory_and_invalid(self):
        # Asian Games women: Pinnacle -26.5, Bet365 "26.5", EV supplied -> OddsNotifier compared magnitudes; the signed
        # comparison contradicts it (the Bet365 pairing is listed reversed) -> INVALID, nothing implied
        v = alert_classifier.classify(alert(863))
        self.assertEqual(v['status'], 'INVALID')
        self.assertIn('EV supplied', v['reason'])

    def test_favourite_flip_below_ten_stays_eligible(self):
        v = alert_classifier.classify(alert(1131))   # Arellano: Pinnacle -3 vs Bet365 1.5 -> HOME 1.5, +4.5
        self.assertEqual((v['status'], v['parsed']['selection_side'], v['parsed']['comparison']['line_advantage']), ('PARSED', 'HOME', '4.5'))


if __name__ == '__main__':
    unittest.main()
