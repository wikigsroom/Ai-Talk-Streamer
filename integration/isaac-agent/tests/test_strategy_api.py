"""HTTP authorization and replay matrix at the strategy boundary."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from io import BytesIO
import urllib.request
import urllib.error

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'tests'))
from isaac_jev.strategy import StrategyService,DOMAINS,StrategyError
from isaac_jev.strategy_server import StrategyServer
from isaac_jev.models import GameState
from strategy_fixtures import scenario


class StrategyApiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.service=StrategyService(self.temp.name)
        self.server=StrategyServer(self.service,'test-local-token',port=0);self.server.start()
        self.url='http://127.0.0.1:'+str(self.server.server.server_port)
    def tearDown(self):self.server.close();self.service.close();self.temp.cleanup()
    def post(self,body,headers=None):
        request=urllib.request.Request(self.url+'/control',data=json.dumps(body).encode(),headers={'Content-Type':'application/json',**(headers or {})})
        try:
            with urllib.request.urlopen(request,timeout=2) as response:return response.status,json.load(response)
        except urllib.error.HTTPError as response:return response.code,json.load(response)
    def test_writes_require_token_and_reject_browser_origins(self):
        body={'enabled':True,'live':True}
        self.assertEqual(self.post(body)[0],403)
        self.assertEqual(self.post(body,{'X-Isaac-Token':'wrong'})[0],403)
        self.assertEqual(self.post(body,{'X-Isaac-Token':'test-local-token','Origin':'http://example.invalid'})[0],403)
        self.assertFalse(self.service.enabled)
        self.assertEqual(self.post(body,{'X-Isaac-Token':'test-local-token'})[0],200)
        self.assertTrue(self.service.live)
    def test_invalid_control_types_cannot_arm(self):
        for value in ['true',1,{},None]:
            self.assertEqual(self.post({'enabled':value},{'X-Isaac-Token':'test-local-token'})[0],400)
        self.assertFalse(self.service.enabled)
    def test_queries_expose_effects_and_history_without_mutating_control(self):
        raw=scenario();raw['strategy']['effects']={'known':True,'collectibles':[{'id':34,'count':1}]}
        self.service.update(raw,GameState.from_message(raw))
        for topic in ['effects','history','health','bosses']:
            with urllib.request.urlopen(self.url+'/query?topic='+topic,timeout=2) as response:
                value=json.load(response)
            self.assertTrue(value['connected']);self.assertIn('data',value)
        self.assertFalse(self.service.enabled)

    def test_host_status_exposes_only_public_fields(self):
        from isaac_jev.strategy_server import host_status
        payload={'ready':True,'model':'gpt-6-luna','api_key':'secret','sessionId':'private-session','lastError':'raw error'}
        with patch('isaac_jev.strategy_server.urllib.request.urlopen',return_value=BytesIO(json.dumps(payload).encode())):
            value=host_status()
        self.assertTrue(value['ready']);self.assertEqual(value['model'],'gpt-6-luna')
        self.assertNotIn('api_key',value);self.assertNotIn('sessionId',value);self.assertNotIn('lastError',value)


class DomainSafetyMatrixTests(unittest.TestCase):
    def test_all_domains_accept_known_state_reject_stale_state_and_defer_unknown_inventory(self):
        with tempfile.TemporaryDirectory() as folder:
            for domain in DOMAINS:
                with self.subTest(domain=domain):
                    service=StrategyService(folder,clock=lambda:1000)
                    try:
                        service.configure(enabled=True,live=False)
                        raw=scenario(domain);service.update(raw,GameState.from_message(raw))
                        d=service.decision();offer=next(o for o in d['offers'] if o['domain']==domain and o['op']!='wait')
                        body={'plan_id':'matrix-'+domain,'decision_id':d['id'],'context_id':d['context_id'],
                              'offer_id':offer['id'],'budget':offer['cost']}
                        self.assertEqual(service.submit(body)['status'],'observed')
                        # Rebuild a new decision, then make the native room identity stale.
                        service.resolved.clear();service.update(raw,GameState.from_message(raw))
                        d=service.decision();offer=next(o for o in d['offers'] if o['domain']==domain and o['op']!='wait')
                        body.update(plan_id='stale-'+domain,decision_id=d['id'],context_id=d['context_id'],offer_id=offer['id'])
                        raw['room_index']+=1;service.update(raw,GameState.from_message(raw))
                        with self.assertRaises(StrategyError):service.submit(body)
                        service.pending=None;service.resolved.clear();raw['strategy']['inventory_known']=False
                        service.update(raw,GameState.from_message(raw));self.assertFalse(service.decision()['pending'])
                    finally:service.close()

if __name__=='__main__':unittest.main()
