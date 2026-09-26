"""Real ML examples; explicitly marked mutations cover absent/adversarial feed cases."""
import copy
from datetime import datetime
from decimal import Decimal
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from core.alert_classifier import classify
from core.execution_terms import compare, minimum_price
from core.moneyline import sharp_signal, VERSION
from core.pipeline import SourceMessage
from core.rules_engine import evaluate
from tests.pipeline_support import ROOT, Clock, FakeGateway, pipeline, ready_result
from tests.test_scaled_execution import scaled_config

ROWS={r['message_id']:r for r in json.loads((ROOT/'tests/fixtures/moneyline_real.json').read_text(encoding='utf-8'))['messages']}
def cfg():
    c=scaled_config();c['sports']['basketball']['markets']['MONEYLINE']['max_line_deterioration']=None
    return c
def parsed(mid):return classify(ROWS[mid]['text'])['parsed']
def decision(mid, p=None):
    r=ROWS[mid]
    return evaluate(p or parsed(mid),cfg(),instruction_id='ml-audit',received_at=r['received_at'],now=datetime.fromisoformat(r['received_at']))
def msg(mid):
    r=ROWS[mid]
    return SourceMessage(chat_id=r['chat_id'],message_id=mid,text=r['text'],received_at=r['received_at'],source_timestamp=r['source_timestamp'])


class MoneylineInterpretation(unittest.TestCase):
    def test_real_home_and_away_opening_current_book_mapping(self):
        for mid,side,op,current,book in [('67969','HOME','2.200','1.613','2.25'),('68122','AWAY','3.190','1.531','1.83')]:
            with self.subTest(message=mid):
                p=parsed(mid);self.assertEqual(p['interpretation_version'],VERSION)
                self.assertEqual((p['target_side'],p['alert_price']),(side,book))
                self.assertIsNone(p['target_line'])
                self.assertEqual(p['sharp_signal']['opening_prices'][side],op)
                self.assertEqual(p['sharp_signal']['current_prices'][side],current)
                for group in ('opening','pinnacle','comparison'):
                    self.assertEqual([q['side'] for q in p[group]['quotes']],['HOME','AWAY'])
                self.assertEqual(decision(mid)['decision'],'ACCEPT')

    def test_real_favourite_and_underdog_shortening(self):
        for mid,side,role in [('68111','HOME','FAVOURITE'),('68169','AWAY','FAVOURITE'),('68001','HOME','UNDERDOG'),('68122','AWAY','UNDERDOG')]:
            p=parsed(mid)
            self.assertEqual((p['target_side'],p['sharp_signal']['opening_role']),(side,role))
            self.assertGreater(Decimal(p['sharp_signal']['magnitude']),0)
            self.assertEqual(decision(mid)['decision'],'ACCEPT')

    def test_real_highlight_agrees_ev_belongs_only_to_same_side(self):
        p=parsed('67969')
        self.assertEqual((p['target_side'],p['highlighted_side'],p['displayed_ev_percent']),('HOME','HOME','127.72'))
        self.assertIsNone(p['sides'][1]['comparison']['supplied_ev'])
        self.assertEqual(p['sides'][1]['comparison']['ev_status'],'SUPPLIED_FOR_OTHER_SIDE')

    def test_real_opposing_highlight_never_changes_candidate_or_lends_ev(self):
        for mid in ('67974','68005'):
            p=parsed(mid)
            self.assertEqual((p['target_side'],p['highlighted_side']),('HOME','AWAY'))
            self.assertIsNone(p['displayed_ev_percent'])
            self.assertEqual(p['comparison']['ev_status'],'SUPPLIED_FOR_OTHER_SIDE')
            self.assertFalse(p['sharp_signal']['highlight_agrees'])
            self.assertEqual(decision(mid)['decision'],'REJECT')

    def test_real_recent_arrow_drop_with_no_net_shortening_does_not_qualify(self):
        for mid in ('69212','69215'):
            v=classify(ROWS[mid]['text'])
            self.assertEqual(v['status'],'AMBIGUOUS');self.assertIsNone(v['parsed']['target_side'])
            self.assertEqual(v['parsed']['pinnacle']['quotes'][0]['movement'],'DOWN')

    def test_real_nonselected_book_price_one_is_retained_not_used(self):
        p=parsed('68743')
        self.assertEqual((p['target_side'],p['alert_price']),('AWAY','18.00'))
        self.assertEqual(p['comparison']['quotes'][0]['price'],'1.00')
        self.assertFalse(p['comparison']['quotes'][0]['executable_price'])
        self.assertEqual(p['bet_quality'],'CLEAR_VALUE_SIGNAL')

    def test_mutated_real_pairs_equal_or_both_shortening_are_ambiguous(self):
        p=parsed('67969');opening=p['opening']['quotes']
        # No equal-opening/current record exists in this snapshot; boundary mutation is explicit.
        self.assertIsNone(sharp_signal(opening,copy.deepcopy(opening),verified=True)['side'])
        both=copy.deepcopy(opening)
        for q in both:q['price']=str(Decimal(q['price'])-Decimal('.01'))
        self.assertIsNone(sharp_signal(opening,both,verified=True)['side'])
        v=classify(ROWS['67969']['text'].replace('1.613\u2b07\ufe0f (1.719) - 2.030\u2b06\ufe0f (1.884)','2.200 - 1.510'))
        self.assertEqual(v['status'],'AMBIGUOUS');self.assertIsNone(v['parsed']['target_side'])

    def test_mutated_real_missing_reversed_or_duplicated_order_is_rejected(self):
        p=parsed('67969');opening=p['opening']['quotes'];current=p['pinnacle']['quotes']
        for broken in (opening[:1],list(reversed(opening)),[opening[0],opening[0]],None):
            self.assertIsNone(sharp_signal(broken,current,verified=True)['side'])
        self.assertIsNone(sharp_signal(opening,current,verified=False)['side'])
        for old,new in [('2.200 - 1.510','2.200 - 3.00 - 1.510'),('San Salvador vs Aguila San Miguel','San Salvador vs San Salvador'),('market=ML','market=Unknown'),('2.200 - 1.510','NaN - 1.510')]:
            v=classify(ROWS['67969']['text'].replace(old,new))
            self.assertIn(v['status'],('INVALID','AMBIGUOUS'))

    def test_mutated_real_unknown_or_opposing_ev_never_becomes_selected_ev(self):
        for text in (ROWS['67969']['text'].replace('**2.25**','2.25'),
                     ROWS['67969']['text'].replace('**2.25** - 1.57','2.25 - **1.57**')):
            p=classify(text)['parsed'];self.assertEqual(p['target_side'],'HOME')
            self.assertIsNone(p['displayed_ev_percent']);self.assertEqual(decision('67969',p)['decision'],'REJECT')
        v=classify(ROWS['67969']['text'].replace('1.57\n','**1.57**\n'))
        self.assertEqual(v['status'],'AMBIGUOUS')

    def test_corrupt_same_side_book_mapping_or_old_version_fails_closed(self):
        for kind in ('book_order','price','version','line'):
            p=parsed('67969')
            if kind=='book_order':p['comparison']['quotes'].reverse()
            if kind=='price':p['alert_price']='1.57'
            if kind=='version':p['interpretation_version']='sharp-money-1'
            if kind=='line':p['target_line']='0'
            self.assertEqual(decision('67969',p)['decision'],'REJECT')

    def test_no_second_movement_floor_or_line_policy_on_moneyline(self):
        p=parsed('68169');c=cfg();c['global']['min_sharp_movement']=10
        r=ROWS['68169'];d=evaluate(p,c,instruction_id='ml',received_at=r['received_at'],now=datetime.fromisoformat(r['received_at']))
        self.assertEqual(d['decision'],'ACCEPT');self.assertIsNone(d['instruction']['max_line_deterioration'])

    def test_live_price_boundaries_use_original_net_payout_and_no_handicap(self):
        for mid in ('67969','68122','68169'):
            p=parsed(mid);r=dict(market='MONEYLINE',side=p['target_side'],line=None,price=p['alert_price'])
            floor=minimum_price(r['price'],net_percent=10)
            for line in (None,'','NONE'):
                self.assertTrue(compare(r,dict(r,line=line,price=str(floor)),net_percent=10)['acceptable'])
                self.assertFalse(compare(r,dict(r,line=line,price=str(floor-Decimal('.01'))),net_percent=10)['acceptable'])
            self.assertTrue(compare(r,dict(r,price=str(Decimal(r['price'])+1)),net_percent=10)['acceptable'])
            self.assertFalse(compare(r,dict(r,side='AWAY' if r['side']=='HOME' else 'HOME'),net_percent=10)['acceptable'])
            self.assertFalse(compare(r,dict(r,line='0'),net_percent=10)['acceptable'])


class MoneylinePipeline(unittest.TestCase):
    def test_intake_device_payload_and_rejected_price_audit(self):
        for live,expected in [('2.13','READY'),('2.12','PRICE_CHANGED')]:
            with self.subTest(live=live),tempfile.TemporaryDirectory() as tmp:
                r=ROWS['67969'];c=Clock(datetime.fromisoformat(r['received_at']));p=pipeline(Path(tmp)/'p.db',c,cfg=cfg());g=FakeGateway(c)
                iid=p.ingest(msg('67969'))['instruction_id'];p.tick(g)
                payload=g.submitted[0]
                self.assertEqual((payload['market'],payload['side'],payload['minimum_price']),('MONEYLINE','HOME','2.13'))
                self.assertIsNone(payload['line']);self.assertNotIn('max_line_deterioration',payload)
                result=ready_result(iid,price=live)
                result['selection'].update(market='MONEYLINE',side='HOME',line='',selection_name='San Salvador')
                result['execution_observations']=[dict(stage='prepare',observed=result['selection'])]
                self.assertEqual(p.apply_result(iid,result),expected)
                with p.store.connection() as db:
                    row=p.store.get_instruction(db,iid);quote=json.loads(row['result_payload'])['execution_comparison']
                    self.assertEqual((quote['requested']['price'],quote['live']['price']),('2.25',live))
                    self.assertEqual(quote['acceptable'],expected=='READY')

    def test_ml_survives_hold_approval_without_line_or_opponent_substitution(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=ROWS['68169'];c=Clock(datetime.fromisoformat(r['received_at']));p=pipeline(Path(tmp)/'p.db',c,cfg=cfg(),final_action_enabled=True);g=FakeGateway(c)
            iid=p.ingest(msg('68169'))['instruction_id'];p.tick(g)
            with p.store.connection() as db:row=p.store.get_instruction(db,iid)
            self.assertEqual(row['state'],'AWAITING_APPROVAL')
            p.final.approve(iid[:10],'operator');p.tick(g)
            final=g.submitted[-1]
            self.assertEqual((final['action'],final['market'],final['side'],final['line']),('PLACE_HELD','MONEYLINE','AWAY',''))
            self.assertEqual(final['minimum_price'],'1.34');self.assertEqual(final['held_instruction_id'],iid)

    def test_entire_frozen_spread_totals_classification_is_unchanged(self):
        data=json.loads(gzip.decompress((ROOT/'evidence/moneyline-audit/baseline.json.gz').read_bytes()))
        tail=ROOT/'evidence/moneyline-audit/postcutoff-baseline.json'
        if tail.exists():data['rows'].extend(json.loads(tail.read_text(encoding='utf-8'))['rows'])
        checked=0
        for r in data['rows']:
            old=copy.deepcopy(r['baseline_classification'])
            if old.get('market') not in ('SPREAD','TOTALS'):continue
            new=classify(r['formatted_text'] or r['raw_text'],channel_id=str(r['chat_id']),message_id=str(r['message_id']),source_timestamp=r['source_timestamp'])
            old.pop('parser_version',None);new.pop('parser_version',None)
            self.assertEqual(new,old,r['id']);checked+=1
        self.assertGreater(checked,1000)
