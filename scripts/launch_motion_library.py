from pathlib import Path
import json,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
state=ROOT/'.setup/material-library-progress.json'
if state.exists():
 import psutil
 old=json.loads(state.read_text(encoding='utf-8'))
 if old.get('status')=='running' and psutil.pid_exists(old.get('pid',0)):
  raise RuntimeError('Existing material generation is still running')
stream=(ROOT/'logs/material-library.log').open('a',encoding='utf-8')
process=subprocess.Popen([str(ROOT/'runtime/livetalking/Scripts/python.exe'),'-X','utf8','-B',str(ROOT/'scripts/generate_motion_library.py'),*sys.argv[1:]],cwd=ROOT,stdout=stream,stderr=stream,stdin=subprocess.DEVNULL,creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP)
print(json.dumps({'pid':process.pid,'log':'logs/material-library.log','arguments':sys.argv[1:]}))
