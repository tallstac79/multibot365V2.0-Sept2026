"""Replaces the disproven favourable-side tests. Directions read from real raw alerts."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from core.alert_classifier import classify
from core.market_interpretation import SHARP_SOURCE, sharp_signal
from core.rules_engine import evaluate
from tests.pipeline_support import ROOT, Clock, MELBOURNE, config, message, pipeline

DATA=json.loads((ROOT/'tests/fixtures/sharp_strategy_real.json').read_text(encoding='utf-8'))
ROWS={r['id']:r for r in DATA['messages']}
def parsed(mid): return classify(ROWS[mid]['text'])['parsed']
def decide(mid,cfg=None,alert=None,now=None):
    r=ROWS[mid]
    return evaluate(alert or parsed(mid),cfg or config(),instruction_id='audit-test',received_at=r['received_at'],now=now or datetime.fromisoformat(r['received_at']))

class RealSharpTargets(unittest.TestCase):
    def test_real_directions_independent_of_favourable_book_side(self):
        expected={9:'UNDER',11:'HOME',12:'AWAY',13:'AWAY',15:'UNDER',18:'AWAY',19:'OVER',20:'UNDER',21:'HOME',23:'OVER',25:'OVER',35:'HOME',37:'UNDER',38:'OVER',48:'HOME',114:'HOME',275:'OVER',341:'HOME',601:'AWAY',1081:'HOME',1223:'HOME',1317:'OVER',1325:'HOME'}
        for mid,side in expected.items():
            with self.subTest(alert=mid):
                p=parsed(mid);self.assertEqual(p['target_side'],side);self.assertEqual(p['target_price_source'],SHARP_SOURCE)
    def test_norrkoping_never_becomes_umea(self):
        p=parsed(1223)
        self.assertEqual((p['target_side'],p['target_line'],p['alert_price']),('HOME','-27.5','1.83'))
        self.assertEqual((p['comparison']['line_advantage'],p['bet_quality']),('-2.5','UNFAVOURABLE'))
        self.assertEqual(decide(1223)['decision'],'REJECT')
    def test_highlight_ev_never_migrates_to_opponent(self):
        p=parsed(1081)
        self.assertEqual((p['target_side'],p['highlighted_side'],p['feed_displayed_ev_percent']),('HOME','AWAY','107.59'))
        self.assertIsNone(p['displayed_ev_percent']);self.assertEqual(p['comparison']['ev_status'],'SUPPLIED_FOR_OTHER_SIDE')
        self.assertEqual(decide(1081)['decision'],'REJECT')
    def test_equal_line_ev_stays_bound_to_sharp_side(self):
        p=parsed(9);self.assertEqual((p['target_side'],p['highlighted_side'],p['displayed_ev_percent']),('UNDER','UNDER','109.91'))
        self.assertEqual(decide(9)['decision'],'ACCEPT')
    def test_recent_reversal_keeps_opening_baseline(self):
        p=parsed(15);self.assertEqual(p['target_side'],'UNDER');self.assertTrue(p['sharp_signal']['recent_line_reversal'])
    def test_favourite_flip_can_have_worse_offer(self):
        p=parsed(21);self.assertEqual((p['target_side'],p['bet_quality']),('HOME','UNFAVOURABLE'))
    def test_cross_book_perspective_is_ambiguous(self):
        for mid in (28,165,349,364,681):
            with self.subTest(alert=mid):
                v=classify(ROWS[mid]['text']);self.assertEqual(v['status'],'AMBIGUOUS');self.assertIsNone(v['parsed']['target_side'])
    def test_no_line_movement_not_inferred_from_book(self):
        v=classify(ROWS[46]['text']);self.assertEqual(v['status'],'AMBIGUOUS');self.assertIsNone(v['parsed']['target_side'])
    def test_numeric_ev_across_opposite_signed_lines_invalid(self):
        self.assertEqual(classify(ROWS[863]['text'])['status'],'INVALID')
    def test_unset_policy_fails_closed(self):
        d=decide(9,config(min_sharp_movement=None));self.assertEqual((d['decision'],d['reason'].split(':')[0]),('REJECT','sharp_movement'))
    def test_explicit_movement_floor(self):
        self.assertEqual(decide(9,config(min_sharp_movement=2))['decision'],'REJECT')
        self.assertEqual(decide(9,config(min_sharp_movement=1.5))['decision'],'ACCEPT')
    def test_unequal_ev_never_invented(self):
        d=decide(25);self.assertEqual(d['decision'],'ACCEPT');self.assertIsNone(d['instruction']['displayed_ev_percent'])
        self.assertEqual(d['instruction']['ev_status'],'NOT_AVAILABLE_UNEQUAL_LINES')
    def test_old_queue_payload_rejected(self):
        p=parsed(25);p['interpretation_version']='market-interp-1';p['target_price_source']='implied_favourable_line'
        self.assertEqual(decide(25,alert=p)['reason'].split(':')[0],'sharp_target')
    def test_wrong_stored_target_rejected(self):
        p=parsed(25);p['target_side']='UNDER';self.assertEqual(decide(25,alert=p)['reason'].split(':')[0],'sharp_target')
    def test_stale_signal_still_fails(self):
        now=datetime.fromisoformat(ROWS[9]['received_at'])+timedelta(days=10);self.assertEqual(decide(9,now=now)['decision'],'STALE')
    def test_real_alert_is_queued_only_once(self):
        now=datetime.fromisoformat(ROWS[25]['received_at'])
        with tempfile.TemporaryDirectory() as tmp:
            p=pipeline(Path(tmp)/'q.sqlite3',Clock(now))
            m=message(MELBOURNE,message_id='920001',text=ROWS[25]['text'])
            m.received_at=now.isoformat();m.source_timestamp=now.isoformat()
            self.assertEqual(p.ingest(m)['state'],'QUEUED');self.assertEqual(p.ingest(m)['status'],'DUPLICATE')

class AdversarialDirections(unittest.TestCase):
    def test_signed_spreads_zero_crossings(self):
        for opening,current,side in [(-4,-7,'HOME'),(-4,-1,'AWAY'),(4,1,'HOME'),(4,7,'AWAY'),(-1,2,'AWAY'),(1,-2,'HOME'),(0,-1,'HOME'),(0,1,'AWAY')]:
            with self.subTest(opening=opening,current=current):
                self.assertEqual(sharp_signal('SPREAD',opening,current,verified=True,perspective='HOME')['side'],side)
    def test_totals(self):
        for opening,current,side in [(160,165,'OVER'),(165,160,'UNDER')]:
            self.assertEqual(sharp_signal('TOTALS',opening,current,verified=True,perspective='TOTAL')['side'],side)
    def test_changed_perspective_ambiguous(self):
        for perspective in ('AWAY','AS_DISPLAYED',None):self.assertIsNone(sharp_signal('SPREAD',-4,-7,verified=True,perspective=perspective)['side'])
    def test_missing_nonfinite_moneyline_fail_closed(self):
        for market,opening,current in [('SPREAD',None,-7),('SPREAD','NaN',-7),('MONEYLINE',2,1.5)]:
            self.assertIsNone(sharp_signal(market,opening,current,verified=True,perspective='HOME')['side'])
    def test_misleading_highlight_does_not_change_target(self):
        p=classify(ROWS[25]['text'].replace('1.83 - 1.83','1.83 - **1.83**'))['parsed']
        self.assertEqual((p['target_side'],p['highlighted_side']),('OVER','UNDER'))
    def test_malformed_double_highlight_cannot_execute(self):
        for text in [ROWS[25]['text'].replace('1.83 - 1.83','**1.83** - **1.83**'),ROWS[25]['text'].replace('1.83 - 1.83','0.50 - 1.83')]:self.assertIn(classify(text)['status'],('AMBIGUOUS','INVALID'))
