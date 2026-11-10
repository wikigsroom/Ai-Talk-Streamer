"""Run the startup sequence against the narrator's actual public HTTP shapes."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
import urllib.request
from urllib.parse import urlparse

from integration.issac.application import Application
from integration.issac.common import AdmissionError


class ApplicationStartupTests(unittest.TestCase):
    def test_narrator_health_precedes_real_channel_probe_and_game_tools(self):
        requests=[]
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                values={
                    '/health':{'dsh_ready':True},
                    '/api/dsh/status':{'health':{'dsh_ready':True}},
                    '/status':{'service':'issac-native-game'},
                }
                self.send_response(200);self.end_headers()
                self.wfile.write(json.dumps(values[self.path]).encode())
            def log_message(self,*_):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            app=object.__new__(Application)
            app.config={'native_paths':{'node':'node','game_python':'game','media_python':'media','voice_python':'voice'}}
            app.root='.';app.children={};app.stop_event=threading.Event();app.candidate={'candidate_id':'test-round'}
            app.prepare=Mock();app.persist=Mock();app.audit=Mock()
            def child(name,*_,**__):app.children[name]=(SimpleNamespace(poll=lambda:None),{})
            app.child=child
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            def http(url,body=None,**_):
                if url.endswith('/api/dsh/probe'):
                    self.assertIn('/health',requests)
                    return {'passed':True,'model':'gpt-6.1-sol','protocol':'responses'}
                if url.endswith('/api/dsh/issac/core/status'):
                    return {'actor_id':'naimei','strategic_owner':'naimei_core_dsh','independent_strategy_host':False,
                        'registeredTools':['isaac_get_state','isaac_get_decision','isaac_lookup','isaac_submit_plan','isaac_wiki_query'],
                        'prompt':{'requested_edition':'rep','complete':True}}
                path=urlparse(url).path
                with opener.open(f'http://127.0.0.1:{server.server_port}'+path,timeout=1) as response:return json.load(response)
            app.http=http
            actual_wait=app.wait_ready
            app.wait_ready=lambda name,url,*_:actual_wait(name,url,timeout=.1)
            app.start()
            self.assertEqual(app.stage,'running_candidate_not_accepted')
            self.assertNotIn('/api/dsh/status',requests)
            self.assertEqual(set(app.children),{'gpu-geometry','game-controller','voice','flashhead','studio','narrator'})
            self.assertEqual(next(iter(app.children)), 'gpu-geometry')
            # The public status envelope remains different from the explicit
            # health endpoint; accepting it accidentally caused the real timeout.
            with self.assertRaisesRegex(AdmissionError,'READY_DEADLINE_NARRATOR'):
                actual_wait('narrator',f'http://127.0.0.1:{server.server_port}/api/dsh/status',timeout=.1)
        finally:
            server.shutdown();server.server_close();thread.join(2)


if __name__=='__main__':unittest.main()
