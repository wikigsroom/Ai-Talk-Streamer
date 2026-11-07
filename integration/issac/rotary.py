"""Single-GPU real FP32 rotary math, preserving the validated Lite operation."""
import torch


def rope_apply(x,freqs,grid_sizes,use_usp=False,sp_size=1,sp_rank=0):
    if use_usp or sp_size!=1:
        raise ValueError('SINGLE_NATIVE_GPU_REQUIRED')
    f,h,w=grid_sizes
    n=x.size(2)
    c=x.size(3)//2
    length=f*h*w
    parts=freqs.split([c-2*(c//3),c//3,c//3],dim=1)
    rotation=torch.cat([
        parts[0][:f].view(f,1,1,-1,2).expand(f,h,w,-1,-1),
        parts[1][:h].view(1,h,1,-1,2).expand(f,h,w,-1,-1),
        parts[2][:w].view(1,1,w,-1,2).expand(f,h,w,-1,-1),
    ],dim=-2).reshape(length,1,c,2)
    pairs=x[0,:length].float().reshape(length,n,c,2)
    real=pairs[...,0]*rotation[...,0]-pairs[...,1]*rotation[...,1]
    imag=pairs[...,0]*rotation[...,1]+pairs[...,1]*rotation[...,0]
    rotated=torch.stack([real,imag],dim=-1).flatten(2)
    return torch.cat([rotated,x[0,length:].float()],dim=0).unsqueeze(0).to(x.dtype)
