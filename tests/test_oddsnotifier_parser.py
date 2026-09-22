import unittest
from pathlib import Path

from core.oddsnotifier_parser import AlertFormatError, parse_oddsnotifier

SAMPLE = (Path(__file__).parent / "fixtures/oddsnotifier_spread.txt").read_text(encoding="utf-8")
META = dict(channel_id="-100123456", message_id="42", source_timestamp="2026-09-15T17:00:00Z")


class ParserTests(unittest.TestCase):
    def test_supplied_sample(self):
        r = parse_oddsnotifier(SAMPLE)
        self.assertEqual((r['sport'], r['country'], r['competition']),
                         ('football', 'England', 'Isthmian Premier League'))
        self.assertEqual((r['home'], r['away']), ('Welling United', 'Cheshunt'))
        self.assertEqual(r['scheduled_at_local'], '2026-09-15T18:45')
        self.assertEqual(r['displayed_line'], '-0.75')
        self.assertEqual(r['pinnacle']['quotes'], [
            dict(position=1, price='2.160', parenthetical_price='1.900'),
            dict(position=2, price='1.662', parenthetical_price='1.884')])
        self.assertEqual([q['price'] for q in r['opening']['quotes']], ['2.000', '1.714'])
        self.assertEqual([q['price'] for q in r['comparison']['quotes']], ['1.85', '1.95'])
        self.assertEqual(r['comparison']['site'], 'Bet365')
        self.assertEqual(r['displayed_ev_percent'], '111.47')
        self.assertEqual(r['raw_text'], SAMPLE)

    def test_no_invented_selection_or_metadata(self):
        r = parse_oddsnotifier(SAMPLE)
        for field in ['target_side', 'target_line', 'alert_price', 'observation_id',
                      'telegram_message_id', 'source_timestamp', 'scheduled_timezone']:
            self.assertIsNone(r[field])

    def test_message_identity_stable_across_edits(self):
        first = parse_oddsnotifier(SAMPLE, **META)
        edited = parse_oddsnotifier(SAMPLE.replace('111.47', '110.00'), **META)
        self.assertEqual(first['observation_id'], edited['observation_id'])
        self.assertEqual(first['source_timestamp'], META['source_timestamp'])
        self.assertEqual(first['telegram_message_id'], '42')

    def test_channel_scoped_identity(self):
        a = parse_oddsnotifier(SAMPLE, **META)['observation_id']
        b = parse_oddsnotifier(SAMPLE, **dict(META, channel_id='-100999'))['observation_id']
        c = parse_oddsnotifier(SAMPLE, **dict(META, message_id='43'))['observation_id']
        self.assertEqual(len({a, b, c}), 3)

    def test_metadata_validation(self):
        for changes in [dict(message_id='0'), dict(message_id=True), dict(channel_id=''),
                        dict(source_timestamp='2026-09-15T17:00:00'), dict(source_timestamp='bad')]:
            with self.subTest(changes=changes), self.assertRaises(AlertFormatError):
                parse_oddsnotifier(SAMPLE, **dict(META, **changes))

    def test_unrelated(self):
        for value in ['', 'hello', 'Football results today']:
            self.assertIsNone(parse_oddsnotifier(value))

    def test_malformed_or_ambiguous(self):
        replacements = [('Spread (-0.75)', 'Spread'), ('2.160', 'NaN'),
                        ('2.160', '1.000'), ('1.85 - 1.95', '1.85 - 1.95 - 2.00'),
                        ('Welling United vs Cheshunt', 'One vs Two vs Three'),
                        ('Welling United vs Cheshunt', 'Same vs Same'),
                        ('15.09.2026', '31.02.2026'), ('EV: 111.47%', 'EV: unknown')]
        for before, after in replacements:
            with self.subTest(before=before), self.assertRaises(AlertFormatError):
                parse_oddsnotifier(SAMPLE.replace(before, after))

    def test_no_neighbor_line_substitution(self):
        r = parse_oddsnotifier(SAMPLE.replace('Bet365 (Spread -0.75)', 'Bet365 (Spread -1.0)'))
        self.assertEqual(r['pinnacle']['line'], '-0.75')
        self.assertEqual(r['comparison']['line'], '-1.0')
        self.assertIsNone(r['target_line'])

    def test_extra_content_rejected(self):
        for value in [SAMPLE + '\nEV: 120%', SAMPLE + SAMPLE, SAMPLE.rsplit('EV:', 1)[0]]:
            with self.assertRaises(AlertFormatError):
                parse_oddsnotifier(value)

    def test_unseen_market_rejected(self):
        for market in ['1X2', 'Moneyline', 'Totals', 'Asian Handicap']:
            with self.subTest(market=market), self.assertRaises(AlertFormatError):
                parse_oddsnotifier(SAMPLE.replace('Spread', market))

    def test_layout_and_generated_names(self):
        for home, away in [('Cedar Town', 'Maple City'), ('Harbor Youth', 'River Youth')]:
            text = SAMPLE.replace('Welling United', home).replace('Cheshunt', away)
            r = parse_oddsnotifier(text.replace('\n', '\r\n'))
            self.assertEqual((r['home'], r['away']), (home, away))

    def test_input_bound(self):
        for value in [None, b'hello', 'x' * 32769]:
            with self.assertRaises(AlertFormatError):
                parse_oddsnotifier(value)


if __name__ == '__main__':
    unittest.main()
