import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,writeFileSync,readFileSync,rmSync,unlinkSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {OriginalIsaacChannel} from '../../../backend/dsh-bridge/channel.mjs';

test('Isaac pins the user-approved GPT 6 Luna API, capacity and private key without saved-channel fallback',()=>{
 const root=mkdtempSync(join(tmpdir(),'issac-channel-'));
 try{
  mkdirSync(join(root,'private/issac'),{recursive:true});mkdirSync(join(root,'configs/issac'),{recursive:true});
  writeFileSync(join(root,'configs/issac/core-model.json'),readFileSync('configs/issac/core-model.json'));
  writeFileSync(join(root,'configs/channel.env'),'AVATAR_LLM_MODEL=foreign');
  const file=join(root,'private/issac/channel.env');
  const config=(model='gpt-6-luna',protocol='responses',base='http://43.160.221.28:9841/v1')=>'AVATAR_LLM_BASE_URL='+base+'\nAVATAR_LLM_MODEL='+model+'\nAVATAR_LLM_PROTOCOL='+protocol+'\nAVATAR_LLM_API_KEY=private-test-key';
  writeFileSync(file,config());const channel=new OriginalIsaacChannel(root),snapshot=channel.snapshot();
  assert.equal(snapshot.model,'gpt-6-luna');assert.equal(snapshot.protocol,'responses');assert.equal(snapshot.getApiKey(),'private-test-key');
  assert.equal(snapshot.contextWindow,1000000);assert.equal(snapshot.maxSerializedMessageBytes,32*1024*1024);
  assert.equal(channel.publicInfo().max_input_estimated_tokens,989760);
  assert.equal(snapshot.source,'issac_user_pinned_luna_api');
  for(const value of [snapshot,channel.settings()]){
    assert.ok(!JSON.stringify(value).includes('private-test-key'));
  }
  assert.ok(!JSON.stringify(channel.settings()).includes('http://43.160.221.28:9841/v1'));
  assert.equal(channel.settings().editable,false);assert.throws(()=>channel.save({model:'other'}),/PRIVATE_CONFIGURATION_REQUIRED/);
  for(const [model,protocol,base] of [['deepseek-flash','responses'],['gpt-6.1-sol','responses'],['other','responses'],['gpt-6-luna','chat_completions'],['gpt-6-luna','responses','https://saved.example.invalid/v1'],['gpt-6-luna','responses','http://api.deepseek.com']]){
    writeFileSync(file,config(model,protocol,base));assert.throws(()=>channel.snapshot(),/ISAAC_APPROVED_CHANNEL_REQUIRED/);
  }
  unlinkSync(file);assert.throws(()=>channel.snapshot(),/CHANNEL_NOT_CONFIGURED/);
 }finally{rmSync(root,{recursive:true,force:true});}
});
