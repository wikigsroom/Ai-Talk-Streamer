"""Record and validate five distinct use cases through the actual live OBS scene."""
from pathlib import Path
import asyncio, base64, datetime, hashlib, json, subprocess, time, uuid, zipfile
import numpy as np
from aiohttp import ClientSession, ClientTimeout

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/vertical/scenarios'
SCENARIOS = [
    ('s01_welcome', '开场欢迎', '招手欢迎观众，随后进入自然播报。'),
    ('s02_explain', '内容讲解', '连续两段讲解，配合摊掌展示与强调动作。'),
    ('s03_listen_reply', '聆听后回应', '先安静倾听，再播报准备好的回应文字。'),
    ('s04_interrupt_resume', '打断后恢复', '中途停止一段播报，留出静音，再切换新内容继续。'),
    ('s05_closing', '结束告别', '双手收尾、致谢，并以轻挥手结束。'),
]


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'manifest.json').write_text(json.dumps({'ok': False, 'items': []}), encoding='utf-8')
    report = {'ok': False, 'at': datetime.datetime.now().astimezone().isoformat(), 'items': [], 'text_mode': 'echo', 'scene': 'original daytime dorm', 'avatar_id': 'student_dorm_motion_bank_v3'}
    settings = json.loads((ROOT / 'tools/obs/config/obs-studio/plugin_config/obs-websocket/config.json').read_text(encoding='utf-8'))
    ffmpeg = next((ROOT / 'tools/ffmpeg').rglob('ffmpeg.exe'))
    recording = False
    try:
        async with ClientSession(timeout=ClientTimeout(total=60), trust_env=False) as client:
            async def api(route, data=None):
                async with client.request('GET' if data is None else 'POST', 'http://127.0.0.1:8010/api/studio/' + route, json=data) as response:
                    response.raise_for_status()
                    return await response.json()

            state = await api('status')
            if state['avatar_id'] != report['avatar_id'] or state['viewers'] < 1 or len((await api('motion'))['clips']) < 50:
                raise RuntimeError('The reviewed live motion bank and OBS viewer must be ready')
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

                async def await_recording_stopped():
                    deadline = time.monotonic() + 30
                    while record_event['state'] != 'OBS_WEBSOCKET_OUTPUT_STOPPED':
                        if time.monotonic() > deadline:
                            raise RuntimeError('OBS did not confirm that its recording file was closed')
                        await call('GetRecordStatus')
                        await asyncio.sleep(.2)

                if (await call('GetRecordStatus'))['outputActive'] or (await call('GetStreamStatus'))['outputActive']:
                    raise RuntimeError('An existing OBS output was left untouched')
                await call('SetRecordDirectory', {'recordDirectory': str(OUT)})

                async def wait_speaking(expected, timeout=90):
                    deadline = time.monotonic() + timeout
                    while time.monotonic() < deadline:
                        value = await api('status')
                        if bool(value['speaking']) == expected:
                            return value
                        await asyncio.sleep(.2)
                    raise RuntimeError('Timed out waiting for speaking=' + str(expected))

                for sid, title, description in SCENARIOS:
                    script_sha = hashlib.sha256(json.dumps({'id': sid, 'version': 3, 'stop_gate': 'actual_OBS_STOPPED_event', 'gesture_gate': 'after_actual_speech_starts'}, sort_keys=True).encode()).hexdigest()
                    old_path = OUT / (sid + '.result.json')
                    if old_path.is_file():
                        old = json.loads(old_path.read_text(encoding='utf-8'))
                        existing = OUT / (sid + '.mp4')
                        if old.get('ok') and old.get('test_script_sha256') == script_sha and existing.is_file() and hashlib.sha256(existing.read_bytes()).hexdigest() == old.get('sha256'):
                            report['items'].append(old)
                            continue
                    item = {'id': sid, 'title': title, 'description': description, 'ok': False, 'events': [], 'test_script_sha256': script_sha}
                    start = time.monotonic()

                    def event(name, **values):
                        item['events'].append({'event': name, 'seconds': round(time.monotonic() - start, 3), **values})

                    async def motion(mid):
                        await api('motion', {'id': mid})
                        deadline = time.monotonic() + 20
                        while time.monotonic() < deadline:
                            value = await api('motion')
                            if value['active'] == mid:
                                event('motion_active', id=mid)
                                return
                            await asyncio.sleep(.2)
                        raise RuntimeError('Motion did not become active: ' + mid)

                    async def begin(text):
                        sent = time.monotonic()
                        await api('speak', {'text': text, 'mode': 'echo', 'interrupt': True})
                        await wait_speaking(True)
                        event('speech_started', latency_ms=round((time.monotonic() - sent) * 1000), text=text)

                    async def picture(tag):
                        value = await call('GetSourceScreenshot', {'sourceName': 'Avatar', 'imageFormat': 'png', 'imageWidth': 720, 'imageHeight': 1280})
                        path = OUT / (sid + ('-' + tag if tag else '') + '.png')
                        path.write_bytes(base64.b64decode(value['imageData'].split(',', 1)[1]))
                        event('actual_obs_screenshot', image=path.name, speaking=(await api('status'))['speaking'])

                    async def phase(mid, text, tag=''):
                        await begin(text)
                        await motion(mid)
                        event('phase_motion_during_speech', id=mid, speaking=(await api('status'))['speaking'])
                        await asyncio.sleep(3.5)
                        await picture(tag)
                        await wait_speaking(False)
                        event('speech_completed')

                    await api('interrupt', {})
                    await wait_speaking(False, 10)
                    # OBS may return before its previous recording output is reusable.
                    for attempt in range(5):
                        if (await call('GetRecordStatus'))['outputActive']:
                            raise RuntimeError('An existing recording is active before the next test')
                        try:
                            record_event['state'] = None
                            await call('StartRecord')
                            recording = True
                            break
                        except RuntimeError:
                            if attempt == 4:
                                raise
                            await asyncio.sleep(3)
                    try:
                        for _ in range(20):
                            if (await call('GetRecordStatus'))['outputActive']:
                                break
                            await asyncio.sleep(.25)
                        else:
                            raise RuntimeError('OBS did not start the scenario recording')
                        start = time.monotonic()
                        await asyncio.sleep(1)
                        if sid == 's01_welcome':
                            await phase('m01_welcome_right_wave', '你好，欢迎来我的宿舍坐坐，我是林知夏。今天的阳光刚刚好，先和你打个招呼。你可以在网页里写下想说的话，也可以选一个动作，让我陪你聊一会儿。')
                        elif sid == 's02_explain':
                            await phase('m09_explain_right_palm_up', '如果今天的学习任务有点多，可以先把它们写下来，再分成几个小步骤。不必一开始就做得很完美，先完成最容易开始的那一步，会轻松很多。')
                            await phase('m17_emphasis_right_beat_take2', '还有一个小建议：每做完一段，就给自己几分钟休息。喝一点水，看看窗外，再回来继续。进度慢一点也没关系，能持续下去，就是很好的节奏。', 'second')
                        elif sid == 's03_listen_reply':
                            await motion('m25_listen_tilt_right')
                            await asyncio.sleep(5)
                            event('quiet_listening', speaking=(await api('status'))['speaking'])
                            await phase('m23_emphasis_nod_left_palm', '如果你觉得复习时容易分心，可以试着先把手机放远一点，只给自己安排十分钟。时间到了，再决定要不要继续。我们就从这个很小的目标开始，不着急。')
                        elif sid == 's04_interrupt_resume':
                            await motion('m15_explain_open_hand_side')
                            await begin('今天原本想和你聊一个很长的话题，从早上的课程安排，到下午的自习计划，再到晚上想读的书。不过聊天的时候，如果你突然有了别的想法，也可以随时停下来，我们再换一个新的话题继续。')
                            await asyncio.sleep(2)
                            await picture('before-stop')
                            await asyncio.sleep(4)
                            stopped = time.monotonic()
                            await api('interrupt', {})
                            await wait_speaking(False, 10)
                            event('interrupted', settled_ms=round((time.monotonic() - stopped) * 1000))
                            await asyncio.sleep(3)
                            position = (await call('GetRecordStatus'))['outputDuration'] / 1000
                            item['silence_window_seconds'] = [round(position - .9, 3), round(position - .1, 3)]
                            await phase('m29_listen_hands_fold_right', '好，刚才那段先停在这里。我们换个轻松的话题吧：最近有没有哪一首歌，或者哪一部电影，让你觉得心情特别好？你可以把名字写下来。')
                        else:
                            await phase('m47_closing_palms_then_bow', '今天就先聊到这里，谢谢你愿意过来坐坐，也谢谢你分享自己的想法。希望这一小会儿的陪伴，能让你的心情轻松一点。不管今天过得怎么样，都记得给努力的自己一点鼓励。')
                            await phase('m41_closing_right_goodbye', '那我们下次再见啦。记得照顾好自己，按时吃饭，也给自己留一点休息的时间。祝你今天接下来的安排都顺顺利利。等下次见面的时候，我们再来分享生活里那些有意思的小发现。', 'wave')
                        await asyncio.sleep(5)
                    finally:
                        if recording:
                            item['recorded_path'] = (await call('StopRecord'))['outputPath']
                            recording = False
                            await await_recording_stopped()
                        await api('interrupt', {})
                        await api('motion', {'id': 'auto'})

                    target = OUT / (sid + '.mp4')
                    subprocess.run([str(ffmpeg), '-nostdin', '-v', 'error', '-y', '-i', item['recorded_path'], '-c', 'copy', '-movflags', '+faststart', str(target)], check=True, timeout=60)
                    media = json.loads(subprocess.check_output([str(ffmpeg.with_name('ffprobe.exe')), '-v', 'error', '-show_entries', 'stream=codec_type,width,height,r_frame_rate:format=duration', '-of', 'json', str(target)], text=True, timeout=20))
                    audio = np.frombuffer(subprocess.check_output([str(ffmpeg), '-nostdin', '-v', 'error', '-threads', '2', '-i', str(target), '-vn', '-ac', '1', '-ar', '16000', '-f', 'f32le', 'pipe:1'], timeout=30), dtype='<f4')
                    item.update(media=media, seconds=float(media['format']['duration']), bytes=target.stat().st_size, sha256=hashlib.sha256(target.read_bytes()).hexdigest(), audio_rms=float(np.sqrt(np.mean(audio ** 2))) if audio.size else 0, audio_peak=float(np.max(np.abs(audio))) if audio.size else 0)
                    if sid == 's04_interrupt_resume':
                        lower, upper = item['silence_window_seconds']
                        quiet = audio[int(lower * 16000):int(upper * 16000)]
                        item['silence_rms'] = float(np.sqrt(np.mean(quiet ** 2))) if quiet.size else 1
                    has_video = any(s.get('width') == 720 and s.get('height') == 1280 and s.get('r_frame_rate') == '25/1' for s in media['streams'])
                    has_audio = any(s['codec_type'] == 'audio' for s in media['streams'])
                    active_screenshots = [e for e in item['events'] if e['event'] == 'actual_obs_screenshot']
                    phase_events = [e for e in item['events'] if e['event'] == 'phase_motion_during_speech']
                    item['ok'] = has_video and has_audio and item['seconds'] > 15 and item['audio_rms'] > .002 and bool(active_screenshots) and all(e['speaking'] for e in active_screenshots) and bool(phase_events) and all(e['speaking'] for e in phase_events) and item.get('silence_rms', 0) < .008
                    old_path.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding='utf-8')
                    if not item['ok']:
                        raise RuntimeError('Scenario validation failed: ' + sid)
                    report['items'].append(item)
                    (OUT / 'progress.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                    print(json.dumps({'scenario_complete': sid, 'seconds': item['seconds'], 'audio_rms': item['audio_rms'], 'silence_rms': item.get('silence_rms')}, ensure_ascii=False), flush=True)
                    await asyncio.sleep(4)
                report['obs_stats'] = await call('GetStats')
        report['ok'] = len(report['items']) == 5 and all(item['ok'] for item in report['items'])
        manifest = {'ok': report['ok'], 'count': len(report['items']), 'scene': 'daytime dorm', 'text_mode': 'echo', 'items': [{k: item[k] for k in ('id', 'title', 'description', 'seconds', 'bytes', 'sha256')} | {'url': '/tests/media/' + item['id'] + '.mp4', 'poster_url': '/tests/media/' + item['id'] + '.png'} for item in report['items']]}
        (OUT / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        bundle = OUT / 'portrait-scenario-tests.zip'
        temporary = bundle.with_suffix('.uploading')
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_STORED) as archive:
            archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
            for name in ['result.json'] + [item['id'] + suffix for item in report['items'] for suffix in ('.mp4', '.png', '.result.json')]:
                archive.write(OUT / name, name)
        temporary.replace(bundle)
        (OUT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception as exc:
        report['error'] = str(exc)
        (OUT / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'ok': report['ok'], 'completed': len(report['items']), 'error': report.get('error')}, ensure_ascii=False), flush=True)
    raise SystemExit(0 if report['ok'] else 1)


asyncio.run(main())
