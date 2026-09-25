import json
import tempfile
import unittest
from pathlib import Path
from core.execution_terms import compare
from core.bet_matching import team_present, match
from tests.pipeline_support import Clock, MELBOURNE, FakeGateway, config, message, pipeline, ready_result
from tests.test_final_action import my_bets, MELBOURNE_CARD
from tools.ocr_bench import score, GRIDS


class ExecutionHardening(unittest.TestCase):
    def test_side_specific_slippage_and_improvement(self):
        for market,side,line,live,ok in [('SPREAD','HOME','-7','-6',True),('SPREAD','AWAY','3','2',False),
                ('TOTALS','OVER','165','164',True),('TOTALS','OVER','165','166',False),
                ('TOTALS','UNDER','165','166',True),('TOTALS','UNDER','165','164',False)]:
            request=dict(market=market,side=side,line=line,price='1.83')
            self.assertEqual(compare(request,dict(request,line=live,price='1.90'),odds_tolerance=0,line_tolerance=0)['acceptable'],ok)
        r=dict(market='SPREAD',side='HOME',line='-7',price='1.83')
        self.assertTrue(compare(r,dict(r,price='1.81',line='-7.5'),odds_tolerance=.02,line_tolerance=.5)['acceptable'])
        self.assertFalse(compare(r,dict(r,price='1.80'),odds_tolerance=.02,line_tolerance=0)['acceptable'])
        self.assertFalse(compare(r,dict(r,side='AWAY'),odds_tolerance=1,line_tolerance=10)['acceptable'])
        self.assertFalse(compare(r,r,odds_tolerance=None,line_tolerance=None)['acceptable'])

    def test_reserve_women_and_age_identity_cannot_borrow_opponent_marker(self):
        for name,wrong in [('Club II','Club III'),('Club B','Club Academy'),('Team U21','Team U23'),('Beroe W','Beroe')]:
            self.assertFalse(team_present(wrong.lower(),name))
        self.assertTrue(team_present('beroe (w)','Beroe W'))

    def test_card_boundaries_and_missing_opponent(self):
        i=dict(home='SE Melbourne Phoenix',away='Melbourne United',market='TOTALS',selection='OVER',line='190.5',stake='1.00',odds='2.20')
        self.assertTrue(match(i,my_bets('x',MELBOURNE_CARD)['my_bets'])['found'])
        wrong=['£1.00 Single','Over 190.5','Melbourne United v Perth Wildcats','6/5',
               '£1.00 Single','Under 190.5','SE Melbourne Phoenix v Other Club','6/5']
        self.assertFalse(match(i,my_bets('x',wrong)['my_bets'])['found'])
        self.assertFalse(match(i,my_bets('x',MELBOURNE_CARD[1:])['my_bets'])['found'])

    def test_missing_nontarget_cell_fails_benchmark(self):
        key=next(iter(GRIDS));truth=GRIDS[key]
        fr=dict(c='grid',key=key,target=truth[0])
        ok,errors,_=score(fr,dict(parsed=dict(cells=truth[:-1])))
        self.assertFalse(ok);self.assertIn('labelled_cell_missing',errors)

    def test_changed_movement_context_is_retained_and_supersedes_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock=Clock();p=pipeline(Path(tmp)/'p.db',clock)
            first=p.ingest(message(MELBOURNE))
            raw=MELBOURNE['raw_text']
            import re
            changed=re.sub(r'Opening \(([\d.]+)\)',lambda m:'Opening ('+str(float(m[1])-1)+')',raw)
            self.assertNotEqual(changed,raw)
            second=p.ingest(message(MELBOURNE,message_id='999999',text=changed))
            self.assertEqual(second['status'],'PARSED')
            with p.store.connection() as db:
                self.assertEqual(p.store.get_instruction(db,first['instruction_id'])['state'],'STALE')

    def test_diagnostics_lease_suppresses_new_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=Clock();p=pipeline(Path(tmp)/'p.db',c);g=FakeGateway(c);g.health_extra['diagnostics_active']=True
            p.ingest(message(MELBOURNE));p.tick(g);self.assertEqual(g.submitted,[])

    def test_receipt_terms_never_fall_back_to_requested_or_legacy_fields(self):
        from core.lifecycle import State
        from tests.test_final_action import placement_result
        with tempfile.TemporaryDirectory() as tmp:
            p=pipeline(Path(tmp)/'p.db',Clock());iid=p.ingest(message(MELBOURNE))['instruction_id']
            with p.store.tx() as db:
                row=p.store.get_instruction(db,iid)
                p.final.record_outcome(db,row,State.COMPLETED,placement_result(iid))
                bet=db.execute('SELECT * FROM bets WHERE instruction_id=?',(iid,)).fetchone()
                self.assertEqual(bet['requested_odds'],row['alert_price'])
                self.assertIsNone(bet['actual_odds']);self.assertIsNone(bet['actual_stake'])
                result=placement_result(iid,actual_terms=dict(line='190.5',odds='2.25',stake='1.00'))
                p.final.record_outcome(db,row,State.COMPLETED,result)
                bet=db.execute('SELECT * FROM bets WHERE instruction_id=?',(iid,)).fetchone()
                self.assertEqual(bet['actual_odds'],'2.25');self.assertEqual(bet['requested_odds'],'2.20')
