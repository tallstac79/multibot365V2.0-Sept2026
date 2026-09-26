"""Operator policy examples and rejected-quote persistence; no phone/network calls."""
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from core.decision_support import validate
from core.execution_terms import compare, minimum_price, line_allowance, comparisons_for_result
from tests.pipeline_support import Clock, FakeGateway, RYTAS, config, message, pipeline, fail_result, ready_result


def scaled_config():
    cfg = config(min_sharp_movement=None)
    for rule in cfg['sports']['basketball']['markets'].values():
        rule.update(max_odds_deterioration=None, max_net_payout_deterioration_percent=10)
    cfg['sports']['basketball']['markets']['SPREAD'].update(max_line_deterioration=1, max_line_deterioration_percent=10)
    cfg['sports']['basketball']['markets']['TOTALS']['max_line_deterioration'] = None
    return cfg


class ScaledExecutionTests(unittest.TestCase):
    def test_net_payout_floor_rounds_up_never_decimal_percentage(self):
        for odds, expected in [('1.83','1.75'),('2.15','2.04'),('1.01','1.01'),('3.00','2.80')]:
            self.assertEqual(minimum_price(odds, net_percent=10), Decimal(expected))
        self.assertEqual(minimum_price('1.83', net_percent=0), Decimal('1.83'))
        for bad in (None, 'NaN', -1, 101, 'Infinity'):
            with self.assertRaises((ValueError, ArithmeticError)):
                minimum_price('1.83', net_percent=bad)
        r=dict(market='SPREAD',side='HOME',line='-15.5',price='1.83')
        self.assertTrue(compare(r,dict(r,price='1.75'),net_percent=10,line_tolerance=1,line_percent=10)['acceptable'])
        self.assertFalse(compare(r,dict(r,price='1.74'),net_percent=10,line_tolerance=1,line_percent=10)['acceptable'])

    def test_operator_spread_examples_both_sides_and_signs(self):
        for side in ('HOME','AWAY'):
            for sign in (1,-1):
                for magnitude, expected in [('25.5',True),('15.5',True),('10.5',True),('5.5',False),('1.5',False)]:
                    line = sign*Decimal(magnitude)
                    r=dict(market='SPREAD',side=side,line=str(line),price='1.83')
                    with self.subTest(side=side,line=line):
                        q=compare(r,dict(r,line=str(line-1),price='1.75'),net_percent=10,line_tolerance=1,line_percent=10)
                        self.assertEqual(q['acceptable'],expected)
                        self.assertTrue(compare(r,dict(r,line=str(line+2),price='2.10'),net_percent=10,line_tolerance=1,line_percent=10)['acceptable'])
        self.assertEqual(line_allowance('SPREAD','-5.5',1,10),Decimal('.55'))
        self.assertEqual(line_allowance('SPREAD','0',1,10),0)
        r=dict(market='SPREAD',side='AWAY',line='.5',price='1.83')
        self.assertFalse(compare(r,dict(r,line='-.5'),net_percent=10,line_tolerance=1,line_percent=10)['acceptable'])

    def test_totals_are_absolute_and_remain_unset(self):
        r=dict(market='TOTALS',side='OVER',line='165.5',price='1.83')
        self.assertFalse(compare(r,r,net_percent=10,line_tolerance=None)['acceptable'])
        for side,live,ok in [('OVER','166',True),('OVER','166.5',False),('UNDER','165',True),('UNDER','164.5',False),('OVER','160',True),('UNDER','170',True)]:
            req=dict(r,side=side)
            self.assertEqual(compare(req,dict(req,line=live),net_percent=10,line_tolerance=.5)['acceptable'],ok)
        with self.assertRaises(ValueError): line_allowance('TOTALS','165.5',1,10)
        validate(scaled_config())
        cfg=scaled_config();cfg['sports']['basketball']['markets']['TOTALS'].update(max_line_deterioration=1,max_line_deterioration_percent=10)
        with self.assertRaises(ValueError): validate(cfg)
        cfg=scaled_config();cfg['sports']['basketball']['markets']['SPREAD']['max_odds_deterioration']=.1
        with self.assertRaises(ValueError): validate(cfg)

    def test_multiread_limits_never_compound_or_borrow_previous_quote(self):
        r=dict(market='SPREAD',side='HOME',line='-10.5',price='1.83')
        policy=dict(max_net_payout_deterioration_percent=10,max_line_deterioration='1')
        result=dict(status='FAIL',detail='too much movement',execution_observations=[
            dict(stage='grid',observed=dict(r,line='-11',price='1.79')),
            dict(stage='pretap',observed=dict(r,line='-12',price='1.71'))])
        qs=comparisons_for_result(r,result,policy)
        self.assertTrue(qs[0]['acceptable']);self.assertFalse(qs[1]['acceptable'])
        self.assertEqual(qs[1]['requested'],r)
        result['execution_observations'].append(dict(stage='pretap',observed=None))
        q=comparisons_for_result(r,result,policy)[-1]
        self.assertIsNone(q['live']);self.assertFalse(q['acceptable'])
        result['execution_observations'].append(dict(stage='pretap', observed=dict(r,market=None)))
        self.assertFalse(comparisons_for_result(r,result,policy)[-1]['acceptable'])

    def test_rules_bind_original_minimum_and_effective_line_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=pipeline(Path(tmp)/'p.db',Clock(),cfg=scaled_config())
            iid=p.ingest(message(RYTAS))['instruction_id']
            with p.store.connection() as db:
                row=p.store.get_instruction(db,iid)
                self.assertEqual(row['state'],'QUEUED')
                policy=json.loads(row['rules_result'])['instruction']
                self.assertEqual(policy['minimum_price'],'1.75')
                self.assertEqual(policy['max_line_deterioration'],'1')
                payload=p.build_payload(row)
                self.assertEqual(payload['minimum_price'],'1.75')
                self.assertEqual(payload['max_line_deterioration'],'1')

    def test_failures_persist_requested_and_observed_or_unknown(self):
        for stage in ('grid','pretap','unreadable'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as tmp:
                c=Clock();p=pipeline(Path(tmp)/'p.db',c,cfg=scaled_config());g=FakeGateway(c)
                iid=p.ingest(message(RYTAS))['instruction_id'];p.tick(g)
                result=fail_result(iid,'BELOW_MINIMUM')
                observed=None if stage=='unreadable' else dict(market='SPREAD',side='HOME',line='-20.5',price='1.60')
                result['execution_observations']=[dict(stage=stage,observed=observed)]
                p.apply_result(iid,result)
                with p.store.connection() as db:
                    row=p.store.get_instruction(db,iid)
                    stored=json.loads(row['result_payload'])['execution_comparison']
                    self.assertEqual(stored['requested']['price'],'1.83')
                    self.assertEqual(stored['live'],observed)
                    self.assertEqual(stored['stage'],stage)
                    self.assertFalse(stored['acceptable'])
                    self.assertGreater(db.execute("SELECT COUNT(*) FROM audit_events WHERE kind='ALERT_TO_LIVE_COMPARISON' AND instruction_id=?",(iid,)).fetchone()[0],0)

    def test_ready_accepts_within_tolerance_latest_terms(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=Clock();p=pipeline(Path(tmp)/'p.db',c,cfg=scaled_config());g=FakeGateway(c)
            iid=p.ingest(message(RYTAS))['instruction_id'];p.tick(g)
            with p.store.connection() as db: row=dict(p.store.get_instruction(db,iid))
            result=ready_result(iid,price='1.75')
            result['selection'].update(market='SPREAD',side=row['selection'],line=str(Decimal(row['line'])-1))
            result['execution_observations']=[dict(stage='prepare',observed=result['selection'],identity_verified=True)]
            self.assertEqual(p.apply_result(iid,result),'READY')

    def test_rules_rejection_keeps_requested_terms_with_unknown_live(self):
        from tests.pipeline_support import MELBOURNE
        with tempfile.TemporaryDirectory() as tmp:
            p=pipeline(Path(tmp)/'p.db',Clock(),cfg=scaled_config())
            iid=p.ingest(message(MELBOURNE))['instruction_id']
            with p.store.connection() as db:
                row=p.store.get_instruction(db,iid);self.assertEqual(row['state'],'REJECTED')
                audit=db.execute("SELECT detail FROM audit_events WHERE kind='ALERT_TO_LIVE_COMPARISON' AND instruction_id=?",(iid,)).fetchone()
                q=json.loads(audit[0]);self.assertIsNone(q['live']);self.assertEqual(q['requested']['price'],'2.20')
