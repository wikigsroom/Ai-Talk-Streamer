"""Explicit hardware presets. Applying a preset never starts services or models."""
from pathlib import Path
import argparse,datetime,json,shutil,socket

ROOT=Path(__file__).resolve().parents[1]
PRESETS={
    'rtx3080-original':{'batch_size':8,'tts_device':'cuda','tts_half':True},
    'rtx3080-batch4':{'batch_size':4,'tts_device':'cuda','tts_half':True},
    'rtx3080-batch2':{'batch_size':2,'tts_device':'cuda','tts_half':True},
    'rtx3080-batch1':{'batch_size':1,'tts_device':'cuda','tts_half':True},
    'rtx3080-cpu-tts':{'batch_size':1,'tts_device':'cpu','tts_half':False},
}

def minimum_free_gib(service):
    path=ROOT/'configs/hardware-profile.json'
    if not path.exists():return 12
    profile=json.loads(path.read_text(encoding='utf-8'))
    value=profile.get('minimum_free_gib',{}).get(service,12)
    if not isinstance(value,(int,float)) or value<0:raise ValueError('Invalid hardware memory gate')
    return value

def apply(preset):
    if preset not in PRESETS:raise ValueError('Unknown hardware preset')
    for port in [8010,9880]:
        with socket.socket() as sock:
            sock.settimeout(.5)
            if sock.connect_ex(('127.0.0.1',port))==0:raise RuntimeError('Stop the project services before changing a hardware preset')
    import yaml
    live_path=ROOT/'configs/livetalking.yaml';tts_path=ROOT/'configs/tts-v2.yaml'
    live=json.loads(live_path.read_text(encoding='utf-8-sig'))
    tts=yaml.safe_load(tts_path.read_text(encoding='utf-8-sig'))
    custom=tts.get('custom')
    if not isinstance(custom,dict) or custom.get('version')!='v2':raise RuntimeError('This preset requires the existing GPT-SoVITS v2 configuration')
    values=PRESETS[preset]
    stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup=ROOT/'.setup/hardware-backups'/stamp;backup.mkdir(parents=True)
    for path in [live_path,tts_path,ROOT/'configs/hardware-profile.json']:
        if path.exists():shutil.copy2(path,backup/path.name)
    live['batch_size']=values['batch_size']
    custom.update(device=values['tts_device'],is_half=values['tts_half'])
    live_path.write_text(json.dumps(live,ensure_ascii=False,indent=2),encoding='utf-8')
    tts_path.write_text(yaml.safe_dump(tts,allow_unicode=True,sort_keys=False),encoding='utf-8')
    record={'preset':preset,**values,'cudnn_benchmark':True,'target_fps':25,'canvas':[720,1280],'avatar_id':live['avatar_id'],'minimum_free_gib':{'tts':0 if values['tts_device']=='cpu' else 2,'avatar':2},'applied_at':datetime.datetime.now().astimezone().isoformat(),'note':'The memory gate only permits a launch attempt. Actual model peaks and speed must be measured. No automatic downgrade.'}
    (ROOT/'configs/hardware-profile.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(record,ensure_ascii=False))
    return record

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('preset',choices=PRESETS);args=parser.parse_args();apply(args.preset)
