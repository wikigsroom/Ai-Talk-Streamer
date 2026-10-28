"""K05: native Windows LatentSync 1.6; dlib geometry adapter, original generation."""
from bench_common import *
import types,pickle

def main():
 label='K05';mon=Monitor(label);start=time.perf_counter();metrics={'id':label,'name':'LatentSync 1.6','ok':False,'audio_seconds':60,'offline_prerecorded':True,'configuration':'512 px / FP16 / 16-frame chunks / 20 DDIM steps / CFG 1.5','num_inference_steps':20,'guidance_scale':1.5,'seed':20261028}
 try:
  # Invoke this file in its isolated environment, preserving production packages.
  src=R/'src/lipsync-benchmark/latent';os.chdir(src);sys.path.insert(0,str(src));os.environ['PATH']=str(Path(ffmpeg()).parent)+os.pathsep+os.environ['PATH']
  import torch
  torch.set_num_threads(2);torch.set_num_interop_threads(1)
  # Windows-compatible existing dlib landmarks replace only InsightFace detection.
  # The three canonical eyebrow / nose anchors feed the original AlignRestore.
  import dlib,face_recognition_models
  class Detector:
   def __init__(self,device='cuda'):
    self.detector=dlib.get_frontal_face_detector();self.predictor=dlib.shape_predictor(os.path.relpath(face_recognition_models.pose_predictor_model_location()));self.previous=None
   def __call__(self,image):
    if isinstance(image,torch.Tensor):image=image.cpu().numpy()
    small=cv2.resize(image,(0,0),fx=.5,fy=.5);rects=self.detector(small,0)
    if rects:
     box=max(rects,key=lambda r:r.width()*r.height());rectangle=dlib.rectangle(box.left()*2,box.top()*2,box.right()*2,box.bottom()*2);self.previous=rectangle
    elif self.previous is not None:rectangle=self.previous
    else:raise RuntimeError('dlib adapter did not detect the first face')
    shape=self.predictor(image,rectangle);pts=np.array([(shape.part(i).x,shape.part(i).y) for i in range(68)],np.float32)
    result=np.zeros((106,2),np.float32);result[[43,48,49,51,50]]=pts[17:22].mean(0);result[101:106]=pts[22:27].mean(0);result[[74,77,83,86]]=pts[31:36].mean(0)
    return np.array([rectangle.left(),rectangle.top(),rectangle.right(),rectangle.bottom()]),result
  stub=types.ModuleType('latentsync.utils.face_detector');stub.FaceDetector=Detector;sys.modules[stub.__name__]=stub
  from diffusers import AutoencoderKL,DDIMScheduler
  from omegaconf import OmegaConf
  from latentsync.models.unet import UNet3DConditionModel
  from latentsync.whisper.audio2feature import Audio2Feature
  from latentsync.pipelines.lipsync_pipeline import LipsyncPipeline
  original_load_state=UNet3DConditionModel.load_state_dict
  def checked_load_state(self,*args,**kwargs):
   result=original_load_state(self,*args,**kwargs)
   metrics['checkpoint_key_validation']={'missing_keys':list(result.missing_keys),'unexpected_keys':list(result.unexpected_keys)}
   if result.missing_keys or result.unexpected_keys:raise RuntimeError('UNet checkpoint is not a complete architecture match; refusing a partial-weight benchmark')
   return result
  UNet3DConditionModel.load_state_dict=checked_load_state
  config=OmegaConf.load(src/'configs/unet/stage2_512.yaml')
  scheduler=DDIMScheduler.from_pretrained(str(src/'configs'))
  audio_encoder=Audio2Feature(model_path=str(R/'models/lipsync-benchmark/latent/whisper/tiny.pt'),device='cuda',num_frames=16,audio_feat_length=config.data.audio_feat_length)
  vae=AutoencoderKL.from_pretrained(str(LIVE/'models/sd-vae'),torch_dtype=torch.float16,local_files_only=True);vae.config.scaling_factor=.18215;vae.config.shift_factor=0
  unet,_=UNet3DConditionModel.from_pretrained(OmegaConf.to_container(config.model),str(R/'models/lipsync-benchmark/latent/latentsync_unet.pt'),device='cpu');unet=unet.to(dtype=torch.float16)
  pipe=LipsyncPipeline(vae=vae,audio_encoder=audio_encoder,unet=unet,scheduler=scheduler).to('cuda')
  torch.cuda.synchronize();metrics['cold_load_seconds']=time.perf_counter()-start
  inp=manifest();paths=sorted((AV/'full_imgs').glob('*.png'),key=lambda p:int(p.stem));coords=pickle.loads((AV/'coords.pkl').read_bytes())
  source=O/'inputs/source-motion-60s.mp4'
  tick=time.perf_counter()
  if not source.exists():
   encoder=Encoder(source)
   for idx in inp['test_frame_ids']:encoder.write(cv2.imread(str(paths[idx])))
   encoder.close()
  metrics['source_prepare_seconds']=time.perf_counter()-tick
  torch.cuda.reset_peak_memory_stats();run=time.perf_counter();progress={'denoising_steps_completed':0,'total_denoising_steps':((N+15)//16)*20}
  def callback(i,t,latents):
   progress['denoising_steps_completed']+=1
   if i==19:save(f'{label}/progress.json',dict(progress,elapsed_seconds=time.perf_counter()-run))
  # Timers wrap original stages without modifying network math or sampling strength.
  for obj,attr,key in [(pipe,'affine_transform_video','affine_transform_video_seconds'),(pipe,'restore_video','restore_video_seconds'),(pipe,'decode_latents','decode_latents_seconds'),(pipe.audio_encoder,'audio2feat','feature_seconds'),(pipe.unet,'forward','inference_seconds')]:
   original=getattr(obj,attr)
   def timed(*args,_fn=original,_key=key,**kwargs):
    torch.cuda.synchronize();t=time.perf_counter();out=_fn(*args,**kwargs);torch.cuda.synchronize();metrics[_key]=metrics.get(_key,0)+time.perf_counter()-t;return out
   setattr(obj,attr,timed)
  generated=O/'K05/generated-face-composite.mp4';generated.parent.mkdir(parents=True,exist_ok=True)
  torch.manual_seed(20261028);torch.cuda.manual_seed_all(20261028)
  pipe(video_path=os.path.relpath(source),audio_path=os.path.relpath(O/inp['audio']),video_out_path=os.path.relpath(generated),num_frames=16,num_inference_steps=20,guidance_scale=1.5,weight_dtype=torch.float16,width=512,height=512,mask_image_path=os.path.relpath(src/'latentsync/utils/mask.png'),temp_dir=os.path.relpath(O/'K05/pipeline-temp'),callback=callback)
  torch.cuda.synchronize();metrics['pipeline_wall_seconds']=time.perf_counter()-run
  # Freeze all body, hand and background pixels to the common original motion.
  capture=cv2.VideoCapture(os.path.relpath(generated));encoder=Encoder(O/label/f'{label}-60s.mp4',O/inp['audio']);count=0;blend=0
  while count<N:
   ok,frame=capture.read()
   if not ok:raise RuntimeError(f'LatentSync produced only {count} frames, expected {N}')
   idx=inp['test_frame_ids'][count];original=cv2.imread(str(paths[idx]));x1,y1,x2,y2=map(int,coords[idx]);t=time.perf_counter();out=mouth_blend(original,frame[y1:y2,x1:x2],coords[idx],color=True);blend+=time.perf_counter()-t;encoder.write(out)
   if count in [50,275,550,850,1150,1400]:
    p=O/label/'stills'/f'{count:04d}.jpg';p.parent.mkdir(parents=True,exist_ok=True);cv2.imwrite(str(p),out)
   count+=1
  capture.release();encoded=encoder.close();wall=time.perf_counter()-run
  metrics.update(ok=True,**encoded,render_wall_seconds=wall,total_with_load_seconds=time.perf_counter()-start,blend_seconds=blend,render_fps=N/wall,render_rtf=wall/60,torch_peak_allocated_mib=torch.cuda.max_memory_allocated()/2**20,torch_peak_reserved_mib=torch.cuda.max_memory_reserved()/2**20,video=f'{label}/{label}-60s.mp4',input_audio_sha256=inp['audio_sha256'],notes=['Uses native dlib 68-point landmarks to supply three canonical anchors to the original affine alignment. This is an asset adapter, not the official InsightFace detector baseline.','20-step CFG 1.5 generation is unchanged. No hidden low-step fallback.','Final composite preserves original full-body motion with the same lower-face mask as K02/K03/K04.','Batch offline pipeline has no streaming TTFF measurement; first_frame_seconds is intentionally absent.'])
 except Exception as exc:metrics.update(error=str(exc),traceback=traceback.format_exc())
 finally:metrics.update(mon.finish());save(f'{label}/result.json',metrics);print(json.dumps(metrics,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
