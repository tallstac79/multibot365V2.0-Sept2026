"""Real-alert policy rejection and conservative cross-book orientation regressions.

Target direction is determined by Pinnacle opening-to-current movement.
These replace the former favourable-side and arbitrary 10-point perspective assumptions.
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


class RulesCanRejectSharpTargets(unittest.TestCase):
    def setUp(self):
        self.p = alert_classifier.classify(alert(341))['parsed']     # CD Castro HOME -1.5, +3.0, sharp HOME
        self.now = received(341)
        self.assertEqual((self.p['selection_side'], self.p['comparison']['line_advantage'], self.p['target_price_source']),
                         ('HOME', '3.0', 'pinnacle_opening_to_current'))
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

    def test_highlight_never_changes_net_target(self):
        worse = alert(341).replace('1.83 - 1.83', '1.83 - **1.83**')
        p = alert_classifier.classify(worse)['parsed']
        self.assertEqual((p['selection_side'], p['highlighted_side']), ('HOME', 'AWAY'))
        self.assertEqual(decide(p, config(), self.now)['decision'], 'ACCEPT')

    def test_explicit_test_policy_allows_favourable_sharp_offer(self):
        # Explicit test movement policy and inherited line floor pass; later replay is stale.
        d = decide(self.p, config(), self.now)
        self.assertEqual({c['name'] for c in d['checks'] if not c['passed']}, set())
        late = decide(self.p, config(), self.now.replace(year=self.now.year + 1))
        self.assertEqual(late['decision'], 'STALE')


class OrientationAndMirrorEvidence(unittest.TestCase):
    def test_large_cross_book_disagreement_is_ambiguous(self):
        for mid in (681, 364):
            v = alert_classifier.classify(alert(mid))
            self.assertEqual((v['status'], v['parsed']['selection_side']), ('AMBIGUOUS', None), mid)

    def test_mirror_without_ev_requires_orientation(self):
        v = alert_classifier.classify(alert(1034))
        self.assertEqual(v['status'], 'AMBIGUOUS')
        self.assertIsNone(v['parsed']['target_side'])

    def test_mirror_with_supplied_ev_is_contradictory_and_invalid(self):
        # Asian Games women: Pinnacle -26.5, Bet365 "26.5", EV supplied -> OddsNotifier compared magnitudes; the signed
        # comparison contradicts it (the Bet365 pairing may be reversed) -> INVALID, no executable target
        v = alert_classifier.classify(alert(863))
        self.assertEqual(v['status'], 'INVALID')
        self.assertIn('EV supplied', v['reason'])

    def test_small_cross_book_flip_requires_orientation(self):
        v = alert_classifier.classify(alert(1131))
        self.assertEqual(v['status'], 'AMBIGUOUS')
        self.assertIsNone(v['parsed']['target_side'])


if __name__ == '__main__':
    unittest.main()
