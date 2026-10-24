"""Record the real local OBS scene and verify encoded picture and speech."""
from pathlib import Path
import asyncio, base64, datetime, hashlib, json, subprocess, time, uuid
import numpy as np
from aiohttp import ClientSession, ClientTimeout

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/vertical'


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    result = {'ok': False, 'at': datetime.datetime.now().astimezone().isoformat()}
    started_recording = False
    settings = json.loads((ROOT / 'tools/obs/config/obs-studio/plugin_config/obs-websocket/config.json').read_text(encoding='utf-8'))
    try:
        async with ClientSession(timeout=ClientTimeout(total=60), trust_env=False) as client:
            async with client.ws_connect('http://127.0.0.1:4457') as ws:
                hello = await ws.receive_json()
                identify = {'rpcVersion': 1, 'eventSubscriptions': 64}
                auth = hello['d'].get('authentication')
                if auth:
                    secret = base64.b64encode(hashlib.sha256((settings['server_password'] + auth['salt']).encode()).digest()).decode()
                    identify['authentication'] = base64.b64encode(hashlib.sha256((secret + auth['challenge']).encode()).digest()).decode()
                await ws.send_json({'op': 1, 'd': identify})
                if (await ws.receive_json())['op'] != 2:
                    raise RuntimeError('OBS authentication failed')

                record_event = {'state': None}

                async def call(name, data=None):
                    rid = uuid.uuid4().hex
                    await ws.send_json({'op': 6, 'd': {'requestType': name, 'requestId': rid, 'requestData': data or {}}})
                    while True:
                        packet = await ws.receive_json()
                        if packet['op'] == 5 and packet['d']['eventType'] == 'RecordStateChanged':
                            record_event['state'] = packet['d']['eventData']['outputState']
                        if packet['op'] == 7 and packet['d']['requestId'] == rid:
                            body = packet['d']
                            if not body['requestStatus']['result']:
                                raise RuntimeError(name + ': ' + body['requestStatus'].get('comment', 'failed'))
                            return body.get('responseData', {})

                result['streaming'] = await call('GetStreamStatus')
                if result['streaming']['outputActive']:
                    raise RuntimeError('An existing stream is active; no recording test was started')
                if (await call('GetRecordStatus'))['outputActive']:
                    raise RuntimeError('An existing recording is active; it was left untouched')
                await call('PressInputPropertiesButton', {'inputName': 'Avatar Browser', 'propertyName': 'refreshnocache'})
                for _ in range(90):
                    async with client.get('http://127.0.0.1:8010/api/studio/status') as response:
                        initial = await response.json()
                    if initial['viewers'] > 0:
                        break
                    await asyncio.sleep(1)
                else:
                    raise RuntimeError('OBS browser source did not connect to the live portrait')
                result['audio_mute'] = await call('GetInputMute', {'inputName': 'Avatar Browser'})
                result['audio_volume'] = await call('GetInputVolume', {'inputName': 'Avatar Browser'})
                # Warm the real TTS before the delivered take, retaining actual live capture.
                async with client.post('http://127.0.0.1:8010/api/studio/speak', json={'text': '你好，欢迎来到直播间。', 'mode': 'echo', 'interrupt': True}) as response:
                    response.raise_for_status()
                warm_started=time.monotonic();warm_began=False
                for _ in range(180):
                    async with client.get('http://127.0.0.1:8010/api/studio/status') as response:
                        warm_state=await response.json()
                    if warm_state['speaking']:warm_began=True
                    elif warm_began:break
                    await asyncio.sleep(.5)
                else:raise RuntimeError('TTS warm-up did not complete')
                result['tts_warmup_completed']=True
                result['tts_warmup_seconds']=round(time.monotonic()-warm_started,2)
                await call('SetRecordDirectory', {'recordDirectory': str(OUT)})
                try:
                    await call('StartRecord')
                    started_recording = True
                    for attempt in range(20):
                        result['record_start'] = await call('GetRecordStatus')
                        if result['record_start']['outputActive']:
                            break
                        await asyncio.sleep(.25)
                    else:
                        started_recording = False
                        raise RuntimeError('OBS did not enter recording state; inspect its own windows and logs')
                    await asyncio.sleep(3)
                    text = '你好，我是林知夏，欢迎来到我的直播间。今天的阳光很好，先和你打个招呼。你可以在网页里写下一句话，让我读给你听，也可以选择不同的动作，试试招手、摊手讲解，或者安静倾听。如果接入你的对话模型，我们还可以聊聊学习、生活，以及今天遇到的新发现。很高兴在这里见到你。'
                    sent = time.monotonic()
                    async with client.post('http://127.0.0.1:8010/api/studio/speak', json={'text': text, 'mode': 'echo', 'interrupt': True}) as response:
                        response.raise_for_status()
                    began = None
                    picture_saved = False
                    first_motion_sent=False;second_motion_sent=False
                    result['motion_requests']=[]
                    while time.monotonic() - sent < 55:
                        async with client.get('http://127.0.0.1:8010/api/studio/status') as response:
                            state = await response.json()
                        if state['speaking'] and began is None:
                            began = time.monotonic()
                            result['first_speech_ms'] = round((began - sent) * 1000)
                        if began is not None:
                            async with client.get('http://127.0.0.1:8010/api/studio/motion') as response:
                                motion=await response.json()
                            if motion.get('available'):
                                chosen=None
                                if not first_motion_sent:chosen='m01_welcome_right_wave';first_motion_sent=True
                                elif not second_motion_sent and motion.get('active')=='m01_welcome_right_wave' and motion.get('remaining_seconds',8)<4:
                                    chosen='m09_explain_right_palm_up';second_motion_sent=True
                                if chosen:
                                    async with client.post('http://127.0.0.1:8010/api/studio/motion',json={'id':chosen}) as response:response.raise_for_status()
                                    result['motion_requests'].append({'id':chosen,'seconds_from_send':round(time.monotonic()-sent,2)})
                        if began is not None and time.monotonic() - began > 2 and not picture_saved:
                            picture = await call('GetSourceScreenshot', {'sourceName': 'Avatar', 'imageFormat': 'png', 'imageWidth': 720, 'imageHeight': 1280})
                            (OUT / 'obs-speaking.png').write_bytes(base64.b64decode(picture['imageData'].split(',', 1)[1]))
                            picture_saved = True
                        if began is not None and not state['speaking']:
                            result['speaking_seconds'] = round(time.monotonic() - began, 2)
                            break
                        await asyncio.sleep(.2)
                    else:
                        raise RuntimeError('Speech did not finish within the recording window')
                    await asyncio.sleep(7)
                finally:
                    if started_recording:
                        recorded = await call('StopRecord')
                        result['recorded_path'] = recorded['outputPath']
                        started_recording = False
                        stop_deadline = time.monotonic() + 30
                        while record_event['state'] != 'OBS_WEBSOCKET_OUTPUT_STOPPED':
                            if time.monotonic() > stop_deadline:
                                raise RuntimeError('OBS did not confirm recording finalization')
                            await call('GetRecordStatus')
                            await asyncio.sleep(.2)
                result['obs_stats'] = await call('GetStats')
        ffmpeg = next((ROOT / 'tools/ffmpeg').rglob('ffmpeg.exe'))
        ffprobe = ffmpeg.with_name('ffprobe.exe')
        target = OUT / 'vertical-demo.mp4'
        process = subprocess.run([str(ffmpeg), '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-i', result['recorded_path'], '-c', 'copy', '-movflags', '+faststart', str(target)], capture_output=True, timeout=45)
        if process.returncode:
            raise RuntimeError(process.stderr.decode('utf-8', errors='replace')[-1500:])
        metadata = json.loads(subprocess.check_output([str(ffprobe), '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(target)], timeout=20))
        result['media'] = {'path': str(target), 'bytes': target.stat().st_size, 'duration': float(metadata['format']['duration']), 'streams': [{k: stream[k] for k in ('codec_type', 'codec_name', 'width', 'height', 'r_frame_rate', 'sample_rate', 'channels') if k in stream} for stream in metadata['streams']]}
        audio = np.frombuffer(subprocess.check_output([str(ffmpeg), '-nostdin', '-v', 'error', '-threads', '2', '-i', str(target), '-vn', '-ac', '1', '-ar', '16000', '-f', 'f32le', 'pipe:1'], timeout=30), dtype='<f4')
        result['audio'] = {'samples': int(audio.size), 'rms': float(np.sqrt(np.mean(audio ** 2))) if audio.size else 0, 'peak': float(np.max(np.abs(audio))) if audio.size else 0}
        result['ok'] = any(s['codec_type'] == 'video' and s.get('width') == 720 and s.get('height') == 1280 for s in result['media']['streams']) and any(s['codec_type'] == 'audio' for s in result['media']['streams']) and result['audio']['rms'] > .002 and result['audio']['peak'] > .03
    except Exception as exc:
        result['error'] = str(exc)
    (ROOT / '.setup/vertical-obs-recording.result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False), flush=True)
    raise SystemExit(0 if result['ok'] else 1)


asyncio.run(main())
