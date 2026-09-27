"""Operator 'Signal:' line (core.status_notifier._signal): price markets show the Pinnacle price movement that selected the
side, never 'opening None -> current None' (27 Sep 2026 football 1X2 Torrijos v Quintanar Del Rey)."""
import json
import unittest

from core.status_notifier import _signal

TORRIJOS_1X2 = {
    'sharp_signal': {'basis': 'price', 'side': 'AWAY', 'status': 'IDENTIFIED', 'opening_line': None, 'current_line': None,
                     'opening_prices': {'HOME': '2.310', 'AWAY': '3.060'}, 'current_prices': {'HOME': '2.950', 'DRAW': '2.850', 'AWAY': '2.490'},
                     'draw_opening_supplied': False, 'highlight_agrees': True},
    'comparison': {'bet365_price': '3.10', 'line_applicable': False, 'line_advantage': None, 'ev_status': 'SUPPLIED_EQUAL_LINE', 'supplied_ev': '115.02'},
}
BASKETBALL_SPREAD = {
    'sharp_signal': {'side': 'AWAY', 'status': 'IDENTIFIED', 'opening_line': '-7', 'current_line': '-4.5'},
    'comparison': {'line_advantage': '1.0', 'ev_status': 'NOT_AVAILABLE_UNEQUAL_LINES'},
}


class SignalMessageTests(unittest.TestCase):
    def test_football_1x2_shows_the_price_movement_that_selected_the_side(self):
        text = _signal({'normalized_alert': json.dumps(TORRIJOS_1X2)})
        self.assertNotIn('None', text)
        self.assertIn('selects AWAY', text)
        self.assertIn('AWAY 3.060 -> 2.490 (-18.6%) shortened', text)
        self.assertIn('HOME 2.310 -> 2.950 (+27.7%)', text)
        self.assertIn('DRAW 2.850 (no opening price; not a candidate)', text)
        self.assertIn('Bet365 AWAY 3.10 (bold highlight agrees)', text)
        self.assertIn('EV 115.02%', text)

    def test_same_line_price_move_names_the_line(self):
        alert = {'sharp_signal': {'side': 'HOME', 'opening_line': '-2.75', 'current_line': '-2.75', 'opening_prices': {'HOME': '1.746', 'AWAY': '1.961'},
                                  'current_prices': {'HOME': '1.628', 'AWAY': '1.980'}, 'highlight_agrees': True},
                 'comparison': {'bet365_price': '2.00', 'line_applicable': True, 'line_advantage': '0', 'ev_status': 'SUPPLIED_EQUAL_LINE', 'supplied_ev': '111.65'}}
        text = _signal({'normalized_alert': json.dumps(alert)})
        self.assertIn('line -2.75 unchanged; HOME 1.746 -> 1.628 (-6.8%) shortened', text)

    def test_line_signals_keep_their_wording(self):
        self.assertEqual(_signal({'normalized_alert': json.dumps(BASKETBALL_SPREAD)}),
                         'Pinnacle opening -7 -> current -4.5: AWAY; same-side Bet365 advantage 1.0 pts; EV NOT_AVAILABLE_UNEQUAL_LINES')


if __name__ == '__main__':
    unittest.main()
