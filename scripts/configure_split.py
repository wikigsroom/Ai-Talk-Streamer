"""Select A-device inference with a B-device Livehime receiver, without starting a stream."""
from pathlib import Path
from urllib.parse import urlsplit
import argparse,datetime,json,shutil,urllib.request

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receiver-url',default='http://127.0.0.1:8020')
    parser.add_argument('--isolated-state',help='Optional new test-state path. Omit to retain the current memory path.')
    args=parser.parse_args();origin=urlsplit(args.receiver_url)
    if origin.scheme not in ('http','https') or not origin.hostname or origin.username or origin.password or origin.path not in ('','/') or origin.query or origin.fragment:
        raise ValueError('receiver-url must be the B-device browser origin')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open('http://127.0.0.1:3092/api/dsh/status',timeout=3) as response:
            if json.load(response).get('broadcast'):raise RuntimeError('End the A-device local session before changing its deployment')
    except urllib.error.URLError:pass
    pointer=ROOT/'configs/dsh-active-policy.json';policy_source=ROOT/'docs/dsh-humanity/examples/bridge-policy.example.json'
    if pointer.exists():policy_source=(ROOT/json.loads(pointer.read_text(encoding='utf-8-sig'))['policy_file']).resolve()
    if not policy_source.is_relative_to(ROOT):raise ValueError('Policy outside project')
    policy=json.loads(policy_source.read_text(encoding='utf-8-sig'));policy.pop('example_only',None)
    policy['playback']['lease_timeout_ms']=30000
    if args.isolated_state:
        state=(ROOT/args.isolated_state).resolve()
        if not state.is_relative_to(ROOT/'state') or state==ROOT/'state':raise ValueError('Isolated state must be a project state subdirectory')
        policy['deployment'].update(state_relative_path=state.relative_to(ROOT).as_posix(),dsh_home_relative_path=(state/'dsh-home').relative_to(ROOT).as_posix())
    platform_file=ROOT/'configs/platforms.private.json'
    platforms=json.loads(platform_file.read_text(encoding='utf-8-sig')) if platform_file.exists() else {'version':1,'platforms':{}}
    platforms.setdefault('platforms',{}).setdefault('bilibili',{}).update(output_mode='livehime',client_location='receiver',receiver_url=origin.scheme+'://'+origin.netloc)
    target=ROOT/'configs/split-device-policy.private.json';backup=ROOT/'.setup/split-device/config-backups'/datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    for p in (platform_file,pointer,target):
        if p.exists():backup.mkdir(parents=True,exist_ok=True);shutil.copy2(p,backup/p.name)
    for p,value in [(platform_file,platforms),(target,policy),(pointer,{'policy_file':target.relative_to(ROOT).as_posix()})]:
        p.parent.mkdir(parents=True,exist_ok=True);temporary=p.with_suffix(p.suffix+'.tmp');temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');temporary.replace(p)
    print(json.dumps({'configured':True,'role':'inference','client_location':'receiver','dsh_restart_required':True,'memory_path':policy['deployment']['state_relative_path'],'public_broadcast_started':False}))

if __name__=='__main__':main()
