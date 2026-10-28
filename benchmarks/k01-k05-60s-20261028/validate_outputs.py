"""Decode every finished video; assert duration, frame count and common audio."""
from bench_common import *
import soundfile as sf,pickle
from scipy.signal import correlate,correlation_lags

def main():
 requested=set(sys.argv[1:]);valid_ids={'K01','K02','K03','K04','K05'}
 if requested and not requested<=valid_ids:raise ValueError('Only explicit benchmark IDs may be validated')
 inp=manifest();coords=pickle.loads((AV/'coords.pkl').read_bytes());paths=sorted((AV/'full_imgs').glob('*.png'),key=lambda p:int(p.stem));reference,sr=sf.read(str(O/inp['audio']),dtype='float32');all_results=[];reused=[]
 probe=str(Path(ffmpeg()).with_name('ffprobe.exe'))
 for label in ['K01','K02','K03','K04','K05']:
  result_path=O/label/'result.json'
  if not result_path.exists():all_results.append({'id':label,'verified':False,'status':'not_run'});continue
  result=json.loads(result_path.read_text(encoding='utf-8'))
  if not result.get('ok'):all_results.append({'id':label,'verified':False,'status':'render_failed','error':result.get('error')});continue
  prior=O/label/'verification.json'
  if requested and label not in requested and prior.exists():all_results.append(json.loads(prior.read_text(encoding='utf-8')));continue
  if not requested and prior.exists():
   previous=json.loads(prior.read_text(encoding='utf-8'));video=O/result['video']
   # Prior full-frame/source-pixel/audio evidence is still valid for identical
   # video and frozen audio bytes. Avoid decoding unchanged successes again.
   if previous.get('verified') and result.get('input_audio_sha256')==inp['audio_sha256'] and previous.get('video_sha256')==hashlib.sha256(video.read_bytes()).hexdigest():
    all_results.append(previous);reused.append({'id':label,'video_sha256':previous['video_sha256'],'source_audio_sha256':inp['audio_sha256'],'reused_original_full_decode_and_source_checks':True});continue
  video=O/result['video'];metadata=json.loads(subprocess.check_output([probe,'-v','error','-show_streams','-show_format','-of','json',str(video)],creationflags=subprocess.CREATE_NO_WINDOW));v=next(s for s in metadata['streams'] if s['codec_type']=='video');a=next(s for s in metadata['streams'] if s['codec_type']=='audio')
  raw=subprocess.check_output([ffmpeg(),'-v','error','-i',str(video),'-map','0:a:0','-f','f32le','-ar','16000','-ac','1','pipe:1'],creationflags=subprocess.CREATE_NO_WINDOW);decoded=np.frombuffer(raw,dtype='<f4');length=min(len(reference),len(decoded));x=reference[:length];y=decoded[:length]
  corr=correlate(y-y.mean(),x-x.mean(),mode='full',method='fft');lags=correlation_lags(len(y),len(x),mode='full');valid=np.abs(lags)<1600;best=np.flatnonzero(valid)[np.argmax(corr[valid])];lag=int(lags[best]);correlation=float(corr[best]/np.sqrt(np.sum((x-x.mean())**2)*np.sum((y-y.mean())**2)))
  cap=cv2.VideoCapture(os.path.relpath(video));count=0;outside=[];mouth=[];last=None;cuts={round(c['timeline_start_seconds']*25) for c in inp['test_clips']}
  while True:
   ok,frame=cap.read()
   if not ok:break
   if count>=N:count+=1;continue
   if count%25==0:
    idx=inp['test_frame_ids'][count];source=cv2.imread(str(paths[idx]));x1,y1,x2,y2=map(int,coords[idx]);mask=np.ones(frame.shape[:2],bool);mask[max(0,y1-8):y2+8,max(0,x1-8):x2+8]=False
    outside.append(float(np.abs(frame.astype(np.float32)-source.astype(np.float32))[mask].mean()))
   if count%5==0:
    idx=inp['test_frame_ids'][count];x1,y1,x2,y2=map(int,coords[idx]);patch=cv2.resize(frame[y1:y2,x1:x2],(64,64))
    if last is not None and count not in cuts:mouth.append(float(np.abs(patch.astype(np.float32)-last.astype(np.float32)).mean()))
    last=patch
   count+=1
  cap.release();duration=float(v.get('duration',metadata['format']['duration']));checks={'decoded_frames_1500':count==N,'resolution_720x1280':v['width']==720 and v['height']==1280,'fps_25':v['avg_frame_rate']=='25/1','duration_60s':abs(duration-60)<.045,'common_audio_sha256':result.get('input_audio_sha256')==inp['audio_sha256'],'audio_correlation_above_0_98':correlation>.98,'audio_offset_below_20ms':abs(lag)/16000<.02,'outside_face_mean_pixel_error_below_3':float(np.mean(outside))<3}
  row={'id':label,'verified':all(checks.values()),'checks':checks,'decoded_frames':count,'video_seconds':duration,'audio_seconds':len(decoded)/16000,'audio_correlation':correlation,'audio_offset_ms':lag/16,'outside_face_mean_absolute_pixel_error':float(np.mean(outside)),'face_temporal_mean_absolute_difference':float(np.mean(mouth)),'face_temporal_metric_is_not_a_quality_score':True,'video_sha256':hashlib.sha256(video.read_bytes()).hexdigest(),'metadata':metadata}
  save(f'{label}/verification.json',row);all_results.append(row)
 save('verification-summary.json',all_results)
 if not requested:save('verification-reuse.json',{'observed_at':time.time(),'unchanged_verified_files':reused,'note':'Original full-frame, source-pixel and soundtrack proofs are retained unchanged after byte-identical video and frozen source-audio hash checks. New or changed files are fully decoded.'})
if __name__=='__main__':main()
