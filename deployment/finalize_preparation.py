"""Capture the final preparation manifest, locks and static entry-point checks."""
from pathlib import Path
import ast,csv,datetime,hashlib,json,os,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from runtime_environment import environment

def main():
    manifests={name:json.loads((ROOT/'.setup'/f'{name}.result.json').read_text(encoding='utf-8')) for name in ['readiness','avatar','asset-check','models','environments','extras','configuration','runtime-assets']}
    if not all(value.get('ok',False) for value in manifests.values()):raise RuntimeError('Some preparation checks have not passed')
    for source in list((ROOT/'deployment').glob('*.py'))+list((ROOT/'scripts').glob('*.py'))+list((ROOT/'integration').glob('*.py')):
        ast.parse(source.read_text(encoding='utf-8-sig'),filename=str(source))
    for name in ('livetalking','tts'):
        text=(ROOT/'logs'/f'{name}_freeze.log').read_text(encoding='utf-8').strip()
        (ROOT/'configs'/f'requirements-lock-{name}.txt').write_text('--extra-index-url https://download.pytorch.org/whl/cu128\n'+text+'\n',encoding='utf-8')
    records=json.loads((ROOT/'.setup/model-download.results.json').read_text(encoding='utf-8'))
    records+=manifests['runtime-assets']['models']+manifests['extras']['files']
    with (ROOT/'模型文件清单.csv').open('w',encoding='utf-8-sig',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=['local_path','bytes','sha256_local','repo','revision','url','sha256_upstream'],extrasaction='ignore');writer.writeheader();writer.writerows(records)
    gpu=subprocess.check_output(['nvidia-smi','--query-gpu=name,memory.total,memory.free,driver_version','--format=csv,noheader'],text=True).strip()
    manifest={'ok':True,'prepared_at':datetime.datetime.now().astimezone().isoformat(),'machine':os.environ.get('COMPUTERNAME'),'project':str(ROOT),'selected_scheme':1,'stack':['LiveTalking','MuseTalk 1.5','GPT-SoVITS v2 / v2ProPlus','OBS 31.1.2'],
        'gpu':gpu,'native_windows':True,'virtualization_used':False,'model_and_demo_download_files':len(records),'model_and_demo_download_bytes':sum(item['bytes'] for item in records),
        'dependency_checks':len(manifests['readiness']['checks']),'module_imports':sum(len(json.loads((ROOT/'.setup'/f'{name}.imports.json').read_text(encoding='utf-8'))) for name in ('livetalking','tts')),
        'asset_checks':len(manifests['asset-check']['checks']),'demo_avatar':manifests['avatar'],
        'services_started':False,'speech_synthesis_tested':False,'talking_head_inference_tested':False,'obs_preview_tested':False,'cloud_llm_called':False,'live_broadcast_started':False,
        'pending_configuration':['User cloud LLM endpoint, API key, exact model ID and protocol before chat testing','Own avatar/voice and target platform settings before production'],
        'runbook':'docs/DEPLOYMENT.md','entrypoint':'Avatar.cmd','powershell_entrypoint':'Start-Avatar.ps1','hash_manifest':'模型文件清单.csv','dependencies_lock':['configs/requirements-lock-livetalking.txt','configs/requirements-lock-tts.txt']}
    (ROOT/'.setup/preparation-complete.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
