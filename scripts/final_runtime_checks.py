"""Save native environment locks and verify the installed, active stack."""
from pathlib import Path
import ast,datetime,json,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];uv=ROOT/'tools/uv/uv.exe'
result={'ok':True,'at':datetime.datetime.now().astimezone().isoformat(),'checks':[]}
for name in ('livetalking','tts'):
    python=ROOT/'runtime'/name/'Scripts/python.exe'
    process=subprocess.run([str(uv),'pip','check','--python',str(python)],capture_output=True,text=True,encoding='utf-8',errors='replace')
    result['checks'].append({'name':name+'_dependencies','ok':process.returncode==0,'output':process.stdout+process.stderr})
    process=subprocess.run([str(uv),'pip','freeze','--python',str(python)],capture_output=True,text=True,encoding='utf-8',errors='replace',check=True)
    target=ROOT/'configs'/('requirements-'+name+'-verified.txt');target.write_text(process.stdout,encoding='utf-8')
paths=list((ROOT/'scripts').glob('*.py'))+list((ROOT/'integration').glob('*.py'))
for path in paths:ast.parse(path.read_text(encoding='utf-8-sig'),filename=str(path))
result['checks'].append({'name':'project_python_syntax','ok':True,'files':len(paths)})
result['ok']=all(item['ok'] for item in result['checks'])
(ROOT/'.setup/final-checks.result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False),flush=True)
sys.exit(0 if result['ok'] else 1)
