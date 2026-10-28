"""K05 full sampling strength, bounded native-Windows I/O and CPU weight offload.

The network, DDIM update and mask/affine functions come from the pinned upstream.
Only frame residency, VAE batch slicing and weight residency are adapted. This
shared-resource execution mode must be named in the report; it is not the
unmodified full-video official entry point's speed benchmark.
"""
from bench_common import *
import types,pickle,gc,psutil

def main():
 probe='--probe' in sys.argv;resident='--resident' in sys.argv;label=('K05-resident-fit-probe' if resident else 'K05-fit-probe') if probe else 'K05';count=16 if probe else N
 proof=('K05/resident-fit-probe.json' if resident else 'K05/fit-probe.json') if probe else 'K05/result.json';budget=8192 if resident else 4096;wait_seconds=0
 if (O/proof).exists():
  old=json.loads((O/proof).read_text(encoding='utf-8'));save('attempts/'+label+'-'+str(int(time.time()))+'.json',old)
 mon=Monitor(label);start=time.perf_counter();metrics={'id':'K05','name':'LatentSync 1.6','ok':False,'probe_only':probe,'audio_seconds':count/FPS,'offline_prerecorded':True,'configuration':'512 px / FP16 / 16-frame chunks / 20 DDIM steps / CFG 1.5','num_inference_steps':20,'guidance_scale':1.5,'seed':20261028,'execution_adapter':'bounded frame I/O + VAE batch slicing + sequential CPU weight offload','allocator_limit_mib':budget,'source_input':'original common PNG frames; no intermediate source H.264 generation loss'}
 if resident:metrics['execution_adapter']='bounded frame I/O + VAE batch slicing + resident CUDA weights'
 def guard(initial=False):
  nonlocal wait_seconds
  tick=time.perf_counter();waited=False
  while True:
   free=float(subprocess.check_output(['nvidia-smi','--query-gpu=memory.free','--format=csv,noheader,nounits'],creationflags=subprocess.CREATE_NO_WINDOW).decode().splitlines()[0]);ram=psutil.virtual_memory().available/2**30;cpu=psutil.cpu_percent(.2)
   if free>=((9000 if resident else 8500) if initial else (6000 if resident else 6500)) and ram>=((6 if resident else 12) if initial else 4) and cpu<(85 if initial else 99):break
   waited=True;save('K05/bounded-progress.json',{'stage':'waiting for spare resources','initial_load':initial,'gpu_free_mib':free,'ram_free_gib':ram,'cpu_percent':cpu,'frames_completed':metrics.get('frames_completed',0),'probe_only':probe});time.sleep(10)
  if waited:wait_seconds+=time.perf_counter()-tick
 try:
  guard(True);psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
  src=R/'src/lipsync-benchmark/latent';os.chdir(src);sys.path.insert(0,str(src));os.environ['PATH']=str(Path(ffmpeg()).parent)+os.pathsep+os.environ['PATH']
  import torch
  torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.set_grad_enabled(False)
  torch.cuda.set_per_process_memory_fraction(budget*2**20/torch.cuda.get_device_properties(0).total_memory)
  import dlib,face_recognition_models
  class Detector:
   def __init__(self,device='cuda'):
    self.detector=dlib.get_frontal_face_detector();self.predictor=dlib.shape_predictor(os.path.relpath(face_recognition_models.pose_predictor_model_location()));self.previous=None
   def __call__(self,image):
    if isinstance(image,torch.Tensor):image=image.cpu().numpy()
    rects=self.detector(cv2.resize(image,(0,0),fx=.5,fy=.5),0)
    if rects:
     box=max(rects,key=lambda r:r.width()*r.height());rectangle=dlib.rectangle(box.left()*2,box.top()*2,box.right()*2,box.bottom()*2);self.previous=rectangle
    elif self.previous is not None:rectangle=self.previous
    else:raise RuntimeError('No initial face detected by the native geometry adapter')
    shape=self.predictor(image,rectangle);pts=np.array([(shape.part(i).x,shape.part(i).y) for i in range(68)],np.float32)
    points=np.zeros((106,2),np.float32);points[[43,48,49,51,50]]=pts[17:22].mean(0);points[101:106]=pts[22:27].mean(0);points[[74,77,83,86]]=pts[31:36].mean(0)
    return np.array([rectangle.left(),rectangle.top(),rectangle.right(),rectangle.bottom()]),points
  stub=types.ModuleType('latentsync.utils.face_detector');stub.FaceDetector=Detector;sys.modules[stub.__name__]=stub
  from diffusers import AutoencoderKL,DDIMScheduler
  from omegaconf import OmegaConf
  from latentsync.models.unet import UNet3DConditionModel
  from latentsync.whisper.audio2feature import Audio2Feature
  from latentsync.pipelines.lipsync_pipeline import LipsyncPipeline
  from latentsync.utils.image_processor import ImageProcessor,load_fixed_mask
  config=OmegaConf.load(src/'configs/unet/stage2_512.yaml');scheduler=DDIMScheduler.from_pretrained(str(src/'configs'))
  audio_encoder=Audio2Feature(model_path=str(R/'models/lipsync-benchmark/latent/whisper/tiny.pt'),device='cuda',num_frames=16,audio_feat_length=config.data.audio_feat_length)
  vae=AutoencoderKL.from_pretrained(str(LIVE/'models/sd-vae'),torch_dtype=torch.float16,local_files_only=True);vae.config.scaling_factor=.18215;vae.config.shift_factor=0;vae.enable_slicing()
  # Avoid a second 5GB FP32 allocation while other projects use system RAM.
  # Strict assignment validates every original key/shape; all weights are cast
  # to the same FP16 dtype as the upstream inference entry point.
  from accelerate import init_empty_weights
  with init_empty_weights():unet=UNet3DConditionModel.from_config(OmegaConf.to_container(config.model))
  raw=torch.load(str(R/'models/lipsync-benchmark/latent/latentsync_unet.pt'),map_location='cpu',mmap=True,weights_only=True)
  load_device='cuda' if resident else 'cpu'
  half={k:(v.to(device=load_device,dtype=torch.float16) if v.is_floating_point() else v.to(device=load_device)) for k,v in raw['state_dict'].items()}
  checked=torch.nn.Module.load_state_dict(unet,half,strict=True,assign=True)
  metrics['checkpoint_key_validation']={'missing_keys':list(checked.missing_keys),'unexpected_keys':list(checked.unexpected_keys),'strict':True,'mmap_meta_initialization':True,'direct_resident_device_loading':resident};del half,raw
  unet=unet.to(dtype=torch.float16);gc.collect()
  pipe=LipsyncPipeline(vae=vae,audio_encoder=audio_encoder,unet=unet,scheduler=scheduler)
  # Accelerate moves individual modules without changing precision or attention.
  if resident:pipe.to('cuda')
  else:pipe.enable_sequential_cpu_offload(gpu_id=0,device='cuda')
  pipe.unet.eval();pipe.vae.eval();gc.collect()
  metrics['runtime_versions']={'torch':torch.__version__}
  import diffusers,accelerate
  metrics['runtime_versions'].update(diffusers=diffusers.__version__,accelerate=accelerate.__version__)
  torch.cuda.synchronize();metrics['cold_load_seconds']=time.perf_counter()-start-wait_seconds
  inp=manifest();paths=sorted((AV/'full_imgs').glob('*.png'),key=lambda p:int(p.stem));coords=pickle.loads((AV/'coords.pkl').read_bytes())
  torch.cuda.reset_peak_memory_stats();run=time.perf_counter();wait_at_run=wait_seconds
  def timed(fn,key,*args,**kwargs):
   torch.cuda.synchronize();tick=time.perf_counter();out=fn(*args,**kwargs);torch.cuda.synchronize();metrics[key]=metrics.get(key,0)+time.perf_counter()-tick;return out
  feature=timed(audio_encoder.audio2feat,'feature_seconds',os.path.relpath(O/inp['audio']));chunks=audio_encoder.feature2chunks(feature_array=feature,fps=FPS)
  metrics['available_audio_feature_frames']=len(chunks)
  if len(chunks)<count:raise RuntimeError('Audio encoder did not cover every requested frame')
  pipe.image_processor=ImageProcessor(512,device='cuda',mask_image=load_fixed_mask(512,os.path.relpath(src/'latentsync/utils/mask.png')))
  scheduler.set_timesteps(20,device='cuda');timesteps=scheduler.timesteps;extra=pipe.prepare_extra_step_kwargs(None,0.0)
  torch.manual_seed(20261028);torch.cuda.manual_seed_all(20261028)
  all_latents=pipe.prepare_latents(count,pipe.vae.config.latent_channels,512,512,torch.float16,torch.device('cuda'),None)
  target=O/('diagnostics/k05-resident-fit/probe-0p64s.mp4' if resident else 'diagnostics/k05-fit/probe-0p64s.mp4') if probe else O/'K05/K05-60s.mp4';encoder=Encoder(target,O/inp['audio']) if not probe else Encoder(target)
  for offset in range(0,count,16):
   gc.collect();torch.cuda.empty_cache();guard(False)
   ids=inp['test_frame_ids'][offset:min(offset+16,count)];originals=[cv2.imread(str(paths[i])) for i in ids]
   rgb=np.stack([cv2.cvtColor(frame,cv2.COLOR_BGR2RGB) for frame in originals])
   faces,boxes,matrices=timed(pipe.affine_transform_video,'affine_transform_video_seconds',rgb)
   audio_embeds=torch.stack(chunks[offset:offset+len(ids)]).to('cuda',dtype=torch.float16);audio_embeds=torch.cat([torch.zeros_like(audio_embeds),audio_embeds])
   latents=all_latents[:,:,offset:offset+len(ids)]
   ref,masked,masks=pipe.image_processor.prepare_masks_and_masked_images(faces,affine_transform=False)
   mask_latents,masked_latents=timed(pipe.prepare_mask_latents,'vae_encode_seconds',masks,masked,512,512,torch.float16,torch.device('cuda'),None,True)
   ref_latents=timed(pipe.prepare_image_latents,'vae_encode_seconds',ref,torch.device('cuda'),torch.float16,None,True)
   for step,t in enumerate(timesteps):
    unet_input=scheduler.scale_model_input(torch.cat([latents]*2),t);unet_input=torch.cat([unet_input,mask_latents,masked_latents,ref_latents],dim=1)
    predicted=timed(pipe.unet,'inference_seconds',unet_input,t,encoder_hidden_states=audio_embeds).sample
    uncond,audio=predicted.chunk(2);predicted=uncond+1.5*(audio-uncond)
    latents=scheduler.step(predicted,t,latents,**extra).prev_sample
    save('K05/bounded-progress.json',{'stage':'denoising','frames_completed':offset,'chunk_frames':len(ids),'step':step+1,'steps_per_chunk':20,'total_frames':count,'elapsed_seconds':time.perf_counter()-run,'probe_only':probe})
   decoded=timed(pipe.decode_latents,'decode_latents_seconds',latents)
   decoded=pipe.paste_surrounding_pixels_back(decoded,ref,1-masks,torch.device('cuda'),torch.float16)
   restored=timed(pipe.restore_video,'restore_video_seconds',decoded,rgb,boxes,matrices)
   for j,frame in enumerate(restored):
    idx=offset+j;tick=time.perf_counter();frame=cv2.cvtColor(frame,cv2.COLOR_RGB2BGR);x1,y1,x2,y2=map(int,coords[ids[j]])
    out=mouth_blend(originals[j],frame[y1:y2,x1:x2],coords[ids[j]],color=True);metrics['blend_seconds']=metrics.get('blend_seconds',0)+time.perf_counter()-tick;encoder.write(out)
    if not probe and idx in [50,275,550,850,1150,1400]:
     still=O/'K05/stills'/f'{idx:04d}.jpg';still.parent.mkdir(parents=True,exist_ok=True);cv2.imwrite(str(still),out)
   metrics['frames_completed']=offset+len(ids);save('K05/bounded-progress.json',{'stage':'encoded chunk','frames_completed':metrics['frames_completed'],'total_frames':count,'elapsed_seconds':time.perf_counter()-run,'probe_only':probe})
   del originals,rgb,faces,boxes,matrices,audio_embeds,latents,ref,masked,masks,mask_latents,masked_latents,ref_latents,unet_input,predicted,uncond,audio,decoded,restored
  encoded=encoder.close();torch.cuda.synchronize();wall=time.perf_counter()-run;run_wait=wait_seconds-wait_at_run
  metrics.update(ok=True,**encoded,render_wall_seconds=wall,total_with_load_seconds=time.perf_counter()-start,resource_wait_seconds=wait_seconds,render_resource_wait_seconds=run_wait,render_active_seconds=wall-run_wait,render_fps=count/wall,render_rtf=wall/(count/FPS),torch_peak_allocated_mib=torch.cuda.max_memory_allocated()/2**20,torch_peak_reserved_mib=torch.cuda.max_memory_reserved()/2**20,input_audio_sha256=inp['audio_sha256'],video=target.relative_to(O).as_posix(),notes=['Original 512 / 16 frames / 20 DDIM / CFG1.5 / FP16 network strength retained.','Execution: '+metrics['execution_adapter']+'. This is an adapted execution mode, not the official full-video speed entry point.','Native dlib anchors feed the original affine alignment; original mask and restoration math retained.','Final portrait uses the common original body/background and bounded lower-face composite.','Cooperative waits are included in wall time and explicitly split from active execution; no streaming TTFF claimed.'])
 except Exception as exc:
  metrics.update(error=str(exc),traceback=traceback.format_exc())
  if 'encoder' in locals():
   try:encoder.close()
   except Exception:pass
 finally:metrics.update(mon.finish());save(proof,metrics);print(json.dumps(metrics,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
