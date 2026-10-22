"""Run a bounded project stage with persistent logs and an exit-status record."""
from pathlib import Path
import argparse,datetime,json,os,subprocess,sys
from runtime_environment import ROOT,environment
TASKS={'encode':'encode_vertical_sources.py','motion':'analyze_vertical_motion.py','compare':'compare_vertical_faces.py','prepare':'prepare_vertical_avatar.py','compose':'compose_vertical_loop.py','record':'record_vertical_acceptance.py','tour':'record_motion_tour.py','scenarios':'record_scenario_tests.py','assemble':'assemble_motion_bank.py','package':'package_motion_materials.py'}
parser=argparse.ArgumentParser();parser.add_argument('task',choices=TASKS);parser.add_argument('--worker',action='store_true');parser.add_argument('arguments',nargs='*');args=parser.parse_intermixed_args()
state_path=ROOT/'.setup'/('vertical-task-'+args.task+'.json')
if not args.worker:
    if state_path.exists():
        old=json.loads(state_path.read_text(encoding='utf-8'))
        if old.get('status')=='running':
            import psutil
            if psutil.pid_exists(old['pid']):raise RuntimeError('This project stage is already running')
    log=ROOT/'logs'/('vertical-'+args.task+'.log');stream=log.open('a',encoding='utf-8')
    command=[str(ROOT/'runtime/livetalking/Scripts/python.exe'),'-X','utf8','-B',str(Path(__file__).resolve()),args.task,'--worker',*args.arguments]
    process=subprocess.Popen(command,cwd=ROOT,env=environment(),stdout=stream,stderr=stream,stdin=subprocess.DEVNULL,creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP)
    state={'status':'running','pid':process.pid,'task':args.task,'arguments':args.arguments,'log':str(log),'at':datetime.datetime.now().astimezone().isoformat()}
    state_path.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(state,ensure_ascii=False),flush=True)
else:
    command=[sys.executable,'-X','utf8','-B',str(ROOT/'scripts'/TASKS[args.task]),*args.arguments]
    result=subprocess.run(command,cwd=ROOT,env=environment())
    state={'status':'complete' if result.returncode==0 else 'failed','pid':os.getpid(),'task':args.task,'arguments':args.arguments,'exit_code':result.returncode,'at':datetime.datetime.now().astimezone().isoformat()}
    state_path.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(state,ensure_ascii=False),flush=True)
    sys.exit(result.returncode)
