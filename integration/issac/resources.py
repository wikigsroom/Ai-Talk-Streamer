"""Measured native capacity; existing jobs are observed and never interrupted."""
from __future__ import annotations

import json
import math
import re
import subprocess
import threading
import time
import urllib.request

from .common import AdmissionError

MIB=1024**2
MEDIA_RESERVE_MIB=18000
GPU_MARGIN_MIB=2048
HOST_MARGIN_MIB=6144


def snapshot():
    import psutil
    raw=subprocess.check_output(['nvidia-smi','--query-gpu=memory.total,memory.free,utilization.gpu',
        '--format=csv,noheader,nounits'],text=True,timeout=10,creationflags=0x08000000)
    lines=[x for x in raw.splitlines() if x.strip()]
    if len(lines)!=1:raise AdmissionError('ONE_NATIVE_GPU_REQUIRED')
    total,free,utilization=[int(x.strip()) for x in lines[0].split(',')]
    memory=psutil.virtual_memory()
    running=None
    try:
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open('http://127.0.0.1:8188/queue',timeout=2) as response:
            running=len(json.load(response).get('queue_running',[]))
    except (OSError,ValueError):pass
    return {'gpu_total_mib':total,'gpu_free_mib':free,'gpu_utilization_percent':utilization,
            'host_total_bytes':memory.total,'host_available_bytes':memory.available,
            'comfy_running_jobs':running,'at_unix':time.time()}


def available_for_initialization(row,minimum_free_mib):
    return (row['gpu_free_mib']>=minimum_free_mib and row['gpu_utilization_percent']<35
            and not row.get('comfy_running_jobs') and row['host_available_bytes']>=HOST_MARGIN_MIB*MIB)


def wait_for_capacity(stop,minimum_free_mib,progress=None):
    if stop is None:stop=threading.Event()
    last=0
    while not stop.is_set():
        row=snapshot()
        if available_for_initialization(row,minimum_free_mib):return row
        if progress and time.monotonic()-last>=10:
            progress(row);last=time.monotonic()
        stop.wait(2)
    raise AdmissionError('RESOURCE_WAIT_CANCELLED')


def parse_estimate(output):
    """Read lms's explicit estimates; unknown output is never guessed from size."""
    text=re.sub(r'\x1b\[[0-9;]*m','',output)
    values={}
    for field,label in [('gpu_bytes','GPU'),('total_bytes','Total')]:
        match=re.search(r'Estimated\s+'+label+r'\s+Memory\s*:\s*([\d.]+)\s*(B|[KMGT]i?B)\b',text,re.I)
        if not match:raise AdmissionError('ACTUAL_LMS_MEMORY_ESTIMATE_REQUIRED')
        unit=match[2].upper().replace('I','')
        exponent={'B':0,'KB':1,'MB':2,'GB':3,'TB':4}[unit]
        values[field]=math.ceil(float(match[1])*(1024**exponent))
    if re.search(r'confidence\s*:\s*low',text,re.I) or 'will fail to load' in text.lower():
        raise AdmissionError('LOCAL_MODEL_RESOURCE_ESTIMATE_REJECTED')
    if not 0<=values['gpu_bytes']<=values['total_bytes']:
        raise AdmissionError('LOCAL_MODEL_RESOURCE_ESTIMATE_INVALID')
    return values


def assess_estimate(estimate,observed,*,reserve_mib=MEDIA_RESERVE_MIB,host_extra_reserve_mib=0):
    # Add a rounding allowance to the CLI's formatted estimate and keep room
    # for the two media models plus Windows and normal recording overhead.
    if type(reserve_mib) is not int or reserve_mib<=0 or type(host_extra_reserve_mib) is not int or host_extra_reserve_mib<0:
        raise AdmissionError('POSITIVE_MEASURED_MEDIA_RESERVE_REQUIRED')
    gpu_required=estimate['gpu_bytes']+(512+reserve_mib+GPU_MARGIN_MIB)*MIB
    host_required=estimate['total_bytes']-estimate['gpu_bytes']+(512+HOST_MARGIN_MIB+host_extra_reserve_mib)*MIB
    gpu_available=observed['gpu_free_mib']*MIB
    host_available=observed['host_available_bytes']
    return {'fits':gpu_required<=gpu_available and host_required<=host_available,
            'gpu_required_bytes':gpu_required,'gpu_available_bytes':gpu_available,
            'host_required_bytes':host_required,'host_available_bytes':host_available,
            'gpu_shortfall_bytes':max(0,gpu_required-gpu_available),
            'host_shortfall_bytes':max(0,host_required-host_available),
            'media_reserve_mib':reserve_mib,'gpu_margin_mib':GPU_MARGIN_MIB,
            'host_margin_mib':HOST_MARGIN_MIB,'host_extra_reserve_mib':host_extra_reserve_mib,'estimate_rounding_mib':512}


def estimate_fits(estimate,observed,*,reserve_mib=MEDIA_RESERVE_MIB,host_extra_reserve_mib=0):
    return assess_estimate(estimate,observed,reserve_mib=reserve_mib,host_extra_reserve_mib=host_extra_reserve_mib)['fits']


def offload_candidates(fraction,maximum=.6):
    if maximum not in (.6,1) or type(fraction) not in (int,float) or not 0<fraction<=maximum:
        raise AdmissionError('BOUNDED_EXISTING_MODEL_OFFLOAD_REQUIRED')
    # Real LMS estimates round fractions to whole layers: .375 and .36 used
    # the same memory, missing GPU capacity by 47 MiB. Probe the intervening
    # layer boundaries before dropping to .338; every point still requires a
    # real CLI estimate and both original capacity checks.
    scales=(1,.9,5/6,.8,71/90,7/9,23/30,34/45,.75,.5)
    return sorted({round(fraction*scale,3) for scale in scales},reverse=True)
