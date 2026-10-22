"""One authenticated loopback worker owns the local MuseTalk/Whisper GPU models."""
from pathlib import Path
import datetime,json,os,sys,threading,time,traceback
from multiprocessing.connection import Listener
import numpy as np
import psutil
ROOT=Path(__file__).resolve().parents[1];repo=ROOT/'src/LiveTalking'
os.chdir(repo);sys.path.insert(0,str(repo))
parent=psutil.Process(int(os.environ['AVATAR_GPU_PARENT']));parent_started=parent.create_time()
def watchdog():
    while True:
        time.sleep(2)
        try:
            if parent.create_time()!=parent_started or not parent.is_running():os._exit(0)
        except psutil.NoSuchProcess:os._exit(0)
threading.Thread(target=watchdog,daemon=True).start()
import torch
torch.set_num_threads(1);torch.set_num_interop_threads(1)
from avatars.musetalk_avatar import load_model,load_avatar,warm_up,MuseReal
model=load_model();config=json.loads((ROOT/'configs/livetalking.yaml').read_text(encoding='utf-8-sig'))
avatar=load_avatar(config['avatar_id']);renderer=MuseReal.__new__(MuseReal)
renderer.vae,renderer.unet,renderer.pe,renderer.timesteps,renderer.audio_processor=model
renderer.input_latent_list_cycle=avatar[4];renderer.batch_size=config['batch_size']
warm_up(renderer.batch_size,model);torch.cuda.synchronize()
pipe=r'\\.\pipe\avatar-gpu-'+os.environ['AVATAR_GPU_WORKER_RUN']
listener=Listener(pipe,family='AF_PIPE',authkey=bytes.fromhex(os.environ['AVATAR_GPU_WORKER_AUTH']))
state={'ready':True,'pid':os.getpid(),'parent_pid':parent.pid,'pipe':pipe,'run_id':os.environ['AVATAR_GPU_WORKER_RUN'],'avatar_id':config['avatar_id'],'at':datetime.datetime.now().astimezone().isoformat()}
(ROOT/'.setup/gpu-worker.json').write_text(json.dumps(state),encoding='utf-8');print(json.dumps(state),flush=True)
try:
    connection=listener.accept()
    while True:
        request=connection.recv();start=time.perf_counter()
        try:
            operation=request['operation']
            if operation=='features':value=renderer.audio_processor.audio2feat(request['wave'])[:128]
            elif operation=='render':
                renderer._studio_frame_indices=request.get('indices')
                value=renderer.inference_batch(request['index'],request['features'])
            else:raise ValueError('Unknown GPU operation')
            connection.send({'ok':True,'value':value})
            elapsed=time.perf_counter()-start
            if elapsed>1:print(json.dumps({'operation':operation,'seconds':elapsed}),flush=True)
        except Exception:connection.send({'ok':False,'error':traceback.format_exc()})
except (EOFError,ConnectionError,OSError):pass
finally:listener.close()
