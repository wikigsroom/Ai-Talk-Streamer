"""Upgrade only this task's static result server to support media byte ranges."""
import sys,os,subprocess,json,socket,time
from pathlib import Path
R=Path('C:/dev/虚拟数字人直播');W=R/'operations/k01-k05-60s-20261028';O=R/'outputs/lipsync-k01-k05-60s-20261028'
if '--serve' in sys.argv:
 import http.server,functools
 from range_http import MediaHandler
 http.server.ThreadingHTTPServer(('0.0.0.0',8035),functools.partial(MediaHandler,directory=str(O))).serve_forever()
else:
 import psutil
 for process in psutil.process_iter(['pid','name','cmdline']):
  try:
   args=process.info['cmdline'] or []
   if 'http.server' in args and '8035' in args and str(O) in args:
    process.terminate();process.wait(timeout=8)
   elif str(W/'serve_remote_review.py') in args and '--serve' in args:
    print('Existing media-range result server retained.');sys.exit(0)
  except (psutil.NoSuchProcess,psutil.AccessDenied):continue
 with (W/'remote-review-http.log').open('ab') as log:
  p=subprocess.Popen([sys.executable,'-X','utf8','-B',str(__file__),'--serve'],cwd=str(O),stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
 (O/'http-process.json').write_text(json.dumps({'pid':p.pid,'port':8035,'root':str(O),'byte_ranges':True},ensure_ascii=False),encoding='utf-8');print(p.pid)
