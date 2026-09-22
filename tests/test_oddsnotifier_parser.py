import unittest
import json
from pathlib import Path

from core.oddsnotifier_parser import AlertFormatError, parse_oddsnotifier

SAMPLE = (Path(__file__).parent / "fixtures/oddsnotifier_spread.txt").read_text(encoding="utf-8")
META = dict(channel_id="-100123456", message_id="42", source_timestamp="2026-09-15T17:00:00Z")
FIXTURES = Path(__file__).parent / 'fixtures'


def sample(name):
    return (FIXTURES / f'oddsnotifier_{name}.txt').read_text(encoding='utf-8')


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

    def test_all_sample_provenance_and_default_unmapped(self):
        manifest = json.loads((FIXTURES / 'oddsnotifier_manifest.json').read_text())
        self.assertEqual(sum(s['provenance'] == 'synthetic' for s in manifest['samples']), 5)
        for entry in manifest['samples']:
            with self.subTest(file=entry['file']):
                text = (FIXTURES / entry['file']).read_text()
                r = parse_oddsnotifier(text, sample_provenance=entry['provenance'])
                self.assertEqual((r['sport'], r['market']), (entry['sport'], entry['market']))
                self.assertEqual(r['sample_provenance'], entry['provenance'])
                self.assertFalse(r['quote_mapping']['production_verified'])
                self.assertIsNone(r['quote_mapping']['profile'])
                for group in ['pinnacle', 'opening', 'comparison']:
                    self.assertTrue(all('side' not in q for q in r[group]['quotes']))
                self.assertIsNone(r['target_side'])

    def test_explicit_football_three_way_mapping(self):
        r = parse_oddsnotifier(sample('football_ml'), ordering_profile='synthetic_order_v1')
        self.assertEqual(r['market'], '1X2')
        expected = [('HOME', '1.420'), ('DRAW', '5.200'), ('AWAY', '8.100')]
        self.assertEqual([(q['side'], q['price']) for q in r['pinnacle']['quotes']], expected)
        self.assertEqual([(q['side'], q['price']) for q in r['comparison']['quotes']],
                         [('HOME', '1.40'), ('DRAW', '5.00'), ('AWAY', '8.00')])
        self.assertEqual([(q['side'], q['price']) for q in r['opening']['quotes']],
                         [('HOME', '1.500'), ('DRAW', '4.800'), ('AWAY', '7.500')])
        self.assertIsNone(r['displayed_line'])
        self.assertIsNone(r['target_side'])

    def test_explicit_basketball_two_way_mapping(self):
        r = parse_oddsnotifier(sample('basketball_ml'), ordering_profile='synthetic_order_v1')
        self.assertEqual(r['market'], 'MONEYLINE')
        self.assertEqual([(q['side'], q['price']) for q in r['pinnacle']['quotes']],
                         [('HOME', '1.620'), ('AWAY', '2.380')])
        self.assertEqual(r['quote_mapping']['sides_by_position'], ['HOME', 'AWAY'])
        self.assertFalse(r['quote_mapping']['production_verified'])

    def test_explicit_total_order_for_both_sports(self):
        for name, line, prices in [('football_total', '2.5', ['1.820', '2.080']),
                                   ('basketball_total', '224.5', ['1.850', '2.050'])]:
            with self.subTest(name=name):
                r = parse_oddsnotifier(sample(name), ordering_profile='synthetic_order_v1')
                self.assertEqual(r['displayed_line'], line)
                self.assertEqual([(q['side'], q['price']) for q in r['pinnacle']['quotes']],
                                 list(zip(['OVER', 'UNDER'], prices)))
                for group in ['opening', 'comparison']:
                    self.assertEqual([q['side'] for q in r[group]['quotes']], ['OVER', 'UNDER'])
                self.assertIn('quote_mapping_is_unverified_assumption', r['unresolved'])

    def test_explicit_spread_order_no_line_inversion(self):
        for name, line in [('spread', '-0.75'), ('basketball_spread', '-4.5')]:
            r = parse_oddsnotifier(sample(name), ordering_profile='synthetic_order_v1')
            self.assertEqual([q['side'] for q in r['pinnacle']['quotes']], ['HOME', 'AWAY'])
            self.assertEqual(r['displayed_line'], line)
            self.assertIsNone(r['target_line'])
            self.assertTrue(all('line' not in q for q in r['pinnacle']['quotes']))

    def test_wrong_counts_for_every_quote_group(self):
        for name in ['football_ml', 'basketball_ml', 'football_total', 'basketball_spread']:
            for row_index in [5, 7, 9]:
                rows = [r for r in sample(name).splitlines() if r]
                cells = rows[row_index].split(' - ')
                for changed in [cells[:-1], cells + ['3.000']]:
                    with self.subTest(name=name, row=row_index, count=len(changed)):
                        corrupt = rows.copy()
                        corrupt[row_index] = ' - '.join(changed)
                        with self.assertRaises(AlertFormatError):
                            parse_oddsnotifier('\n'.join(corrupt))

    def test_inconsistent_market_headers(self):
        for before, after in [('Bet365 (Total 2.5)', 'Bet365 (Spread 2.5)'),
                              ('Opening (2.5)', 'Opening'), ('Total (2.5)', 'Total')]:
            with self.subTest(before=before), self.assertRaises(AlertFormatError):
                parse_oddsnotifier(sample('football_total').replace(before, after))

    def test_unknown_mapping_never_falls_back(self):
        for profile in ['production', 'HOME/AWAY', '', True]:
            with self.subTest(profile=profile), self.assertRaises(AlertFormatError):
                parse_oddsnotifier(SAMPLE, ordering_profile=profile)

    def test_invalid_provenance(self):
        with self.assertRaises(AlertFormatError):
            parse_oddsnotifier(SAMPLE, sample_provenance='verified_live')

    def test_parenthetical_uniformity(self):
        with self.assertRaises(AlertFormatError):
            parse_oddsnotifier(SAMPLE.replace(' (1.884)', ''))
        r = parse_oddsnotifier(sample('basketball_spread'))
        self.assertNotIn('parenthetical_price_meaning_unspecified', r['unresolved'])

    def test_negative_total_rejected(self):
        with self.assertRaises(AlertFormatError):
            parse_oddsnotifier(sample('football_total').replace('2.5', '-2.5'))

    def test_pricing_does_not_choose_side(self):
        for ev in ['0.00', '111.47', '999.99']:
            r = parse_oddsnotifier(SAMPLE.replace('111.47', ev), ordering_profile='synthetic_order_v1')
            self.assertIsNone(r['target_side'])
            self.assertIsNone(r['alert_price'])


if __name__ == '__main__':
    unittest.main()
