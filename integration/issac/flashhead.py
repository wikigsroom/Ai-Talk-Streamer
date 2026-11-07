"""Native FlashHead Lite 512/25, using the retained local source and weights."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import time

from .common import AdmissionError, file_hash, inside, read_json


class Engine:
    def __init__(self, root, mode='M03'):
        import numpy as np
        import torch
        self.root=Path(root).resolve()
        source=inside(root,'src/flashhead')
        sys.path.insert(0,str(source))
        import flash_head.src.pipeline.flash_head_pipeline as module
        module.COMPILE_MODEL=False
        module.COMPILE_VAE=False
        from flash_head.inference import get_pipeline, get_audio_embedding, run_pipeline
        self.embedding,self.run_pipeline=get_audio_embedding,run_pipeline
        self.torch,self.np=torch,np
        torch.set_num_threads(6)
        torch.backends.cuda.matmul.allow_tf32=True
        torch.backends.cudnn.allow_tf32=True
        self.pipeline=get_pipeline(1,str(inside(root,'models/flashhead/SoulX-FlashHead-1_3B')),
                    'lite',str(inside(root,'models/flashhead/wav2vec2-base-960h')))
        self.frames=33
        self.overlap=(2-1)*self.pipeline.config.vae_stride[0]+1
        self.new_frames=self.frames-self.overlap
        if self.new_frames!=24:
            raise AdmissionError('PINNED_FLASHHEAD_FRAME_STRIDE_CHANGED')
        self.samples=self.new_frames*640
        self.audio_history=np.zeros(8*16000,dtype=np.float32)
        config=read_json(inside(root,'configs/issac/runtime.json'))['media']
        if config.get('fast_rope',True):
            from flash_head.src.modules import flash_head_model
            from .rotary import rope_apply
            self.pipeline.model.freqs=torch.view_as_real(self.pipeline.model.freqs).float().contiguous().to(self.pipeline.device)
            flash_head_model.rope_apply=rope_apply
        self.configure(mode)
        compile_mode=config.get('compile_mode','model-vae')
        if compile_mode=='model-vae':
            import triton.knobs
            triton.knobs.getenv=os.getenv
            self.pipeline.model=torch.compile(self.pipeline.model,mode='default',dynamic=False)
            self.pipeline.vae.model.encode=torch.compile(self.pipeline.vae.model.encode,mode='default',dynamic=False)
            self.pipeline.vae.model.decode=torch.compile(self.pipeline.vae.model.decode,mode='default',dynamic=False)
        elif compile_mode!='none':
            raise AdmissionError('PINNED_NATIVE_COMPILE_MODE_REQUIRED')

    def configure(self, mode):
        config=read_json(inside(self.root,'state/issac-materials/runtime-bank.json'))
        row=config['modes'].get(mode)
        if not row:
            raise AdmissionError('PREPARED_MODE_REQUIRED')
        ref=inside(self.root,row['engine_reference'])
        if file_hash(ref)!=row['engine_reference_sha256']:
            raise AdmissionError('SAME_MODE_ENGINE_REFERENCE_CHANGED')
        with self.torch.inference_mode():
            self.pipeline.prepare_params(str(ref),(512,512),self.frames,self.overlap,4,42,5.,1.,False)
        self.mode=mode
        self.reset()

    def reset(self):
        self.audio_history.fill(0)
        with self.torch.inference_mode():
            self.pipeline.reset_person_name(self.pipeline.person_name)

    def render(self, pcm):
        if len(pcm)!=self.samples:
            raise AdmissionError('EXACT_PCM_CHUNK_REQUIRED')
        started=time.perf_counter()
        self.audio_history[:-self.samples]=self.audio_history[self.samples:]
        self.audio_history[-self.samples:]=pcm.astype(self.np.float32)/32768
        with self.torch.inference_mode():
            embedding=self.embedding(self.pipeline,self.audio_history,200-self.frames,200)
            audio_at=time.perf_counter()
            frames=self.run_pipeline(self.pipeline,embedding)[self.overlap:].to(self.torch.uint8).cpu().numpy()
        if len(frames)!=self.new_frames or frames.shape[1:3]!=(512,512):
            raise AdmissionError('ACTUAL_FLASHHEAD_FRAME_SHAPE_CHANGED')
        return frames,{'seconds':time.perf_counter()-started,'audio_embedding_seconds':audio_at-started,
                      'actual_new_frames':len(frames),'mode':self.mode,'steps':4,'batch':1}
