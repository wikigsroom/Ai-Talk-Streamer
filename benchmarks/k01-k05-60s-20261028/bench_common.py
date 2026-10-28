"""Shared, isolated native-Windows benchmark support. Never modifies production."""
import os,sys,json,time,threading,subprocess,hashlib,traceback
from pathlib import Path
import numpy as np
import cv2

# OpenCV's Windows file APIs may reject non-ASCII absolute paths silently.
_native_imread=cv2.imread;_native_imwrite=cv2.imwrite
def read_image(path,flags=cv2.IMREAD_COLOR):
 path=os.fspath(path)
 if not path.isascii():
  try:return cv2.imdecode(np.fromfile(path,dtype=np.uint8),flags)
  except (OSError,ValueError):return None
 return _native_imread(path,flags)
def write_image(path,image,params=None):
 path=os.fspath(path)
 if not path.isascii():
  ok,buffer=cv2.imencode(Path(path).suffix,image,params or [])
  if not ok:raise IOError('OpenCV could not encode '+path)
  buffer.tofile(path);return True
 ok=_native_imwrite(path,image,params or [])
 if not ok:raise IOError('OpenCV could not write '+path)
 return ok
cv2.imread=read_image;cv2.imwrite=write_image

R=Path('C:/dev/虚拟数字人直播')
W=R/'operations/k01-k05-60s-20261028'
O=R/'outputs/lipsync-k01-k05-60s-20261028'
LIVE=R/'src/LiveTalking'
AV=LIVE/'data/avatars/student_dorm_motion_bank_v3'
FPS=25;N=1500
os.environ['AVATAR_GPU_ISOLATION']='0'
os.environ['AVATAR_GPU_WORKER_CHILD']='1'
os.environ['HF_HOME']=str(R/'cache/lipsync-benchmark/huggingface')
os.environ['TORCH_HOME']=str(R/'cache/lipsync-benchmark/torch')
os.environ['PYTHONUTF8']='1'
os.environ['OMP_NUM_THREADS']='2'
os.environ['MKL_NUM_THREADS']='2'
O.mkdir(parents=True,exist_ok=True)

_progress_write_warning=False

def save(name,data):
 global _progress_write_warning
 p=O/name;p.parent.mkdir(parents=True,exist_ok=True)
 tmp=p.with_name(p.name+f'.{os.getpid()}.{threading.get_ident()}.tmp')
 telemetry=p.name=='progress.json'
 try:
  tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
  # Windows readers/antivirus can briefly deny replacement of an open file.
  # Keep the previous complete JSON visible and retry this task's own rename.
  for attempt in range(3 if telemetry else 40):
   try:os.replace(tmp,p);break
   except PermissionError:
    if attempt==(2 if telemetry else 39):raise
    time.sleep(min(.025*(attempt+1),.25))
 except PermissionError:
  if not telemetry:raise
  # Progress is transient telemetry, never a checkpoint or measured result.
  # A slow reader must not abort a multi-hour optimizer run. Preserve its latest
  # snapshot under this invocation's stable fallback filename for inspection.
  fallback=p.with_name(f'progress-fallback-{os.getpid()}.json')
  try:fallback.write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
  except OSError:pass
  if not _progress_write_warning:
   print('Progress JSON temporarily locked; training continues. Checkpoints/results remain strict.',file=sys.stderr,flush=True);_progress_write_warning=True
  return False
 finally:
  try:tmp.unlink(missing_ok=True)
  except OSError:pass
 return True

def manifest():
 p=O/'input-manifest.json'
 if p.exists():
  value=json.loads(p.read_text(encoding='utf-8'))
  if value['audio_sha256']!=hashlib.sha256((O/'audio/common-60s.wav').read_bytes()).hexdigest():raise RuntimeError('Audio changed after manifest freeze: create a separate run, do not mix input hashes')
  return value
 index=json.loads((AV/'motion-index.json').read_text(encoding='utf-8-sig'))
 selected=[index['clips'][2+i] for i in [0,8,16,24,32,40,44,47]]
 ids=[];clips=[]
 for c in selected:
  take=min(c['frames'],N-len(ids));start=len(ids)
  ids+=list(range(c['start_frame'],c['start_frame']+take))
  clips.append(dict(c,timeline_start_seconds=start/FPS,timeline_end_seconds=len(ids)/FPS))
 all_train=[c for c in index['clips'][2:] if c not in selected]
 train_ids=[j for c in all_train for j in range(c['start_frame'],c['start_frame']+c['frames'])]
 d={'test_frame_ids':ids,'train_frame_ids':train_ids,'test_clips':clips,'test_train_motion_disjoint':not set(ids)&set(train_ids),'avatar':AV.name,'frames':N,'fps':FPS,'width':720,'height':1280,'audio':'audio/common-60s.wav','audio_sha256':hashlib.sha256((O/'audio/common-60s.wav').read_bytes()).hexdigest(),'seed':20261028,'co_running_services_preserved':True}
 save('input-manifest.json',d);return d

def ffmpeg():
 paths=list((R/'tools/ffmpeg').rglob('ffmpeg.exe'))
 if not paths:raise FileNotFoundError('Existing native FFmpeg not found')
 return str(paths[0])

class Encoder:
 def __init__(self,target,audio=None,width=720,height=1280):
  self.target=Path(target);self.target.parent.mkdir(parents=True,exist_ok=True)
  cmd=[ffmpeg(),'-y','-hide_banner','-loglevel','error','-f','rawvideo','-pix_fmt','bgr24','-s',f'{width}x{height}','-r','25','-i','pipe:0']
  if audio:cmd+=['-i',str(audio),'-map','0:v:0','-map','1:a:0']
  cmd+=['-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-threads','4']
  if audio:cmd+=['-c:a','aac','-b:a','192k']
  cmd+=['-movflags','+faststart',str(self.target)]
  self.log=open(self.target.with_suffix('.ffmpeg.log'),'wb');self.p=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=self.log,creationflags=subprocess.CREATE_NO_WINDOW);self.frames=0;self.io_seconds=0
 def write(self,frame):
  t=time.perf_counter();self.p.stdin.write(np.ascontiguousarray(frame,dtype=np.uint8).tobytes());self.io_seconds+=time.perf_counter()-t;self.frames+=1
 def close(self):
  t=time.perf_counter();self.p.stdin.close();code=self.p.wait();self.log.close()
  if code:raise RuntimeError(f'FFmpeg exit {code}: {self.target}')
  return {'frames_encoded':self.frames,'encoder_backpressure_seconds':self.io_seconds,'encoder_flush_seconds':time.perf_counter()-t,'bytes':self.target.stat().st_size}

class Monitor:
 def __init__(self,label):
  import psutil
  self.label=label;self.proc=psutil.Process();self.psutil=psutil;self.samples=[];self.stop_event=threading.Event();self.start=time.perf_counter()
  self.thread=threading.Thread(target=self.loop,daemon=True);self.thread.start()
 def loop(self):
  while not self.stop_event.is_set():
   row={'elapsed_seconds':round(time.perf_counter()-self.start,3),'process_rss_mib':self.proc.memory_info().rss/2**20,'system_ram_used_mib':self.psutil.virtual_memory().used/2**20,'system_cpu_percent':self.psutil.cpu_percent()}
   try:
    value=subprocess.check_output(['nvidia-smi','--query-gpu=memory.used,memory.free,utilization.gpu,power.draw','--format=csv,noheader,nounits'],timeout=8,creationflags=subprocess.CREATE_NO_WINDOW).decode().strip().split(',')
    row.update(dict(zip(['gpu_total_used_mib','gpu_free_mib','gpu_util_percent','gpu_power_watts'],[float(v.strip()) for v in value])))
   except Exception as e:row['gpu_sample_error']=str(e)
   self.samples.append(row);self.stop_event.wait(1)
 def finish(self):
  self.stop_event.set();self.thread.join(timeout=10);save(f'{self.label}/resources.json',self.samples)
  result={}
  for key in ['process_rss_mib','system_ram_used_mib','gpu_total_used_mib','gpu_util_percent','gpu_power_watts']:
   vals=[s[key] for s in self.samples if key in s]
   if vals:result[key+'_peak']=max(vals);result[key+'_mean']=sum(vals)/len(vals)
  return result

def mouth_blend(source,prediction,bbox,strength=1.0,color=True):
 """A bounded lower-face composite; leaves all pixels outside bbox unchanged."""
 x1,y1,x2,y2=map(int,bbox);h=y2-y1;w=x2-x1
 pred=cv2.resize(prediction,(w,h)).astype(np.float32);orig=source[y1:y2,x1:x2].astype(np.float32)
 yy,xx=np.mgrid[:h,:w].astype(np.float32);dist=((xx-w*.50)/(w*.43))**2+((yy-h*.73)/(h*.29))**2
 alpha=np.clip((1.0-dist)*5,0,1)[...,None]*strength
 if color:
  border=(dist>.75)&(dist<1.3)
  if border.sum()>10:
   correction=np.clip(np.median(orig[border]-pred[border],axis=0),-18,18)
   pred=np.clip(pred+correction,0,255)
 out=source.copy();out[y1:y2,x1:x2]=np.clip(orig*(1-alpha)+pred*alpha,0,255).astype(np.uint8)
 return out

def result_fail(label,error):
 save(f'{label}/result.json',{'id':label,'ok':False,'error':str(error),'traceback':traceback.format_exc(),'timestamp':time.time()})
