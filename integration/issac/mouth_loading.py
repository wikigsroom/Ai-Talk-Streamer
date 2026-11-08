"""Avoid a temporary FP32 copy while loading the existing BF16 mouth model."""
from contextlib import contextmanager
from pathlib import Path

from .common import AdmissionError


@contextmanager
def native_bf16_loaders(root, torch, diffusion_class, vae_class):
    """Only the dedicated mouth child uses these scoped upstream entry points.

    The diffusion loader supports meta initialization through the installed
    Diffusers/Accelerate pair. The retained custom VAE supports torch_dtype,
    but does not implement Diffusers' low_cpu_mem_usage option.
    """
    base=(Path(root).resolve()/'models/flashhead/SoulX-FlashHead-1_3B')
    originals=[]
    try:
        for cls,subdirectory,low_cpu in ((diffusion_class,'Model_Lite',True),
                                        (vae_class,'VAE_LTX',False)):
            own=cls.__dict__.get('from_pretrained')
            original=cls.from_pretrained
            expected=(base/subdirectory).resolve()
            def load(bound_cls,path,*args,_original=original,_expected=expected,
                     _low_cpu=low_cpu,**kwargs):
                if Path(path).resolve()!=_expected:
                    raise AdmissionError('PINNED_LOCAL_MOUTH_WEIGHT_DIRECTORY_REQUIRED')
                if kwargs.get('torch_dtype',torch.bfloat16)!=torch.bfloat16:
                    raise AdmissionError('ORIGINAL_MOUTH_BF16_PRECISION_REQUIRED')
                kwargs['torch_dtype']=torch.bfloat16
                if _low_cpu:
                    kwargs.update(low_cpu_mem_usage=True,local_files_only=True)
                return _original(path,*args,**kwargs)
            originals.append((cls,own))
            cls.from_pretrained=classmethod(load)
        yield
    finally:
        for cls,own in reversed(originals):
            if own is None:delattr(cls,'from_pretrained')
            else:setattr(cls,'from_pretrained',own)


def verify_loaded_precision(pipeline,torch):
    for name,model in (('diffusion',pipeline.model),('vae',pipeline.vae.model)):
        parameters=list(model.parameters())
        if not parameters or any(p.is_meta or (p.is_floating_point() and p.dtype!=torch.bfloat16)
                                 for p in parameters):
            raise AdmissionError('ACTUAL_MOUTH_BF16_WEIGHT_LOADING_NOT_CONFIRMED_'+name)
    return {'policy':'native-low-cpu-v1','diffusion_low_cpu_mem_usage':True,
            'diffusion_dtype':'torch.bfloat16','vae_dtype':'torch.bfloat16',
            'audio_encoder_precision_changed':False,'new_weight_bytes':0}
