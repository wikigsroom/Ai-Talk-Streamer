"""Inject a stopped primary failure in an isolated adapter; run real local F07."""
from pathlib import Path
import argparse
import asyncio
import hashlib
import json
import sys
import uuid
from aiohttp import web, ClientSession

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from integration.naimei_studio import Studio
from integration.naimei_voice_contract import cache_matches
from integration.naimei_text import spoken_text


async def verify(root):
    state = {'busy': True, 'cancel_calls': 0}
    async def fail(_request):
        return web.json_response({'error': 'INJECTED_STOPPED_PRIMARY_FAILURE'}, status=503)
    async def cancel(_request):
        state['cancel_calls'] += 1
        return web.json_response({'accepted': True})
    async def health(_request):
        return web.json_response({'busy': state['busy']})
    app = web.Application()
    app.add_routes([web.post('/tts', fail), web.post('/cancel', cancel), web.get('/health', health)])
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    try:
        await web.TCPSite(runner, '127.0.0.1', 0).start()
        port = runner.addresses[0][1]
        studio = Studio(root)
        studio.config = {**studio.config, 'tts_primary_url': f'http://127.0.0.1:{port}'}
        text = '奶妹仍然使用原来选定的声音，备用模型也使用同一份参考。'
        async with ClientSession() as studio.http:
            try:
                await studio.synthesize(text, 'busy-primary-check-' + uuid.uuid4().hex)
                raise AssertionError('Busy primary must not run a second GPU model')
            except RuntimeError as exc:
                assert str(exc) == 'PRIMARY_STILL_COMPUTING_NO_FALLBACK'
            state['busy'] = False
            rid = 'approved-route-check-' + uuid.uuid4().hex
            audio, engine, metrics = await studio.synthesize(text, rid)
        voice = next(v for v in studio.voice_profile['voices'] if v['id'] == 'F07')
        assert engine == 'F5-TTS-v1' and cache_matches(metrics, voice, spoken_text(text))
        assert metrics['precision'] == 'torch.float32' and state['cancel_calls'] == 2
        path = root / 'assets/naimei/live-v1/voice/fallback/O07-to-F07-check.wav'
        path.write_bytes(audio)
        result = {**metrics, 'text': text, 'sha256': hashlib.sha256(audio).hexdigest(),
                  'primary_failure_injected_in_isolated_adapter': True, 'fallback_inference_real': True,
                  'production_primary_stopped': False, 'busy_primary_blocks_fallback': True,
                  'human_listening_accepted': False}
        path.with_suffix('.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
        print(json.dumps(result, ensure_ascii=False))
    finally:
        await runner.cleanup()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    asyncio.run(verify(args.root.resolve()))
