"""Native, outbound-only LAN link for the isolated Naimei studio."""
import asyncio
import base64
import json
import os
from pathlib import Path
import struct
import time
import aiohttp

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / 'state/naimei/relay'
STATIC = {'/', '/output.html', '/health', '/naimei.css', '/naimei.js', '/naimei-output.js',
          '/local-stream.js', '/browser-id.js', '/dsh-playback.js', '/room-client.js', '/room-audio.js'}


def allowed(path):
    route = path.split('?', 1)[0]
    return (route in STATIC or route in {'/api/studio/status', '/api/studio/stream'}
            or route.startswith(('/api/dsh/', '/api/naimei/', '/naimei-assets/')))


async def connection(config):
    channels, tasks = {}, set()
    async with aiohttp.ClientSession(trust_env=False, timeout=aiohttp.ClientTimeout(total=None, sock_connect=8)) as session:
        async with session.ws_connect(config['controller'], headers={'Authorization': 'Bearer ' + config['token']},
                                      heartbeat=15, compress=0, max_msg_size=64 * 1024 * 1024) as tunnel:
            (STATE / 'status.json').write_text(json.dumps({'connected': True, 'updated': time.time(), 'cloud_used': False, 'pid': os.getpid()}), 'utf-8')

            async def request(item):
                try:
                    if not allowed(item['path']):
                        raise ValueError('Unsupported Naimei path')
                    target = 'http://127.0.0.1:8052' + item['path']
                    if item['type'] == 'http':
                        async with session.request(item['method'], target, data=base64.b64decode(item.get('body', '')),
                                                   headers=item.get('headers', {}), timeout=aiohttp.ClientTimeout(total=60)) as response:
                            body = await response.read()
                            headers = {key: value for key, value in response.headers.items()
                                       if key.lower() in {'content-type', 'content-range', 'accept-ranges'}}
                            await tunnel.send_json({'id': item['id'], 'status': response.status,
                                                    'headers': headers, 'body': base64.b64encode(body).decode()})
                    elif item['type'] == 'ws_open':
                        if item['path'].split('?', 1)[0] != '/api/studio/stream':
                            raise ValueError('Unsupported WebSocket')
                        channel = item['channel']
                        ws = await session.ws_connect(target, heartbeat=15, compress=0, max_msg_size=4 * 1024 * 1024)
                        channels[channel] = ws
                        await tunnel.send_json({'id': item['id'], 'opened': True})
                        try:
                            async for message in ws:
                                if message.type == aiohttp.WSMsgType.BINARY:
                                    await tunnel.send_bytes(struct.pack('!IB', channel, 1) + message.data)
                                elif message.type == aiohttp.WSMsgType.TEXT:
                                    await tunnel.send_bytes(struct.pack('!IB', channel, 2) + message.data.encode())
                        finally:
                            channels.pop(channel, None)
                            await ws.close()
                            if not tunnel.closed:
                                await tunnel.send_bytes(struct.pack('!IB', channel, 3))
                except Exception as error:
                    if not tunnel.closed:
                        await tunnel.send_json({'id': item['id'], 'error': str(error)})

            try:
                async for message in tunnel:
                    if message.type == aiohttp.WSMsgType.BINARY:
                        if len(message.data) < 5:
                            continue
                        channel, kind = struct.unpack_from('!IB', message.data)
                        ws = channels.get(channel)
                        if ws and not ws.closed:
                            if kind == 1:
                                await ws.send_bytes(message.data[5:])
                            elif kind == 2:
                                await ws.send_str(message.data[5:].decode())
                    elif message.type == aiohttp.WSMsgType.TEXT:
                        try:
                            item = json.loads(message.data)
                        except (ValueError, TypeError):
                            continue
                        if not isinstance(item, dict):
                            continue
                        if item.get('type') == 'shutdown':
                            return False
                        if item.get('type') == 'ws_close':
                            channel = item.get('channel')
                            if not isinstance(channel, int):
                                continue
                            ws = channels.pop(channel, None)
                            if ws:
                                await ws.close()
                        elif item.get('type') in {'http', 'ws_open'}:
                            if len(tasks) >= 64:
                                await tunnel.send_json({'id': item['id'], 'error': 'Naimei relay request limit'})
                                continue
                            task = asyncio.create_task(request(item))
                            tasks.add(task)
                            task.add_done_callback(tasks.discard)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                for ws in list(channels.values()):
                    await ws.close()


async def main():
    config = json.loads((STATE / 'config.json').read_text('utf-8-sig'))
    while True:
        try:
            if await connection(config) is False:
                return
        except (OSError, aiohttp.ClientError, asyncio.TimeoutError) as error:
            (STATE / 'status.json').write_text(json.dumps({'connected': False, 'updated': time.time(), 'error': str(error)}), 'utf-8')
        await asyncio.sleep(2)


if __name__ == '__main__':
    asyncio.run(main())
