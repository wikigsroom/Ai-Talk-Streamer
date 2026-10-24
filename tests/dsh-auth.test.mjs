import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {StateStore} from '../backend/memory/store.mjs';
import {Auth} from '../backend/dsh-bridge/auth.mjs';
import {StreamState} from '../backend/dsh-bridge/state.mjs';
import {loadPolicy} from '../backend/dsh-bridge/policy.mjs';

function fixture(){const parent=resolve('../outputs/dsh-humanity/unit');mkdirSync(parent,{recursive:true});const root=mkdtempSync(join(parent,'auth-')),db=new StateStore(':memory:');const state=new StreamState(db,loadPolicy(root),'test');return {db,state,auth:new Auth(root,db,state)};}
const headers=cookie=>({cookie:cookie.split(';')[0]});
test('A18: equal viewer labels receive distinct stable partitions; anonymous identity changes between broadcasts',()=>{
 const f=fixture();try{
  const a=f.auth.invite('同名'),b=f.auth.invite('同名');assert.notEqual(a.viewer_id,b.viewer_id);
  const first=f.auth.login(a.invitation_token),second=f.auth.login(a.invitation_token);assert.equal(first.principal.viewer_id,second.principal.viewer_id);
  const op=f.auth.resolve({authorization:'Bearer '+f.auth.operatorKey});
  const anonymous=f.auth.anonymous({}),one=f.state.createBroadcast(op),afterStart=f.auth.anonymous(headers(anonymous.cookie));
  assert.notEqual(anonymous.principal.viewer_id,afterStart.principal.viewer_id);assert.ok(afterStart.principal.viewer_id.includes(one.broadcast_id));
  f.state.end(op);f.state.tick();f.state.createBroadcast(op);const next=f.auth.anonymous(headers(afterStart.cookie));assert.notEqual(next.principal.viewer_id,afterStart.principal.viewer_id);
  assert.equal(f.auth.anonymous(headers(first.cookie)).principal.viewer_id,a.viewer_id);
 }finally{f.db.close()}
});
test('A13/A40: OBS credential is scoped and cannot log in as an operator or an ordinary invited viewer',()=>{
 const f=fixture();try{const credential=f.auth.playbackCredential(),h={authorization:'Bearer '+credential.token};
  const p=f.auth.resolve(h);assert.equal(p.role,'playback');assert.equal(p.consumer_id,credential.consumer_id);
  assert.throws(()=>f.auth.require(h,'operator'),/OPERATOR_REQUIRED/);assert.throws(()=>f.auth.login(credential.token),/LOGIN_INVALID/);
  assert.equal(f.auth.anonymous(h).principal.role,'viewer');assert.equal(f.auth.resolve({authorization:'Bearer '+f.auth.mediaKey}).role,'media');
 }finally{f.db.close()}
});
