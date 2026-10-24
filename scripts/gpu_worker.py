"""One authenticated loopback worker owns the local MuseTalk/Whisper GPU models."""
from pathlib import Path
import datetime,gc,json,os,sys,threading,time,traceback
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
hardware_path=ROOT/'configs/hardware-profile.json'
hardware=json.loads(hardware_path.read_text(encoding='utf-8')) if hardware_path.exists() else {}
if hardware.get('cudnn_benchmark'):
    torch.backends.cudnn.benchmark=True
    if hasattr(torch.backends.cudnn,'benchmark_limit'):torch.backends.cudnn.benchmark_limit=3
    print(json.dumps({'cudnn_benchmark':True,'benchmark_limit':getattr(torch.backends.cudnn,'benchmark_limit',None)}),flush=True)
from avatars.musetalk_avatar import load_model,load_avatar,warm_up,MuseReal

def memory_stats(stage):
    torch.cuda.synchronize()
    data={'stage':stage,'allocated_mib':round(torch.cuda.memory_allocated()/2**20,1),'reserved_mib':round(torch.cuda.memory_reserved()/2**20,1),'peak_allocated_mib':round(torch.cuda.max_memory_allocated()/2**20,1)}
    print(json.dumps({'cuda_memory':data}),flush=True)
    return data

model=load_model();memory_stats('models_loaded')
# FP32-to-FP16 conversion leaves large free blocks in the CUDA allocator.
# Return those blocks before warming the renderer alongside the speech service.
gc.collect();torch.cuda.empty_cache();memory_stats('model_cache_released')
config=json.loads((ROOT/'configs/livetalking.yaml').read_text(encoding='utf-8-sig'))
avatar=load_avatar(config['avatar_id']);renderer=MuseReal.__new__(MuseReal)
renderer.vae,renderer.unet,renderer.pe,renderer.timesteps,renderer.audio_processor=model
renderer.input_latent_list_cycle=avatar[4];renderer.batch_size=config['batch_size']
warm_up(renderer.batch_size,model);memory_stats('warmed')
if config.get('tts')=='moss-ttsd':
    # Prime real speech features and the renderer's actual latent layout before
    # accepting viewers; synthetic upstream warm-up misses this first batch.
    import soundfile as sf
    from scipy.signal import resample_poly
    from math import gcd
    voice_config=json.loads((ROOT/'configs/moss-live.json').read_text(encoding='utf-8'))
    voice_id=voice_config['voice_id']
    sample=ROOT/'web/voice-audio/female-a-v1'/('benchmark-moss-v01.wav' if voice_id=='v01' else 'voice'+voice_id[1:]+'-moss-'+voice_id+'.wav')
    wave,rate=sf.read(str(sample),dtype='float32',always_2d=True)
    factor=gcd(rate,16000)
    wave=resample_poly(wave.mean(1),16000//factor,rate//factor).astype(np.float32)
    tick=time.monotonic()
    with torch.inference_mode():
        renderer.audio_processor.audio2feat(wave)
        renderer.inference_batch(0,[np.zeros((50,384),np.float16) for _ in range(renderer.batch_size)])
    memory_stats('moss_real_speech_warmed')
    print(json.dumps({'moss_real_speech_warm_seconds':time.monotonic()-tick}),flush=True)
gc.collect();torch.cuda.empty_cache();cuda_memory=memory_stats('startup_cache_released')
pipe=r'\\.\pipe\avatar-gpu-'+os.environ['AVATAR_GPU_WORKER_RUN']
listener=Listener(pipe,family='AF_PIPE',authkey=bytes.fromhex(os.environ['AVATAR_GPU_WORKER_AUTH']))
state={'ready':True,'pid':os.getpid(),'parent_pid':parent.pid,'pipe':pipe,'run_id':os.environ['AVATAR_GPU_WORKER_RUN'],'avatar_id':config['avatar_id'],'cuda_memory':cuda_memory,'at':datetime.datetime.now().astimezone().isoformat()}
(ROOT/'.setup/gpu-worker.json').write_text(json.dumps(state),encoding='utf-8');print(json.dumps(state),flush=True)
try:
    connection=listener.accept()
    timings={}
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
            aggregate=timings.setdefault(operation,{'count':0,'seconds':0.0,'maximum_seconds':0.0})
            aggregate['count']+=1;aggregate['seconds']+=elapsed;aggregate['maximum_seconds']=max(aggregate['maximum_seconds'],elapsed)
            if aggregate['count']<=3 or aggregate['count']%25==0:
                statistics={'at':datetime.datetime.now().astimezone().isoformat(),'batch_size':renderer.batch_size,'operations':timings,
                            'allocated_mib':round(torch.cuda.memory_allocated()/2**20,1),'reserved_mib':round(torch.cuda.memory_reserved()/2**20,1)}
                (ROOT/'.setup/gpu-inference-statistics.json').write_text(json.dumps(statistics),encoding='utf-8')
            if elapsed>1:print(json.dumps({'operation':operation,'seconds':elapsed}),flush=True)
        except Exception:connection.send({'ok':False,'error':traceback.format_exc()})
except (EOFError,ConnectionError,OSError):pass
finally:listener.close()
