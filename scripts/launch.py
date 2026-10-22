"""Native Windows entry points for the prepared local avatar stack."""
from pathlib import Path
import argparse,json,os,socket,subprocess,sys,time
from runtime_environment import ROOT,environment

def port_open(port):
    with socket.socket() as sock:
        sock.settimeout(.5)
        return sock.connect_ex(('127.0.0.1',port))==0

def gpu_free():
    value=subprocess.check_output(['nvidia-smi','--query-gpu=memory.free','--format=csv,noheader,nounits'],text=True)
    return int(value.splitlines()[0])

def state():
    data={}
    for name in ('bootstrap','models','environments','extras','configuration','runtime-assets','readiness','asset-check','avatar'):
        path=ROOT/'.setup'/f'{name}.result.json'
        value=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        data[name]=(bool(value) and all(isinstance(item,dict) and not item.get('error') for item in value)) if isinstance(value,list) else value.get('ok',False)
    env=environment()
    data['cloud_llm_configured']=all(env.get(key,'').strip() for key in ('AVATAR_LLM_BASE_URL','AVATAR_LLM_API_KEY','AVATAR_LLM_MODEL'))
    data['gpu_free_mib']=gpu_free()
    data['ports']={'tts_9880':port_open(9880),'avatar_8010':port_open(8010)}
    return data

def require_prepared():
    for name in ('readiness','asset-check'):
        path=ROOT/'.setup'/f'{name}.result.json'
        if not path.exists() or not json.loads(path.read_text(encoding='utf-8'))['ok']:
            raise RuntimeError(f'Preparation checks have not passed; inspect .setup/{name}.result.json')

def start_service(name,profile='v2',minimum=12):
    require_prepared()
    free=gpu_free()
    if free<minimum*1024:raise RuntimeError(f'Only {free} MiB GPU memory is free; need {minimum} GiB. Existing applications are left running.')
    env=environment()
    if name=='tts':
        port=9880;cwd=ROOT/'src/GPT-SoVITS';python=ROOT/'runtime/tts/Scripts/python.exe'
        args=[str(python),'-X','utf8','-B',str(cwd/'api_v2.py'),'-a','127.0.0.1','-p',str(port),'-c',str(ROOT/'configs'/f'tts-{profile}.yaml')]
    else:
        port=8010;cwd=ROOT/'src/LiveTalking';python=ROOT/'runtime/livetalking/Scripts/python.exe'
        config=json.loads((ROOT/'configs/livetalking.yaml').read_text(encoding='utf-8-sig'))
        if not (cwd/'data/avatars'/config['avatar_id']/'latents.pt').exists():raise RuntimeError('Prepare the selected avatar first.')
        args=[str(python),'-X','utf8','-B',str(cwd/'app.py'),'--config',str(ROOT/'configs/livetalking.yaml')]
    if port_open(port):raise RuntimeError(f'Port {port} is already in use; no duplicate process was started.')
    stdout=(ROOT/'logs'/f'{name}.runtime.stdout.log').open('a',encoding='utf-8')
    stderr=(ROOT/'logs'/f'{name}.runtime.stderr.log').open('a',encoding='utf-8')
    process=subprocess.Popen(args,cwd=cwd,env=env,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,close_fds=True,creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP)
    path=ROOT/'.setup/services.json'
    info=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    info[name]={'pid':process.pid,'command':args,'started':time.time()};path.write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'service':name,'pid':process.pid,'port':port,'logs':str(ROOT/'logs')},ensure_ascii=False))

def stop_services(only=None):
    import psutil
    path=ROOT/'.setup/services.json'
    info=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    for name,entry in list(info.items()):
        if only and name!=only:continue
        expected=entry['command'][4].casefold()
        owned=[]
        for process in psutil.process_iter(['pid','exe','cmdline']):
            try:
                if not Path(process.info['exe'] or '').resolve().is_relative_to(ROOT):continue
                if expected not in [arg.casefold() for arg in (process.info['cmdline'] or [])]:continue
                if process.create_time()+15<entry['started']:continue
                owned.append(process)
            except (psutil.NoSuchProcess,psutil.AccessDenied):continue
        for process in owned:
            try:process.terminate()
            except psutil.NoSuchProcess:pass
        psutil.wait_procs(owned,timeout=10)
        print('Stopped '+name+' ('+str(len(owned))+' project processes)')
        del info[name]
    path.write_text(json.dumps(info),encoding='utf-8')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['status','precheck','prepare-avatar','start-tts','start-avatar','start-obs','stop','send'])
    parser.add_argument('--profile',choices=['v2','v2ProPlus'],default='v2')
    parser.add_argument('--min-free-gib',type=int,default=12)
    parser.add_argument('--text',default='你好，这是本地数字人直播链路测试。')
    parser.add_argument('--chat',action='store_true')
    parser.add_argument('--session',default='')
    args=parser.parse_args()
    if args.action in ('status','precheck'):
        data=state();print(json.dumps(data,ensure_ascii=False,indent=2))
        if args.action=='precheck':
            require_prepared()
            if not data['avatar']:raise RuntimeError('Avatar preprocessing has not completed')
    elif args.action=='prepare-avatar':
        require_prepared();subprocess.run([sys.executable,'-X','utf8','-B',str(ROOT/'scripts/prepare_avatar.py')],cwd=ROOT,env=environment(),check=True)
    elif args.action in ('start-tts','start-avatar'):
        start_service('tts' if args.action=='start-tts' else 'avatar',args.profile,args.min_free_gib)
    elif args.action=='start-obs':
        exe=ROOT/'tools/obs/bin/64bit/obs64.exe'
        subprocess.Popen([str(exe),'--portable','--collection','Avatar Local','--profile','Avatar Local'],cwd=exe.parent,env=environment(),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,close_fds=True,creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP)
        print('Opened portable OBS; recording and broadcasting require manual controls.')
    elif args.action=='stop':stop_services()
    elif args.action=='send':
        import requests
        env=environment()
        if args.chat and not all(env.get(key,'') for key in ('AVATAR_LLM_BASE_URL','AVATAR_LLM_API_KEY','AVATAR_LLM_MODEL')):raise RuntimeError('Fill configs/channel.env before a cloud LLM test')
        client=requests.Session();client.trust_env=False
        session=args.session
        if not session:
            response=client.get('http://127.0.0.1:8010/api/admin/sessions',timeout=10);response.raise_for_status()
            sessions=response.json().get('data',{}).get('sessions',[])
            if len(sessions)!=1:raise RuntimeError('Connect the OBS browser source or one preview page first; exactly one session is required')
            session=str(sessions[0]['sessionid'])
        response=client.post('http://127.0.0.1:8010/human',json={'sessionid':session,'type':'chat' if args.chat else 'echo','text':args.text},timeout=30)
        response.raise_for_status();print(response.text)

if __name__=='__main__':
    try:main()
    except Exception as exc:print('ERROR: '+str(exc),file=sys.stderr);sys.exit(1)
