"""Author FeatherTalk landmarks and audio, with disjoint training/test motion."""
from bench_common import *
import soundfile as sf,shutil
import torch

def main():
 start=time.perf_counter();src=R/'src/lipsync-benchmark/feather';sys.path.insert(0,str(src));sys.path.insert(0,str(src/'data_utils'));os.chdir(src/'data_utils')
 torch.set_num_threads(2);cpu_only='--cpu' in sys.argv;device=torch.device('cpu' if cpu_only else 'cuda')
 # These three pinned upstream checkpoints predate PyTorch's weights_only default.
 original_load=torch.load
 def trusted_load(*args,**kwargs):kwargs.setdefault('weights_only',False);return original_load(*args,**kwargs)
 torch.load=trusted_load
 from get_landmark import Landmark
 from feather_hubert.feather_hubert import load_feather_hubert,get_feather_hubert_from_16k_speech,make_even_first_dim
 inp=manifest();paths=sorted((AV/'full_imgs').glob('*.png'),key=lambda p:int(p.stem));test=O/'K03/test-dataset';train=O/'training'
 for folder,count in [(test,N),(train,len(inp['train_frame_ids']))]:
  folder.mkdir(parents=True,exist_ok=True)
  (folder/'clip_ranges.json').write_text(json.dumps({'ranges':[{'start':s,'end':min(s+200,count)} for s in range(0,count,200)]},indent=2),encoding='utf-8')
 (test/'full_body_img').mkdir(parents=True,exist_ok=True)
 for i,idx in enumerate(inp['test_frame_ids']):
  p=test/'full_body_img'/f'{i}.jpg'
  if not p.exists():cv2.imwrite(str(p),cv2.imread(str(paths[idx])),[cv2.IMWRITE_JPEG_QUALITY,96])
 shutil.copy2(O/inp['audio'],test/'aud.wav');shutil.copy2(train/'audio.wav',train/'aud.wav')
 original_cuda_available=torch.cuda.is_available
 if cpu_only:torch.cuda.is_available=lambda:False
 try:landmark=Landmark()
 finally:torch.cuda.is_available=original_cuda_available
 if cpu_only:
  from landmark_cpu_batch import configure,infer
  configure(landmark,src/'data_utils')
  sample=[train/'full_body_img'/f'{i}.jpg' for i in range(10)]
  reference=infer(landmark,sample);differences=[]
  for i,points in enumerate(reference):
   p=train/'landmarks'/f'{i}.lms'
   if p.exists():differences.append(float(np.max(np.abs(np.loadtxt(p)-points))))
  if differences and max(differences)>1:raise RuntimeError('CPU batching changed original landmarks by more than one pixel')
  save('K03/preprocess-backend-check.json',{'same_weights':True,'scrfd':'ONNX Runtime CPU, 2 threads','pfld':'original PyTorch FP32 CPU, batch16, 2 threads','landmark_max_pixel_difference':differences,'cuda_used':False})
 for label,folder,count in [('training',train,len(inp['train_frame_ids'])),('test',test,N)]:
  (folder/'landmarks').mkdir(exist_ok=True)
  remaining=[]
  for i in range(count):
   p=folder/'landmarks'/f'{i}.lms'
   try:valid=p.exists() and np.loadtxt(p).shape==(110,2)
   except ValueError:valid=False
   if not valid:remaining.append(i)
  for start_index in range(0,len(remaining),16 if cpu_only else 1):
   indices=remaining[start_index:start_index+(16 if cpu_only else 1)]
   if cpu_only:points=infer(landmark,[folder/'full_body_img'/f'{i}.jpg' for i in indices])
   else:
    i=indices[0]
    with torch.inference_mode():pts,x,y=landmark.detect(str(folder/'full_body_img'/f'{i}.jpg'))
    points=[pts+np.array([x,y])]
   for i,pts in zip(indices,points):np.savetxt(str(folder/'landmarks'/f'{i}.lms'),pts,fmt='%d')
   save('K03/preprocess-progress.json',{'stage':'landmarks-'+label,'frame':indices[-1]+1,'total':count,'cpu_batch':16 if cpu_only else None,'observed_at':time.time()})
 del landmark
 if not cpu_only:torch.cuda.empty_cache()
 encoder=load_feather_hubert(src/'feather_hubert.pth',device=device)
 for label,folder,count in [('training',train,len(inp['train_frame_ids'])),('test',test,N)]:
  wave,sr=sf.read(str(folder/'aud.wav'),dtype='float32');assert sr==16000
  features=get_feather_hubert_from_16k_speech(wave,encoder,device=device);features=make_even_first_dim(features).numpy().reshape(-1,2,1024)
  if len(features)<count:features=np.pad(features,((0,count-len(features)),(0,0),(0,0)))
  np.save(folder/'aud_hu.npy',features[:count]);save('K03/preprocess-progress.json',{'stage':'audio-'+label,'frames':len(features)})
 save('K03/preprocessing.json',{'ok':True,'wall_seconds':time.perf_counter()-start,'device':str(device),'cpu_threads':2,'train_frames':len(inp['train_frame_ids']),'test_frames':N,'landmark_detector':'upstream SCRFD/PFLD 110 points','audio_encoder':'upstream FeatherHuBERT','test_motion_disjoint':inp['test_train_motion_disjoint']})
if __name__=='__main__':
 try:main()
 except Exception as exc:result_fail('K03-preprocess',exc);raise
