"""Launch a project-only preparation job detached from the MCP shell."""
from pathlib import Path
import datetime,json,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
name=sys.argv[1]
scripts={'environments':'prepare_environments.py','extras':'prepare_extras.py','configure':'configure_stack.py','readiness':'readiness.py','runtime-assets':'prepare_runtime_assets.py','ffmpeg7':'prepare_ffmpeg7.py','avatar':'../scripts/prepare_avatar.py','asset-check':'asset_probe.py'}
if name not in scripts:raise SystemExit('Unknown preparation job')
out=(ROOT/'logs'/f'{name}.stdout.log').open('w',encoding='utf-8')
err=(ROOT/'logs'/f'{name}.stderr.log').open('w',encoding='utf-8')
interpreter=str(ROOT/'runtime/livetalking/Scripts/python.exe') if name=='avatar' else sys.executable
env=None
if name=='asset-check':
    sys.path.insert(0,str(ROOT/'scripts'))
    from runtime_environment import environment
    env=environment(cpu=True)
    interpreter=str(ROOT/'runtime/tts/Scripts/python.exe')
process=subprocess.Popen([interpreter,'-X','utf8','-B',str(ROOT/'deployment'/scripts[name])],cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=err,close_fds=True,creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP)
info={'pid':process.pid,'started':datetime.datetime.now().astimezone().isoformat(),'script':scripts[name]}
(ROOT/'.setup'/f'{name}.process.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(info,ensure_ascii=False))
