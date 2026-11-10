import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {OriginalIsaacChannel} from '../../../backend/dsh-bridge/channel.mjs';

test('Isaac inherits only the approved private channel and public settings never expose its URL or key',()=>{
 const root=mkdtempSync(join(tmpdir(),'issac-channel-'));
 try{
  mkdirSync(join(root,'private/issac'),{recursive:true});mkdirSync(join(root,'configs'));
  writeFileSync(join(root,'configs/channel.env'),'AVATAR_LLM_MODEL=foreign');
  const file=join(root,'private/issac/channel.env');
  const config=(model='gpt-6.1-sol',protocol='responses')=>'AVATAR_LLM_BASE_URL=https://saved.example.invalid/v1\nAVATAR_LLM_MODEL='+model+'\nAVATAR_LLM_PROTOCOL='+protocol+'\nAVATAR_LLM_API_KEY=private-test-key';
  writeFileSync(file,config());const channel=new OriginalIsaacChannel(root),snapshot=channel.snapshot();
  assert.equal(snapshot.model,'gpt-6.1-sol');assert.equal(snapshot.protocol,'responses');assert.equal(snapshot.getApiKey(),'private-test-key');
  for(const value of [snapshot,channel.settings()]){
    assert.ok(!JSON.stringify(value).includes('private-test-key'));
  }
  assert.ok(!JSON.stringify(channel.settings()).includes('saved.example.invalid'));
  assert.equal(channel.settings().editable,false);assert.throws(()=>channel.save({model:'other'}),/INHERITED/);
  for(const [model,protocol] of [['other','responses'],['gpt-6.1-sol','chat_completions']]){
    writeFileSync(file,config(model,protocol));assert.throws(()=>channel.snapshot(),/ORIGINAL_GPT_6_1_SOL_RESPONSES/);
  }
 }finally{rmSync(root,{recursive:true,force:true});}
});
