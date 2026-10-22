"""Acquire upstream demonstration inputs; no model inference or streaming."""
from pathlib import Path
import concurrent.futures,json,sys,wave
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'deployment'))
from download_models import download,get

def github_file(repo,path,target,role):
    with get('https://api.github.com/repos/'+repo+'/commits/main') as response:revision=json.load(response)['sha']
    return {'repo':repo,'revision':revision,'remote_file':path,'role':role,'url':'https://raw.githubusercontent.com/'+repo+'/'+revision+'/'+path,'local_path':target}

def main():
    records=[
        github_file('TMElyralab/MuseTalk','data/video/yongen.mp4','assets/demo/yongen.mp4','upstream demo video; test only'),
        github_file('FunAudioLLM/CosyVoice','asset/zero_shot_prompt.wav','assets/demo/reference_zh.wav','upstream demonstration reference voice; test only'),
        github_file('FunAudioLLM/CosyVoice','example.py','assets/demo/CosyVoice_example.py.txt','reference voice transcript provenance'),
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(download,records))
    if not all(r['ok'] for r in results):raise RuntimeError('Demonstration input download failed')
    # Reject a Git LFS pointer or an HTML error saved under a media extension.
    video=ROOT/'assets/demo/yongen.mp4'
    if video.stat().st_size<10000 or b'ftyp' not in video.read_bytes()[:64]:raise RuntimeError('Demo video is not an MP4 payload')
    with wave.open(str(ROOT/'assets/demo/reference_zh.wav'),'rb') as f:
        duration=f.getnframes()/f.getframerate()
        if not 3<=duration<=10:raise RuntimeError(f'Unexpected reference duration: {duration}')
    (ROOT/'assets/demo/reference_zh.txt').write_text('希望你以后能够做的比我还好呦。',encoding='utf-8')
    (ROOT/'.setup/extras.result.json').write_text(json.dumps({'ok':True,'files':results,'reference_seconds':duration},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'ok':True,'files':len(results),'reference_seconds':duration},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
