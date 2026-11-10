"""Loopback-only DSH game API. It never constructs a second game bridge."""
from __future__ import annotations
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
from urllib.parse import urlparse, parse_qs
import threading
from .strategy import StrategyError

from pathlib import Path
import urllib.request

PAGE = Path(__file__).with_name('strategy_dashboard.html').read_text(encoding='utf8')


def host_status():
    # Read-only, fixed loopback destination, explicit public fields only.
    try:
        with urllib.request.urlopen('http://127.0.0.1:9533/status', timeout=.4) as response:
            raw = json.load(response)
        return {k: raw.get(k) for k in ('ready', 'dshVersion', 'model', 'automatic', 'busy', 'turns', 'failures')}
    except (OSError, ValueError): return {'ready': False}



class StrategyServer:
    def __init__(self, service, token: str, port=9532, *, wiki=None, control=None):
        outer = self
        self.service, self.token = service, token

        class Handler(BaseHTTPRequestHandler):
            def send_json(self, status, value):
                payload = json.dumps(value, ensure_ascii=False).encode('utf8')
                self.send_response(status); self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(payload))); self.send_header('Cache-Control', 'no-store')
                self.end_headers(); self.wfile.write(payload)

            def do_GET(self):
                url = urlparse(self.path); query = parse_qs(url.query)
                try:
                    if url.path == '/':
                        self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8'); self.end_headers(); self.wfile.write(PAGE.encode('utf8')); return
                    if url.path == '/status': value = service.status()
                    elif url.path == '/host-status': value = host_status()
                    elif url.path == '/query': value = service.query(query.get('topic', ['state'])[0])
                    elif url.path == '/decision': value = service.decision()
                    elif url.path == '/wiki-context': value = service.wiki_context()
                    elif url.path == '/events': value = service.read_events(int(query.get('after', [0])[0]))
                    elif url.path == '/lookup': value = service.lookup(query.get('kind', ['domain'])[0], query.get('id', ['route'])[0])
                    else: self.send_json(404, {'error': 'not found'}); return
                    self.send_json(200, value)
                except (ValueError, TypeError, KeyError) as error: self.send_json(400, {'error': str(error)})

            def do_POST(self):
                if not hmac.compare_digest(self.headers.get('X-Isaac-Token', ''), token):
                    self.send_json(403, {'error': 'local authorization required'}); return
                if self.headers.get('Origin'):
                    self.send_json(403, {'error': 'browser mutations disabled'}); return
                try:
                    length = int(self.headers.get('Content-Length', 0))
                    if not 0 < length <= 32768: raise StrategyError('invalid request size')
                    body = json.loads(self.rfile.read(length))
                    if not isinstance(body, dict): raise StrategyError('object required')
                    if self.path == '/plan': result = service.submit(body)
                    elif self.path == '/wiki':
                        if wiki is None or set(body) != {'query','context'}:
                            raise StrategyError('structured Wiki query and bound context required')
                        result = wiki.execute(body['query'], body['context'])
                    elif self.path == '/control':
                        if type(body.get('enabled')) is not bool or type(body.get('live', False)) is not bool:
                            raise StrategyError('boolean enabled/live required')
                        result = control(body) if control is not None else service.configure(enabled=body['enabled'], live=body.get('live', False))
                    else: self.send_json(404, {'error': 'not found'}); return
                    self.send_json(200, result)
                except (ValueError, TypeError, KeyError) as error: self.send_json(400, {'error': str(error)})

            def log_message(self, *_args): pass

        self.server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self): self.thread.start()
    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)
