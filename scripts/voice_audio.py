"""Native FFmpeg mastering and measurable audio checks for voice auditions."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import numpy as np


def run(arguments):
    result=subprocess.run(arguments,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
    return result.stdout,result.stderr.decode('utf-8',errors='replace')


def ffmpeg():
    found=shutil.which('ffmpeg')
    if not found:raise RuntimeError('Native FFmpeg must be on PATH')
    return found


def loudness(path):
    _,log=run([ffmpeg(),'-hide_banner','-nostdin','-i',str(path),'-af','loudnorm=I=-20:TP=-2:LRA=11:print_format=json','-f','null','-'])
    matches=list(re.finditer(r'\{\s*"input_i"[\s\S]*?\}',log))
    if not matches:raise RuntimeError('FFmpeg did not return loudness measurements')
    return json.loads(matches[-1].group(0))


def pcm(path,rate=24000):
    data,log=run([ffmpeg(),'-nostdin','-v','error','-i',str(path),'-ac','1','-ar',str(rate),'-f','f32le','pipe:1'])
    if log.strip():raise RuntimeError('Audio decode error: '+log)
    return np.frombuffer(data,dtype=np.float32).copy()


def pitch(data,rate=24000):
    """Rough autocorrelation estimate; not a perceptual or identity score."""
    values=[];frame=int(rate*.04);hop=int(rate*.02)
    window=np.hanning(frame)
    lower=int(rate/420);upper=int(rate/85)
    for offset in range(0,len(data)-frame,hop):
        section=data[offset:offset+frame].astype(np.float64)
        if np.sqrt(np.mean(section**2))<.012:continue
        section=(section-section.mean())*window
        spectrum=np.fft.rfft(section,n=2048)
        correlation=np.fft.irfft(spectrum*spectrum.conjugate(),n=2048)[:frame]
        if correlation[0]<=1e-9:continue
        lag=lower+int(np.argmax(correlation[lower:upper]))
        if correlation[lag]/correlation[0]>=.42:values.append(rate/lag)
    return round(float(np.median(values)),1) if values else None


def master(source,target):
    source,target=Path(source),Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    measured=loudness(source)
    settings={'measured_I':measured['input_i'],'measured_TP':measured['input_tp'],'measured_LRA':measured['input_lra'],'measured_thresh':measured['input_thresh'],'offset':measured['target_offset']}
    filt='loudnorm=I=-20:TP=-2:LRA=11:linear=true:'+':'.join(key+'='+value for key,value in settings.items())
    run([ffmpeg(),'-nostdin','-v','error','-y','-i',str(source),'-af',filt,'-ar','24000','-ac','1','-c:a','pcm_s16le',str(target)])
    data=pcm(target);original=pcm(source)
    if not len(data) or not np.isfinite(data).all():raise RuntimeError('Empty or non-finite audio')
    duration=len(data)/24000
    if abs(duration-len(original)/24000)>.02:raise RuntimeError('Mastering changed the natural duration')
    peak=float(np.max(np.abs(data)));rms=float(np.sqrt(np.mean(data**2)))
    clipped=int(np.count_nonzero(np.abs(data)>=.999))
    bars=np.array([np.sqrt(np.mean(part**2)) for part in np.array_split(data,40)])
    bars=np.sqrt(bars/max(float(bars.max()),1e-8))
    levels=loudness(target)
    return {'seconds':round(duration,3),'sample_rate':24000,'channels':1,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
            'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'bytes':target.stat().st_size,'peak':round(peak,6),'rms':round(rms,6),
            'clipped_samples':clipped,'integrated_lufs':float(levels['input_i']),'true_peak_dbtp':float(levels['input_tp']),
            'median_f0_hz_approx':pitch(data),'waveform':[round(float(value),3) for value in bars],
            'full_decode_passed':True,'natural_duration_preserved':True,'pitch_or_formant_shift':False,
            'ok':clipped==0 and rms>.005 and peak<.95 and float(levels['input_tp'])<=-1.8}
