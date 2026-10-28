"""Configure and control only the project-local native B-device receiver."""
from pathlib import Path
import argparse,json,os,socket,subprocess,sys,time,urllib.request
from receiver_service import validate_config

ROOT=Path(__file__).resolve().parents[1]
CONFIG=ROOT/'configs/receiver.private.json'
RECORD=ROOT/'outputs/receiver/process.json'

def status(config):
    try:
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open('http://127.0.0.1:'+str(config['port'])+'/receiver/status',timeout=3) as response:return json.load(response)
    except OSError:return {'running':False,'port':config['port']}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['configure','start','stop','status'])
    parser.add_argument('--upstream');parser.add_argument('--client');parser.add_argument('--receiver-id',default='receiver-b');parser.add_argument('--port',type=int,default=8020)
    args=parser.parse_args()
    config=json.loads(CONFIG.read_text(encoding='utf-8-sig')) if CONFIG.exists() else {'upstream':args.upstream or 'http://A_DEVICE_VPN_HOST:8010','port':args.port,'bind':'127.0.0.1','receiver_id':args.receiver_id}
    if args.action=='configure':
        if status(config).get('role')=='receiver':raise RuntimeError('Stop the receiver before changing its upstream')
        if args.upstream:config['upstream']=args.upstream
        if args.client:config['client_executable']=args.client
        config.update(port=args.port,receiver_id=args.receiver_id);config=validate_config(config)
        CONFIG.parent.mkdir(exist_ok=True);CONFIG.write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'configured':True,'upstream':config['upstream'],'port':config['port']}));return
    if not CONFIG.exists():raise RuntimeError('Configure the A-device VPN origin first')
    config=validate_config(config)
    if args.action=='status':print(json.dumps(status(config),ensure_ascii=False));return
    if args.action=='start':
        current=status(config)
        if current.get('role')=='receiver':print(json.dumps({'already_running':True,**current}));return
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1',config['port']))==0:raise RuntimeError('Receiver port belongs to another service')
        RECORD.parent.mkdir(parents=True,exist_ok=True)
        command=[sys.executable,'-X','utf8','-B',str(ROOT/'scripts/receiver_service.py'),'--config',str(CONFIG)]
        kwargs={'cwd':ROOT,'stdin':subprocess.DEVNULL,'close_fds':True}
        if os.name=='nt':kwargs['creationflags']=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.CREATE_NO_WINDOW
        with (RECORD.parent/'stdout.log').open('ab') as out,(RECORD.parent/'stderr.log').open('ab') as err:
            process=subprocess.Popen(command,stdout=out,stderr=err,**kwargs)
        RECORD.write_text(json.dumps({'pid':process.pid,'command':command,'started_at':time.time()},ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'started':True,'pid':process.pid,'url':'http://127.0.0.1:'+str(config['port'])+'/receiver/'}));return
    import psutil
    if not RECORD.exists():raise RuntimeError('No owned receiver process record')
    record=json.loads(RECORD.read_text(encoding='utf-8'))
    try:
        process=psutil.Process(record['pid'])
        if Path(process.exe()).resolve()!=Path(record['command'][0]).resolve() or record['command'][4] not in process.cmdline() or process.create_time()<record['started_at']-10:
            raise RuntimeError('Receiver process ownership mismatch')
        # A native Windows venv launcher has a second Python process. Stop only
        # descendants running this exact receiver/config before its launcher.
        children=[]
        for child in process.children(recursive=True):
            try:
                command=child.cmdline()
                if record['command'][4] in command and str(CONFIG) in command:
                    children.append(child)
            except psutil.NoSuchProcess:
                pass
        for child in reversed(children):
            try:child.terminate()
            except psutil.NoSuchProcess:pass
        _,alive=psutil.wait_procs(children,timeout=10)
        if alive:raise RuntimeError('Receiver descendants did not stop; launcher left intact')
        if process.is_running():process.terminate();process.wait(timeout=10)
    except psutil.NoSuchProcess:pass
    print(json.dumps({'stopped':True,'inference_host_unchanged':True,'public_broadcast_stopped':False}))

if __name__=='__main__':main()
