"""Static preparation checks and CPU imports, without running avatar/TTS inference."""
from pathlib import Path
import ast,datetime,json,os,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from runtime_environment import environment
checks=[]

def record(name,ok,**extra):
    value={'name':name,'ok':bool(ok),**extra};checks.append(value)
    print(json.dumps(value,ensure_ascii=False),flush=True)

def command(name,args,env,cwd=ROOT,timeout=120):
    try:
        result=subprocess.run([str(x) for x in args],cwd=cwd,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
        (ROOT/'logs'/f'{name}.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
        record(name,result.returncode==0,returncode=result.returncode,log=f'logs/{name}.log',tail=(result.stdout+'\n'+result.stderr)[-2500:])
    except Exception as exc:record(name,False,error=str(exc))

def main():
    env=environment(cpu=True)
    for name in ['bootstrap','models','environments','extras','configuration','runtime-assets']:
        path=ROOT/'.setup'/f'{name}.result.json'
        value=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        good=(bool(value) and all(isinstance(item,dict) and not item.get('error') for item in value)) if isinstance(value,list) else value.get('ok',False)
        record(name+'_manifest',good)
    model_records=json.loads((ROOT/'.setup/model-download.results.json').read_text(encoding='utf-8'))
    missing=[r['local_path'] for r in model_records if not (ROOT/r['local_path']).exists() or (ROOT/r['local_path']).stat().st_size!=r['bytes']]
    record('model_files',not missing,files=len(model_records),missing=missing,download_sha256_verified=True)
    for name in ['livetalking','tts']:
        python=ROOT/'runtime'/name/'Scripts/python.exe'
        command(name+'_pip_check',[python,'-m','pip','check'],env)
        command(name+'_imports',[python,'-X','utf8','-B',ROOT/'deployment/import_probe.py',name],env,timeout=150)
        command(name+'_freeze',[python,'-m','pip','freeze'],env)
    for name in ['ffmpeg','ffmpeg-shared','ffmpeg7-shared']:
        binary=next((ROOT/'tools'/name).rglob('ffmpeg.exe'),None)
        record(name+'_binary',binary is not None)
        if binary:command(name+'_version',[binary,'-version'],env)
    obs=ROOT/'tools/obs/bin/64bit/obs64.exe'
    record('obs_portable',obs.exists() and (ROOT/'tools/obs/portable_mode.txt').exists() and (ROOT/'tools/obs/config/obs-studio/basic/scenes/Avatar_Local.json').exists())
    files=list((ROOT/'deployment').glob('*.py'))+list((ROOT/'scripts').glob('*.py'))+list((ROOT/'integration').glob('*.py'))
    failures=[]
    for file in files:
        try:ast.parse(file.read_text(encoding='utf-8-sig'),filename=str(file))
        except Exception as exc:failures.append({'path':str(file.relative_to(ROOT)),'error':str(exc)})
    record('python_source_syntax',not failures,files=len(files),failures=failures)
    result={'ok':all(c['ok'] for c in checks),'at':datetime.datetime.now().astimezone().isoformat(),'checks':checks,'scope':'installation metadata, file sizes, CPU imports and source syntax only','avatar_inference_run':False,'tts_synthesis_run':False,'cloud_llm_called':False,'obs_started':False}
    (ROOT/'.setup/readiness.result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('READINESS_DONE '+str(result['ok']),flush=True)
    if not result['ok']:raise SystemExit(1)

if __name__=='__main__':main()
