"""Independent O07 speech and disjoint motion for a clearly labelled teacher pilot."""
from bench_common import *
import urllib.request,soundfile as sf,math
from scipy.signal import resample_poly

def main():
 inp=manifest();count=len(inp['train_frame_ids']);duration=count/25;folder=O/'training';folder.mkdir(exist_ok=True)
 sentences=[
 '今天我们聊一聊，如何把平凡的日子过得有滋有味。',
 '清晨起床后，先喝一杯温水，再慢慢整理自己的书桌。',
 '书架上的小说和笔记本，都记录着一些特别的回忆。',
 '周末的时候，我喜欢听音乐，也喜欢做简单的甜点。',
 '如果遇到难题，可以把思路写下来，再逐个检查。',
 '比起急着得到答案，我更愿意理解问题背后的原因。',
 '朋友之间的相处，需要倾听，也需要温柔的表达。',
 '有时候只是一句问候，就能让人的心情轻松许多。',
 '窗帘旁边放着一盏台灯，暖暖的光落在书页上。',
 '我把橙子切成小块，装进玻璃碗里，准备和朋友分享。',
 '小猫趴在柔软的毯子上，听到脚步声就抬起了头。',
 '我们一起去公园散步，看树叶随着微风轻轻晃动。',
 '写作业的时候，记得隔一会儿就活动一下肩膀和手腕。',
 '长时间盯着屏幕容易疲劳，要给眼睛一点休息的时间。',
 '我试着学习一种新乐器，开始很慢，后来渐渐找到了节奏。',
 '读到喜欢的句子时，我会用铅笔轻轻画一条线。',
 '你有没有一个很想去的地方，愿意跟我说说吗？',
 '旅途中最难忘的，也许是路边的一碗热汤和一次善意的帮助。',
 '别忘了带上雨伞，天气变化的时候，多照顾自己一点。',
 '计划可以调整，偶尔停下来看看，也是一种向前走的方式。',
 '我刚学会一道新菜，调味还不够熟练，不过家里人很喜欢。',
 '咬一口脆脆的饼干，再喝一点热牛奶，感觉特别满足。',
 '笔记不一定要写得漂亮，能帮自己理解，就已经很好了。',
 '碰到意见不同的人，先问清楚彼此在意的是什么。',
 '这本相册里有好多照片，每一张都有它自己的故事。',
 '我喜欢安静的图书馆，也喜欢和朋友一起热热闹闹地讨论。',
 '把复杂的工作分成小任务，完成一项，就认真肯定一下自己。',
 '明天的事情，今天可以先准备一点点，不用给自己太大压力。',
 '花瓶里的花开得正好，淡淡的香气让房间变得很舒服。',
 '晚上睡觉前，我会把手机放远一些，听一段舒缓的音乐。',
 '这段练习用来学习自然的口型，它不会使用后面的评测台词。',
 '苹果香蕉和草莓各有不同的味道，你最喜欢哪一种水果？',
 '爸爸把白色杯子摆好，妈妈拿来了刚刚烤好的面包。',
 '轻轻呼吸，缓缓说话，让每一个词都表达得清楚一点。',
 '遇到开心的事情，我们就笑一笑，也把这份快乐分享出去。',
 '理解自己的感受很重要，累了的时候，可以坦然地休息。',
 '今天练习到这里，还有许多有趣的小事情，留着慢慢聊。',
 '每一次认真尝试，都会积累一点经验，也会带来新的发现。',
 '请把红色的书放在左边，把蓝色的笔记本放在右边。',
 '一二三四五，六七八九十。我们换一个速度，再清楚地读一次。']
 op=urllib.request.build_opener(urllib.request.ProxyHandler({}));parts=[];texts=[]
 for i,text in enumerate(sentences):
  p=folder/f'speech-{i+1:02d}.wav'
  if not p.exists():
   req=urllib.request.Request('http://127.0.0.1:9880/tts',json.dumps({'request_id':f'lipsync-training-{i+1:02d}','text':text,'voice_id':'O07','allow_fallback':False}).encode(),{'Content-Type':'application/json'})
   p.write_bytes(op.open(req,timeout=120).read())
  wave,sr=sf.read(str(p),dtype='float32',always_2d=True);wave=wave.mean(1)
  if sr!=16000:
   g=math.gcd(sr,16000);wave=resample_poly(wave,16000//g,sr//g).astype(np.float32)
  parts.append(np.concatenate([wave,np.zeros(3200,np.float32)]));texts.append(text)
  save('training/audio-progress.json',{'sentences_ready':i+1,'total':len(sentences)})
 wave=np.concatenate(parts);repeats=math.ceil((count*640)/len(wave));joined=np.tile(wave,repeats)[:count*640]
 sf.write(str(folder/'audio.wav'),joined,16000,subtype='PCM_16')
 save('training/provenance.json',{'teacher':'K01 MuseTalk1.5','synthetic_teacher_pilot':True,'not_official_final_quality':True,'seconds':duration,'frames':count,'frame_ids':inp['train_frame_ids'],'test_train_motion_disjoint':inp['test_train_motion_disjoint'],'test_text_excluded':True,'independent_texts':texts,'audio_loop_repetitions':repeats,'last_training_audio_cut_to_frame_boundary':True,'training_audio_sha256':hashlib.sha256((folder/'audio.wav').read_bytes()).hexdigest()})
if __name__=='__main__':main()
