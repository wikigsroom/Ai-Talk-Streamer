import test from 'node:test';
import assert from 'node:assert/strict';
import { canonical } from '../backend/dsh-bridge/channel.mjs';
import { estimateModelContext, MAX_MODEL_REPLAY_CHARACTERS } from '../backend/dsh-bridge/host.mjs';

const options = { provider: 'studio-fixture', model: 'fixture', protocol: 'responses', maxTokens: 512 };
const signedMessage = (size = 9000) => ({ role: 'assistant', content: [{ type: 'tool-call', name: 'game_check_action', arguments: '{"data":"{}"}' }],
  source: { kind: 'model', provider: options.provider, model: options.model, replayState: {
    response: { api: 'openai-responses' }, blocks: [{ type: 'reasoning', thinkingSignature: 'opaque-fixture'.repeat(size).slice(0, size) }, { type: 'tool-call' }] } } });

test('opaque native Responses replay reserves bounded reasoning tokens without changing the SDK payload', () => {
  const messages = [{ role: 'user', content: [{ type: 'text', text: '实际游戏观测' }] }, signedMessage()];
  const before = structuredClone(messages), estimate = estimateModelContext(messages, options);
  assert.equal(estimate.replay_transport_characters, 9000);
  assert.equal(estimate.replay_token_reserve, 512);
  assert.equal(estimate.replay_transport_within_limit, true);
  const plain = structuredClone(messages); delete plain[1].source.replayState.blocks[0].thinkingSignature;
  assert.equal(estimate.estimated_input_tokens, Math.ceil(canonical(plain).length / 2) + 512);
  assert(estimate.estimated_input_tokens < Math.ceil(canonical(messages).length / 2));
  assert.deepEqual(messages, before, 'encrypted continuation must be forwarded byte for byte');
  assert.equal(estimateModelContext([...messages, signedMessage()], options).replay_token_reserve, 1024);
});

test('user text, tool results, foreign signatures and plaintext reasoning cannot bypass the context budget', () => {
  for (const change of [m => m.role = 'user', m => m.role = 'tool', m => m.source.kind = 'user',
    m => m.source.provider = 'other', m => m.source.model = 'other', m => m.source.replayState.response.api = 'other',
    m => m.source.replayState.blocks[0].type = 'text']) {
    const message = signedMessage(15000); change(message);
    const result = estimateModelContext([message], options);
    assert.equal(result.replay_transport_characters, 0);
    assert.equal(result.estimated_input_tokens, Math.ceil(canonical([message]).length / 2));
    assert(result.estimated_input_tokens > 6000);
  }
  const message = signedMessage(); message.content.push({ type: 'reasoning', text: '明文仍须计费'.repeat(4000) });
  assert(estimateModelContext([message], options).estimated_input_tokens > 6000);
  assert(estimateModelContext([{ role: 'tool', content: [{ type: 'text', text: JSON.stringify(signedMessage(15000)) }] }], options).estimated_input_tokens > 6000);
  assert.equal(estimateModelContext([signedMessage()], { ...options, protocol: 'chat_completions' }).replay_transport_characters, 0);
});

test('encrypted replay has an independent transport ceiling and cannot hide arbitrary data', () => {
  const estimate = estimateModelContext([signedMessage(MAX_MODEL_REPLAY_CHARACTERS + 1)], options);
  assert.equal(estimate.replay_transport_within_limit, false);
  const message = signedMessage(); message.source.replayState.unrecognized = 'must-count'.repeat(1500);
  assert(estimateModelContext([message], options).estimated_input_tokens > 6000);
});
