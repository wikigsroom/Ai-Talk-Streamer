from pathlib import Path
import json, shutil, subprocess, sys
ROOT=Path(__file__).resolve().parents[1]
ffmpeg=next((ROOT/'tools/ffmpeg').rglob('ffmpeg.exe'))
ffprobe=ffmpeg.with_name('ffprobe.exe')
for name in sys.argv[1:] or ['idle_a','idle_b']:
    folder=ROOT/'outputs/vertical/source'/(name+'_frames')
    frames=list(folder.glob('frame*.png'))
    if len(frames)!=192:raise RuntimeError('Expected 192 actual generated frames: '+name)
    target=folder.parent/(name+'.mp4')
    subprocess.run([str(ffmpeg),'-v','error','-y','-framerate','24','-i',str(folder/'frame%06d.png'),'-c:v','libx264','-threads','8','-preset','fast','-crf','16','-pix_fmt','yuv420p','-movflags','+faststart',str(target)],check=True)
    metadata=json.loads(subprocess.check_output([str(ffprobe),'-v','error','-show_entries','stream=codec_name,width,height,r_frame_rate,nb_frames:format=duration','-of','json',str(target)],text=True))
    (folder.parent/(name+'.media.json')).write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    print(name,json.dumps(metadata),flush=True)
