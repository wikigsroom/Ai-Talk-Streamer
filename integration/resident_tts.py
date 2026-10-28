"""LiveTalking adapter for the approved resident O07/F07 voice pair."""
from io import BytesIO
from math import gcd
from threading import Thread
import json
import uuid
import hashlib
import numpy as np
import requests
import soundfile as sf
from scipy.signal import resample_poly
from registry import register
from utils.logger import logger
from .base_tts import BaseTTS, State


@register('tts', 'resident-local')
class ResidentTTS(BaseTTS):
    requires_complete_reply = True

    def __init__(self, opt, parent):
        super().__init__(opt, parent)
        self.http = requests.Session()
        self.http.trust_env = False
        self.epoch = 0
        self.active_request = None
        self.expected_reference = getattr(opt, 'TTS_REFERENCE_SHA256', '')
        self.allowed = {'O07': 'OmniVoice', 'F07': 'F5-TTS-v1'}

    def current(self, info, epoch):
        return (self.state == State.RUNNING and self.epoch == epoch and
                ('generation' not in info or info['generation'] == getattr(self.parent, '_studio_generation', None)) and
                (not info.get('dsh') or info.get('runtime_epoch') == getattr(self.parent, '_dsh_runtime_epoch', None)))

    def flush_talk(self):
        with self.msgqueue.mutex:
            self.msgqueue.queue.clear()
        self.epoch += 1
        self.state = State.PAUSE
        active = self.active_request
        if active:
            def cancel():
                try:
                    with requests.Session() as http:
                        http.trust_env = False
                        http.post(self.opt.TTS_SERVER.rstrip('/') + '/cancel',
                                  json={'request_id': active}, timeout=(1, 2))
                except requests.RequestException:
                    logger.warning('Local speech cancellation endpoint did not answer; stale audio will still be discarded')
            Thread(target=cancel, daemon=True).start()

    def txt_to_audio(self, msg):
        text, info = msg
        epoch = self.epoch
        if not self.current(info, epoch):
            return
        request_id = uuid.uuid4().hex
        self.active_request = request_id
        try:
            gpu = getattr(getattr(self.parent, 'audio_processor', None), 'client', None)
            if gpu is not None:
                gpu.call('release_cache')
                if not self.current(info, epoch):
                    return
            self.parent.send_msg(json.dumps({'status': 'generating', 'text': text,
                                            'engine': 'OmniVoice', 'voice_id': 'O07'}, ensure_ascii=False))
            response = self.http.post(self.opt.TTS_SERVER.rstrip('/') + '/tts',
                                      json={'text': text, 'request_id': request_id}, timeout=(3, 120 if info.get('dsh') else 600))
            if not self.current(info, epoch):
                return
            response.raise_for_status()
            voice_id = response.headers.get('X-TTS-Voice')
            engine = response.headers.get('X-TTS-Engine')
            if (self.allowed.get(voice_id) != engine or not self.expected_reference or
                    response.headers.get('X-TTS-Reference-SHA256') != self.expected_reference):
                raise RuntimeError('Speech engine, voice or approved reference does not match')
            if response.headers.get('X-TTS-Fallback') == 'true':
                self.parent.send_msg(json.dumps({'status': 'tts_fallback', 'engine': engine,
                    'voice_id': voice_id, 'text': 'O07 暂时不可用，本次使用 F07 备用音色。'}, ensure_ascii=False))
            if not response.headers.get('Content-Type', '').startswith('audio/wav'):
                raise RuntimeError('Local speech returned a non-audio response')
            wave, rate = sf.read(BytesIO(response.content), dtype='float32', always_2d=True)
            wave = wave.mean(1)
            if not len(wave) or not np.isfinite(wave).all():
                raise RuntimeError('Local speech returned empty or invalid samples')
            if rate != self.sample_rate:
                factor = gcd(rate, self.sample_rate)
                wave = resample_poly(wave, self.sample_rate // factor, rate // factor).astype(np.float32)
            logger.info('%s generated %.3fs audio in %ss', voice_id,
                        len(wave) / self.sample_rate, response.headers.get('X-TTS-Wall-Seconds', '?'))
            if gpu is not None:
                gpu.call('prepare_speech')
                if not self.current(info, epoch):
                    return
            if info.get('dsh'):
                from server.dsh_bridge import post_media
                post_media('audio-ready', {**info, 'valid_sample_count': len(wave),
                           'audio_sha256': hashlib.sha256((wave * 32767).astype('<i2').tobytes()).hexdigest()})
            # Enqueue a complete utterance. Retain and pad the final partial frame.
            for offset in range(0, len(wave), self.chunk):
                if not self.current(info, epoch):
                    return
                chunk = wave[offset:offset + self.chunk]
                if len(chunk) < self.chunk:
                    chunk = np.pad(chunk, (0, self.chunk - len(chunk)))
                event = {**info, 'tts_engine': engine, 'voice_id': voice_id,
                         'sample_offset': offset, 'valid_samples': min(self.chunk, len(wave) - offset),
                         'valid_sample_count': len(wave), 'sample_final': offset + self.chunk >= len(wave)}
                if offset == 0:
                    event.update(status='start', text=text)
                self.parent.put_audio_frame(chunk, event)
            if self.current(info, epoch):
                self.parent.put_audio_frame(np.zeros(self.chunk, np.float32),
                                            {**info, 'status': 'end', 'text': text,
                                             'tts_engine': engine, 'voice_id': voice_id})
        except Exception:
            if self.current(info, epoch):
                logger.exception('Local speech synthesis failed')
                self.parent.send_msg(json.dumps({'status': 'error', 'text': 'O07 与备用 F07 语音生成未完成，请查看本地语音服务日志。'}, ensure_ascii=False))
                if info.get('dsh'):
                    try:
                        from server.dsh_bridge import post_media
                        post_media('failed', {'request_id': info['request_id']})
                    except requests.RequestException:
                        logger.warning('DSH failure receipt unavailable; request deadline remains active')
        finally:
            if self.active_request == request_id:
                self.active_request = None

    def stop_tts(self):
        self.flush_talk()
        self.http.close()
