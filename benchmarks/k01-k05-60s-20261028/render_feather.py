"""K03: held-out 60 s, author preprocessing/model, preserved full-body source."""
from bench_common import *
import pickle,soundfile as sf

def main():
 label='K03';mon=Monitor(label);start=time.perf_counter();metrics={'id':label,'name':'FeatherTalk 女A教师训练实验版','ok':False,'audio_seconds':60,'offline_prerecorded':True,'configuration':'144 px / FP32 / batch 16 / 60 training epochs','synthetic_teacher_pilot':True,'teacher':'K01 MuseTalk1.5','batch_size':16}
 try:
  src=R/'src/lipsync-benchmark/feather';sys.path.insert(0,str(src));os.chdir(src)
  import torch
  torch.set_num_threads(1);torch.set_num_interop_threads(1);torch.backends.cudnn.benchmark=True
  from inference import load_model,prepare_model_input,paste_prediction
  from face_utils import gather_audio_window,reshape_audio_feat
  from data_utils.feather_hubert.feather_hubert import load_feather_hubert,get_feather_hubert_from_16k_speech,make_even_first_dim
  checkpoint=R/'models/lipsync-benchmark/feather/female-a-teacher-pilot/inference.pth'
  model=load_model(str(checkpoint),torch.device('cuda'))
  from model import visual_model_config
  metrics.update(runtime_versions={'torch':torch.__version__},runtime_model_config=visual_model_config(model),inference_reparameterization='upstream inference.load_model default; fused on load')
  metrics.update(checkpoint_sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest(),checkpoint_bytes=checkpoint.stat().st_size)
  audio_encoder=load_feather_hubert(src/'feather_hubert.pth',torch.device('cuda'))
  with torch.inference_mode():model(torch.zeros(16,6,144,144,device='cuda'),torch.zeros(16,model.audio_half_window*4,1024,device='cuda'))
  torch.cuda.synchronize();metrics['cold_load_seconds']=time.perf_counter()-start
  inp=manifest();test=O/'K03/test-dataset';paths=sorted((AV/'full_imgs').glob('*.png'),key=lambda p:int(p.stem));coords=pickle.loads((AV/'coords.pkl').read_bytes())
  run=time.perf_counter();t=time.perf_counter();wave,sr=sf.read(str(O/inp['audio']),dtype='float32');features=make_even_first_dim(get_feather_hubert_from_16k_speech(wave,audio_encoder,device=torch.device('cuda'))).numpy().reshape(-1,2,1024)
  if len(features)<N:features=np.pad(features,((0,N-len(features)),(0,0),(0,0)))
  metrics['feature_seconds']=time.perf_counter()-t
  encoder=Encoder(O/label/f'{label}-60s.mp4',O/inp['audio']);inference=read=blend=0;first=None;torch.cuda.reset_peak_memory_stats();batch_times=[]
  for index in range(0,N,16):
   bt=time.perf_counter();t=time.perf_counter();frames=[];inputs=[];audio=[];geometry=[];ids=inp['test_frame_ids'][index:index+16]
   for j,idx in enumerate(ids):
    frame=cv2.imread(str(paths[idx]));model_input,face_crop,bbox,original_size=prepare_model_input(frame,str(test/'landmarks'/f'{index+j}.lms'),torch.device('cuda'))
    frames.append(frame);inputs.append(model_input);geometry.append((face_crop,bbox,original_size));audio.append(reshape_audio_feat(gather_audio_window(features,index+j,half_window=model.audio_half_window),raw_hubert=model.raw_hubert_audio))
   read+=time.perf_counter()-t;t=time.perf_counter()
   with torch.inference_mode():preds=model(torch.cat(inputs),torch.stack(audio).cuda()).cpu().numpy().transpose(0,2,3,1)
   torch.cuda.synchronize();inference+=time.perf_counter()-t
   for j,pred in enumerate(preds):
    t=time.perf_counter();generated=frames[j].copy();paste_prediction(generated,np.clip(pred*255,0,255).astype(np.uint8),*geometry[j]);x1,y1,x2,y2=map(int,coords[ids[j]])
    out=mouth_blend(frames[j],generated[y1:y2,x1:x2],coords[ids[j]],color=True);blend+=time.perf_counter()-t
    if first is None:first=time.perf_counter()-run
    encoder.write(out)
    if index+j in [50,275,550,850,1150,1400]:
     p=O/label/'stills'/f'{index+j:04d}.jpg';p.parent.mkdir(parents=True,exist_ok=True);cv2.imwrite(str(p),out)
   batch_times.append(time.perf_counter()-bt)
   if index%80==0:save(f'{label}/progress.json',{'frame':min(index+16,N),'of':N,'elapsed_seconds':time.perf_counter()-run})
  encoded=encoder.close();wall=time.perf_counter()-run
  metrics.update(ok=True,**encoded,render_wall_seconds=wall,total_with_load_seconds=time.perf_counter()-start,inference_seconds=inference,read_preprocess_seconds=read,blend_seconds=blend,first_frame_seconds=first,first_frame_excludes_model_load=True,render_fps=N/wall,render_rtf=wall/60,torch_peak_allocated_mib=torch.cuda.max_memory_allocated()/2**20,torch_peak_reserved_mib=torch.cuda.max_memory_reserved()/2**20,batch_seconds_p50=float(np.percentile(batch_times,50)),batch_seconds_p95=float(np.percentile(batch_times,95)),video=f'{label}/{label}-60s.mp4',input_audio_sha256=inp['audio_sha256'],notes=['Identity trained on disjoint motion clips and independent O07 speech using K01 synthetic mouth labels. This is not real human speech ground truth.','Teacher errors can be inherited; 60 epochs is an initial training budget, not a proof of model quality ceiling.','Original 144 px author preprocessing and 20-frame audio context are retained.'])
 except Exception as exc:metrics.update(error=str(exc),traceback=traceback.format_exc())
 finally:metrics.update(mon.finish());save(f'{label}/result.json',metrics);print(json.dumps(metrics,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
