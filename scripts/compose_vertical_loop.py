from pathlib import Path
import json,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
for name in ('idle_a','idle_b'):
    if not (ROOT/'outputs/vertical/source'/(name+'.mp4')).is_file():raise RuntimeError('Bundled baseline source is missing: '+name)
ffmpeg=next((ROOT/'tools/ffmpeg').rglob('ffmpeg.exe'));ffprobe=ffmpeg.with_name('ffprobe.exe')
target=ROOT/'assets/vertical/idle-loop-720x1280.mp4'
filters='[0:v]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,fps=25,setpts=PTS-STARTPTS[a];[1:v]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,fps=25,setpts=PTS-STARTPTS[b];[a][b]concat=n=2:v=1:a=0[v]'
subprocess.run([str(ffmpeg),'-v','error','-y','-i',str(ROOT/'outputs/vertical/source/idle_a.mp4'),'-i',str(ROOT/'outputs/vertical/source/idle_b.mp4'),'-filter_complex',filters,'-map','[v]','-an','-c:v','libx264','-threads','8','-preset','fast','-crf','16','-pix_fmt','yuv420p','-movflags','+faststart',str(target)],check=True)
metadata=json.loads(subprocess.check_output([str(ffprobe),'-v','error','-show_entries','stream=codec_name,width,height,r_frame_rate,nb_frames:format=duration','-of','json',str(target)],text=True))
shutil.copy2(target,ROOT/'outputs/vertical/vertical-idle.mp4')
(ROOT/'outputs/vertical/idle-loop.media.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
print(json.dumps({'ok':True,'source_video':str(target),'metadata':metadata}),flush=True)
