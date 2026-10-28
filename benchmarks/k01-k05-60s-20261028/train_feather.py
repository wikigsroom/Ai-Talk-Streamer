"""Instrument the original 60-epoch trainer; do not alter original loss weights."""
from bench_common import *
import random,functools,psutil

def main():
 import torch
 cooperative='--cooperative' in sys.argv
 label='K03-training';mon=Monitor(label);start=time.perf_counter();invocation_started_at=time.time();src=R/'src/lipsync-benchmark/feather';sys.path.insert(0,str(src));os.chdir(src)
 torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.backends.cudnn.benchmark=False
 if cooperative:
  fit=json.loads((O/'K03/native-fit-probe.json').read_text(encoding='utf-8'))
  if not fit.get('ok') or fit.get('saved_activation_storage')!='CUDA' or fit.get('original_batchsize')!=16:raise RuntimeError('Original full-batch native CUDA fit probe must succeed before cooperative training')
  if fit.get('torch_peak_reserved_mib',999999)>7800:raise RuntimeError('Probe exceeded the selected 8GiB cooperative training envelope')
  torch.cuda.set_per_process_memory_fraction(8192*2**20/torch.cuda.get_device_properties(0).total_memory);psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
 random.seed(20261028);np.random.seed(20261028);torch.manual_seed(20261028);torch.cuda.manual_seed_all(20261028)
 import train
 import dataset_mouth_roi as dataset_module
 # Cache decoded 152px crops, not full portrait frames. This preserves exact
 # transforms/sampling and avoids re-decoding ~0.96M full-size JPEGs over60epochs.
 original_crop=dataset_module.load_face_crop;original_landmarks=dataset_module.read_landmarks
 cached_crop=functools.lru_cache(maxsize=10000)(original_crop)
 cached_landmarks=functools.lru_cache(maxsize=10000)(original_landmarks)
 dataset_module.load_face_crop=lambda *a,**kw:cached_crop(*a,**kw).copy()
 dataset_module.read_landmarks=lambda path:cached_landmarks(path).copy()
 cache_start=time.perf_counter();frames=len(manifest()['train_frame_ids'])
 for i in range(frames):
  image=str(O/'training/full_body_img'/f'{i}.jpg');landmark=str(O/'training/landmarks'/f'{i}.lms');cached_crop(image,landmark,crop_size=152);cached_landmarks(landmark)
  if i%250==0:save('K03/progress.json',{'stage':'preload-training-crops','frame':i,'total':frames})
 cache_seconds=time.perf_counter()-cache_start
 history=[];step_parts=[];epoch=0;resource_wait=0;original_epoch=train.train_one_epoch;original_loss=train.compute_total_loss
 class YieldingLoader:
  def __init__(self,loader):self.loader=loader
  def __iter__(self):
   nonlocal resource_wait
   for batch in self.loader:
    if cooperative:
     before=time.perf_counter();waiting=False
     while True:
      free=torch.cuda.mem_get_info()[0]/2**20;ram=psutil.virtual_memory().available/2**30
      if free<10000:torch.cuda.empty_cache();free=torch.cuda.mem_get_info()[0]/2**20
      if free>=10000 and ram>=4:break
      waiting=True;save('K03/progress.json',{'stage':'yielding to shared resource use','epoch':epoch,'total_epochs':60,'steps_in_epoch':len(step_parts),'gpu_free_mib':free,'ram_free_gib':ram,'resource_wait_seconds':resource_wait+time.perf_counter()-before});time.sleep(3)
     if waiting:resource_wait+=time.perf_counter()-before
    yield batch
 def measured_loss(*args,**kwargs):
  loss,parts=original_loss(*args,**kwargs);step_parts.append(parts)
  if len(step_parts)%25==0:save('K03/progress.json',{'stage':'training native FP32','epoch':epoch,'total_epochs':60,'steps_in_epoch':len(step_parts),'elapsed_seconds':time.perf_counter()-start,'resource_wait_seconds':resource_wait,'latest_loss':parts})
  return loss,parts
 def measured_epoch(*args,**kwargs):
  nonlocal epoch
  t=time.perf_counter();wait_at_epoch=resource_wait;step_parts.clear();call_args=list(args)
  if cooperative:call_args[1]=YieldingLoader(call_args[1])
  result=original_epoch(*call_args,**kwargs);torch.cuda.synchronize();epoch+=1
  row={'epoch':epoch,'seconds':time.perf_counter()-t,'resource_wait_seconds':resource_wait-wait_at_epoch,'steps':len(step_parts),'elapsed_seconds':time.perf_counter()-start,'invocation_started_at':invocation_started_at,'losses':{k:float(np.mean([d[k] for d in step_parts])) for k in step_parts[0]} if step_parts else {}}
  # An extra rolling checkpoint enables safe task-local resume without losing
  # nine epochs if a different project's resource requirements change.
  train.save_checkpoint(str(dest/'last.pth'),args[0],args[2],epoch-1)
  history.append(row);save('K03/training-history.json',history);save('K03/progress.json',dict(row,total_epochs=60));print(json.dumps(row),flush=True);return result
 train.compute_total_loss=measured_loss;train.train_one_epoch=measured_epoch
 dest=R/'models/lipsync-benchmark/feather/female-a-teacher-pilot';dest.mkdir(parents=True,exist_ok=True)
 sys.argv=['train.py','--dataset_dir',str(O/'training'),'--save_dir',str(dest),'--model','feathertalk','--epochs','60','--batchsize','16','--num_workers','0','--save_every','10','--see_res','--see_res_dir',str(O/'K03/training-stills')]
 ckpt=dest/'last.pth'
 resumed_from_epoch=0
 if ckpt.exists():
  sys.argv+=['--resume',str(ckpt)];resumed_from_epoch=int(torch.load(ckpt,map_location='cpu',weights_only=True).get('epoch',-1))+1;epoch=resumed_from_epoch
  hp=O/'K03/training-history.json'
  if hp.exists():history=[r for r in json.loads(hp.read_text(encoding='utf-8')) if r['epoch']<=resumed_from_epoch]
 try:
  loss_weights=R/'cache/lipsync-benchmark/torch/hub/checkpoints/vgg19-dcbb9e9d.pth'
  while not loss_weights.exists():
   vgg=json.loads((O/'vgg-setup.json').read_text(encoding='utf-8')) if (O/'vgg-setup.json').exists() else {}
   if vgg.get('error'):raise RuntimeError('Original VGG perceptual weights not ready: '+vgg['error'])
   save('K03/progress.json',{'stage':'waiting for original perceptual training weights','download':vgg});time.sleep(15)
  train.main();torch.cuda.synchronize()
  # Keep the resumable original checkpoint and export the exact same inference
  # weights separately so optimizer slots are not counted as deployment weights.
  saved=torch.load(ckpt,map_location='cpu',weights_only=True);inference=dest/'inference.pth'
  if int(saved['epoch'])+1!=60:raise RuntimeError('Original training checkpoint did not complete the requested 60 epochs')
  torch.save({k:saved[k] for k in ['model','model_config','epoch']},inference)
  prior_attempts=json.loads((O/'K03/training-attempts.json').read_text(encoding='utf-8')) if (O/'K03/training-attempts.json').exists() else []
  elapsed=time.perf_counter()-start
  save('K03/training-invocations.json',{'resumed_from_epoch':resumed_from_epoch,'current_invocation_started_at':invocation_started_at,'current_entry_wall_seconds':elapsed,'prior_failed_stage_wall_seconds':sum(x['stage_wall_seconds'] for x in prior_attempts),'aggregate_measured_training_wall_seconds':elapsed+sum(x['stage_wall_seconds'] for x in prior_attempts),'aggregate_boundary':'current training entry plus prior suite stage windows; excludes idle gap between invocations, includes prior launch/publication overhead','epochs_completed_in_current_invocation':60-resumed_from_epoch,'retained_completed_epochs':resumed_from_epoch,'random_state_restored':False,'random_state_note':'Upstream model/optimizer/epoch resume; reseeds20261028, not an uninterrupted bit-identical random sequence.','prior_attempts':prior_attempts})
  save('K03/training.json',{'ok':True,'synthetic_teacher_pilot':True,'teacher':'K01 MuseTalk1.5','epochs_requested':60,'batchsize':16,'precision':'FP32','native_windows_num_workers':0,'seed':20261028,'wall_seconds':time.perf_counter()-start,'resource_wait_seconds':resource_wait,'cooperative_gpu_budget_mib':8192 if cooperative else None,'training_saved_activations':'CUDA','cpu_crop_cache':{'frames':frames,'crop_size':152,'seconds':cache_seconds,'changes_model_math':False},'checkpoint':str(ckpt),'checkpoint_sha256':hashlib.sha256(ckpt.read_bytes()).hexdigest(),'inference_checkpoint':str(inference),'inference_checkpoint_bytes':inference.stat().st_size,'inference_checkpoint_sha256':hashlib.sha256(inference.read_bytes()).hexdigest(),'history':history,'torch_peak_allocated_mib':torch.cuda.max_memory_allocated()/2**20,'torch_peak_reserved_mib':torch.cuda.max_memory_reserved()/2**20,**mon.finish()})
 except Exception as exc:mon.finish();result_fail('K03-training',exc);raise
if __name__=='__main__':main()
