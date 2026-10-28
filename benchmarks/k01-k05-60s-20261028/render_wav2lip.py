"""K04: original GAN checkpoint, original 96 px / 80-bin mel network, cached geometry."""
from bench_common import *
import pickle,soundfile as sf
from scipy.signal import lfilter
import librosa
os.chdir(LIVE);sys.path.insert(0,str(LIVE))
import torch
torch.set_num_threads(1);torch.set_num_interop_threads(1)
torch.backends.cudnn.benchmark=True
import types,importlib.util
pkg=types.ModuleType('bench_wav2lip');pkg.__path__=[str(W/'wav2lip-original')];sys.modules[pkg.__name__]=pkg
spec=importlib.util.spec_from_file_location('bench_wav2lip.wav2lip',W/'wav2lip-original/wav2lip.py');original_module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=original_module;spec.loader.exec_module(original_module);Wav2Lip=original_module.Wav2Lip

def main():
 label='K04';mon=Monitor(label);start=time.perf_counter();metrics={'id':label,'name':'Wav2Lip GAN','ok':False,'audio_seconds':60,'configuration':'original 96x96 / FP32 / batch 16','batch_size':16,'offline_prerecorded':True,'license_note':'Original public weights are for non-commercial research; deployment requires separate rights review.'}
 try:
  inp=manifest();wave,sr=sf.read(str(O/inp['audio']),dtype='float32');assert sr==16000
  model=Wav2Lip();ckpt=torch.load(R/'models/lipsync-benchmark/wav2lip/checkpoints/wav2lip_gan.pth',map_location='cpu',weights_only=False)
  model.load_state_dict({k.replace('module.',''):v for k,v in ckpt['state_dict'].items()});model=model.cuda().eval()
  with torch.inference_mode():model(torch.zeros(16,1,80,16,device='cuda'),torch.zeros(16,6,96,96,device='cuda'))
  torch.cuda.synchronize();metrics['cold_load_seconds']=time.perf_counter()-start
  coords=pickle.loads((AV/'coords.pkl').read_bytes());paths=sorted((AV/'full_imgs').glob('*.png'),key=lambda p:int(p.stem))
  t_run=time.perf_counter();tick=time.perf_counter();pre=lfilter([1,-.97],[1],wave)
  spec=np.abs(librosa.stft(pre,n_fft=800,hop_length=200,win_length=800))
  mel=np.dot(librosa.filters.mel(sr=16000,n_fft=800,n_mels=80,fmin=55,fmax=7600),spec)
  mel=20*np.log10(np.maximum(1e-5,mel))-20;mel=np.clip(8*((mel+100)/100)-4,-4,4).astype(np.float32)
  metrics['feature_seconds']=time.perf_counter()-tick
  encoder=Encoder(O/label/f'{label}-60s.mp4',O/inp['audio']);inference=read=blend=0;first=None;batch_times=[];torch.cuda.reset_peak_memory_stats()
  for index in range(0,N,16):
   bt=time.perf_counter();t=time.perf_counter();ids=inp['test_frame_ids'][index:index+16];frames=[cv2.imread(str(paths[i])) for i in ids];crops=[];mels=[]
   for j,(idx,frame) in enumerate(zip(ids,frames)):
    x1,y1,x2,y2=coords[idx];crop=cv2.resize(frame[y1:y2,x1:x2],(96,96));masked=crop.copy();masked[48:]=0;crops.append(np.concatenate([masked,crop],axis=2)/255.)
    mel_start=min(int((index+j)*80/25),mel.shape[1]-16);mels.append(mel[:,mel_start:mel_start+16])
   read+=time.perf_counter()-t;t=time.perf_counter()
   im=torch.from_numpy(np.asarray(crops,dtype=np.float32).transpose(0,3,1,2)).cuda();aud=torch.from_numpy(np.asarray(mels)[:,None]).cuda()
   with torch.inference_mode():pred=model(aud,im).cpu().numpy().transpose(0,2,3,1)*255
   torch.cuda.synchronize();inference+=time.perf_counter()-t
   for j,patch in enumerate(pred):
    t=time.perf_counter();frame=mouth_blend(frames[j],patch,coords[ids[j]],color=True);blend+=time.perf_counter()-t
    if first is None:first=time.perf_counter()-t_run
    encoder.write(frame)
    if index+j in [50,275,550,850,1150,1400]:
     p=O/label/'stills'/f'{index+j:04d}.jpg';p.parent.mkdir(parents=True,exist_ok=True);cv2.imwrite(str(p),frame)
   batch_times.append(time.perf_counter()-bt)
   if index%80==0:save(f'{label}/progress.json',{'frame':min(index+16,N),'of':N,'elapsed_seconds':time.perf_counter()-t_run})
  encoded=encoder.close();wall=time.perf_counter()-t_run
  metrics.update(ok=True,**encoded,render_wall_seconds=wall,total_with_load_seconds=time.perf_counter()-start,inference_seconds=inference,read_preprocess_seconds=read,blend_seconds=blend,first_frame_seconds=first,first_frame_excludes_model_load=True,render_fps=N/wall,render_rtf=wall/60,torch_peak_allocated_mib=torch.cuda.max_memory_allocated()/2**20,torch_peak_reserved_mib=torch.cuda.max_memory_reserved()/2**20,batch_seconds_p50=float(np.percentile(batch_times,50)),batch_seconds_p95=float(np.percentile(batch_times,95)),video=f'{label}/{label}-60s.mp4',input_audio_sha256=inp['audio_sha256'],notes=['Uses existing avatar face coordinates; no redetection or replacement of full-body motion.','Lower-face ellipse and bounded color match are shared with K02, K03 and K05.'])
 except Exception as exc:metrics.update(error=str(exc),traceback=traceback.format_exc())
 finally:metrics.update(mon.finish());save(f'{label}/result.json',metrics);print(json.dumps(metrics,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
