"""Regression checks against frozen historical observations, no live dependencies."""
import copy
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import unittest

from tools.identity_v2_replay import captured_header, text_rows, event_id
from tools.offline_event_identity import resolve, CONFIRMED, VARIANT, RECHECK, CONFLICT, AMBIGUOUS

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'evidence/identity-v2'


class ReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=json.loads((FOLDER/'inputs.json').read_text())
        cls.cases={r['instruction_id']:r for r in cls.data['cases']}
        cls.results=json.loads((FOLDER/'results.json').read_text())

    def replay(self,case):
        return resolve(case['alert'],case['page'],aliases=self.data['aliases'],competition_mappings=self.data['competition_mappings'])

    def test_every_frozen_direct_failure_present_once(self):
        snapshot=json.loads((FOLDER/'snapshot.json').read_text())
        self.assertEqual(len(self.cases),46)
        self.assertEqual(set(self.cases),{r['instruction_id'] for r in snapshot['rows']})
        self.assertEqual({r['device_stage'] for r in snapshot['rows']},{'ALIAS_REQUIRED','TARGET_NOT_FOUND','WRONG_EVENT'})

    def test_both_real_boca_tigers_records_recovered_without_alias(self):
        for iid in ['on-e3d73d9be8ffcd6727f59839','on-7035a28fe078550828b8c5e6']:
            r=self.replay(self.cases[iid])
            self.assertEqual(r['verdict'],VARIANT)
            self.assertEqual(r['evidence']['market_fingerprint']['fingerprint_match'],'MATCHES')
            self.assertEqual(r['permanent_aliases_created'],[])
            self.assertFalse(r['evidence']['event_id']['independently_observed'])

    def test_all_seven_real_lodz_variants_recovered(self):
        cases=[c for c in self.cases.values() if c['alert']['home']=='LKS Lodz']
        self.assertEqual(len(cases),7)
        for c in cases:self.assertEqual(self.replay(c)['verdict'],VARIANT)

    def test_three_bydgoszcz_captures_use_independent_roman_review(self):
        cases=[c for c in self.cases.values() if 'Bydgoszcz' in c['alert']['home']]
        self.assertEqual(len(cases),3)
        for c in cases:
            self.assertEqual(self.replay(c)['verdict'],VARIANT)
            self.assertIsNone(c['page']['home']['confidence'])
            unreviewed=copy.deepcopy(c);unreviewed['page']['home'].pop('reread')
            self.assertEqual(self.replay(unreviewed)['verdict'],RECHECK)

    def test_wrapped_torun_line_is_preserved(self):
        c=self.cases['on-7568867893977163a3442a04']
        header=captured_header(text_rows(ROOT/c['page']['capture']),2026)
        self.assertIn('Torun',header['away'])

    def test_visual_reviews_are_bound_to_real_images(self):
        for entry in json.loads((FOLDER/'capture-manifest.json').read_text()):
            self.assertEqual(entry['http_status'],200)
            for artifact in entry['artifacts']:
                self.assertEqual(hashlib.sha256((ROOT/artifact['path']).read_bytes()).hexdigest(),artifact['sha256'])
        reviews=json.loads((FOLDER/'visual-reviews.json').read_text())
        for path,r in reviews.items():
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),r['artifact_sha256'])
            self.assertIsNone(r['home']['confidence'])

    def test_movement_is_observed_not_a_tolerance_or_alert_copy(self):
        c=self.cases['on-8d9ec0935d6e1241f712a8db'];r=self.replay(c)
        self.assertEqual(r['evidence']['market_fingerprint']['fingerprint_match'],'MOVED_PLAUSIBLY')
        self.assertEqual(Decimal(c['alert']['market_fingerprint']['line']),Decimal('4.5'))
        self.assertEqual(Decimal(c['page']['market_fingerprint']['line']),Decimal('3.0'))
        c=copy.deepcopy(c);c['page']['prior_snapshots']=[]
        self.assertEqual(self.replay(c)['verdict'],CONFLICT)

    def test_report_is_reproducible_and_inputs_unchanged(self):
        before=copy.deepcopy(self.data)
        for row in self.results:
            if row.get('cohort','operational')=='operational':self.assertEqual(self.replay(row),row['result'])
        self.assertEqual(before,self.data)

    def test_csv_covers_both_cohorts_and_all_evidence_dimensions(self):
        with (FOLDER/'replay.csv').open(encoding='utf-8-sig',newline='') as f:
            reader=csv.DictReader(f);rows=list(reader)
            for field in ['gender','age','squad_tier','reserve','academy','market_fingerprint','direct_url_evidence','ocr_reread']:
                self.assertIn(field,reader.fieldnames)
        self.assertEqual(len(rows),len(self.results))
        self.assertEqual(sum(r['cohort']=='operational' for r in rows),46)

    def test_historical_kickoff_and_reversed_conflicts_remain(self):
        lookup={r['instruction_id']:r for r in self.results}
        for iid in ['tzprobe-1790440976-1','e-search-wrong-183030']:
            self.assertEqual(lookup[iid]['result']['verdict'],CONFLICT)

    def test_dst_fold_and_gap_cannot_be_invented_from_screenshot(self):
        for label in ['29 Mar 01:30','25 Oct 01:30']:
            header=captured_header([dict(cy=280,text='Example '+label),dict(cy=330,text='Home vs Away')],2026)
            self.assertIsNone(header['kickoff'])

    def test_adversarial_mutations_have_no_false_confirmations(self):
        rows=json.loads((FOLDER/'adversarial-inputs.json').read_text())
        self.assertGreaterEqual(len(rows),15)
        for row in rows:
            with self.subTest(row['name']):
                self.assertEqual(resolve(row['alert'],row['page'])['verdict'],row['expected'])


if __name__=='__main__':unittest.main()
