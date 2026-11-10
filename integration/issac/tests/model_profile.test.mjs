import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,writeFileSync,rmSync} from 'node:fs';
import {join} from 'node:path';
import {loadIsaacModel} from '../../../backend/dsh-bridge/isaac-model.mjs';
import {loadPolicy} from '../../../backend/dsh-bridge/policy.mjs';

test('official Flash model and game policy admit its 1M window with explicit output and tool reserves',()=>{
  const root=process.cwd(),model=loadIsaacModel(root),policy=loadPolicy(root,'configs/issac/bridge-policy.json');
  assert.equal(model.context_window_tokens,1000000);
  assert.equal(model.max_input_estimated_tokens+model.max_output_tokens+model.context_reserve_tokens,model.context_window_tokens);
  assert.equal(policy.conversation.game_context_max_estimated_tokens,model.max_input_estimated_tokens);
  assert.equal(policy.conversation.context_max_estimated_tokens,model.max_input_estimated_tokens);
  mkdirSync(join(root,'state'),{recursive:true});const folder=mkdtempSync(join(root,'state/issac-context-policy-'));
  try{
    const path=join(folder,'policy.json');
    for(const budget of [30000,100000,model.max_input_estimated_tokens]){
      const candidate=structuredClone(policy);candidate.conversation.game_context_max_estimated_tokens=budget;
      writeFileSync(path,JSON.stringify(candidate));assert.equal(loadPolicy(root,path).conversation.game_context_max_estimated_tokens,budget);
    }
    for(const budget of [model.max_input_estimated_tokens+1,model.context_window_tokens]){
      const candidate=structuredClone(policy);candidate.conversation.game_context_max_estimated_tokens=budget;
      writeFileSync(path,JSON.stringify(candidate));assert.throws(()=>loadPolicy(root,path),/CONFIG_GAME_CONTEXT_SCOPE/);
    }
    const candidate=structuredClone(policy);candidate.conversation.context_max_estimated_tokens=model.context_window_tokens;
    writeFileSync(path,JSON.stringify(candidate));assert.throws(()=>loadPolicy(root,path),/CONFIG_CONVERSATION_RANGE/);
  }finally{rmSync(folder,{recursive:true,force:true});}
});
