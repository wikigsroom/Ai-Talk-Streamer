import test from 'node:test';
import assert from 'node:assert/strict';
import { StreamBridge } from '../backend/dsh-bridge/server.mjs';

test('manual echo reaches the avatar without an LLM channel or model call', async () => {
  const sent = [], failed = [];
  const request = { request_id: 'offline-echo', mode: 'echo', runtime_epoch: 1, generation: 2 };
  const text = '你好，我是奶妹。';
  const bridge = {
    controllers: new Map(),
    policy: { conversation: { model_timeout_ms: 1000, final_speech_max_chars: 160 } },
    channel: { snapshot() { throw Error('CHANNEL_NOT_CONFIGURED'); } },
    memory: { context() { throw Error('Offline echo must not construct LLM context'); } },
    host: { generate() { throw Error('Offline echo must not invoke a model'); } },
    state: {
      input: () => ({ text }), matches: () => true,
      textReady: (id, speech, epoch, generation) => ({ request_id: id, text: speech, runtime_epoch: epoch, generation }),
      fail: (...args) => failed.push(args),
    },
    mediaCommand: async (...args) => sent.push(args),
  };
  await StreamBridge.prototype.processRequest.call(bridge, request);
  assert.deepEqual(failed, []);
  assert.equal(sent.length, 1);
  assert.equal(sent[0][0], 'speak');
  assert.equal(sent[0][1].text, text);
  assert.equal(bridge.controllers.size, 0);
});
