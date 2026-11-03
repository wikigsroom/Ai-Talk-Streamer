"""Check the actual native K02 / O07 / F07 MC installation without inference.

This generates fresh MC preparation checks. It never copies historical manifests
or claims that obsolete GPT-SoVITS/OBS dependencies were installed or tested.
"""
from pathlib import Path
import ast,json,os,platform,subprocess,sys,time
from mc_deployment import installed_source_identity, inside, read, require, sha, digest, model_runtime_rows
from native_operation import atomic_json, operation

ROOT=Path(__file__).resolve().parents[1]


def run(root=ROOT):
    root=Path(root).resolve()
    require(os.name=='nt' and platform.node().casefold()=='desktop-2qqpn1h', 'MC_NATIVE_RUNTIME_REQUIRES_REMOTE_3080')
    source=installed_source_identity(root)
    dependencies=read(inside(root,'.setup/mc-offline-dependencies.json'),limit=64*1024*1024)
    require(dependencies['installation_root']==str(root) and len(dependencies['source_snapshot_sha256'])==64,
            'MC_READINESS_DEPENDENCY_SOURCE_MISMATCH')
    checks=[]
    def check(name,fn):
        started=time.monotonic()
        atomic_json(root,root/'.setup/mc-readiness-progress.json',{'phase':name,'running':True,'at':time.time(),'checks':checks})
        try: details=fn();checks.append({'name':name,'ok':True,'details':details})
        except Exception as error:checks.append({'name':name,'ok':False,'error_type':type(error).__name__,'error':str(error)[:500]})
        checks[-1]['elapsed_seconds']=time.monotonic()-started
        atomic_json(root,root/'.setup/mc-readiness-progress.json',{'phase':name,'running':False,'at':time.time(),'checks':checks})
    def model_files():
        lock=read(root/'configs/releases/rtx3080-k02-runtime-lock.json');rows={r['path']:r for r in model_runtime_rows(lock)}
        archive=[r['path'] for r in lock['model_files'] if r['path'] not in rows]
        for name,pin in dependencies['files'].items():
            if name.startswith('src/LiveTalking/models/') or name.endswith(('/latents.pt','/coords.pkl','/mask_coords.pkl')):
                rows[name]={'path':name,**pin}
        for name,pin in rows.items():
            path=inside(root,name)
            require(path.stat().st_size==pin['bytes'] and sha(path)==pin['sha256'],'MC_READINESS_MODEL_PIN_CHANGED')
        return {'files':len(rows),'inventory_sha256':digest(rows),
                'archive_metadata_missing':[name for name in archive if not inside(root,name).is_file()],
                'historical_provenance_reconstructed':False}
    def assets():
        voices=read(root/'configs/resident-tts.json');config=read(root/'configs/livetalking.yaml')
        require(config['tts']=='resident-local' and config['batch_size']==4,'MC_READINESS_K02_PROFILE')
        require(voices['default_voice_id']=='O07' and set(voices['voices'])=={'O07','F07'},'MC_READINESS_VOICES')
        require(sha(inside(root,voices['reference_audio']))==voices['reference_sha256'],'MC_READINESS_VOICE_REFERENCE')
        bank=inside(root,'src/LiveTalking/data/avatars/'+config['avatar_id'])
        frames=sorted((bank/'full_imgs').glob('*.png'));masks=sorted((bank/'mask').glob('*.png'))
        require(frames and len(frames)==len(masks) and (bank/'latents.pt').is_file(),'MC_READINESS_AVATAR_BANK')
        for group in [frames,masks]:
            for path in [group[0],group[-1]]:
                require(path.read_bytes()[:8]==b'\x89PNG\r\n\x1a\n','MC_READINESS_AVATAR_IMAGE')
        return {'avatar_id':config['avatar_id'],'frames':len(frames),'masks':len(masks),'reference_sha256':voices['reference_sha256'],
                'scope':'INDEX_COUNTS_AND_BOUNDARY_PNG_HEADERS_NOT_RENDERED_MOTION_ACCEPTANCE'}
    def syntax():
        files=[p for folder in ['scripts','deployment','integration'] for p in (root/folder).glob('*.py')]
        for path in files:ast.parse(path.read_text(encoding='utf-8-sig'),filename=str(path))
        return {'files':len(files)}
    def runtime_projection():
        from mc_runtime_projection import validate
        files=validate(root,source)
        return {'files':files,'scope':'EXACT_BYTES_IMPORTED_BY_LIVETALKING_NOT_MODEL_INFERENCE'}
    def imports(name,modules,source_path=None):
        from runtime_environment import environment
        executable=root/('runtime/'+name+'/Scripts/python.exe')
        script='import importlib,json,sys;'
        if source_path:script+='sys.path[:0]='+repr([str(root/source_path),str(root/source_path/'src')])+';'
        script+='modules='+repr(modules)+';loaded=[importlib.import_module(m) for m in modules];print(json.dumps({"modules":modules,"python":sys.version.split()[0]}))'
        logs=root/'logs';logs.mkdir(exist_ok=True);log=logs/('mc-readiness-'+name.replace('/','-')+'.log')
        env=environment(cpu=True)
        with log.open('wb') as out:
            process=subprocess.run([str(executable),'-X','utf8','-B','-c',script],cwd=root,env=env,stdout=out,stderr=subprocess.STDOUT,
                                   timeout=180,creationflags=0x08000000)
        require(process.returncode==0,'MC_READINESS_IMPORT_FAILED:'+log.relative_to(root).as_posix())
        return {'exit_code':process.returncode,'log':log.relative_to(root).as_posix(),'modules':modules,'cpu_only':True}
    with operation(root,'mc-native-readiness'):
        check('source_syntax',syntax);check('runtime_source_projection',runtime_projection)
        check('pinned_model_bytes',model_files);check('approved_reference_and_avatar_index',assets)
        check('avatar_cpu_imports',lambda:imports('livetalking',['torch','cv2','diffusers','transformers','aiortc','soundfile','psutil']))
        check('O07_cpu_imports',lambda:imports('tts-benchmark/omnivoice',['torch','soundfile','omnivoice'],'src/tts-benchmark/omnivoice'))
        check('F07_cpu_imports',lambda:imports('tts-benchmark/f5',['torch','soundfile','f5_tts.api'],'src/tts-benchmark/f5'))
        check('public_collector_imports',lambda:imports('platforms',['aiohttp','blivedm']))
        result={'ok':all(row['ok'] for row in checks),'schema_version':1,'checks':checks,
                'classification':'MC_NATIVE_ASSET_AND_CPU_IMPORT_CHECKS_NOT_REAL_GAME_INFERENCE_ACCEPTANCE',
                'source_snapshot_sha256':source['snapshot_sha256'],'dependency_import_snapshot_sha256':dependencies['source_snapshot_sha256'],
                'models_loaded':False,'model_forward_run':False,
                'avatar_inference_run':False,'tts_synthesis_run':False,'public_broadcast_started':False,'real_acceptance_passed':0}
        atomic_json(root,root/'.setup/readiness.result.json',result)
        atomic_json(root,root/'.setup/asset-check.result.json',result)
    return result


if __name__=='__main__':
    result=run();print(json.dumps(result,ensure_ascii=False));sys.exit(0 if result['ok'] else 1)
