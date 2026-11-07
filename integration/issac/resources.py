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


def estimate_fits(estimate,observed,*,reserve_mib=MEDIA_RESERVE_MIB):
    # Add a rounding allowance to the CLI's formatted estimate and keep room
    # for the two media models plus Windows and normal recording overhead.
    gpu_limit=max(0,observed['gpu_free_mib']-reserve_mib-GPU_MARGIN_MIB)*MIB
    host_limit=max(0,observed['host_available_bytes']-HOST_MARGIN_MIB*MIB)
    return (estimate['gpu_bytes']+512*MIB<=gpu_limit
            and estimate['total_bytes']-estimate['gpu_bytes']+512*MIB<=host_limit)
