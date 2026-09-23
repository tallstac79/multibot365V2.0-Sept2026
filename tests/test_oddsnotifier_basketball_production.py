"""Production raw fixture tests; mutations below are explicitly robustness cases."""
import json
import unittest
from pathlib import Path
from core.oddsnotifier_parser import parse_oddsnotifier, AlertFormatError, PRODUCTION_BASKETBALL_PROFILE
from core.decision_support import apply_rules, defaults

FIXTURES=Path(__file__).parent/'fixtures'

def raw(name): return (FIXTURES/f'oddsnotifier_basketball_{name}_real.txt').read_text(encoding='utf-8-sig')
def parse(text,**kwargs): return parse_oddsnotifier(text,ordering_profile=PRODUCTION_BASKETBALL_PROFILE,sample_provenance='user_reported_real',**kwargs)

class ProductionBasketballTests(unittest.TestCase):
    def test_exact_melbourne_190_5_expected_instruction(self):
        text=raw('melbourne_190_5');p=parse(text,target_position=1)
        self.assertEqual(p['raw_text'],text)
        self.assertEqual((p['fixture'],p['market'],p['target_line'],p['target_side'],p['alert_price'],p['displayed_ev_percent']),
            ('SE Melbourne Phoenix vs Melbourne United','TOTALS','190.5','OVER','2.20','113.52'))
        instruction,reason=apply_rules(p,'OVER',defaults(),'confirmed-melbourne','2026-09-23T12:00:00Z',sample=False)
        self.assertEqual(instruction['line'],'190.5');self.assertEqual(instruction['alert_price'],'2.20')
        self.assertEqual(p['opening']['line'],'187.5');self.assertTrue(p['quote_mapping']['production_verified'])
        self.assertEqual(p['target_price_source'],'user_confirmed_quote_position')
    def test_exact_rytas_expected_instruction(self):
        text=raw('rytas');p=parse(text,target_position=1)
        self.assertEqual((p['fixture'],p['market'],p['target_side'],p['target_line'],p['alert_price'],p['displayed_ev_percent']),
            ('Rytas Vilnius vs Shanghai Sharks','SPREAD','HOME','-18.5','1.83','108.47'))
        self.assertTrue(p['alternate_line']['current']);self.assertFalse(p['alternate_line']['comparison'])
        self.assertEqual(p['opening']['line'],'-17.5')
        self.assertEqual([(q['side'],q['line']) for q in p['comparison']['quotes']],[('HOME','-18.5'),('AWAY','+18.5')])
        result,_=apply_rules(p,'HOME',defaults(),'confirmed-rytas','2026-09-23T12:00:00Z',sample=False)
        self.assertEqual(result['line'],'-18.5');self.assertEqual(result['alert_price'],'1.83')
    def test_additional_raw_totals_remain_target_ambiguous(self):
        for name,line,ev in [('melbourne','190','110.69'),('prague','176','116.64')]:
            p=parse(raw(name));self.assertEqual(p['comparison']['line'],line)
            self.assertEqual(p['displayed_ev_percent'],ev);self.assertIsNone(p['target_side'])
            self.assertEqual([q['side'] for q in p['comparison']['quotes']],['OVER','UNDER'])
    def test_bold_first_and_second_prices(self):
        text=raw('melbourne_190_5')
        p=parse(text.replace('2.20 - 1.65','**2.20** - 1.65'))
        self.assertEqual((p['target_side'],p['alert_price']),('OVER','2.20'))
        p=parse(text.replace('2.20 - 1.65','2.20 - **1.65**'))
        self.assertEqual((p['target_side'],p['alert_price']),('UNDER','1.65'))
    def test_spread_away_inverts_current_comparison_not_opening(self):
        text=raw('rytas').replace('Bet365 (Spread -18.5)','Bet365 (Spread -19.5)').replace('1.83 - 1.83','1.83 - **1.83**')
        p=parse(text)
        self.assertEqual((p['target_side'],p['target_line']),('AWAY','+19.5'))
        self.assertEqual(p['opening']['quotes'][1]['line'],'+17.5')
        self.assertEqual(p['pinnacle']['quotes'][1]['line'],'+18.5')
    def test_missing_bold_never_guesses_equal_or_higher_price(self):
        for name in ('rytas','melbourne_190_5'):
            self.assertIsNone(parse(raw(name))['target_side'])
    def test_multiple_or_conflicting_target_rejected(self):
        text=raw('melbourne_190_5')
        with self.assertRaises(AlertFormatError): parse(text.replace('2.20 - 1.65','**2.20** - **1.65**'))
        with self.assertRaises(AlertFormatError): parse(text.replace('2.20 - 1.65','**2.20** - 1.65'),target_position=2)
        for position in (0,3,True,'1'):
            with self.assertRaises(AlertFormatError): parse(text,target_position=position)
    def test_moneyline_still_unverified(self):
        text=(FIXTURES/'oddsnotifier_basketball_ml.txt').read_text()
        p=parse_oddsnotifier(text)
        self.assertFalse(p['quote_mapping']['production_verified']);self.assertIsNone(p['target_side'])
        with self.assertRaises(AlertFormatError): parse(text)
    def test_wrong_counts_urls_and_markets_rejected(self):
        text=raw('melbourne_190_5')
        for bad in [text.replace('2.20 - 1.65','2.20 - 1.65 - 2.00'),text.replace('?market=Totals','?market=Spread'),
                    text.replace('Bet365 (Totals','Bet365 (Spread'),text.replace('190.5','-190.5'),text+'\nextra',text.replace('24.09.2026','31.02.2026')]:
            with self.subTest(bad=bad[-60:]),self.assertRaises(AlertFormatError): parse(bad)
    def test_observed_bold_telegram_messages(self):
        rows=json.loads((FIXTURES.parents[1]/'evidence/dashboard/telegram-basketball-observed.json').read_text(encoding='utf-8'))
        expected={'67894':('OVER','190.5','2.20','113.52'),'67895':('HOME','-18.5','1.83','108.47'),
                  '67897':('OVER','176','2.20','116.64'),'67898':('OVER','190','2.15','110.69')}
        for row in rows:
            p=parse(row['raw_text'])
            self.assertEqual((p['target_side'],p['target_line'],p['alert_price'],p['displayed_ev_percent']),expected[row['message_id']])
            self.assertEqual(p['target_price_source'],'bold_bet365_quote')

    def test_manifest_provenance_and_profile(self):
        manifest=json.loads((FIXTURES/'oddsnotifier_manifest.json').read_text())
        entries=[s for s in manifest['samples'] if s.get('profile')==PRODUCTION_BASKETBALL_PROFILE]
        self.assertEqual(len(entries),4)
        for entry in entries:
            self.assertEqual(entry['provenance'],'user_reported_real')
            p=parse((FIXTURES/entry['file']).read_text(encoding='utf-8-sig'),target_position=entry.get('target_position'))
            self.assertEqual(p['market'],entry['market'])

if __name__=='__main__':unittest.main()
