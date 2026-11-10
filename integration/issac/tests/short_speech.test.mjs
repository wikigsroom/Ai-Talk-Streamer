import test from 'node:test';
import assert from 'node:assert/strict';
import {SpokenHistory,shortSpeech,speechSimilarity} from '../../../backend/dsh-bridge/short-speech.mjs';
import {compactContinuous} from '../../../backend/dsh-bridge/continuous-context.mjs';

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
test('continuous compaction is a durable replacement citing every old surface node',async()=>{
  let appended;const nodes=[1,3,7,9],history=[{input:'旧房间',reply:'先补血。'}];
  const agent={runMaintenance:async work=>work(),session:{surface:{nodes},append:(...args)=>{appended=args;}}};
  await compactContinuous(agent,{createUserMessage:v=>v},history);
  assert.equal(appended[0],'user/message');assert.match(appended[1].content[0].text,/旧房间/);
  assert.deepEqual(appended[2],{surfaceOp:{op:'replace',startSeq:1,endSeq:9},sourceEventSeqs:nodes});
  assert.deepEqual(nodes,[1,3,7,9]);
});
