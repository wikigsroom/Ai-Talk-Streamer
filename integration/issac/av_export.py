"""Preserve ordered real frames and paired audio with explicit timestamps."""
from __future__ import annotations

from array import array
import json
from pathlib import Path
import subprocess
import sys

from .common import AdmissionError, write_json
from .materials import ffmpeg


def run(command, *, timeout=300):
    return subprocess.run(command, capture_output=True, timeout=timeout, creationflags=0x08000000)


def inspect(root, path, frames, fps, *, size=None, sound_required=False):
    result=run([ffmpeg(root,'ffprobe.exe'),'-v','error','-count_frames','-show_streams','-show_format','-of','json',str(path)])
    if result.returncode:raise AdmissionError('EXPORTED_AV_PROBE_FAILED')
    metadata=json.loads(result.stdout)
    videos=[s for s in metadata['streams'] if s['codec_type']=='video']
    audio=[s for s in metadata['streams'] if s['codec_type']=='audio']
    if len(videos)!=1 or len(audio)!=1:raise AdmissionError('EXPORTED_VIDEO_AND_AUDIO_REQUIRED')
    video=videos[0];numerator,denominator=map(int,video['avg_frame_rate'].split('/'))
    duration=frames/fps
    if (int(video.get('nb_read_frames',0))!=frames or denominator==0 or abs(numerator/denominator-fps)>.001
            or size and (video['width'],video['height'])!=tuple(size)
            or abs(float(video.get('start_time',0)))>1/fps
            or abs(float(video.get('duration',0))-duration)>1/fps
            or abs(float(audio[0].get('duration',0))-duration)>.08):
        raise AdmissionError('EXPORTED_AV_FRAME_OR_TIMING_MISMATCH')
    decoded=run([ffmpeg(root),'-v','error','-i',str(path),'-map','0:v:0','-map','0:a:0','-f','null','-'],timeout=600)
    if decoded.returncode:raise AdmissionError('EXPORTED_AV_DECODE_FAILED')
    pcm=run([ffmpeg(root),'-v','error','-i',str(path),'-map','0:a:0','-ar','16000','-ac','1','-f','s16le','-'])
    if pcm.returncode or not pcm.stdout:raise AdmissionError('EXPORTED_AUDIO_DECODE_FAILED')
    samples=array('h');samples.frombytes(pcm.stdout)
    if sys.byteorder!='little':samples.byteswap()
    peak=max(abs(x) for x in samples);rms=(sum(x*x for x in samples)/len(samples))**.5
    if sound_required and (peak==0 or rms<1):raise AdmissionError('EXPORTED_SPEECH_AUDIO_IS_SILENT')
    return {'probe':metadata,'decoded_frames':frames,'decoded_audio_samples':len(samples),
            'audio_peak':peak,'audio_rms':rms,'decode_exit_code':0}


def mux_review(root, folder, packets, *, sound_required=False):
    folder=Path(folder);duration=packets/25
    if packets<=0 or (folder/'actual.s16le').stat().st_size!=packets*1280:
        raise AdmissionError('PAIRED_REVIEW_AUDIO_LENGTH_REQUIRED')
    path=folder/'review.mp4'
    command=[ffmpeg(root),'-hide_banner','-v','error','-n','-fflags','+genpts','-r','25',
        '-i',str(folder/'actual.h264'),'-f','s16le','-ar','16000','-ac','1','-i',str(folder/'actual.s16le'),
        '-map','0:v:0','-map','1:a:0','-vf','setpts=N/(25*TB)',
        '-af','asetpts=N/SR/TB','-fps_mode','passthrough','-c:v','libx264','-threads','4',
        '-preset','fast','-crf','18','-c:a','aac','-ar','48000','-ac','1','-movflags','+faststart',str(path)]
    result=run(command,timeout=300);(folder/'mux.log').write_bytes(result.stderr)
    if result.returncode:raise AdmissionError('ACTUAL_MOUTH_REVIEW_MUX_FAILED')
    report=inspect(root,path,packets,25,sound_required=sound_required)
    report.update(continuous_duration_seconds=duration,paired_actual_pcm=True,duplicated_frames=False,
                  replaced_audio=False,subjective_audio_video_review_required=True)
    write_json(folder/'av-verification.json',report)
    return report


def trim_official(root, raw, final, offset, seconds):
    # Output timestamps start at zero after the real continuous interval is
    # selected. No CFR conversion, padding or frame repetition is permitted.
    frames=seconds*30
    command=[ffmpeg(root),'-hide_banner','-v','error','-n','-i',str(raw),
        '-filter_complex',f'[0:v:0]trim=start={offset},setpts=PTS-STARTPTS,trim=end_frame={frames}[v];'
                          f'[0:a:0]atrim=start={offset},asetpts=PTS-STARTPTS,atrim=duration={seconds}[a]',
        '-map','[v]','-map','[a]','-fps_mode','passthrough','-c:v','libx264','-threads','4',
        '-preset','fast','-crf','18','-c:a','aac','-b:a','192k','-movflags','+faststart',str(final)]
    result=run(command,timeout=1800);Path(final).with_suffix('.trim.log').write_bytes(result.stderr)
    if result.returncode:raise AdmissionError('OFFICIAL_RECORDING_CONTINUOUS_TRIM_FAILED')
    return inspect(root,final,frames,30,size=(1920,1080),sound_required=True)
