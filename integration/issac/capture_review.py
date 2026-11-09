"""Record the real muted v3 observer for mouth review, never for delivery."""
from __future__ import annotations
import argparse
import asyncio
import json
from pathlib import Path
import struct
import time
import uuid

from aiohttp import ClientSession,ClientTimeout,WSMsgType

from .common import AdmissionError,inside,write_json
from .deployment import require_candidate
from .av_export import mux_review


async def capture(root,mode,seconds=60,speak=False):
    if mode not in {'M01','M02','M03'} or not 30<=seconds<=120:raise AdmissionError('BOUNDED_MODE_REVIEW_REQUIRED')
    candidate=require_candidate(root);folder=inside(root,'state/issac-acceptance/mouth')/(mode+'-'+uuid.uuid4().hex);folder.mkdir(parents=True)
    requests=[];packets=0;profile=None;trace=[];start=time.monotonic();wire_start=time.perf_counter();metrics=[]
    async with ClientSession(trust_env=False) as http:
        async with http.get('http://127.0.0.1:8062/health') as response:health=await response.json()
        if health.get('mode')!=mode:raise AdmissionError('SWITCH_TO_REVIEW_MODE_BEFORE_CAPTURE')
        revision=health['programme']['revision']
        async def request_speech():
            await asyncio.sleep(3)
            for text in ['大家好呀，我是奶妹。现在握好手柄，准备开始今天的对局啦。',
                         '这里先观察一下敌人的动作，慢一点走。好，躲过去了，继续前进。']:
                async with http.post('http://127.0.0.1:3104/api/dsh/room/speak',json={'text':text,'mode':'echo',
                    'idempotency_key':'mouth-review-'+uuid.uuid4().hex},timeout=ClientTimeout(total=12)) as response:
                    result=await response.json()
                    if response.status not in {200,202} or not result.get('request_id'):raise AdmissionError('ACTUAL_REVIEW_UTTERANCE_NOT_ACCEPTED')
                    requests.append(result['request_id'])
                while time.monotonic()-start<seconds-5:
                    async with http.get('http://127.0.0.1:3104/api/dsh/requests/'+requests[-1]) as response:row=await response.json()
                    if row.get('status')=='COMPLETED':break
                    if row.get('status') in {'FAILED','CANCELLED','UNKNOWN','INTERRUPTED','EXPIRED','REJECTED'}:
                        raise AdmissionError('OFFICIAL_REVIEW_SPEECH_NOT_COMPLETED')
                    await asyncio.sleep(.5)
                await asyncio.sleep(2)
        async def sample():
            while time.monotonic()-start<seconds:
                async with http.get('http://127.0.0.1:8062/health',timeout=ClientTimeout(total=4)) as response:value=await response.json()
                metrics.append({'elapsed':time.monotonic()-start,'health':value});await asyncio.sleep(.5)
        tasks=[asyncio.create_task(sample())]
        if speak:tasks.append(asyncio.create_task(request_speech()))
        failure=None
        try:
            with (folder/'actual.h264').open('wb') as video,(folder/'actual.s16le').open('wb') as audio:
                async with http.ws_connect(f'http://127.0.0.1:8062/api/studio/stream?v=3&codec=h264&programme_revision={revision}',
                    heartbeat=20,max_msg_size=4*1024*1024,compress=0) as socket:
                    while time.monotonic()-start<seconds:
                        message=await asyncio.wait_for(socket.receive(),4)
                        if message.type==WSMsgType.TEXT:
                            value=json.loads(message.data)
                            if value.get('type')=='media.init':
                                if profile:raise AdmissionError('REVIEW_SOURCE_PROFILE_CHANGED')
                                profile=value
                            continue
                        if message.type!=WSMsgType.BINARY:raise AdmissionError('REVIEW_SOURCE_DISCONNECTED')
                        raw=message.data;sequence,n,rate=struct.unpack_from('<III',raw);encoded=raw[12:12+n];pcm=raw[12+n:]
                        if not profile or rate!=16000 or len(pcm)!=1280 or encoded[:4]!=b'AVC1':raise AdmissionError('ACTUAL_REVIEW_PACKET_INVALID')
                        at=8
                        while at<len(encoded):
                            length=struct.unpack_from('>I',encoded,at)[0];at+=4
                            if not length or at+length>len(encoded):raise AdmissionError('REVIEW_AVCC_INVALID')
                            video.write(b'\0\0\0\1'+encoded[at:at+length]);at+=length
                        audio.write(pcm);trace.append({'frame':packets,'sequence':sequence,'elapsed':time.perf_counter()-wire_start});packets+=1
            await asyncio.gather(*tasks)
        except Exception as error:
            failure=str(error) if isinstance(error,AdmissionError) else type(error).__name__
            raise
        finally:
            for task in tasks:
                if not task.done():task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            if failure:
                write_json(folder/'capture-failure.json',{**candidate,'mode':mode,'passed':False,
                    'failure':failure,'requests':requests,'packets':packets,'trace':trace,'metrics':metrics,
                    'actual_elapsed_seconds':time.monotonic()-start,'quality_accepted':False,
                    'official_delivery_recording':False,'observer_muted':True,'playback_authority_claimed':False})
    result={**candidate,'mode':mode,'profile':profile,'packets':packets,'actual_elapsed_seconds':time.monotonic()-start,
        'requests':requests,'trace':trace,'metrics':metrics,'official_delivery_recording':False,
        'observer_muted':True,'playback_authority_claimed':False,'quality_accepted':False}
    write_json(folder/'capture.json',result)
    mux_review(root,folder,packets,sound_required=speak)
    contact_sheets(folder,mode)
    return {'folder':folder.relative_to(root).as_posix(),'frames':packets,'quality_accepted':False,'actual_frame_and_audio_review_required':True}


def contact_sheets(folder,mode):
    import cv2
    import numpy as np
    from PIL import Image,ImageDraw
    video=cv2.VideoCapture(str(folder/'review.mp4'));index=0;sheet=None;paths=[];previous=None;differences=[]
    cx,cy=(263,258) if mode=='M03' else (259,201)
    try:
        while True:
            okay,frame=video.read()
            if not okay:break
            crop=frame[max(0,cy-36):cy+36,max(0,cx-54):cx+54]
            crop=cv2.cvtColor(crop,cv2.COLOR_BGR2RGB)
            if previous is not None:differences.append(float(np.abs(crop.astype(np.float32)-previous).mean()))
            previous=crop.astype(np.float32)
            if index%48==0:sheet=Image.new('RGB',(108*3*6,72*3*8+24*8),'#202027')
            col,row=index%6,(index%48)//6;tile=Image.fromarray(crop).resize((324,216))
            sheet.paste(tile,(col*324,row*240));ImageDraw.Draw(sheet).text((col*324+4,row*240+218),f'{index:05d} / {index/25:.2f}s',fill='white')
            index+=1
            if index%48==0:
                path=folder/f'mouth-allframes-{index//48:03d}.jpg';sheet.save(path,quality=92);paths.append(path.name);sheet=None
        if sheet is not None:
            path=folder/f'mouth-allframes-{index//48+1:03d}.jpg';sheet.save(path,quality=92);paths.append(path.name)
    finally:video.release()
    write_json(folder/'mouth-inspection.json',{'decoded_frames':index,'all_frames_in_contact_sheets':True,
        'contact_sheets':paths,'mouth_crop_frame_differences':differences,
        'difference_is_not_phoneme_or_fang_acceptance':True,'actual_full_speed_audio_video_review_required':True})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True,type=Path);parser.add_argument('--mode',required=True)
    parser.add_argument('--seconds',type=int,default=60);parser.add_argument('--speak',action='store_true');args=parser.parse_args()
    print(json.dumps(asyncio.run(capture(args.root.resolve(),args.mode,args.seconds,args.speak)),ensure_ascii=False))
