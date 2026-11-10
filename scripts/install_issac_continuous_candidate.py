"""Stage/test a frozen candidate, then replace its owners without closing Isaac."""
from pathlib import Path
import argparse,hashlib,json,os,shutil,subprocess,sys,time,urllib.request,uuid,zipfile


PINNED_ROOT=Path('C:/dev/虚拟数字人直播/issac')


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def put(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.tmp');temporary.write_text(canonical(value)+'\n','utf8');os.replace(temporary,path)


def pinned(root):
    if os.name!='nt' or root.resolve()!=PINNED_ROOT.resolve():raise ValueError('PINNED_NATIVE_INSTALLATION_REQUIRED')


def source_path(stage,name):
    parts=Path(name).parts;path=(stage/name).resolve()
    if (not parts or Path(name).is_absolute() or ':' in name or '\\' in name
            or not path.is_relative_to(stage.resolve()) or '..' in parts or 'private' in parts
            or parts[0] in {'runtime','models','game','state','operations','.setup','outputs','cache'}):
        raise ValueError('FROZEN_SOURCE_PATH_REJECTED')
    return path


def validate(root,stage,manifest):
    pinned(root)
    if manifest.get('branch')!='issac' or not manifest.get('all_round_code_complete') or manifest.get('tests_started_at_freeze') is not False:
        raise ValueError('WHOLE_ROUND_FREEZE_REQUIRED')
    for row in manifest['files']:
        path=source_path(stage,row['path'])
        if path.stat().st_size!=row['bytes'] or sha(path)!=row['sha256']:raise ValueError('FROZEN_STAGED_SOURCE_CHANGED')


def prepare(root,archive,expected):
    pinned(root)
    if sha(archive)!=expected:raise ValueError('TRANSFERRED_SOURCE_CHECKSUM_MISMATCH')
    stage=root/'operations/continuous-install'/uuid.uuid4().hex/'source';stage.mkdir(parents=True)
    with zipfile.ZipFile(archive) as source:
        manifest=json.loads(source.read('.source-manifest.json'))
        names={row['path'] for row in manifest['files']}
        if len(names)!=len(manifest['files']) or set(source.namelist())!=names|{'.source-manifest.json'}:raise ValueError('FROZEN_MEMBERS_DIFFER')
        for name in names:
            target=source_path(stage,name)
            target.parent.mkdir(parents=True,exist_ok=True)
            with source.open(name) as incoming,target.open('xb') as output:shutil.copyfileobj(incoming,output,1024**2)
    validate(root,stage,manifest)
    result={'stage':str(stage),'candidate_id':manifest['candidate_id'],'archive':str(archive),
        'archive_sha256':expected,'manifest':manifest,'manifest_sha256':hashlib.sha256(canonical(manifest).encode()).hexdigest()}
    receipt=stage.parent/'prepared.json';put(receipt,result)
    return {'prepared':True,'receipt':str(receipt),'candidate_id':manifest['candidate_id']}


def apply(root,prepared,regressions):
    import psutil
    record=json.loads(prepared.read_text('utf8'));stage=Path(record['stage']);manifest=record['manifest']
    validate(root,stage,manifest)
    if (not stage.is_relative_to(root/'operations/continuous-install')
            or sha(record['archive'])!=record['archive_sha256']
            or hashlib.sha256(canonical(manifest).encode()).hexdigest()!=record['manifest_sha256']):
        raise ValueError('PREPARED_SOURCE_PROVENANCE_CHANGED')
    with zipfile.ZipFile(record['archive']) as archive:
        if json.loads(archive.read('.source-manifest.json'))!=manifest:raise ValueError('ARCHIVED_MANIFEST_CHANGED')
    proof=json.loads(regressions.read_text('utf8'))
    if (proof.get('candidate_id')!=manifest['candidate_id'] or proof.get('complete') is not True
            or proof.get('passed') is not True or len(proof.get('results',[]))!=6
            or any(v['exit_code']!=0 for v in proof['results'])):raise ValueError('SIX_FROZEN_REGRESSION_SUITES_REQUIRED')
    old=json.loads((root/'.setup/source-manifest.json').read_text('utf8'))
    origin=json.loads((root/'.setup/deployment-origin.json').read_text('utf8'))
    if hashlib.sha256(canonical(old).encode()).hexdigest()!=origin['source_manifest_sha256']:raise ValueError('PRIOR_SOURCE_PROVENANCE_CHANGED')
    before={row['path']:row for row in old['files']};after={row['path']:row for row in manifest['files']}
    for name,row in before.items():
        if sha(root/name)!=row['sha256']:raise ValueError('PRIOR_SOURCE_CHANGED')
    if set(before)-set(after):raise ValueError('LIVE_MIGRATION_CANNOT_RETIRE_SOURCE')
    if any((root/name).exists() for name in set(after)-set(before)):raise ValueError('UNTRACKED_INSTALL_DESTINATION_CONFLICT')
    for name,row in before.items():
        if (name.startswith('web/issac/') or name=='configs/issac/programme-layout.json') and row['sha256']!=after[name]['sha256']:
            raise ValueError('LIVE_OFFICIAL_SOURCE_MUST_REMAIN_IDENTICAL')
    if shutil.disk_usage(root).free<1024**3:raise ValueError('SOURCE_ROLLBACK_CAPACITY_REQUIRED')
    backup=stage.parent/'prior-source';backup.mkdir(exist_ok=False)
    changed=[row for row in manifest['files'] if row['path'] not in before or row['sha256']!=before[row['path']]['sha256']]
    for row in changed:
        destination=root/row['path']
        if destination.exists():
            saved=backup/row['path'];saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(destination,saved)
    for name in ['source-manifest.json','deployment-origin.json','candidate.json']:shutil.copy2(root/'.setup'/name,backup/name)
    sys.path.insert(0,str(stage))
    from integration.issac.native_game import NativeGame
    from integration.issac.continuity import NO_AUTOMATIC_PAUSE_GUARD
    from integration.issac.saves import SaveProtection
    protection=SaveProtection(root);protection.verify()
    token=(root/'private/issac/bridge-token.txt').read_text('ascii').strip()
    http=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def api(port,path,body=None,timeout=5):
        request=urllib.request.Request('http://127.0.0.1:'+str(port)+path,data=None if body is None else json.dumps(body).encode(),
            headers={'Content-Type':'application/json','X-Isaac-Token':token})
        with http.open(request,timeout=timeout) as response:return json.load(response)
    current=api(9534,'/status')
    if current.get('manual_override') or (current.get('live_cycle') or {}).get('phase')=='operator_paused':raise ValueError('EXPLICIT_OPERATOR_CONTROL_PRESERVED')
    if (current.get('live_cycle') or {}).get('phase')=='natural_paused':
        api(9534,'/control',{'action':'natural_resume','expected_revision':current['control_revision']},timeout=15)
    deadline=time.monotonic()+600
    while True:
        view=api(9532,'/query?topic=state');room=(view.get('data') or {}).get('room') or {}
        if view.get('connected') and view.get('age_ms',9999)<1500 and room.get('clear') and not room.get('paused') and not room.get('dead'):break
        if time.monotonic()>=deadline:raise ValueError('WAITING_FOR_OBSERVED_CLEAR_ROOM_WITHOUT_PAUSING')
        time.sleep(.25)
    registry=json.loads((root/'state/issac-stream/application.json').read_text('utf8'))
    game=next(row for row in registry['processes'] if row['name']=='isaac-game')
    process=psutil.Process(game['pid'])
    if process.create_time()!=game['created_at'] or sha(process.exe())!=game['executable_sha256']:raise ValueError('GAME_IDENTITY_CHANGED')
    native=NativeGame(root)
    try:
        native.attach(game['pid']);first=native.observe();protection.admit_current(native.process,native.progress())
        if first['paused']:raise ValueError('UNPAUSED_GAME_REQUIRED')
        if native.rpc('evaluate',NO_AUTOMATIC_PAUSE_GUARD)!='automatic pause forbidden':raise ValueError('LIVE_PAUSE_GUARD_REQUIRED')
    finally:
        if native.session:native.session.detach()
    def terminate_owned(row):
        try:
            q=psutil.Process(row['pid'])
            if q.create_time()!=row['created_at'] or Path(q.exe()).resolve()!=Path(row['executable']).resolve() or sha(q.exe())!=row['executable_sha256']:
                raise ValueError('MIGRATION_COMPONENT_IDENTITY_CHANGED')
            q.terminate();q.wait(8)
        except psutil.NoSuchProcess:pass
        if row.get('launcher_pid') and row['launcher_pid']!=row['pid']:
            try:
                q=psutil.Process(row['launcher_pid'])
                if (q.create_time()!=row['launcher_created_at'] or Path(q.exe()).resolve()!=Path(row['launcher_executable']).resolve()
                        or sha(q.exe())!=row['launcher_sha256']):raise ValueError('MIGRATION_LAUNCHER_IDENTITY_CHANGED')
                q.terminate();q.wait(8)
            except psutil.NoSuchProcess:pass
    parent=psutil.Process(registry['pid'])
    if parent.create_time()!=registry['created_at'] or not Path(parent.exe()).resolve().is_relative_to(root/'runtime') or 'integration.issac.application' not in parent.cmdline():
        raise ValueError('MIGRATION_APPLICATION_IDENTITY_CHANGED')
    parent.terminate();parent.wait(8)
    # The already loaded voice, mouth model, GPU worker, official encoder and game remain alive.
    for row in registry['processes']:
        if row['name'] in {'game-controller','studio','narrator'}:terminate_owned(row)
    new_origin={**origin,'source_commit':manifest['source_commit'],'archive_sha256':record['archive_sha256'],
        'source_manifest_sha256':record['manifest_sha256'],'installed_at_unix':time.time(),'verified_files':len(manifest['files']),
        'previous_source_backup':str(backup),'previous_candidate_id':old['candidate_id'],'application_accepted':False,
        'continuous_game_migration':True,'preserved_game_pid':game['pid'],'preserved_game_created_at':game['created_at']}
    try:
        for row in changed:
            destination=root/row['path'];destination.parent.mkdir(parents=True,exist_ok=True)
            temporary=destination.with_name(destination.name+'.continuous-tmp');shutil.copy2(stage/row['path'],temporary);os.replace(temporary,destination)
            if sha(destination)!=row['sha256']:raise ValueError('INSTALLED_SOURCE_CHANGED')
        put(root/'.setup/source-manifest.json',manifest);put(root/'.setup/deployment-origin.json',new_origin)
        put(root/'.setup/candidate.json',{'id':manifest['candidate_id'],'source_commit':manifest['source_commit'],
            'source_manifest_sha256':record['manifest_sha256'],'accepted':False})
    except Exception:
        for row in changed:
            destination=root/row['path'];saved=backup/row['path']
            if saved.exists():shutil.copy2(saved,destination)
            elif destination.exists() and sha(destination)==row['sha256']:destination.unlink()
        for name in ['source-manifest.json','deployment-origin.json','candidate.json']:shutil.copy2(backup/name,root/'.setup'/name)
        put(stage.parent/'failure.json',{'game_left_running':True,'source_rolled_back':True,'old_interrupting_stack_not_started':True})
        raise
    from integration.issac.materials import inherit_reviewed_bank
    from integration.issac.livehime import Livehime
    from integration.issac.preparation import runtime_environment
    bank=inherit_reviewed_bank(root);Livehime(root).adopt_verified_running_owner()
    log=(stage.parent/'adopt-application.log').open('ab')
    child=subprocess.Popen([str(root/'runtime/isaac-native/Scripts/python.exe'),'-X','utf8','-B','-m','integration.issac.application',
        '--root',str(root),'--adopt-running'],cwd=root,env=runtime_environment(root,'game'),stdin=subprocess.DEVNULL,
        stdout=log,stderr=subprocess.STDOUT,creationflags=0x08000200,close_fds=True)
    deadline=time.monotonic()+180
    while True:
        try:
            if all(api(port,path,timeout=2).get('ready') is True for port,path in [(8062,'/health'),(3104,'/api/dsh/issac/core/status')]):break
        except Exception:pass
        if child.poll() is not None or time.monotonic()>=deadline:raise ValueError('ADOPTED_STACK_NOT_READY_GAME_LEFT_RUNNING')
        time.sleep(.5)
    api(9534,'/control',{'action':'adopt_live','pid':game['pid']},timeout=25)
    api(3104,'/api/dsh/issac/rehearsal/start',{},timeout=35)
    api(3104,'/api/dsh/platforms/bilibili/collector/start',{},timeout=12)
    last=api(9534,'/control',{'action':'observe'},timeout=5)['observation'];protection.verify()
    if psutil.Process(game['pid']).create_time()!=game['created_at'] or last['paused']:raise ValueError('GAME_CONTINUITY_NOT_CONFIRMED')
    result={'installed':True,'candidate_id':manifest['candidate_id'],'source_commit':manifest['source_commit'],
        'source_files_verified':len(manifest['files']),'game_pid':game['pid'],'game_created_at':game['created_at'],
        'first_native':first,'last_native':last,'game_stop_requested':False,'game_pause_requested':False,
        'official_process_restarted':False,'voice_model_restarted':False,'mouth_model_restarted':False,'body':bank}
    put(stage.parent/'installed.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=PINNED_ROOT)
    parser.add_argument('--archive',type=Path);parser.add_argument('--sha256');parser.add_argument('--prepared',type=Path)
    parser.add_argument('--regressions',type=Path);args=parser.parse_args()
    if args.prepared:result=apply(args.root.resolve(),args.prepared,args.regressions)
    else:result=prepare(args.root.resolve(),args.archive,args.sha256)
    print(json.dumps(result,ensure_ascii=False),flush=True)
