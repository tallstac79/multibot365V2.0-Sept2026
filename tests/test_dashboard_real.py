import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from core.observation_store import record_alert
from core.notification_formatter import format_result
from core.decision_support import Store, defaults, apply_rules
from dashboard.services import ROOT, Health
from dashboard.adapters import result_history
from dashboard.app import create_app

class RealDashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.db=self.root/'.local/oddsnotifier.sqlite3'
        self.client=TestClient(create_app(self.root,health=Health(self.root,network=lambda:{})))
        self.raw=(ROOT/'tests/fixtures/oddsnotifier_basketball_total.txt').read_text()
    def tearDown(self): self.tmp.cleanup()
    def record(self,**changes):
        args=dict(channel_id='-123',message_id='10',source_timestamp='2026-09-23T10:00:00Z',received_at='2026-09-23T10:01:00Z',origin='production')
        args.update(changes)
        return record_alert(self.db,self.raw,**args)
    def test_empty_real_source_is_read_only(self):
        self.assertEqual(self.client.get('/api/alerts').json()['items'],[])
        self.assertFalse(self.db.exists())
    def test_existing_empty_sqlite_is_empty_without_migration(self):
        connection=sqlite3.connect(self.db);connection.close()
        before=self.db.read_bytes()
        self.assertEqual(self.client.get('/api/alerts').json()['items'],[])
        self.assertEqual(self.db.read_bytes(),before)

    def test_real_parser_record_details(self):
        self.record();row=self.client.get('/api/alerts').json()['items'][0]
        self.assertEqual(row['raw_text'],self.raw)
        self.assertEqual(row['status'],'AMBIGUOUS')
        self.assertIsNone(row['instruction']);self.assertIsNone(row['side'])
        self.assertEqual(row['provenance']['mode'],'REAL DATA')
        self.assertEqual([e['stage'] for e in row['timeline']],['RECEIVED','PARSED','NORMALIZED'])
    def test_malformed_and_duplicate_stored(self):
        self.record();self.record()
        self.raw='New odds update on Pinnacle\nbroken';self.record(message_id='11')
        rows=self.client.get('/api/alerts').json()['items']
        self.assertEqual([r['status'] for r in rows],['INVALID','DUPLICATE','AMBIGUOUS'])
        self.assertTrue(rows[0]['warnings'])
    def test_samples_excluded_and_switch_read_only(self):
        self.record(origin='sample');before=self.db.read_bytes()
        self.assertEqual(self.client.get('/api/alerts?mode=real').json()['items'],[])
        self.assertEqual(before,self.db.read_bytes())
    def test_corrupt_database_fails_explicitly(self):
        self.db.write_text('corrupt')
        self.assertEqual(self.client.get('/api/alerts').status_code,503)
    def test_production_history_separation_and_timeline(self):
        rows=result_history(ROOT,'real');self.assertGreater(len(rows),0)
        self.assertTrue(all('REAL DATA' in r['origin'] for r in rows))
        self.assertTrue(all('live-' in r['instruction_id'] for r in rows))
        row=next(r for r in rows if r['instruction_id']=='live-ready-1790108608')
        self.assertEqual(row['device_id'],'samsung-R5CT61TE14Z')
        stages={e['stage'] for e in row['timeline']}
        self.assertIn('RECEIVED',stages);self.assertIn('DEVICE_RESULT',stages)
        self.assertNotIn('RULES_APPLIED',stages);self.assertNotIn('PARSED',stages)
        self.assertIsNotNone(row['time'])
    def test_unknown_history_origin_excluded(self):
        path=self.root/'evidence/unknown';path.mkdir(parents=True)
        (path/'result.json').write_text(json.dumps({'instruction_id':'unknown','status':'PASS'}))
        self.assertEqual(self.client.get('/api/history').json()['items'],[])
    def test_formatter_preserves_status_and_no_invented_source(self):
        text=format_result({'instruction_id':'abc','status':'FAIL','stage':'TIMEOUT','detail':'Deadline expired',
            'fixture_name':'Arsenal v Leeds','selection':{'market':'MONEYLINE','side':'HOME','price':'1.33'},'final_state':{'stake':'1'}})
        for value in ('Status: FAIL','Stage: TIMEOUT','Reason: Deadline expired','Stake: £1.00'): self.assertIn(value,text)
        self.assertNotIn('REJECTED',text);self.assertNotIn('OddsNotifier',text)
    def test_log_filters_on_existing_logs(self):
        logs=self.root/'logs';logs.mkdir()
        (logs/'multibot.log').write_text('23/09/2026 10:00:00 [coordinator] ERROR: instruction_id=abc device_id=phone timeout\ninvalid\n'+
            json.dumps({'timestamp':'2026-09-23T11:00:00Z','component':'parser','severity':'INFO','instruction_id':'def','device_id':'other','message':'parsed'})+'\n')
        rows=self.client.get('/api/logs?instruction_id=abc&device_id=phone&severity=ERROR&component=coordinator').json()['items']
        self.assertEqual(len(rows),1)
        self.assertEqual(self.client.get('/api/logs?since=2026-09-23T10:59:00Z').json()['total'],1)
    def test_recommendation_requires_explicit_verified_target(self):
        from core.oddsnotifier_parser import parse_oddsnotifier
        parsed=parse_oddsnotifier(self.raw)
        parsed['target_side']='OVER';parsed['alert_price']='2.20'
        result,reason=apply_rules(parsed,'OVER',defaults(),'abc','2026-09-23T10:00:00Z',sample=False)
        self.assertIsNone(result)
        parsed['quote_mapping']['production_verified']=True;parsed['target_line']='190.5'
        result,reason=apply_rules(parsed,'OVER',defaults(),'abc','2026-09-23T10:00:00Z',sample=False)
        self.assertEqual(result['line'],'190.5');self.assertEqual(result['alert_price'],'2.20')
        self.assertFalse(result['dispatchable'])
    def test_malformed_health_payload_does_not_leak_into_ui(self):
        folder=self.root/'.local';folder.mkdir(exist_ok=True)
        (folder/'coordinator.json').write_text(json.dumps({'url':'http://phone.ts.net','token':'private'}))
        class Client:
            def __init__(self,config):pass
            def health(self): return ['malformed']
        h=Health(self.root,Client,network=lambda:{'BackendState':'Running','Peer':{'x':{'DNSName':'phone.ts.net.','Online':True,'ID':'node123'}}})
        result=h.get()
        self.assertEqual(result['coordinator']['health'],{})
        self.assertEqual(result['phone']['device_id'],'node123')
        self.assertEqual(result['phone']['status'],'DEGRADED')
    def test_observed_telegram_snapshot_produces_real_recommendations(self):
        from tools.import_oddsnotifier_records import import_snapshot
        source=ROOT/'evidence/dashboard/telegram-basketball-observed.json'
        import_snapshot(source,self.db)
        rows=self.client.get('/api/alerts?mode=real').json()['items']
        self.assertEqual(len(rows),4)
        self.assertTrue(all(r['status']=='PARSED' and r['recommendation'] for r in rows))
        self.assertTrue(all(r['source_timestamp'] is None for r in rows))
        rytas=next(r for r in rows if r['source_message_id']=='67895')
        self.assertEqual((rytas['recommendation']['side'],rytas['recommendation']['line'],rytas['alert_price']),('HOME','-18.5','1.83'))
        self.assertNotIn('RULES_APPLIED',[e['stage'] for e in rytas['timeline']])
        self.assertEqual(rytas['parsed']['target_price_source'],'bold_bet365_quote')
        import_snapshot(source,self.db)
        self.assertTrue(all(r['status']=='DUPLICATE' for r in self.client.get('/api/alerts').json()['items'][:4]))

    def test_real_evidence_screenshot(self):
        client=TestClient(create_app(ROOT,db_path=self.root/'test.sqlite3',health=Health(self.root,network=lambda:{})))
        rows=client.get('/api/history').json()['items']
        link=next(e['url'] for row in rows for e in row['evidence'] if e['name'].endswith('.png'))
        response=client.get(link)
        self.assertEqual(response.status_code,200);self.assertIn('image/png',response.headers['content-type'])

if __name__=='__main__':unittest.main()
