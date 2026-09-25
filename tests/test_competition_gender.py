"""Competition-aware women's marker: the backend only ever SAYS a competition is women's; the phone's resolver
decides, with corroboration, whether a feed name without "(W)" may resolve to Bet365's "(W)" team."""
import tempfile
import unittest
from pathlib import Path

from core.competition_gender import womens_competition
from tests.pipeline_support import ROOT, MELBOURNE, Clock, message, pipeline

WOMEN_ALERT = (ROOT / 'tests/fixtures/oddsnotifier_basketball_women_real.txt').read_text(encoding='utf-8')


class CompetitionGenderTests(unittest.TestCase):
    def test_explicit_women_tokens_only(self):
        for name in ('Superior Nacional Women', 'Women', 'Eurocup Qualification Women', 'WNBA', 'Liga Femenina', 'LFB', 'BSNF',
                     'Ligue Féminine', 'Frauen Bundesliga', 'NBL1 West W', 'Premier League (W)'):
            self.assertTrue(womens_competition(name), name)
        for name in ('Nationale 1', 'NBL', 'B League', 'Euroleague', 'Superior Nacional', 'Bundesliga', 'Championnat Pro B',
                     'Paulista FPB U20', None, ''):
            self.assertFalse(womens_competition(name), name)
        self.assertTrue(womens_competition(None, 'Puerto Rico - Superior Nacional Women'))

    def test_payload_carries_the_flag_only_for_a_womens_competition(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pipeline(Path(tmp) / 'w.sqlite3', Clock())
            women = p.ingest(message(MELBOURNE, message_id='930001', text=WOMEN_ALERT))
            self.assertEqual((women['status'], women['state']), ('PARSED', 'QUEUED'))
            men = p.ingest(message(MELBOURNE, message_id='930002'))
            self.assertEqual(men['state'], 'QUEUED')
            with p.store.connection() as db:
                w_row = p.store.get_instruction(db, women['instruction_id'])
                m_row = p.store.get_instruction(db, men['instruction_id'])
            self.assertEqual(w_row['competition'], 'Superior Nacional Women')
            self.assertEqual(p.build_payload(w_row).get('competition_women'), 'true')
            self.assertNotIn('competition_women', p.build_payload(m_row))


if __name__ == '__main__':
    unittest.main()
