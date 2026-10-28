"""Five synchronized real outputs: 60s overview, 6s mouth GIF and still sheet."""
import json,subprocess,shutil,wave
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
P=Path(__file__).resolve().parent;O=P.parent.parent/'outputs/lipsync-k01-k05-60s-20261028';labels=['K01','K02','K03','K04','K05'];names=['MuseTalk 1.5','Local blend','FeatherTalk pilot','Wav2Lip GAN','LatentSync 1.6'];ffmpeg=shutil.which('ffmpeg')
if not ffmpeg:
    candidates=list((P.parent.parent/'tools/ffmpeg').rglob('ffmpeg.exe'))
    if not candidates:raise RuntimeError('Existing native FFmpeg was not found')
    ffmpeg=str(candidates[0])
for k in labels:
    if not json.loads((O/k/'result.json').read_text(encoding='utf-8')).get('ok'):raise RuntimeError('All five actual clips are required')
cmd=[ffmpeg,'-hide_banner','-loglevel','error','-y']
for k in labels:cmd+=['-threads','2','-i',str(O/k/f'{k}-60s.mp4')]
cmd+=['-i',str(O/'audio/common-60s.wav')];filters=[]
for i,(k,name) in enumerate(zip(labels,names)):
    filters.append(f"[{i}:v]split=2[p{i}][m{i}];[p{i}]scale=288:512,pad=288:548:0:36:color=0x172f49,drawtext=fontfile='C\\:/Windows/Fonts/arial.ttf':text='{k} {name}':fontcolor=white:fontsize=17:x=10:y=8[a{i}];[m{i}]crop=240:150:260:465,scale=288:180[b{i}];[a{i}][b{i}]vstack=inputs=2[v{i}]")
filters.append(''.join(f'[v{i}]' for i in range(5))+'hstack=inputs=5[v]')
cmd+=['-filter_complex_threads','2','-filter_complex',';'.join(filters),'-map','[v]','-map','5:a:0','-c:v','libx264','-preset','fast','-crf','18','-threads','4','-c:a','aac','-b:a','192k','-movflags','+faststart',str(O/'K01-K05-comparison-60s.mp4')]
subprocess.run(cmd,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
for begin,duration,filename in [('8','6','mouth-comparison-08s-14s.gif'),('57.35','2.65','mouth-comparison-silent-tail.gif')]:
    cmd=[ffmpeg,'-hide_banner','-loglevel','error','-y']
    for k in labels:cmd+=['-threads','2','-ss',begin,'-t',duration,'-i',str(O/k/f'{k}-60s.mp4')]
    filters=[]
    for i,k in enumerate(labels):filters.append(f"[{i}:v]fps=10,crop=240:150:260:465,pad=240:182:0:32:color=0x172f49,drawtext=fontfile='C\\:/Windows/Fonts/arial.ttf':text='{k}':fontcolor=white:fontsize=22:x=10:y=4[v{i}]")
    filters.append(''.join(f'[v{i}]' for i in range(5))+'hstack=inputs=5,split[s0][s1];[s0]palettegen=max_colors=192[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3[v]')
    cmd+=['-filter_complex_threads','2','-filter_complex',';'.join(filters),'-map','[v]','-loop','0',str(O/filename)]
    subprocess.run(cmd,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',22);sheet=Image.new('RGB',(300*5,370*6),'#edf2f7');draw=ImageDraw.Draw(sheet)
for y,frame in enumerate([50,275,550,850,1150,1400]):
    for x,k in enumerate(labels):
        image=Image.open(O/k/'stills'/f'{frame:04d}.jpg').convert('RGB').crop((220,280,520,610));sheet.paste(image,(x*300,y*370+32));draw.text((x*300+8,y*370+3),f'{k}  {frame/25:.2f}s',fill='#172f49',font=font)
sheet.save(O/'same-frame-face-sheet.jpg',quality=94)
probe=str(Path(ffmpeg).with_name('ffprobe.exe'))
meta=json.loads(subprocess.check_output([probe,'-v','error','-threads','2','-count_frames','-show_streams','-show_format','-of','json',str(O/'K01-K05-comparison-60s.mp4')],creationflags=subprocess.CREATE_NO_WINDOW))
video=next(s for s in meta['streams'] if s['codec_type']=='video')
if int(video['nb_read_frames'])!=1500 or video['width']!=1440 or video['height']!=728 or abs(float(video['duration'])-60)>.045:raise RuntimeError('Five-way overview must also be a complete60-second,1500-frame video')
records=[]
for filename,begin,end in [('mouth-comparison-08s-14s.gif',8,14),('mouth-comparison-silent-tail.gif',57.35,60)]:
    with Image.open(O/filename) as gif:
        duration=0
        for n in range(gif.n_frames):gif.seek(n);duration+=gif.info.get('duration',0)/1000
        records.append({'path':filename,'source_interval_seconds':[begin,end],'width':gif.width,'height':gif.height,'frames':gif.n_frames,'actual_gif_seconds':duration,'duration_quantized_to_10fps':True})
with wave.open(str(O/'audio/common-60s.wav')) as audio:
    audio.setpos(round(57.35*audio.getframerate()));tail=audio.readframes(audio.getnframes()-audio.tell())
if any(tail):raise RuntimeError('The shared PCM silent-tail fixture must contain only zero samples')
manifest={'overview':{'path':'K01-K05-comparison-60s.mp4','decoded_frames':int(video['nb_read_frames']),'video_seconds':float(video['duration']),'width':video['width'],'height':video['height'],'common_audio':'audio/common-60s.wav'},'gif_previews':records,'silent_tail_pcm_bytes':len(tail),'silent_tail_is_all_zero':True,'note':'These are derived review assets. GIF durations are measured after encoding and may differ slightly from the source interval because of10fps quantization.'}
(O/'review-assets.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(manifest,ensure_ascii=False),flush=True)
