"""Encode a separately regenerated take, preserving the rejected first attempt."""
from pathlib import Path
import json,subprocess,sys
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/vertical/materials'
ffmpeg=next((ROOT/'tools/ffmpeg').rglob('ffmpeg.exe'));ffprobe=ffmpeg.with_name('ffprobe.exe')
def encode_and_review(item):
 name=item['id'];folder=OUT/(name+'_frames');frames=sorted(folder.glob('frame*.png'))
 if len(frames)!=192:raise RuntimeError(f'{name}: expected 192 generated frames, received {len(frames)}')
 target=OUT/(name+'.mp4')
 command=[str(ffmpeg),'-v','error','-y','-framerate','24','-i',str(folder/'frame%06d.png'),'-vf','scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,fps=25','-an','-c:v','libx264','-threads','6','-preset','fast','-crf','16','-pix_fmt','yuv420p','-movflags','+faststart',str(target)]
 subprocess.run(command,check=True,timeout=180)
 metadata=json.loads(subprocess.check_output([str(ffprobe),'-v','error','-show_entries','stream=width,height,nb_frames,r_frame_rate:format=duration','-of','json',str(target)],text=True))
 video=metadata['streams'][0]
 if (video['width'],video['height'])!=(720,1280) or int(video['nb_frames'])!=200:raise RuntimeError('Portrait encode verification failed')
 sample=[0,24,48,72,96,120,144,188]
 sheet=Image.new('RGB',(960,904),'#edf0f3');draw=ImageDraw.Draw(sheet)
 font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',16)
 for i,index in enumerate(sample):
  with Image.open(frames[index]) as im:
   image=im.convert('RGB');image.thumbnail((240,427),Image.Resampling.LANCZOS)
   x=(i%4)*240;y=(i//4)*452
   sheet.paste(image,(x,y+25));draw.text((x+5,y+4),f'{name[:3]} / {index/24:.2f}s',font=font,fill='#1b2838')
 review=OUT/'review'/(name+'.jpg');sheet.save(review,quality=94)
 return {'status':'generated_awaiting_review','video':str(target.relative_to(ROOT)).replace('\\','/'),'review':str(review.relative_to(ROOT)).replace('\\','/'),'media':metadata,'bytes':target.stat().st_size,'title':item['title'],'category':item['category']}

items=json.loads((ROOT/'configs/vertical/materials/retry-catalog.json').read_text(encoding='utf-8'))
name=sys.argv[1]
if name not in items:raise RuntimeError('Unknown retry take')
result=encode_and_review(items[name])
(ROOT/'configs/vertical/materials'/(name+'.encoded.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
