"""Generate one identical, complete-sentence 60s O07 input; never send to live playback."""
from pathlib import Path
import json,urllib.request,time,hashlib,io,math
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly
R=Path('C:/dev/虚拟数字人直播');O=R/'outputs/lipsync-k01-k05-60s-20261028'
O.mkdir(parents=True,exist_ok=True);(O/'audio').mkdir(exist_ok=True)
sentences=[
'大家好，我是林知夏，欢迎来我的宿舍坐一会儿。',
'这次我们用同样的声音，比较不同模型的嘴部效果。',
'爸爸妈妈准备了八杯冰水，别忘了慢慢喝。',
'小熊吹泡泡，葡萄和苹果放在白色盘子里。',
'遇到复杂的事情，先把它拆成几个小步骤。',
'不要着急，我们可以一边思考，一边慢慢说明。',
'你最近在看什么书，或者有什么喜欢的电影？',
'嗯，我听见了。这个问题，确实值得认真想一想。',
'谢谢你的陪伴，也谢谢每一条真诚的留言。',
'今天先聊到这里，记得休息，我们下次再见。',
'微风吹过窗边，桌上的绿植轻轻摇晃。',
'不必每一步都很完美，保持自己的节奏就好。',
'我们再把数字读一遍，一二三四五六七八九十。',
'闭上嘴巴，然后轻轻呼气。现在放松肩膀，再继续说话。',
'苹果、葡萄、泡泡和白纸，这几个词的嘴形各不相同。',
'说到这里稍微停一下。好了，我们接着看下一段画面。',
'请观察我说话时的牙齿、嘴角，还有下巴的自然变化。',
'最后再说一次，谢谢你，我们下次见。']
segments=[];waves=[];used=.15;tts_seconds=0
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
for i,text in enumerate(sentences):
 p=O/'audio'/f'o07-s{i+1:02d}.wav';meta=p.with_suffix('.json')
 if not p.exists():
  tick=time.perf_counter();req=urllib.request.Request('http://127.0.0.1:9880/tts',json.dumps({'request_id':f'lipsync60-audio-{i+1:02d}','text':text,'voice_id':'O07','allow_fallback':False}).encode(),{'Content-Type':'application/json'})
  with opener.open(req,timeout=120) as response:
   content=response.read();headers={k:v for k,v in response.headers.items() if k.lower().startswith('x-tts-')}
  p.write_bytes(content);meta.write_text(json.dumps({'text':text,'wall_seconds':time.perf_counter()-tick,'headers':headers},ensure_ascii=False,indent=2),encoding='utf-8')
 wave,sr=sf.read(str(p),dtype='float32',always_2d=True);wave=wave.mean(1)
 if sr!=16000:
  factor=math.gcd(sr,16000);wave=resample_poly(wave,16000//factor,sr//factor).astype(np.float32)
 duration=len(wave)/16000
 if used+duration+.22>59.7:
  continue
 start=used;waves.extend([wave,np.zeros(3520,np.float32)]);used+=duration+.22
 m=json.loads(meta.read_text(encoding='utf-8'));tts_seconds+=m['wall_seconds']
 segments.append({'id':i+1,'text':text,'start_seconds':start,'end_seconds':start+duration,'original_audio':str(p.relative_to(O)),'tts_wall_seconds':m['wall_seconds']})
 print(json.dumps({'audio_segment':i+1,'seconds':duration,'timeline_seconds':used},ensure_ascii=False),flush=True)
 if used>=54:break
wave=np.concatenate([np.zeros(2400,np.float32),*waves]);wave=np.pad(wave,(0,960000-len(wave)))
target=O/'audio/common-60s.wav';sf.write(str(target),wave,16000,subtype='PCM_16')
report={'ok':True,'voice':'O07','sample_rate':16000,'samples':len(wave),'seconds':60,'speech_timeline_end_seconds':used-.22,'tail_silence_seconds':60-(used-.22),'tts_total_wall_seconds':tts_seconds,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'segments':segments,'rate_changed':False,'speech_truncated':False,'generated_for_offline_benchmark_only':True}
(O/'audio/input.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
for rel in ['avatars/audio_features/base_asr.py','avatars/audio_features/whisper.py','avatars/musetalk/utils/native_landmarks.py']:
 p=R/'src/LiveTalking'/rel
 if p.exists():(O/(p.name+'.source.txt')).write_bytes(p.read_bytes())
c=json.loads((R/'configs/livetalking.yaml').read_text(encoding='utf-8-sig'))
(O/'avatar-feature-settings.json').write_text(json.dumps({k:c.get(k) for k in ['l','r','fps','batch_size','avatar_id','model','asr_model','bbox_shift']}),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False),flush=True)
