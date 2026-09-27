"""My Bets verification uses the terms the bet was struck at (core.final_action.placed_terms): receipt first, then the
pre-tap verified terms, then the alert. Real case 27 Sep 2026: alert UNDER 165.5, receipt ST2998906111W UNDER 166.5."""
import json
import unittest
from pathlib import Path

from core import bet_matching
from core.final_action import placed_terms

MY_BETS = json.loads((Path(__file__).parent / 'fixtures/mybets_elitzur_under_166_5.json').read_text(encoding='utf-8'))
ROW = dict(home='Elitzur Ashkelon', away='Maccabi Kiryat Gat', fixture='Elitzur Ashkelon vs Maccabi Kiryat Gat', market='TOTALS',
           selection='UNDER', selection_name='Under', line='165.5', observed_price='1.83', stake='0.10')
BET = dict(line='165.5', odds='1.83', stake='0.10', requested_line='165.5', verified_line='166.5', verified_odds='1.83',
           actual_line='166.5', actual_odds='1.83', actual_stake='0.10')


class PlacedTermsTests(unittest.TestCase):
    def test_receipt_line_is_what_my_bets_must_show(self):
        self.assertEqual(placed_terms(ROW, BET)['line'], '166.5')
        found = bet_matching.match(placed_terms(ROW, BET), MY_BETS)
        self.assertTrue(found['found'])
        self.assertEqual(found['confidence'], 'EXACT')
        # the old behaviour (alert line) never finds the receipted bet
        self.assertFalse(bet_matching.match(dict(ROW, odds='1.83'), MY_BETS)['found'])

    def test_fallbacks(self):
        self.assertEqual(placed_terms(ROW, dict(BET, actual_line=None))['line'], '166.5')              # pre-tap verified
        self.assertEqual(placed_terms(ROW, dict(BET, actual_line=None, verified_line=None))['line'], '165.5')  # alert
        self.assertEqual(placed_terms(dict(ROW, market='MONEYLINE', line=None), BET).get('line'), None)  # no line market
        # a different line on the slip than on My Bets is still not a match
        self.assertFalse(bet_matching.match(placed_terms(ROW, dict(BET, actual_line='164.5')), MY_BETS)['found'])


class BookmakerNamesTests(unittest.TestCase):
    """27 Sep 2026 16:32Z on-44ef3e22: feed 'Elitzur Holon v Maccabi Ashdod', receipt LT1295027291W, My Bets
    'Elitzur Holon (W) +3.0 1.83 ... Elitzur Holon (W) v Maccabi Bnot Ashdod (W)': three checks failed on the feed names."""
    MY_BETS = json.loads((Path(__file__).parent / 'fixtures/mybets_holon_women.json').read_text(encoding='utf-8'))
    ROW = dict(home='Elitzur Holon', away='Maccabi Ashdod', market='SPREAD', selection='HOME', selection_name='Elitzur Holon', line='3',
               observed_price='1.83', stake='0.10',
               dispatch_payload=json.dumps(dict(action='PLACE_HELD', home='Elitzur Holon (W)', away='Maccabi Bnot Ashdod (W)',
                                                selection_name='Elitzur Holon (W)', line='+3.0', price='1.83')))
    BET = dict(line='3', odds='1.83', stake='0.10', verified_line='+3.0', actual_line='+3.0', actual_odds='1.83', actual_stake='0.10')

    def test_verification_uses_the_names_bet365_showed(self):
        terms = placed_terms(self.ROW, self.BET)
        self.assertEqual((terms['home'], terms['away']), ('Elitzur Holon (W)', 'Maccabi Bnot Ashdod (W)'))
        found = bet_matching.match(terms, self.MY_BETS)
        self.assertTrue(found['found'], found)
        self.assertFalse(bet_matching.match(dict(self.ROW, line='+3.0', odds='1.83'), self.MY_BETS)['found'])   # the feed names did not

    def test_absence_needs_both_namings(self):
        from core.final_action import absence_under_every_name
        terms = placed_terms(self.ROW, self.BET)
        absent, _ = absence_under_every_name(terms, '0.10', self.MY_BETS, 'OPEN')
        self.assertFalse(absent)                       # the bet is on the list: never "proven absent"


if __name__ == '__main__':
    unittest.main()
