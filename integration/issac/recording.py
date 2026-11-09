"""Genuine official Livehime recording, with retained raw-file provenance."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import subprocess
import time
import uuid

from .acceptance import Runner,record_gate,verify_gates
from .common import AdmissionError,FileLease,digest,file_hash,inside,read_json,write_json
from .delivery import recording_gate,recording_seconds
from .livehime import Livehime
from .materials import ffmpeg
from .record_focus import RecordingHandoff,record_controls


def probe(root,path):
    result=subprocess.run([ffmpeg(root,'ffprobe.exe'),'-v','error','-count_frames',
        '-show_streams','-show_format','-of','json',str(path)],capture_output=True,timeout=180,creationflags=0x08000000)
    if result.returncode:raise AdmissionError('ACTUAL_OFFICIAL_RECORDING_PROBE_FAILED')
    return json.loads(result.stdout)


def official_writers(client,path):
    """Observe a real file handle belonging to the independently owned client."""
    import psutil
    owner=client.owner();parent=psutil.Process(owner['pid']);rows=[]
    for process in [parent,*parent.children(recursive=True)]:
        try:
            executable=Path(process.exe()).resolve()
            if not executable.is_relative_to(client.executable.parent):continue
            if any(Path(f.path).resolve()==path for f in process.open_files()):
                rows.append({'pid':process.pid,'created_at':process.create_time(),
                    'executable':str(executable),'executable_sha256':file_hash(executable),
                    'observed_unix':time.time(),'method':'native_process_open_file_handle'})
        except (psutil.NoSuchProcess,psutil.AccessDenied):continue
    return rows


async def record(root):
    client=Livehime(root);candidate=client.candidate;seconds=recording_seconds(root)
    # All quality gates precede the delivery recording. A preview is not a gate.
    verify_gates(root,before_recording=True)
    scene=read_json(inside(root,'state/issac-acceptance/official-scene.json'));owner=client.owner()
    if (scene.get('accepted') is not True or scene.get('candidate_id')!=candidate['candidate_id']
        or scene.get('official_pid')!=owner['pid'] or scene.get('official_created_at')!=owner['created_at']):
        raise AdmissionError('CURRENT_OFFICIAL_SCENE_APPROVAL_REQUIRED')
    rawdir=inside(root,'outputs/issac/recordings/raw');rawdir.mkdir(parents=True,exist_ok=True)
    baseline={p.resolve() for p in rawdir.rglob('*') if p.is_file()}
    output=inside(root,'outputs/issac/recordings')/('official-'+uuid.uuid4().hex);output.mkdir()
    lease=FileLease(inside(root,'state/issac-stream/official-recording.lock')).acquire()
    runner=None;task=None;started=False;observations=[];error=None;raw=None;report=None
    try:
        handoff=RecordingHandoff(root);pause_receipt=handoff.pause()
        with record_controls(client):
            start_receipt=client.ui('record-start');started=True;capture_start=time.monotonic();unix=time.time()
            screenshot=client.screenshot('recording_started')
        resume_receipt=handoff.resume()
        live_interval=await asyncio.to_thread(handoff.wait_live_interval)
        start=time.monotonic();continuous_offset=start-capture_start
        write_json(output/'start.json',{'owner':owner,'ui':start_receipt,'candidate':candidate,'started_unix':unix,
            'explicit_recording_pause':pause_receipt,'explicit_recording_resume':resume_receipt,
            'live_interval_observation':live_interval,
            'continuous_game_start_seconds':continuous_offset})
        deadline=start+30
        while time.monotonic()<deadline:
            candidates=[p.resolve() for p in rawdir.rglob('*') if p.is_file() and p.resolve() not in baseline
                and p.suffix.lower() in {'.mp4','.flv','.mkv','.mov'} and p.stat().st_mtime>=unix-2]
            if len(candidates)>1:raise AdmissionError('MULTIPLE_NEW_RECORDINGS_REQUIRE_REVIEW')
            if len(candidates)==1 and candidates[0].stat().st_size>4096:
                raw=candidates[0];break
            await asyncio.sleep(.5)
        if raw is None:raise AdmissionError('NO_NEW_OFFICIAL_RECORDING_IN_CONFIGURED_ISSAC_RAW_DIRECTORY')
        writer=official_writers(client,raw)
        if not writer:raise AdmissionError('GENUINE_OFFICIAL_RECORDING_WRITER_NOT_OBSERVED')
        runner=Runner(root);task=asyncio.create_task(runner.cohost(seconds));previous=raw.stat().st_size
        for tick in range(seconds//5+3):
            await asyncio.to_thread(client.owner);size=raw.stat().st_size
            current_writers=await asyncio.to_thread(official_writers,client,raw) if tick%6==0 else []
            observations.append({'elapsed_seconds':time.monotonic()-start,'bytes':size,'growing':size>previous,
                'official_writer':current_writers})
            previous=size
            write_json(output/'progress.json',{'candidate_id':candidate['candidate_id'],'elapsed_seconds':time.monotonic()-start,
                'raw_bytes':size,'required_live_observation_seconds':seconds,'finished':False})
            if task.done() and time.monotonic()-start>=seconds:break
            await asyncio.sleep(5)
        report=await task
        if not report['passed']:raise AdmissionError('OFFICIAL_RECORDING_COHOST_QUALITY_FAILED')
    except Exception as exc:
        error=str(exc) if isinstance(exc,AdmissionError) else 'OFFICIAL_RECORDING_FAILED'
        if task and not task.done():task.cancel();await asyncio.gather(task,return_exceptions=True)
    finally:
        if started:
            try:
                stop_handoff=RecordingHandoff(root)
                try:
                    if stop_handoff.request(9534,'/status').get('armed') is True:
                        stop_handoff.pause()
                except Exception:
                    # A failed pause never rearms control or prevents the
                    # already-started owned recording from being stopped.
                    error=error or 'RECORDING_STOP_GAME_PAUSE_NOT_CONFIRMED'
                with record_controls(client):
                    stop_receipt=client.ui('record-stop');stop_screen=client.screenshot('recording_stopped')
                write_json(output/'stop.json',{'ui':stop_receipt,'screen':stop_screen,'stopped_unix':time.time()})
            except Exception:error=error or 'OFFICIAL_RECORD_STOP_NOT_CONFIRMED'
        if runner:runner.close()
        lease.close()
        write_json(output/'observation.json',{'candidate':candidate,'owner':owner,'raw':raw.relative_to(root).as_posix() if raw else None,
            'samples':observations,'error':error,'cohost':report,'public_broadcast_started':False})
    if error:raise AdmissionError(error)
    # Wait for the official writer to close its file. Never take over that file.
    for _ in range(30):
        if not official_writers(client,raw):break
        await asyncio.sleep(1)
    else:raise AdmissionError('OFFICIAL_RAW_RECORDING_FILE_STILL_OPEN')
    metadata=probe(root,raw);videos=[s for s in metadata['streams'] if s['codec_type']=='video']
    audio=[s for s in metadata['streams'] if s['codec_type']=='audio']
    if len(videos)!=1 or len(audio)!=1:raise AdmissionError('ONE_OFFICIAL_VIDEO_AND_MIXED_AUDIO_TRACK_REQUIRED')
    video=videos[0];rate=video.get('avg_frame_rate','0/1').split('/');fps=int(rate[0])/int(rate[1])
    if ((video['width'],video['height'])!=(1920,1080) or abs(fps-30)>.001
        or int(video.get('nb_read_frames','0'))<int((seconds+continuous_offset)*30)
        or float(metadata['format']['duration'])<seconds+continuous_offset):
        raise AdmissionError('ACTUAL_OFFICIAL_1080P30_'+str(seconds)+'_SECONDS_REQUIRED')
    final=output/('奶妹-以撒的结合-官方直播姬-'+str(seconds)+'秒.mp4')
    # This only cuts a continuous interval from the actual official recording.
    # It adds no image, mouth, voice, repeated frame or alternate audio source.
    command=[ffmpeg(root),'-hide_banner','-v','error','-n','-i',str(raw),'-ss',str(continuous_offset),'-map','0:v:0','-map','0:a:0',
        '-t',str(seconds),'-frames:v',str(seconds*30),'-vsync','0','-c:v','libx264','-preset','fast','-crf','18',
        '-c:a','aac','-b:a','192k','-movflags','+faststart',str(final)]
    with (output/'trim.log').open('wb') as log:
        process=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=1800,creationflags=0x08000000)
    if process.returncode:raise AdmissionError('OFFICIAL_RECORDING_CONTINUOUS_TRIM_FAILED')
    finalmeta=probe(root,final)
    decoded=subprocess.run([ffmpeg(root),'-v','error','-i',str(final),'-map','0:v:0','-map','0:a:0',
        '-f','null','-'],capture_output=True,timeout=600,creationflags=0x08000000)
    sound=subprocess.run([ffmpeg(root),'-hide_banner','-i',str(final),'-vn','-af','volumedetect','-f','null','-'],
        capture_output=True,timeout=180,creationflags=0x08000000)
    (output/'sound-analysis.log').write_bytes(sound.stderr)
    manifest={**candidate,'raw':raw.relative_to(root).as_posix(),'raw_sha256':file_hash(raw),
        'final':final.relative_to(root).as_posix(),'final_sha256':file_hash(final),'official_writer':writer,
        'scene_review_sha256':digest(scene),'recording_started_screen':screenshot,'raw_probe':metadata,'final_probe':finalmeta,
        'decode_exit_code':decoded.returncode,'audio_analysis_exit_code':sound.returncode,
        'continuous_start_seconds':continuous_offset,'continuous_duration_seconds':seconds,'postprocess':'continuous_trim_only',
        'added_or_replaced_audio':False,'generated_or_duplicated_frames':False,'public_broadcast_started':False,
        'subjective_final_review_required':True,'quality_accepted':False}
    write_json(output/'manifest.json',manifest)
    return manifest


def approve(root,relative):
    review=read_json(inside(root,relative));manifest=read_json(inside(root,review['manifest']))
    client=Livehime(root)
    checks={'genuine_official_raw','continuous_'+str(recording_seconds(root))+'_seconds','real_game_visible','mc_geometry_and_title',
        'natural_controller_and_drink_actions','mouth_synchronous_and_fluid','two_upper_fangs_stable',
        'ncm01_and_game_audible','no_double_audio','no_private_reference_audio','no_public_broadcast'}
    if (not review.get('reviewer') or review.get('candidate_id')!=client.candidate['candidate_id']
        or set(review.get('checks',{}))!=checks or any(v is not True for v in review['checks'].values())
        or manifest['candidate_id']!=client.candidate['candidate_id']
        or file_hash(inside(root,manifest['raw']))!=manifest['raw_sha256']
        or file_hash(inside(root,manifest['final']))!=manifest['final_sha256']
        or manifest['decode_exit_code'] or manifest['audio_analysis_exit_code']):
        raise AdmissionError('ACTUAL_FINAL_OFFICIAL_RECORDING_REVIEW_REQUIRED')
    return record_gate(root,recording_gate(root),review['checks'],[relative,review['manifest'],manifest['final'],manifest['raw']])


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True,type=Path)
    parser.add_argument('action',choices=['record','approve']);parser.add_argument('--review');args=parser.parse_args()
    result=asyncio.run(record(args.root.resolve())) if args.action=='record' else approve(args.root.resolve(),args.review)
    print(json.dumps(result,ensure_ascii=False))
