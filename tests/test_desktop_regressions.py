"""Desktop worker regressions from the supervised Place Bet-ready batches (evidence/desktop-worker-placebet-ready/, 28 Sep
2026), offline: no browser, no network, nothing clicked on Bet365.

- proof-04 / proof-12 (Turkiye v Italy, 1X2 DRAW): the phone's header folding gave the event's teams as 'Turkiye' while
  the Full Time Result row shows 'Türkiye', so the 1X2 (and Asian Handicap) rows were never matched: TARGET_NOT_FOUND.
- final-11 (Sweden v Poland, AH HOME 0.0): the expanded Alternative Asian Handicap was read while the groups below it
  had not moved down yet, so its rows were filed under 'Alternative Goal Line' / '1st Half ...' and the worker failed
  LINE_CHANGED ("shows -0.5 @ 1.900").
- Reality Check: fail closed (SESSION_EXPIRED, never answered) and an operator notice on the result, /health and the
  dashboard's log tail.
The page fixtures are rebuilt from the captured text layouts (sNNN_*.txt), the Reality Check page from the live re-check
(runs/recheck-01-tur-1x2-draw/s001_reality_check.txt).
"""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from desktop_worker import bet365_page as bp
from desktop_worker import workflow as wf

FIX = Path(__file__).parent / 'fixtures' / 'desktop'


def words(name):
    return json.loads((FIX / f'{name}.json').read_text(encoding='utf-8'))['words']


def bridge():
    try:
        from desktop_worker.decisions import Decisions
        return Decisions()
    except Exception as e:                          # no JDK / Android SDK on this machine
        raise unittest.SkipTest(f'decision bridge unavailable: {e}')


class FakePage:
    """Serves captured layouts to the worker's own layout read (layout.read_words -> page.evaluate) and records every
    input the worker sends. Nothing here is Bet365."""

    def __init__(self, reads):
        self.reads, self.clicks, self.url = list(reads), [], 'https://www.bet365.com/#/AC/B1/C1/D8/E201150132/F3/I1/'

    async def evaluate(self, script, arg=None):
        return self.reads.pop(0) if len(self.reads) > 1 else self.reads[0]

    async def wait_for_timeout(self, ms):
        pass

    async def goto(self, url, **kw):
        pass

    async def reload(self, **kw):
        pass

    async def screenshot(self, path=None, **kw):
        Path(path).write_bytes(b'')

    def get_by_text(self, text, exact=False):
        page = self

        class Cell:
            @property
            def first(self):
                return self

            async def click(self):
                page.clicks.append(text)
        return Cell()


class Isolated(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        for name, value in (('EVIDENCE', self.tmp / 'evidence'), ('OPERATOR_LOG', self.tmp / 'logs' / 'desktop_worker.log')):
            patcher = mock.patch.object(wf, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_of(self, iid='reg-1'):
        return wf.Run(dict(instruction_id=iid), lambda progress, run_id: None)


class AccentedTeamNames(unittest.TestCase):
    """proof-12-tur-1x2-draw: header 'Türkiye v Italy', the phone's teams ('Turkiye', 'Italy')."""

    @classmethod
    def setUpClass(cls):
        cls.d = bridge()

    @classmethod
    def tearDownClass(cls):
        cls.d.close()

    def test_the_phone_folds_the_header_team(self):
        self.assertEqual(self.d.call('teams', bp.header(words('football_tur_ita_popular'))), ['Turkiye', 'Italy'])

    def test_turkiye_italy_full_time_result_is_found(self):
        home, away = self.d.call('teams', bp.header(words('football_tur_ita_popular')))
        q = {x['side']: x for x in bp.football_quotes(words('football_tur_ita_popular'), home, away, self.d.norm_line)
             if x['market'] == 'MONEYLINE'}
        self.assertEqual(sorted(q), ['AWAY', 'DRAW', 'HOME'])          # was []: TARGET_NOT_FOUND for MONEYLINE/DRAW
        self.assertEqual(q['HOME']['name'], 'Türkiye')                  # the page's own label, as before
        self.assertEqual(q['DRAW']['group'], 'Full Time Result')
        self.assertTrue(all(x['price'] for x in q.values()))

    def test_asian_handicap_header_with_accented_names(self):
        # Asian Lines layout captured for Sweden v Poland (final-11 s006), team labels respelled with accents: the AH
        # columns are matched the same way (no Türkiye Asian Lines page was captured).
        page = [dict(w, text={'Sweden': 'Türkiye', 'Poland': 'Italiä'}.get(w['text'], w['text'])) for w in words('football_swe_pol_asian_lines')]
        q = [(x['market'], x['side'], x['line'], x['name']) for x in bp.football_quotes(page, 'Turkiye', 'Italia', self.d.norm_line)
             if x['market'] == 'SPREAD']
        self.assertEqual(q, [('SPREAD', 'HOME', '-0.5', 'Turkiye'), ('SPREAD', 'AWAY', '+0.5', 'Italia')])

    def test_other_names_are_still_refused(self):
        page = words('football_tur_ita_popular')
        self.assertEqual([x for x in bp.football_quotes(page, 'Tunisia', 'Italy', self.d.norm_line) if x['market'] == 'MONEYLINE'], [])
        self.assertEqual([x for x in bp.football_quotes(page, 'Turkiye', 'Italia', self.d.norm_line) if x['market'] == 'MONEYLINE'], [])


class FoldName(unittest.TestCase):
    def test_folding_matches_the_phone_rule_on_both_sides(self):
        self.assertEqual(bp.fold_name('Türkiye'), 'Turkiye')
        self.assertEqual(bp.fold_name('Bodø/Glimt'), 'Bodo/Glimt')
        self.assertTrue(bp.same_team('Türkiye', 'Turkiye'))
        self.assertTrue(bp.same_team('Türkiye', 'Türkiye'))
        self.assertTrue(bp.same_team('Turkiye', 'Türkiye'))
        self.assertFalse(bp.same_team('Türkiye', 'Tunisia'))
        self.assertFalse(bp.same_team('Italy', 'Italy II'))
        self.assertFalse(bp.same_team('', '?'))


class AlternativeAsianHandicapSettle(Isolated):
    """final-11-swe-ah-home-0: s007 (read mid-layout) vs final-01 s004 (the same group settled)."""

    @classmethod
    def setUpClass(cls):
        cls.d = bridge()

    @classmethod
    def tearDownClass(cls):
        cls.d.close()

    def spread_home(self, page):
        return [(x['group'], x['line'], x['price']) for x in bp.football_quotes(page, 'Sweden', 'Poland', self.d.norm_line)
                if x['market'] == 'SPREAD' and x['side'] == 'HOME']

    def test_the_captured_mid_layout_read_loses_the_group(self):
        # the failure as captured: only the main line is read, the alternative 0.0 row is filed under other titles
        self.assertEqual(self.spread_home(words('football_swe_pol_alt_ah_unsettled')), [('Asian Handicap', '-0.5', '1.900')])
        self.assertNotEqual(bp.layout_signature(words('football_swe_pol_alt_ah_unsettled')),
                            bp.layout_signature(words('football_swe_pol_alt_ah_settled')))

    def test_expand_waits_for_two_agreeing_reads(self):
        unsettled, settled = words('football_swe_pol_alt_ah_unsettled'), words('football_swe_pol_alt_ah_settled')
        page = FakePage([unsettled, unsettled, settled, settled])     # rows-rendered check, then the settle reads
        run = self.run_of()
        got = asyncio.run(wf.DesktopBet365(page, self.d).expand(run, words('football_swe_pol_asian_lines'), ('Alternative Asian Handicap',)))
        self.assertIn(('Alternative Asian Handicap', '0.0', '1.450'), self.spread_home(got))
        self.assertEqual(run.record['expand_settle'], dict(group='Alternative Asian Handicap', reads=3))
        self.assertEqual(page.clicks, ['Alternative Asian Handicap'])  # only the group title; nothing else pressed

    def test_price_ticks_do_not_count_as_layout(self):
        settled = words('football_swe_pol_alt_ah_settled')
        ticked = [dict(w, text='9.999') if w['text'] == '1.450' else w for w in settled]
        self.assertEqual(bp.layout_signature(settled), bp.layout_signature(ticked))

    def test_a_layout_that_never_settles_fails_closed(self):
        unsettled, settled = words('football_swe_pol_alt_ah_unsettled'), words('football_swe_pol_alt_ah_settled')
        page = FakePage([unsettled] + [unsettled, settled] * 20)
        with self.assertRaises(wf.Failure) as c:
            asyncio.run(wf.DesktopBet365(page, self.d).expand(self.run_of(), words('football_swe_pol_asian_lines'), ('Alternative Asian Handicap',)))
        self.assertEqual(c.exception.stage, 'EVENT_NOT_VERIFIED')
        self.assertIn('layout still changing', c.exception.detail)


REALITY_CHECK = words('football_reality_check')      # recheck-01 s001: the live dialog, 28 Sep 2026 16:38 BST


class RealityCheck(Isolated):
    def test_event_page_reality_check_fails_closed_and_notifies(self):
        self.assertTrue(wf._reality_check(REALITY_CHECK))
        page = FakePage([REALITY_CHECK])
        run = self.run_of('reg-rc')
        with self.assertRaises(wf.Failure) as c:
            asyncio.run(wf.DesktopBet365(page, decisions=None).open_event(run, page.url))
        self.assertEqual(c.exception.stage, 'SESSION_EXPIRED')
        self.assertEqual(page.clicks, [])                              # 'Remain Logged In' is never clicked
        alert = run.record['operator_alert']
        self.assertEqual((alert['code'], alert['stage'], alert['instruction_id']), ('REALITY_CHECK_OPEN', 'SESSION_EXPIRED', 'reg-rc'))
        self.assertTrue(alert['message'].startswith('Bet365 Reality Check is open; answer it on the mini PC to continue'))
        self.assertIn(alert['at'].replace('T', ' '), alert['message'])  # timestamped (local time with offset)
        self.assertIn('answer it on the mini PC', c.exception.detail)
        result = run.finish('FAIL', c.exception.stage, c.exception.detail)
        self.assertEqual(result['operator_alert'], alert)
        self.assertIs(result['wager_submitted'], False)
        line = json.loads((self.tmp / 'logs' / 'desktop_worker.log').read_text(encoding='utf-8').splitlines()[-1])
        self.assertEqual((line['component'], line['severity'], line['instruction_id'], line['message']),
                         ('desktop_worker', 'ERROR', 'reg-rc', alert['message']))

    def test_slip_screenshot_reality_check_fails_closed_and_notifies(self):
        run = self.run_of('reg-rc-slip')
        with mock.patch.object(wf.vs, 'screenshot', mock.AsyncMock(return_value=(None, b''))), \
                mock.patch.object(wf.vs, 'read_slip', return_value=dict(present=False, words=[])), \
                mock.patch.object(wf.vs, 'reality_check', return_value=True):
            with self.assertRaises(wf.Failure) as c:
                asyncio.run(wf.DesktopBet365(FakePage([[]]), decisions=None).look(run, 'slip_check'))
        self.assertEqual(c.exception.stage, 'SESSION_EXPIRED')
        self.assertEqual(run.record['operator_alert']['code'], 'REALITY_CHECK_OPEN')

    def test_the_dashboard_log_tail_shows_it(self):
        run = self.run_of('reg-rc-dash')
        wf.reality_check_failure(run, 'dialog open')
        from dashboard.adapters import application_logs

        class NoChanges:
            def changes(self):
                return []
        root = self.tmp
        rows = application_logs(NoChanges(), root)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['component'], rows[0]['severity'], rows[0]['instruction_id'], rows[0]['device_id']),
                         ('desktop_worker', 'ERROR', 'reg-rc-dash', 'desktop-chrome'))
        self.assertIn('Bet365 Reality Check is open; answer it on the mini PC to continue', rows[0]['message'])

    def test_health_carries_the_alert_until_a_later_result(self):
        from desktop_worker.server import Worker
        w = Worker(dict(port=0, token='t', worker_id='dw-test', account_fingerprint=None), ledger_path=self.tmp / 'l.sqlite3',
                   start_executor=False)
        self.assertIsNone(w.health()['operator_alert'])
        alert = dict(code='REALITY_CHECK_OPEN', message='Bet365 Reality Check is open; answer it on the mini PC to continue')
        w.note_result(dict(status='FAIL', stage='SESSION_EXPIRED', operator_alert=alert))
        self.assertEqual(w.health()['operator_alert'], alert)
        w.note_result(dict(status='PASS', stage='PASS'))
        self.assertIsNone(w.health()['operator_alert'])


if __name__ == '__main__':
    unittest.main()
