"""Lookup-only tests. Real names/snapshots; explicit adversarial mutations.

The complete evidence fixture below is a controlled input, not a claim that every
historical failure preserved every field. Historical replay is tested separately.
"""
import copy
import unittest
from tools.offline_event_identity import (
    resolve, dimensions, normalize, name_evidence, fingerprint_evidence,
    CONFIRMED, VARIANT, RECHECK, AMBIGUOUS, CONFLICT,
)


def records():
    # Names/terms from stored Boca/Tigers event frame, 27 September 2026.
    alert = dict(event_id='26832491', sport='basketball', competition='Intercontinental Cup', country='World',
                 kickoff='2026-09-27T06:30:00Z', home='Atletico Boca Juniors', away='Tigers',
                 market_fingerprint=dict(market='SPREAD', period='FULL_GAME', side='HOME', line='-9.5', prices={'HOME':'1.83','AWAY':'1.83'}))
    page = dict(event_id='26832491',event_id_observed=True,page_type='event',prematch=True,unique_event=True,
                competitor_count=0,orientation='home_away',sport='basketball',competition='FIBA Intercontinental Cup',
                kickoff='2026-09-27T07:30:00+01:00',home='Boca Juniors',away='RSSB Tigers',
                captured_at='2026-09-27T06:10:14Z',market_fingerprint=copy.deepcopy(alert['market_fingerprint']))
    return alert,page


class OfflineIdentityTests(unittest.TestCase):
    def test_boca_tigers_recovers_without_exact_team_or_alias(self):
        a,p=records();before=copy.deepcopy((a,p));r=resolve(a,p)
        self.assertEqual(r['verdict'],VARIANT)
        self.assertEqual(r['permanent_aliases_created'],[])
        self.assertEqual((a,p),before)
        self.assertEqual(r['evidence']['away_name']['kind'],'TOKEN_CONTAINMENT')
        self.assertFalse(r['evidence']['away_name']['strong'])

    def test_exact_and_canonical_names(self):
        a,p=records();a.update(home=p['home'],away=p['away'])
        self.assertEqual(resolve(a,p)['verdict'],CONFIRMED)
        p['home']='BC Boca Juniors'
        self.assertEqual(resolve(a,p)['verdict'],VARIANT)

    def test_lodz_gender_and_competition_order_are_independent(self):
        a,p=records();a.update(home='LKS Lodz',away='Sparta Ziebice',competition='Liga 1 Women',country='Poland')
        p.update(home='LKS KK Lodz (W)',away='Sparta Ziebice (W)',competition='Poland 1 Liga Women')
        r=resolve(a,p)
        self.assertEqual(r['verdict'],VARIANT)
        self.assertEqual(r['evidence']['home_gender']['page'],'women')
        self.assertTrue(r['evidence']['home_gender']['supplied_by_competition'])

    def bydgoszcz(self):
        a,p=records();a.update(home='KS Basket 25 II Bydgoszcz',away='Energa Torun II',competition='Liga 1 Women',country='Poland')
        p.update(home=dict(name='KS Basket 25 I Bydgoszcz (W)',source='ocr',confidence=None),
                 away=dict(name='Katarzynki II Torun (W)',source='ocr'),competition='Poland 1 Liga Women')
        return a,p

    def test_roman_ocr_conflict_needs_recheck_not_gender_conflict(self):
        a,p=self.bydgoszcz();r=resolve(a,p)
        self.assertEqual(r['verdict'],RECHECK)
        self.assertEqual(r['evidence']['home_gender']['status'],'AGREE')
        self.assertEqual(r['evidence']['home_squad_tier']['status'],'NEEDS_RECHECK')
        self.assertIsNone(r['evidence']['home_name']['page']['confidence'])

    def test_independent_reread_can_resolve_or_confirm_roman_conflict(self):
        for numeral,want in [('II',VARIANT),('I',CONFLICT)]:
            a,p=self.bydgoszcz()
            p['home']['reread']=dict(name=f'KS Basket 25 {numeral} Bydgoszcz (W)',source='enhanced_ocr',confidence=.99,independent=True)
            self.assertEqual(resolve(a,p)['verdict'],want)

    def test_unknown_missing_numeral_is_not_first_team(self):
        a,p=self.bydgoszcz();p['home']['name']='KS Basket 25 Bydgoszcz (W)'
        self.assertEqual(resolve(a,p)['verdict'],RECHECK)
        self.assertIsNone(dimensions(p['home']['name'])['squad_tier'])

    def test_unreliable_or_repeated_reread_does_not_resolve(self):
        for confidence,independent in [(.5,True),(.99,False)]:
            a,p=self.bydgoszcz();p['home']['reread']=dict(name='KS Basket 25 II Bydgoszcz (W)',source='enhanced_ocr',confidence=confidence,independent=independent)
            self.assertEqual(resolve(a,p)['verdict'],RECHECK)

    def test_distinct_protected_dimensions(self):
        d=dimensions('Example Women U19 II reserves academy')
        self.assertEqual(d,dict(gender='women',age_group='u19',squad_tier='II',reserve=True,academy=True))
        self.assertIsNone(dimensions('Boca Juniors')['reserve'])
        self.assertIsNone(dimensions('Yokohama B-Corsairs')['squad_tier'])

    def test_explicit_gender_conflicts(self):
        a,p=records();a['home']='Boca Juniors Men';p['home']='Boca Juniors Women'
        self.assertEqual(resolve(a,p)['verdict'],CONFLICT)

    def test_youth_and_proven_tier_conflicts(self):
        for feed,page in [('Boca Juniors U19','Boca Juniors U21'),('Boca Juniors I','Boca Juniors II'),('Boca Juniors B','Boca Juniors III')]:
            a,p=records();a['home']=feed;p['home']=page
            self.assertEqual(resolve(a,p)['verdict'],CONFLICT)

    def test_explicit_first_team_vs_reserve_conflict(self):
        a,p=records();a['home']=dict(name='Boca Juniors',dimensions={'reserve':False})
        p['home']='Boca Juniors reserves'
        self.assertEqual(resolve(a,p)['verdict'],CONFLICT)

    def test_wrong_kickoff_and_timezone_naive(self):
        a,p=records();p['kickoff']='2026-09-28T06:30:00Z'
        self.assertEqual(resolve(a,p)['verdict'],CONFLICT)
        p['kickoff']='2026-09-27T06:30:00'
        self.assertEqual(resolve(a,p)['verdict'],AMBIGUOUS)

    def test_small_explicit_kickoff_tolerance(self):
        a,p=records();p['kickoff']='2026-09-27T06:32:00Z'
        self.assertEqual(resolve(a,p,kickoff_tolerance_seconds=120)['verdict'],VARIANT)
        self.assertEqual(resolve(a,p,kickoff_tolerance_seconds=60)['verdict'],CONFLICT)
        with self.assertRaises(ValueError):resolve(a,p,kickoff_tolerance_seconds=3600)

    def test_same_clubs_different_event_or_sport(self):
        for field,value in [('event_id','999'),('sport','football')]:
            a,p=records();p[field]=value
            self.assertEqual(resolve(a,p)['verdict'],CONFLICT)

    def test_wrong_opponent_and_generic_nickname_do_not_confirm(self):
        for away in ('Real Madrid','Tokyo Tigers'):
            a,p=records();a['away']='RSSB Tigers';p['away']=away
            self.assertEqual(resolve(a,p)['verdict'],AMBIGUOUS)

    def test_reversed_opponents(self):
        a,p=records();p['home'],p['away']=p['away'],p['home']
        self.assertEqual(resolve(a,p)['verdict'],CONFLICT)

    def test_duplicate_or_competing_pair_needs_review(self):
        a,p=records();p['competitor_count']=1
        self.assertEqual(resolve(a,p)['verdict'],RECHECK)
        p['competitor_count']=0;p['home']=p['away']='Boca Juniors'
        self.assertEqual(resolve(a,p)['verdict'],RECHECK)

    def test_generic_search_home_redirects(self):
        for kind in ('generic','home','search','closed'):
            a,p=records();p['page_type']=kind
            self.assertEqual(resolve(a,p)['verdict'],CONFLICT)

    def test_unanchored_search_does_not_get_direct_link_privileges(self):
        a,p=records();p['event_id']=None;p['event_id_observed']=False
        self.assertEqual(resolve(a,p)['verdict'],AMBIGUOUS)
        p.update(direct_link_capture=True,requested_event_id=a['event_id'])
        r=resolve(a,p)
        self.assertEqual(r['verdict'],VARIANT)
        self.assertFalse(r['evidence']['event_id']['independently_observed'])

    def test_wrong_competition_or_missing_evidence(self):
        a,p=records();p['competition']='Different League'
        self.assertEqual(resolve(a,p)['verdict'],AMBIGUOUS)
        a['competition_id']='league-a';p['competition_id']='league-b'
        self.assertEqual(resolve(a,p)['verdict'],CONFLICT)
        a.pop('competition_id');p.pop('competition_id')
        p['competition']=None
        self.assertEqual(resolve(a,p)['verdict'],AMBIGUOUS)

    def test_scoped_alias_never_becomes_global(self):
        alias=dict(source='Energa Torun II',target='Katarzynki II',sport='basketball',competition='Liga 1 Women',approved=True)
        yes=name_evidence(alias['source'],alias['target'],[alias],'basketball','Liga 1 Women')
        no=name_evidence(alias['source'],alias['target'],[alias],'basketball','Other League')
        self.assertEqual(yes['kind'],'ALIAS_MATCH');self.assertEqual(no['kind'],'UNRELATED')
        self.assertEqual(alias['source'],'Energa Torun II')

    def test_unicode_initials_split_tokens(self):
        self.assertEqual(normalize('ŁÓDŹ'), 'lodz')
        self.assertEqual(name_evidence('Goyang Skygunners','Goyang Sky Gunners')['kind'],'TOKEN_SPLIT')
        self.assertEqual(name_evidence('Manchester Rovers','M Rovers')['kind'],'INITIALS')
        self.assertEqual(name_evidence('Besançon BC','Besancon')['kind'],'CANONICAL_MATCH')

    def test_fingerprint_is_not_sufficient_without_other_anchors(self):
        a,p=records();p['kickoff']=None;p['competition']=None;p['event_id_observed']=False
        self.assertEqual(resolve(a,p)['verdict'],AMBIGUOUS)

    def test_fingerprint_market_period_side_line_both_prices(self):
        for field,value in [('market','TOTALS'),('period','FIRST_HALF'),('side','AWAY'),('line','-10.5'),('prices',{'HOME':'1.83','AWAY':'1.91'})]:
            a,p=records();p['market_fingerprint'][field]=value
            self.assertEqual(resolve(a,p)['verdict'],CONFLICT,field)

    def test_missing_fingerprint_and_nonfinite_numbers(self):
        for value in (None,{},dict(market='SPREAD',side='HOME',period='FULL_GAME',line='NaN',prices={'HOME':'1.83'}),
                      dict(market='SPREAD',side='DRAW',period='FULL_GAME',line='1.0',prices={'DRAW':'1.83'})):
            a,p=records();p['market_fingerprint']=value
            self.assertEqual(resolve(a,p)['verdict'],AMBIGUOUS)

    def test_recorded_movement_needs_same_event_and_time_order(self):
        a,p=records();old=copy.deepcopy(p['market_fingerprint']);p['market_fingerprint']['line']='-10.5'
        proof=dict(event_id=a['event_id'],independently_observed=True,observed_at='2026-09-27T06:09:00Z',fingerprint=old)
        p['prior_snapshots']=[proof]
        r=resolve(a,p);self.assertEqual(r['verdict'],VARIANT)
        self.assertEqual(r['evidence']['market_fingerprint']['fingerprint_match'],'MOVED_PLAUSIBLY')
        proof['observed_at']='2026-09-27T06:11:00Z'
        self.assertEqual(resolve(a,p)['verdict'],CONFLICT)
        proof.update(observed_at='2026-09-27T06:09:00Z',event_id='different')
        self.assertEqual(resolve(a,p)['verdict'],CONFLICT)

    def test_event_scoped_nickname_evidence_is_not_an_alias(self):
        a,p=self.bydgoszcz();p['home']='KS Basket 25 II Bydgoszcz (W)';p['away']='Katarzynki II'
        self.assertEqual(resolve(a,p)['verdict'],AMBIGUOUS)
        p['name_relationships']=[dict(side='away',feed='Energa Torun II',page='Katarzynki II',event_id=a['event_id'],independent=True,source='controlled roster fixture')]
        r=resolve(a,p);self.assertEqual(r['verdict'],VARIANT);self.assertEqual(r['permanent_aliases_created'],[])

    def test_one_scoped_relationship_cannot_mask_wrong_other_team(self):
        a,p=self.bydgoszcz();p['home']='Unrelated Club II (W)';p['away']='Katarzynki II'
        p['name_relationships']=[dict(side='away',feed='Energa Torun II',page='Katarzynki II',event_id=a['event_id'],independent=True,source='controlled roster fixture')]
        self.assertEqual(resolve(a,p)['verdict'],AMBIGUOUS)

    def test_empty_names_are_missing_not_a_reversed_fixture(self):
        a,p=records();p['home']=p['away']=None
        self.assertEqual(resolve(a,p)['verdict'],AMBIGUOUS)

    def test_generic_url_cannot_borrow_an_event_id(self):
        for url in ['https://www.bet365.com/','https://www.bet365.com/#/SEARCH/','https://bet365.com.evil.test/#/E26832491/']:
            a,p=records();a['event_url']=url
            self.assertEqual(resolve(a,p)['verdict'],CONFLICT)

    def test_missing_competitor_count_is_not_zero(self):
        for value in [None,False,'0']:
            a,p=records();p['competitor_count']=value
            self.assertNotIn(resolve(a,p)['verdict'],(CONFIRMED,VARIANT))

    def test_different_numbered_division_is_a_conflict(self):
        a,p=records();a['competition']='Division 1 Women';p['competition']='Division 2 Women'
        self.assertEqual(resolve(a,p)['verdict'],CONFLICT)

    def test_corroborated_visual_review_has_distinct_provenance(self):
        a,p=self.bydgoszcz()
        p['home']['reread']=dict(name='KS Basket 25 II Bydgoszcz (W)',source='visual_review',independent=True,legible=True,artifact_sha256='a'*64)
        r=resolve(a,p);self.assertEqual(r['verdict'],VARIANT)
        self.assertIsNone(r['evidence']['home_name']['page']['confidence'])
        p['home']['reread'].pop('artifact_sha256')
        self.assertEqual(resolve(a,p)['verdict'],RECHECK)


if __name__=='__main__':unittest.main()
