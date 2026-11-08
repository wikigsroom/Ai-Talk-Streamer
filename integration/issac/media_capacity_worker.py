"""Private native probe actors; never write a body bank or quality approval."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import subprocess
import time
import traceback

from .common import AdmissionError,file_hash,inside,read_json,write_json


def actor(root,folder,role):
    import psutil
    import torch
    torch.cuda.init();torch.cuda.reset_peak_memory_stats()
    process=psutil.Process(os.getpid())
    row={'role':role,'pid':process.pid,'created_at':process.create_time(),'executable':process.exe(),
         'scope':'capacity_only','quality_accepted':False,'started_unix':time.time()}
    def peaks():
        memory=process.memory_info()
        return {'cuda_peak_reserved_bytes':torch.cuda.max_memory_reserved(),
            'cuda_resident_reserved_bytes':torch.cuda.memory_reserved(),
            'host_peak_bytes':max(memory.rss,getattr(memory,'peak_wset',0))}
    if role=='voice':
        from integration.naimei_voice_worker import VoiceWorker
        worker=VoiceWorker(root,root,'OmniVoice');worker.initialize()
        if not worker.ready:raise AdmissionError('FROZEN_NCM01_INITIALIZATION_FAILED_'+str(worker.error))
        text='嗨，我是奶妹。今天继续玩以撒的结合。先看看房间里的敌人，别急着冲过去。手柄拿稳，等它攻击完再移动。咦，这个道具看起来挺有意思，我们查清楚再决定要不要拿。'
        audio,metrics=worker.synthesize(text,'issac-capacity-ncm01','NCM01')
        target=folder/'generated-ncm01.wav';target.write_bytes(audio)
        row.update(voice_id=metrics['voice_id'],precision=metrics['precision'],steps=metrics['steps'],
            reference_preprocess_prompt=metrics['reference_preprocess_prompt'],
            voice_freeze_id=metrics['voice_freeze_id'],generated_audio_sha256=file_hash(target),
            generated_audio_seconds=metrics['audio_seconds'],generation_seconds=metrics['wall_seconds'])
    else:
        import numpy as np
        from .flashhead import Engine
        from .materials import MATERIAL_ROOT,OPEN_ANCHOR,OPEN_SHA,ffmpeg
        class ConditioningProbe(Engine):
            def configure(self,mode):
                ref=inside(self.root,MATERIAL_ROOT+'/'+OPEN_ANCHOR)
                if file_hash(ref)!=OPEN_SHA:raise AdmissionError('PINNED_ORAL_CONDITIONING_ANCHOR_REQUIRED')
                with self.torch.inference_mode():
                    self.pipeline.prepare_params(str(ref),(512,512),self.frames,self.overlap,4,42,5.,1.,False)
                self.mode='capacity-only';self.reset()
        # The only override selects the already locked oral anchor for a
        # capacity experiment. Production Engine still requires an approved bank.
        engine=ConditioningProbe(root)
        for _ in range(4):engine.render(np.zeros(engine.samples,dtype=np.int16))
        raw=subprocess.run([ffmpeg(root),'-v','error','-i',str(folder/'generated-ncm01.wav'),
            '-f','s16le','-ac','1','-ar','16000','pipe:1'],capture_output=True,timeout=60,check=True,creationflags=0x08000000).stdout
        pcm=np.frombuffer(raw,dtype=np.int16)
        if len(pcm)<engine.samples*12:raise AdmissionError('AT_LEAST_11_SECONDS_REAL_NCM01_REQUIRED')
        video=folder/'actual-mouth-capacity-only.mp4';log=(folder/'encoder.log').open('wb')
        command=[ffmpeg(root),'-v','error','-f','rawvideo','-pix_fmt','rgb24','-s','512x512','-r','25','-i','pipe:0',
            '-an','-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',str(video)]
        encoder=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=log,creationflags=0x08000000)
        timings=[];count=0
        try:
            for index in range(12):
                frames,metrics=engine.render(pcm[index*engine.samples:(index+1)*engine.samples])
                encoder.stdin.write(frames.tobytes());count+=len(frames);timings.append(metrics)
            encoder.stdin.close()
            if encoder.wait(timeout=60)!=0:raise AdmissionError('ACTUAL_MEDIA_CAPACITY_VIDEO_ENCODING_FAILED')
        finally:
            if encoder.poll() is None:
                encoder.terminate();encoder.wait(timeout=10)
            log.close()
        media=read_json(inside(root,'configs/issac/runtime.json'))['media']
        row.update(actual_new_frames=count,width=512,height=512,steps=4,batch=1,
            compile_mode=media['compile_mode'],fast_rope=media['fast_rope'],timings=timings,
            conditioning_anchor_sha256=OPEN_SHA,actual_video_sha256=file_hash(video),
            speech_audio_sha256=file_hash(folder/'generated-ncm01.wav'))
    row.update(peaks(),passed=True,stage='measured',measured_unix=time.time())
    write_json(folder/(role+'.json'),row)
    # Hold both actual CUDA models until the supervisor observes concurrency.
    deadline=time.monotonic()+2400
    while not (folder/'stop').exists():
        if time.monotonic()>deadline:raise AdmissionError('MEDIA_ACTOR_HOLD_DEADLINE')
        time.sleep(.5)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--folder',type=Path,required=True);parser.add_argument('--role',choices=['voice','mouth'],required=True)
    args=parser.parse_args();root=args.root.resolve();folder=args.folder.resolve()
    if not folder.is_relative_to(inside(root,'state/issac-acceptance/media-capacity')):
        raise AdmissionError('PRIVATE_CURRENT_MEDIA_PROBE_DIRECTORY_REQUIRED')
    try:actor(root,folder,args.role)
    except Exception as error:
        traceback.print_exc();write_json(folder/(args.role+'.json'),{'role':args.role,'passed':False,'error':str(error),
            'scope':'capacity_only','quality_accepted':False,'failed_unix':time.time()});raise
