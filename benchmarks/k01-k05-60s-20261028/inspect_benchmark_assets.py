"""CPU import smoke, model inventory, and transparent teacher-record erratum."""
import os,sys,json,time,hashlib,subprocess,wave,traceback
from pathlib import Path
R=Path('C:/dev/虚拟数字人直播');O=R/'outputs/lipsync-k01-k05-60s-20261028'
def write(name,data):
    p=O/name;p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(tmp,p)
if '--probe-equivalence' in sys.argv:
    paths=[O/'diagnostics/k05-fit/probe-0p64s.mp4',O/'diagnostics/k05-resident-fit/probe-0p64s.mp4']
    records=[{'path':p.relative_to(O).as_posix(),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths]
    write('K05/probe-execution-equivalence.json',{'probe_only':True,'frames':16,'seconds':.64,'not_a_60_second_test':True,'bitwise_identical':records[0]['sha256']==records[1]['sha256'],'files':records,'scope':'The same short full-strength generation with sequential CPU offload and resident CUDA weights. Does not certify equivalence of every possible input or final60s quality.'})
    write('K05/resident-fit-probe-metadata-correction.json',{'reason':'Probe reused an old output-path/notes label. Original measured record remains unchanged. The execution_adapter field and actual run were resident CUDA weights.','actual_video':records[1]['path'],'actual_execution':'bounded frame I/O + VAE batch slicing + resident CUDA weights','unchanged_metrics':'All measured timings, bytes and resource data in resident-fit-probe.json are retained.'});raise SystemExit(0)
if '--execution-only' in sys.argv:
    from importlib.metadata import version,PackageNotFoundError
    versions={}
    for name in ['torch','torchvision','diffusers','accelerate','numpy','opencv-python','dlib','transformers','kornia']:
        try:versions[name]=version(name)
        except PackageNotFoundError:versions[name]=None
    exports=[]
    folder=R/'src/lipsync-benchmark/latent/latentsync/models'
    for path in folder.glob('*.py'):
        dest=O/'diagnostics'/('latent-'+path.name+'.txt');dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(path.read_bytes());exports.append(dest.name)
    write('diagnostics/execution-audit.json',{'versions':versions,'source_files':exports,'cpu_inspection_only':True,'no_model_load':True});print(json.dumps(versions),flush=True);raise SystemExit(0)
result={}
for name in ([] if '--inventory-only' in sys.argv else ['feather','latent']):
    python=R/f'runtime/lipsync-benchmark/{name}/Scripts/python.exe';src=R/'src/lipsync-benchmark'/name
    setup="import sys,os,json,types;from pathlib import Path;import torch;torch.set_num_threads(2);"
    setup+="sys.path.insert(0,"+repr(str(src))+" );"
    if name=='feather':
        setup+="sys.path.insert(0,"+repr(str(src/'data_utils'))+");import train,inference,get_landmark;from feather_hubert.feather_hubert import load_feather_hubert;print(json.dumps({'imports':'ok','torch':torch.__version__,'device':'CPU smoke only'}))"
    else:
        setup+="s=types.ModuleType('latentsync.utils.face_detector');s.FaceDetector=object;sys.modules[s.__name__]=s;from latentsync.pipelines.lipsync_pipeline import LipsyncPipeline;from latentsync.whisper.audio2feature import Audio2Feature;from latentsync.whisper.whisper.tokenizer import get_tokenizer;t=get_tokenizer(multilingual=True);from diffusers import AutoencoderKL,DDIMScheduler;import diffusers,transformers;print(json.dumps({'imports':'ok','torch':torch.__version__,'diffusers':diffusers.__version__,'transformers':transformers.__version__,'tokenizer':'local assets'}))"
    env=os.environ.copy();env.update(CUDA_VISIBLE_DEVICES='',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONUTF8='1')
    t=time.perf_counter()
    p=subprocess.run([str(python),'-X','utf8','-c',setup],cwd=str(src),env=env,capture_output=True,text=True,encoding='utf-8',timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
    result[name]={'ok':p.returncode==0,'seconds':time.perf_counter()-t,'stdout':p.stdout,'stderr':p.stderr,'no_gpu_allocation':True};write('backend-import-smoke.json',result)
raw=O/'TRAIN/result.json';provenance=O/'training/provenance.json';audio=O/'training/audio.wav'
if raw.exists() and audio.exists():
    d=json.loads(raw.read_text(encoding='utf-8'))
    with wave.open(str(audio)) as w:seconds=w.getnframes()/w.getframerate()
    if d.get('audio_seconds')!=seconds:
        wall=d['render_wall_seconds'];count=int(round(seconds*25))
        write('TRAIN/metadata-correction.json',{'reason':'The initial teacher-frame preparation reused test-run summary labels. Original measured record is retained unchanged; this sidecar corrects derived labels only.','original_record':'TRAIN/result.json','actual_training_audio':'training/audio.wav','audio_seconds':seconds,'frames_saved_as_jpeg':count,'input_audio_sha256':hashlib.sha256(audio.read_bytes()).hexdigest(),'video':None,'render_wall_seconds_unchanged':wall,'render_fps':count/wall,'render_rtf':wall/seconds,'name':'MuseTalk 1.5 teacher material preparation','not_a_60_second_test_result':True})
files=[]
for folder in [R/'models/lipsync-benchmark',R/'src/lipsync-benchmark/feather']:
    if not folder.exists():continue
    for p in folder.rglob('*'):
        if p.is_file() and p.suffix.lower() in ['.pth','.pt','.onnx','.safetensors'] or (p.is_file() and p.name.endswith('.pth.tar')):
            role='backend model / preprocessing'
            if 'female-a-teacher-pilot' in str(p):role='K03 deployment identity weights; no optimizer' if p.name=='inference.pth' else 'K03 resumable training checkpoint / optimizer'
            elif p.name=='feather_hubert.pth':role='K03 inference audio encoder'
            elif p.name in {'checkpoint_epoch_335.pth.tar','scrfd_2.5g_kps.onnx'}:role='K03 one-time avatar landmark preprocessing'
            elif p.name in {'latentsync_unet.pt','tiny.pt'}:role='K05 inference checkpoint'
            elif p.name=='wav2lip_gan.pth':role='K04 downloaded GAN checkpoint'
            files.append({'path':str(p.relative_to(R)),'bytes':p.stat().st_size,'role':role})
vgg=R/'cache/lipsync-benchmark/torch/hub/checkpoints/vgg19-dcbb9e9d.pth'
if vgg.exists():files.append({'path':str(vgg.relative_to(R)),'bytes':vgg.stat().st_size,'role':'K03 training perceptual loss only; not deployed inference'})
vae=R/'src/LiveTalking/models/sd-vae'
for p in vae.glob('*'):
    if p.is_file() and p.suffix in ['.safetensors','.bin','.json']:files.append({'path':str(p.relative_to(R)),'bytes':p.stat().st_size,'role':'existing VAE reused; zero new copy','sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
write('model-file-inventory.json',{'observed_at':time.time(),'files':files,'includes_training_checkpoints':True,'new_download_status':'setup-progress.json','inference_and_training_costs_must_be_separated':True})
print(json.dumps(result,ensure_ascii=False),flush=True)
