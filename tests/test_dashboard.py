"""Deterministic dashboard API/service checks: no phone or USB required."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from dashboard.app import create_app
from dashboard.services import ROOT, Store, Health, defaults, sample_alerts, apply_rules, validate

class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / 'dashboard.sqlite3'
        self.client = TestClient(create_app(ROOT, self.db, Health(self.root, network=lambda: {})))
    def tearDown(self): self.temp.cleanup()
    def test_dashboard_loads_and_assets(self):
        page = self.client.get('/')
        self.assertEqual(page.status_code, 200)
        for label in ('System overview', 'Incoming alerts', 'Execution history', 'Technical logs', 'SAMPLE DATA'):
            self.assertIn(label, page.text)
        for file in ('style.css', 'app.js'): self.assertEqual(self.client.get('/static/'+file).status_code, 200)
    def test_backend_unavailable(self):
        data = self.client.get('/api/status').json()
        self.assertEqual(data['phone']['status'], 'OFFLINE')
        self.assertIsNone(data['phone']['latency_ms'])
        self.assertTrue(data['dashboard']['online'])
        self.assertNotIn('token', json.dumps(data))
    def test_health_online_degraded_and_reconnect(self):
        (self.root/'.local').mkdir()
        (self.root/'.local/coordinator.json').write_text(json.dumps({'url':'http://phone.ts.net:8767','token':'SECRET'}))
        class Fake:
            response = {'healthy':True,'state':'IDLE','heartbeat_ms':1234,'app_version':'test'}
            def __init__(self, config): pass
            def health(self):
                if isinstance(self.response, Exception): raise self.response
                return self.response
        h = Health(self.root, Fake, network=lambda:{'BackendState':'Running','Peer':{'a':{'DNSName':'phone.ts.net.','Online':True}}})
        self.assertEqual(h.get()['phone']['status'], 'ONLINE')
        self.assertEqual(h.get()['network']['phone'], 'ONLINE')
        h.cached_at=0; Fake.response=OSError()
        self.assertEqual(h.get()['phone']['status'], 'DEGRADED')
        self.assertEqual(h.get()['coordinator']['status'], 'OFFLINE')
        self.assertIsNotNone(h.get()['phone']['last_success'])
        h.cached_at=0; Fake.response={'healthy':False}
        self.assertEqual(h.get()['phone']['status'], 'DEGRADED')
        self.assertIsNotNone(h.get()['network']['last_reconnect'])
    def test_fixture_coverage(self):
        rows=self.client.get('/api/alerts?mode=sample').json()['items']
        self.assertEqual({r['status'] for r in rows}, {'PARSED','AMBIGUOUS','INVALID','DUPLICATE','IGNORED'})
        actual={(r['sport'],r['market'],r['side']) for r in rows if r['instruction']}
        for expected in [('football','1X2',s) for s in ('HOME','DRAW','AWAY')]+[('football','SPREAD','HOME'),('football','TOTALS','OVER'),('basketball','MONEYLINE','HOME'),('basketball','SPREAD','HOME'),('basketball','TOTALS','OVER')]:
            self.assertIn(expected,actual)
        self.assertTrue(all(r['provenance']['mode']=='SAMPLE DATA' for r in rows))
    def test_duplicate_and_malformed_fail_closed(self):
        rows=self.client.get('/api/alerts?mode=sample').json()['items']
        duplicate=next(r for r in rows if r['status']=='DUPLICATE')
        original=next(r for r in rows if r['instruction_id']==duplicate['instruction_id'] and r['status']=='PARSED')
        self.assertEqual(duplicate['source_message_id'], original['source_message_id'])
        self.assertIsNone(duplicate['instruction'])
        for r in rows:
            if r['status']!='PARSED': self.assertIsNone(r['instruction'])
    def test_no_live_feed_fabrication(self):
        empty_client=TestClient(create_app(self.root,self.db,Health(self.root,network=lambda:{})))
        self.assertEqual(empty_client.get('/api/alerts?mode=real').json()['items'],[])
        self.assertEqual(self.client.get('/api/alerts?mode=bad').status_code,422)
    def test_config_validation(self):
        for field,value in [('default_stake',-1),('max_stake',0),('allowed_slippage',2),('enabled','true')]:
            config=defaults();config['global'][field]=value
            self.assertEqual(self.client.put('/api/config',json=config).status_code,422)
        config=defaults();config['sports']['football']['markets']['1X2']['stake']=99
        self.assertEqual(self.client.put('/api/config',json=config).status_code,422)
        for malformed in ({}, {'global':None,'sports':None}, {'global':{},'sports':[]}):
            self.assertEqual(self.client.put('/api/config',json=malformed).status_code,422)
        config=defaults();config['global']['default_stake']=float('nan')
        with self.assertRaises(ValueError): validate(config)
    def test_config_persistence_and_audit(self):
        config=defaults();config['global']['default_stake']=2.5
        response=self.client.put('/api/config',json=config)
        self.assertEqual(response.status_code,200)
        reopened=Store(self.db)
        self.assertEqual(reopened.get()['config'],config)
        self.assertTrue(reopened.get()['updated_at'])
        self.assertEqual(len(reopened.changes()),1)
        self.assertEqual(self.client.get('/api/logs?component=dashboard.config').json()['total'],1)
    def test_rules_price_stake_and_disabled(self):
        config=defaults();config['global']['allowed_slippage']=.05;config['global']['default_stake']=2
        rows=sample_alerts({'config':config,'updated_at':'test'})
        row=next(r for r in rows if r['instruction_id']=='sample-2')
        self.assertEqual(row['instruction']['minimum_price'],'1.370')
        self.assertEqual(row['instruction']['stake'],2)
        self.assertFalse(row['instruction']['dispatchable'])
        config['global']['enabled']=False
        self.assertTrue(all(r['instruction'] is None for r in sample_alerts({'config':config})))
    def test_real_observations_remain_unmapped(self):
        for r in self.client.get('/api/alerts?mode=sample').json()['items']:
            if r['provenance']['original']=='user_reported_real' and r['sport']=='football':
                self.assertIsNone(r['instruction'])
                self.assertIsNone(r['parsed']['quote_mapping']['profile'])
    def test_empty_database_history_and_logs(self):
        client=TestClient(create_app(self.root,self.db,Health(self.root,network=lambda:{})))
        self.assertEqual(client.get('/api/history').json()['items'],[])
        self.assertEqual(client.get('/api/logs').json()['items'],[])
    def test_history_filter_and_evidence(self):
        all_rows=self.client.get('/api/history').json()
        self.assertGreater(all_rows['total'],0)
        rows=self.client.get('/api/history?mode=sample&status=TIMEOUT').json()['items']
        self.assertTrue(rows)
        self.assertTrue(all(r['stage']=='TIMEOUT' for r in rows))
        self.assertEqual(self.client.get('/api/history?q=not-present-123').json()['total'],0)
        # The live pipeline store may add records without local evidence; use a recorded one.
        row=next(r for r in all_rows['items'] if r['evidence'])
        self.assertEqual(self.client.get(row['evidence'][0]['url']).status_code,200)
        self.assertEqual(self.client.get('/api/evidence/%2E%2E/BUILD_STATUS.md').status_code,404)
        self.assertEqual(self.client.get('/api/evidence/missing.png').status_code,404)
        self.assertEqual(self.client.get('/api/history?limit=1').json()['items'][0]['instruction_id'],all_rows['items'][0]['instruction_id'])
    def test_malformed_record_ignored(self):
        folder=self.root/'evidence';folder.mkdir()
        (folder/'result.json').write_text('{broken')
        client=TestClient(create_app(self.root,self.db,Health(self.root,network=lambda:{})))
        self.assertEqual(client.get('/api/history').json()['items'],[])
    def test_cross_origin_and_host_rejected(self):
        self.assertEqual(self.client.put('/api/config',json=defaults(),headers={'Origin':'http://evil.example'}).status_code,403)
        self.assertEqual(self.client.get('/api/config',headers={'Host':'evil.example'}).status_code,403)

if __name__=='__main__': unittest.main()
