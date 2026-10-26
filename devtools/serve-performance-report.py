"""Serve only the sanitized frozen report, without models or network proxies."""
from pathlib import Path
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
import argparse
root=Path(__file__).resolve().parents[1]/'docs/analysis/2026-10-27'
class Handler(SimpleHTTPRequestHandler):
 def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(root),**kwargs)
 def do_GET(self):
  if self.path=='/':self.path='/report.html'
  return super().do_GET()
 def end_headers(self):
  self.send_header('Cache-Control','no-cache');super().end_headers()
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8769);a=p.parse_args()
 server=ThreadingHTTPServer(('127.0.0.1',a.port),Handler)
 print('Frozen report: http://127.0.0.1:'+str(a.port)+'/',flush=True)
 try:server.serve_forever()
 except KeyboardInterrupt:pass
 finally:server.server_close()
