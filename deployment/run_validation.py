"""Dispatch a named validation with a durable process record."""
from pathlib import Path
import datetime,json,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from runtime_environment import environment
name=sys.argv[1]
jobs={'compute':('livetalking','probe_compute.py'),'rtc':('livetalking','probe_rtc.py'),'portrait':('livetalking','prepare_avatar.py'),'actual':('livetalking','probe_actual_inference.py')}
envname,script=jobs[name]
process=subprocess.Popen([str(ROOT/'runtime'/envname/'Scripts/python.exe'),'-X','utf8','-B',str(ROOT/'scripts'/script)],cwd=ROOT,env=environment(),stdin=subprocess.DEVNULL,stdout=(ROOT/'logs'/f'{name}-test.stdout.log').open('w',encoding='utf-8'),stderr=(ROOT/'logs'/f'{name}-test.stderr.log').open('w',encoding='utf-8'),close_fds=True,creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP)
info={'pid':process.pid,'at':datetime.datetime.now().astimezone().isoformat(),'script':script}
(ROOT/'.setup'/f'{name}-test.process.json').write_text(json.dumps(info),encoding='utf-8');print(json.dumps(info))
