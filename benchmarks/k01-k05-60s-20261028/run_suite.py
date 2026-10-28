"""One finite suite, resource gates and evidence publication; never clears other jobs."""
from bench_common import *
import urllib.request,msvcrt,psutil

def main():
 lock=(W/'suite.lock').open('a+b');lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
 try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
 except OSError:print('Another benchmark suite already owns the project lock.');return
 previous=O/'suite-status.json'
 if previous.exists():
  archive=O/'attempts'/str(int(time.time()));archive.mkdir(parents=True,exist_ok=True);(archive/'suite-status.json').write_bytes(previous.read_bytes())
 status={'pid':os.getpid(),'started_at':time.time(),'complete':False,'stages':[]};op=urllib.request.build_opener(urllib.request.ProxyHandler({}));PY=str(R/'runtime/livetalking/Scripts/python.exe')
 def publish():
  save('suite-status.json',status)
  subprocess.run([PY,'-X','utf8','-B',str(W/'build_report.py')],cwd=str(R),check=True,stdout=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
 def gate(stage,gpu_mib,ram_gib,heavy=False):
  good=0;required=2 if heavy else 1
  while good<required:
   try:
    free=float(subprocess.check_output(['nvidia-smi','--query-gpu=memory.free','--format=csv,noheader,nounits'],timeout=10,creationflags=subprocess.CREATE_NO_WINDOW).decode().splitlines()[0]);ram=psutil.virtual_memory().available/2**30;cpu=psutil.cpu_percent(interval=.2)
    queue_note='HTTP queue'
    try:
     queue=json.load(op.open('http://127.0.0.1:8188/queue',timeout=5));running=len(queue.get('queue_running',[]));pending=len(queue.get('queue_pending',[]))
    except Exception:
     # If another project stops ComfyUI, an unavailable port is not an active queue.
     # Verify process absence; if still starting/restarting, keep waiting.
     processes=[]
     for p in psutil.process_iter(['pid','cmdline']):
      try:
       command=' '.join(p.info['cmdline'] or []).lower()
       if 'comfyui' in command and 'main.py' in command:processes.append(p.pid)
      except (psutil.NoSuchProcess,psutil.AccessDenied):continue
     if processes and heavy:raise RuntimeError('ComfyUI process present but queue API unavailable; waiting for its owner')
     running=pending=-1 if processes else 0;queue_note='Queue API unavailable; resource-only cooperative gate' if processes else 'ComfyUI server process absent; did not restart it'
    ready=free>=gpu_mib and ram>=ram_gib and cpu<90 and (not heavy or running+pending==0)
    status['waiting']={'stage':stage,'gpu_free_mib':free,'ram_free_gib':ram,'cpu_percent':cpu,'comfy_running':running,'comfy_pending':pending,'queue_probe':queue_note,'heavy_stage_waits_for_empty_comfy_queue':heavy,'ready':ready,'observed_at':time.time()};good=good+1 if ready else 0;publish()
   except Exception as exc:status['waiting']={'stage':stage,'resource_probe_error':str(exc),'observed_at':time.time()};publish();good=0
   if good<required:time.sleep(20)
  status.pop('waiting',None)
 def stage(script,args,proof,gpu=0,ram=4,heavy=False):
  existing=read_proof(proof)
  if existing.get('ok'):
   status['stages'].append({'script':script,'args':args,'status':'already_completed','proof':proof});publish();return
  if gpu:gate(script,gpu,ram,heavy)
  if existing and not existing.get('ok'):
   archive=O/'attempts'/str(int(time.time()));archive.mkdir(parents=True,exist_ok=True);(archive/Path(proof).name).write_text(json.dumps(existing,ensure_ascii=False,indent=2),encoding='utf-8')
  row={'script':script,'args':args,'status':'running','started_at':time.time()};status['stages'].append(row);publish()
  log=W/(script+'.suite.log')
  with log.open('ab') as output:
   proc=subprocess.Popen([PY,'-X','utf8','-B',str(W/'bench_launch.py'),script,*args],cwd=str(R),stdout=output,stderr=output,creationflags=subprocess.CREATE_NO_WINDOW)
   row['pid']=proc.pid;publish();code=proc.wait()
  result=read_proof(proof);row.update(exit_code=code,finished_at=time.time(),status='completed' if code==0 and result.get('ok') else 'failed');publish()
  if row['status']=='failed':raise RuntimeError(f'{script} failed, see its proof and log. No other project was stopped.')
 def read_proof(proof):
  p=O/proof
  return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
 try:
  # K01/K02 already exist: no repeated baseline generation on a busy device.
  publish();subprocess.run([PY,'-X','utf8','-B',str(W/'serve_remote_review.py')],cwd=str(R),check=True,creationflags=subprocess.CREATE_NO_WINDOW)
  stage('render_wav2lip.py',[],'K04/result.json',gpu=3000,ram=5)
  # Heavy stages yield to the user's entire existing ComfyUI queue.
  if not (O/'training/provenance.json').exists():
   gate('prepare_training.py',6000,12,True)
   subprocess.run([PY,'-X','utf8','-B',str(W/'bench_launch.py'),'prepare_training.py'],cwd=str(R),check=True,creationflags=subprocess.CREATE_NO_WINDOW)
  stage('render_muse.py',['TRAIN'],'TRAIN/result.json',gpu=6000,ram=12,heavy=True)
  while not (read_proof('setup-progress.json').get('environment-feather',{}).get('ready') or read_proof('environments.json').get('feather',{}).get('ready')):
   setup=read_proof('setup-progress.json')
   if setup.get('completed'):raise RuntimeError('Feather isolated dependency environment was not installed')
   status['waiting']={'stage':'Feather dependency installation','observed_at':time.time()};publish();time.sleep(30)
  # FP32 CPU preprocessing uses two threads, leaving the other project's GPU queue alone.
  stage('preprocess_assets.py',['--cpu'],'K03/preprocessing.json',gpu=0,ram=6,heavy=False)
  while True:
   setup=read_proof('setup-progress.json')
   weights=R/'models/lipsync-benchmark/latent/latentsync_unet.pt';env=R/'runtime/lipsync-benchmark/latent/Scripts/python.exe'
   if weights.exists() and env.exists() and (setup.get('environment-latent',{}).get('ready') or read_proof('environments.json').get('latent',{}).get('ready')):break
   if setup.get('completed') and not setup.get('environment-latent',{}).get('ready'):raise RuntimeError('LatentSync download/environment setup failed; see setup-progress.json')
   status['waiting']={'stage':'K05 download and isolated environment','observed_at':time.time()};publish();time.sleep(30)
  # Real full-strength fit probes establish a bounded shared-resource path.
  # No other project's queue, models or control service is changed.
  fit=read_proof('K05/resident-fit-probe.json')
  if not fit.get('ok') or not fit.get('checkpoint_key_validation',{}).get('strict'):raise RuntimeError('K05 resident full-strength probe must pass before the 60-second test')
  stage('render_latent_bounded.py',['--resident'],'K05/result.json',gpu=9000,ram=6,heavy=False)
  subprocess.run([PY,'-X','utf8','-B',str(W/'bench_launch.py'),'validate_outputs.py','K05'],cwd=str(R),check=True,creationflags=subprocess.CREATE_NO_WINDOW);publish()
  native=read_proof('K03/native-fit-probe.json')
  if not native.get('ok') or native.get('saved_activation_storage')!='CUDA':raise RuntimeError('Original K03 native full-batch probe must pass before identity training')
  stage('train_feather.py',['--cooperative'],'K03/training.json',gpu=10000,ram=6,heavy=False)
  stage('render_feather.py',[],'K03/result.json',gpu=3000,ram=5)
  status.pop('waiting',None)
  subprocess.run([PY,'-X','utf8','-B',str(W/'bench_launch.py'),'validate_outputs.py'],cwd=str(R),check=True,creationflags=subprocess.CREATE_NO_WINDOW)
  verified=read_proof('verification-summary.json')
  files_ok=isinstance(verified,list) and len(verified)==5 and all(v.get('verified') for v in verified)
  if not files_ok:raise RuntimeError('One or more complete video/audio/source checks failed; final figures withheld')
  for script,args in [('inspect_benchmark_assets.py',['--inventory-only']),('plot_all.py',[]),('make_final_assets.py',[])]:
   status['postprocessing']={'script':script,'started_at':time.time()};publish()
   subprocess.run([PY,'-X','utf8','-B',str(W/'bench_launch.py'),script,*args],cwd=str(R),check=True,creationflags=subprocess.CREATE_NO_WINDOW)
  status.pop('postprocessing',None);status['complete']=True;status['finished_at']=time.time();publish()
  subprocess.run([PY,'-X','utf8','-B',str(W/'bench_launch.py'),'make_delivery_manifest.py'],cwd=str(R),check=True,creationflags=subprocess.CREATE_NO_WINDOW)
 except BaseException as exc:
  status['error']=str(exc);status['traceback']=traceback.format_exc();status['finished_at']=time.time();publish();raise
 finally:
  lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1);lock.close()
if __name__=='__main__':main()
