import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,existsSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {createServer} from 'node:http';
import {StateStore} from '../backend/memory/store.mjs';
import {Auth} from '../backend/dsh-bridge/auth.mjs';
import {StreamState} from '../backend/dsh-bridge/state.mjs';
import {StreamBridge} from '../backend/dsh-bridge/server.mjs';
import {loadPolicy} from '../backend/dsh-bridge/policy.mjs';
function fixture(){const parent=resolve('../outputs/dsh-humanity/unit');mkdirSync(parent,{recursive:true});const root=mkdtempSync(join(parent,'open-access-')),db=new StateStore(':memory:');const state=new StreamState(db,loadPolicy(root),'test');return {root,db,state,auth:new Auth(root,db,state)};}

test('open access: no keys, cookies, role gates, invitation secrets or OBS credentials',()=>{
 const f=fixture();try{
  const direct=f.auth.resolve({});assert.equal(direct.authentication_required,false);assert.equal(direct.access_mode,'open');
  assert.deepEqual(f.auth.resolve({authorization:'Bearer wrong',cookie:'dsh_session=obsolete'}),direct);
  assert.deepEqual(f.auth.require({},'media'),direct);assert.deepEqual(f.auth.require({},'viewer'),direct);
  assert.deepEqual(f.auth.login(),{principal:direct});assert.deepEqual(f.auth.login('wrong'),{principal:direct});
  assert.deepEqual(f.auth.anonymous({}),{principal:direct});
  for(const name of ['dsh-operator.token','dsh-media.token'])assert.equal(existsSync(join(f.root,'configs',name)),false);
  const a=f.auth.invite('同名'),b=f.auth.invite('同名');assert.notEqual(a.viewer_id,b.viewer_id);assert.equal(a.invitation_token,undefined);
  const obs=f.auth.playbackCredential();assert.ok(obs.consumer_id);assert.equal(obs.token,undefined);
 }finally{f.db.close()}
});

test('open access: actual HTTP control, memory, persona, request reads and cross-origin preflight need no authentication',async()=>{
 const f=fixture(),bridge=Object.create(StreamBridge.prototype);
 Object.assign(bridge,{db:f.db,state:f.state,auth:f.auth,ready:true,administration:{locked:false},host:{ready:true,port:{readPersona:()=>({version:'test',document:{identityCard:{name:'林知夏'}}})}},refreshMedia:async()=>({tts_ready:true,avatar_ready:true}),health:()=>({persona_injection_ready:true}),tick:async()=>{}});
 const server=createServer((req,res)=>bridge.handle(req,res));
 try{
  await new Promise(done=>server.listen(0,'127.0.0.1',done));const base='http://127.0.0.1:'+server.address().port;
  const call=async(route,body,extra={})=>{
   const response=await fetch(base+route,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json',Origin:'http://unrestricted.example',...extra},body:body===undefined?undefined:JSON.stringify(body)});
   const value=await response.json();assert.ok(response.ok,route+':'+value.error);assert.equal(response.headers.get('set-cookie'),null);return value;
  };
  assert.equal((await call('/api/dsh/whoami')).authentication_required,false);
  assert.equal((await call('/api/dsh/session',{})).studio.auto_start,true);
  assert.equal((await call('/api/dsh/login',{token:'wrong'})).authentication_required,false);
  await call('/api/dsh/logout',{});
  const preflight=await fetch(base+'/api/dsh/memory',{method:'OPTIONS',headers:{Origin:'http://unrestricted.example','Access-Control-Request-Method':'POST'}});assert.equal(preflight.status,204);assert.equal(preflight.headers.get('access-control-allow-origin'),'*');
  const b=await call('/api/dsh/broadcast/start',{}),lease=await call('/api/dsh/playback/claim',{broadcast_id:b.broadcast_id,consumer_id:'open-test-player'});
  assert.ok(lease.lease_id);const current=f.state.current();await call('/api/dsh/broadcast/ready',{broadcast_id:b.broadcast_id,expected_revision:current.revision,mode:'echo'});
  const request=await call('/api/dsh/requests',{mode:'echo',text:'不需要登录。',idempotency_key:'open-test-request'});
  assert.equal((await call('/api/dsh/requests/'+request.request_id,undefined,{Authorization:'Bearer invalid'})).request_id,request.request_id);
  assert.deepEqual((await call('/api/dsh/memory')).entries,[]);assert.equal((await call('/api/dsh/persona')).document.identityCard.name,'林知夏');
 }finally{const closing=new Promise(done=>server.close(done));server.closeAllConnections();await closing;f.db.close()}
});
