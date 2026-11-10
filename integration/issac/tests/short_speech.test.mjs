import test from 'node:test';
import assert from 'node:assert/strict';
import {SpokenHistory,shortSpeech,speechSimilarity} from '../../../backend/dsh-bridge/short-speech.mjs';
import {compactContinuous,messageBudget} from '../../../backend/dsh-bridge/continuous-context.mjs';

test('opaque provider replay stays intact and has a separate bounded transport size',()=>{
  const messages=[{role:'assistant',content:[{type:'text',text:'先核对首领。'}],
    source:{kind:'model',replayState:{opaque:'x'.repeat(600000)}}}];
  const copy=structuredClone(messages),budget=messageBudget(messages);
  assert.ok(budget.estimated_input_tokens<1000);
  assert.ok(budget.serialized_message_bytes>512*1024);
  assert.deepEqual(messages,copy);
});

test('large visible game and tool results still exceed the semantic context budget',()=>{
  for(const role of ['user','tool']){
    const messages=[{role,content:[{type:'text',text:'x'.repeat(50000)}],toolCallId:'real-tool-id'}];
    assert.ok(messageBudget(messages).estimated_input_tokens>24000);
  }
});

test('speech cap counts punctuation and preserves Unicode code points',()=>{
  for(const text of ['这个道具能补血，拿上以后再往前探索。','😀'.repeat(20),'先拿道具。然后看看还能找到什么有用的东西。']){
    const result=shortSpeech(text);assert.ok(Array.from(result).length<=15);assert.ok(!/[\uD800-\uDBFF]$/.test(result));
  }
});
test('only actual completed speech becomes last_spoken; queued and near repeats are blocked',()=>{
  const ledger=new SpokenHistory();assert.ok(ledger.reserve('a','先补血，再往前走。'));
  assert.equal(ledger.context().last_spoken,null);
  assert.equal(ledger.reserve('b','先补血再往前走！'),false);
  ledger.release('a');assert.ok(ledger.reserve('c','先补血，再往前走。'));
  ledger.completed('c','先补血，再往前走。');assert.equal(ledger.context().last_spoken,'先补血，再往前走。');
  assert.ok(speechSimilarity('先拿上钥匙再走。','我先拿上钥匙再走。')>=.78);
  assert.equal(ledger.reserve('d','先补血，再往前走。'),false);
  assert.ok(ledger.reserve('e','这首领冲得真快。'));
});
test('continuous compaction retains the protected system head and cites every old conversation node',async()=>{
  let appended;const nodes=[0,1,3,7,9],history=[{input:'旧房间',reply:'先补血。'}];
  const agent={runMaintenance:async work=>work(),session:{surface:{nodes},append:(...args)=>{appended=args;}}};
  await compactContinuous(agent,{createUserMessage:v=>v},history);
  assert.equal(appended[0],'user/message');assert.match(appended[1].content[0].text,/旧房间/);
  assert.deepEqual(appended[2],{surfaceOp:{op:'replace',startSeq:1,endSeq:9},sourceEventSeqs:[1,3,7,9]});
  assert.deepEqual(nodes,[0,1,3,7,9]);
});
