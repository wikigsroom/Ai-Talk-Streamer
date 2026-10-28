"""Read a user's Bilibili room with pinned MIT-licensed blivedm; emit NDJSON.

Configuration arrives on stdin so platform cookies never enter process arguments.
The caller owns this process. Stop it by sending {"stop":true} or closing stdin.
"""
import asyncio
import hashlib
import http.cookies
import json
import logging
import sys
import time

import aiohttp
import blivedm


def emit(value):
    print(json.dumps(value, ensure_ascii=False, separators=(',', ':')), flush=True)


class Handler(blivedm.BaseHandler):
    def _on_heartbeat(self, client, message):
        emit({'kind': 'state', 'state': 'CONNECTED'})

    def _on_danmaku(self, client, message):
        key = hashlib.sha256(json.dumps([client.room_id, message.timestamp, message.rnd,
                                       str(message.uid), message.msg], ensure_ascii=False).encode()).hexdigest()
        emit({'kind': 'event', 'room_id': str(client.room_id), 'event': {
            'type': 'comment', 'event_id': key, 'room_id': str(client.room_id),
            'user_id': str(message.uid), 'nickname': message.uname,
            'text': message.msg, 'timestamp': message.timestamp or int(time.time()*1000)}})
        emit({'kind': 'state', 'state': 'RECEIVING'})

    def _on_gift(self, client, message):
        key = hashlib.sha256(json.dumps([client.room_id, getattr(message, 'tid', ''),
                                       message.uid, message.gift_name, message.num,
                                       getattr(message, 'timestamp', 0)]).encode()).hexdigest()
        emit({'kind': 'event', 'room_id': str(client.room_id), 'event': {
            'type': 'gift', 'event_id': key, 'room_id': str(client.room_id),
            'user_id': str(message.uid), 'nickname': message.uname,
            'gift_name': message.gift_name, 'gift_count': message.num,
            'timestamp': getattr(message, 'timestamp', 0) or int(time.time()*1000)}})

    def _on_super_chat(self, client, message):
        emit({'kind': 'event', 'room_id': str(client.room_id), 'event': {
            'type': 'comment', 'event_id': 'sc-'+str(message.id), 'room_id': str(client.room_id),
            'user_id': str(message.uid), 'nickname': message.uname,
            'text': message.message, 'notice_kind': 'superchat', 'timestamp': int(time.time()*1000)}})


async def main():
    config = json.loads(sys.stdin.readline())
    jar = aiohttp.CookieJar()
    if config.get('cookie'):
        cookies = http.cookies.SimpleCookie(config['cookie'])
        for value in cookies.values(): value['domain'] = 'bilibili.com'
        jar.update_cookies(cookies)
    async with aiohttp.ClientSession(cookie_jar=jar, trust_env=True) as session:
        client = blivedm.BLiveClient(int(config['room_id']), session=session)
        client.set_handler(Handler())
        client.start()
        emit({'kind': 'state', 'state': 'CONNECTING'})

        async def stop_input():
            while True:
                line = await asyncio.to_thread(sys.stdin.readline)
                if not line or json.loads(line).get('stop'):
                    client.stop()
                    return

        task = asyncio.create_task(stop_input())
        try:
            await client.join()
        finally:
            await client.stop_and_close()
            task.cancel()
            emit({'kind': 'state', 'state': 'STOPPED'})


if __name__ == '__main__':
    logging.basicConfig(level=logging.ERROR, stream=sys.stderr)
    try:
        asyncio.run(main())
    except Exception:
        emit({'kind': 'state', 'state': 'ERROR', 'error': 'BLIVEDM_RUNTIME_FAILED'})
        raise SystemExit(1)
