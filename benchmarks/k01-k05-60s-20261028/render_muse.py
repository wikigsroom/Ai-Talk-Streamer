"""K01 current MuseTalk and K02 bounded composite ablation, same 60 s input."""
from bench_common import *
import soundfile as sf
os.chdir(LIVE);sys.path.insert(0,str(LIVE))
import torch
torch.set_num_threads(1);torch.set_num_interop_threads(1)
torch.backends.cudnn.benchmark=True
if hasattr(torch.backends.cudnn,'benchmark_limit'):torch.backends.cudnn.benchmark_limit=3
from avatars.musetalk_avatar import load_model,load_avatar,warm_up,MuseReal
from avatars.audio_features.whisper import WhisperASR

def main():
 label=sys.argv[1] if len(sys.argv)>1 else 'K01'
 training=label=='TRAIN'
 mon=Monitor(label);start=time.perf_counter();metrics={'id':label,'name':'MuseTalk 1.5 原方案' if label=='K01' else 'MuseTalk 1.5 局部融合优化','ok':False,'audio_seconds':60,'offline_prerecorded':True,'batch_size':8,'configuration':'fp16 / batch 8 / native PyTorch','cold_load_seconds':None}
 try:
  inp=manifest()
  if training:
   inp=dict(inp,audio='training/audio.wav',test_frame_ids=inp['train_frame_ids'])
  count=len(inp['test_frame_ids']);wave,sr=sf.read(str(O/inp['audio']),dtype='float32');assert sr==16000 and len(wave)==count*640
  model=load_model();avatar=load_avatar(inp['avatar']);warm_up(8,model);torch.cuda.synchronize();metrics['cold_load_seconds']=time.perf_counter()-start
  renderer=MuseReal.__new__(MuseReal);renderer.vae,renderer.unet,renderer.pe,renderer.timesteps,renderer.audio_processor=model
  renderer.frame_list_cycle,renderer.mask_list_cycle,renderer.coord_list_cycle,renderer.mask_coords_list_cycle,renderer.input_latent_list_cycle=avatar;renderer.batch_size=8
  asr=WhisperASR.__new__(WhisperASR)
  # Stream-equivalent 10 left + 10 right audio chunks, each 20 ms.
  padded=np.pad(wave,(3200,3200+5120));feature_seconds=0;inference_seconds=0;blend_seconds=0;read_seconds=0
  encoder=None if training else Encoder(O/label/f'{label}-60s.mp4',O/inp['audio']);t_run=time.perf_counter();torch.cuda.reset_peak_memory_stats()
  if training:(O/'training/full_body_img').mkdir(parents=True,exist_ok=True)
  first=None;batch_times=[];silence_frames=0
  for index in range(0,count,8):
   batch_tick=time.perf_counter();start_sample=index*640
   # 10 history chunks + 16 current output chunks + 10 lookahead chunks.
   context=padded[start_sample:start_sample+11520]
   t=time.perf_counter();features=renderer.audio_processor.audio2feat(context)
   chunks=asr._feature2chunks(features,8,audio_feat_win=[2,3],start=5,feature_idx_multiplier=2);torch.cuda.synchronize();feature_seconds+=time.perf_counter()-t
   ids=inp['test_frame_ids'][index:index+8];ids+=ids[-1:]*(8-len(ids));renderer._studio_frame_indices=ids
   t=time.perf_counter();preds=renderer.inference_batch(index,chunks);torch.cuda.synchronize();inference_seconds+=time.perf_counter()-t
   for j,pred in enumerate(preds):
    if index+j>=count:break
    t=time.perf_counter();idx=ids[j]
    if label=='K01' or training:frame=renderer.paste_back_frame(pred,idx)
    else:
     original=renderer.frame_list_cycle[idx];chunk=wave[(index+j)*640:(index+j+1)*640]
     rms=float(np.sqrt(np.mean(chunk*chunk)))
     # 80 ms attack/release avoids framewise gating flicker. Full speech is unchanged.
     target=0.0 if rms<.0015 else 1.0
     gate=target if index+j==0 else .65*gate+.35*target
     frame=mouth_blend(original,pred,renderer.coord_list_cycle[idx],gate,color=True)
     if gate<.1:silence_frames+=1
    blend_seconds+=time.perf_counter()-t
    if first is None:first=time.perf_counter()-t_run
    if training:cv2.imwrite(str(O/'training/full_body_img'/f'{index+j}.jpg'),frame,[cv2.IMWRITE_JPEG_QUALITY,96])
    else:encoder.write(frame)
    if index+j in [50,275,550,850,1150,1400]:
     path=O/label/'stills'/f'{index+j:04d}.jpg';path.parent.mkdir(parents=True,exist_ok=True);cv2.imwrite(str(path),frame)
   batch_times.append(time.perf_counter()-batch_tick)
   if index%80==0:save(f'{label}/progress.json',{'frame':min(index+8,count),'of':count,'elapsed_seconds':time.perf_counter()-t_run});print(label,index,flush=True)
  encoded=encoder.close() if encoder else {'frames_encoded':count};torch.cuda.synchronize();wall=time.perf_counter()-t_run
  metrics.update(ok=True,**encoded,render_wall_seconds=wall,total_with_load_seconds=time.perf_counter()-start,feature_seconds=feature_seconds,inference_seconds=inference_seconds,blend_seconds=blend_seconds,first_frame_seconds=first,render_fps=N/wall,render_rtf=wall/60,first_frame_excludes_model_load=True,torch_peak_allocated_mib=torch.cuda.max_memory_allocated()/2**20,torch_peak_reserved_mib=torch.cuda.max_memory_reserved()/2**20,batch_seconds_p50=float(np.percentile(batch_times,50)),batch_seconds_p95=float(np.percentile(batch_times,95)),silence_gated_frames=silence_frames,input_audio_sha256=inp['audio_sha256'],video=f'{label}/{label}-60s.mp4',mouth_only_requested=True,notes=['K01 uses the production face mask; K02 narrows to lower-face ellipse, bounded median color match and silence crossfade.','Offline processing supplies 200 ms right audio context. This is not a platform end-to-end latency measurement.'])
  if training:
   metrics.update(name='MuseTalk 1.5 teacher material preparation',audio_seconds=count/FPS,render_fps=count/wall,render_rtf=wall/(count/FPS),input_audio_sha256=hashlib.sha256((O/inp['audio']).read_bytes()).hexdigest(),video=None,frames_saved_as_jpeg=count)
 except Exception as exc:metrics.update(error=str(exc),traceback=traceback.format_exc())
 finally:
  metrics.update(mon.finish());save(f'{label}/result.json',metrics);print(json.dumps(metrics,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
