"""Offline checks against the installed pinned blivedm models and dispatcher.

Run with runtime/platforms/Scripts/python.exe. No client/network is started.
"""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

from blivedm.models import web

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('checked_platform_blivedm', ROOT / 'scripts/platform_blivedm.py')
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


def capture():
    records = []
    collector.emit = records.append
    return records, collector.Handler(), SimpleNamespace(room_id=100)


def vectors(timestamp):
    records, handler, client = capture()
    handler._on_danmaku(client, web.DanmakuMessage(timestamp=timestamp, rnd=1, uid=9, uname='真实SDK夹具', msg='[笑]', admin=1, privilege_type=3, dm_type=1,
        emoticon_options=json.dumps({'url': 'https://i0.hdslb.com/bfs/emote/fixture.png'})))
    handler._on_gift(client, web.GiftMessage(uid=9, uname='真实SDK夹具', gift_name='小花', num=3, timestamp=timestamp // 1000, tid='gift-known'))
    handler._on_gift(client, web.GiftMessage(uid=9, uname='真实SDK夹具', gift_name='小花', timestamp=timestamp // 1000, tid='gift-unknown'))
    handler._on_super_chat(client, web.SuperChatMessage(id=9223372036854775801, uid=9, uname='真实SDK夹具', message='SC原文', price=30, start_time=timestamp // 1000, guard_level=3))
    handler.handle(client, {'cmd':'SUPER_CHAT_MESSAGE_DELETE', 'data':{'ids':[9223372036854775801]}})
    return [value['event'] for value in records if value['kind'] == 'event']


class CollectorProtocolChecks(unittest.TestCase):
    def test_danmaku_preserves_roles_original_time_and_emote_without_fetching(self):
        record = vectors(1793350000000)[0]
        self.assertEqual(record['timestamp'], 1793350000000)
        self.assertEqual((record['admin'], record['guard_level']), (1, 3))
        self.assertEqual(record['emoji_url'], 'https://i0.hdslb.com/bfs/emote/fixture.png')
        self.assertEqual(record['text'], '[笑]')

    def test_missing_sdk_gift_count_is_not_fabricated_as_one(self):
        records = vectors(1793350000000)
        self.assertEqual(records[1]['gift_count'], 3)
        self.assertEqual(records[2]['gift_count'], 0)  # JS treats SDK default zero as invalid/unknown.

    def test_superchat_preserves_64_bit_id_and_original_start_not_local_receive_time(self):
        sc = vectors(1793350000000)[3]
        self.assertEqual(sc['message_id'], '9223372036854775801')
        self.assertEqual(sc['event_id'], 'sc-9223372036854775801')
        self.assertEqual(sc['timestamp'], 1793350000)
        self.assertEqual(sc['sc_amount_yuan'], 30)

    def test_installed_sdk_dispatches_delete_to_our_handler_and_preserves_string_id(self):
        deleted = vectors(1793350000000)[4]
        self.assertEqual(deleted['deletion_target_ids'], ['9223372036854775801'])
        self.assertEqual(deleted['type'], 'delete')

    def test_delete_chunking_is_bounded_and_replay_has_stable_ids(self):
        records, handler, client = capture()
        message = web.SuperChatDeleteMessage(ids=list(range(1, 206)))
        handler._on_super_chat_delete(client, message)
        ids = [value['event']['event_id'] for value in records]
        self.assertEqual([len(value['event']['deletion_target_ids']) for value in records], [100, 100, 5])
        records.clear()
        handler._on_super_chat_delete(client, message)
        self.assertEqual([value['event']['event_id'] for value in records], ids)

    def test_malformed_emote_metadata_does_not_execute_or_crash(self):
        self.assertEqual(collector.emoji_options(SimpleNamespace(emoticon_options='not-json')), {})
        self.assertEqual(collector.emoji_options(SimpleNamespace(emoticon_options='[1,2]')), {})


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--vectors':
        print(json.dumps(vectors(int(sys.argv[2])), ensure_ascii=False))
    else:
        unittest.main(verbosity=2)
