import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

// Exercise the real bridge at the native boundary: input leases, game-thread
// execution, stack restoration and actual capture demand. No game writes.
function fixture({aliasSwap=false,engineReady=true}={}) {
  let now=0,next=10000,top=4,loadError=false;
  const memory=new Map([[52,60],[60,engineReady?70:0],[94,80]]),hooks=[],timers=[],messages=[],calls=[];
  class Pointer {
    constructor(value){this.value=Number(value);}
    add(value){return new Pointer(this.value+value);}
    readPointer(){return new Pointer(memory.get(this.value)||0);}
    readU32(){return memory.get(this.value)||0;}
    readS32(){return this.readU32();}
    writeU32(value){memory.set(this.value,value);}
    writeU8(value){memory.set(this.value,value);}
    readS64(){return {toNumber:()=>memory.get(this.value)||0};}
    readUtf8String(){return memory.get(this.value)||'';}
    readByteArray(size){return new ArrayBuffer(size);}
    toInt32(){return this.value;}
    isNull(){return this.value===0;}
    toString(){return String(this.value);}
    replace(value){this.value=value.value;}
  }
  const ptr=value=>new Pointer(value);
  const functions=new Map(),addresses=new Map();
  function address(name) {
    if(aliasSwap&&name==='wglSwapBuffers')name='SwapBuffers';
    if(!addresses.has(name))addresses.set(name,ptr(next++));
    return addresses.get(name);
  }
  function native(name,fn){functions.set(address(name).toString(),fn);}
  function module(name){return {name,getExportByName:address,findExportByName:address};}
  native('QueryPerformanceFrequency',out=>{out.writeU32(1000000);return true;});
  native('QueryPerformanceCounter',out=>{out.writeU32(now*1000);return true;});
  native('GetWindowThreadProcessId',(_window,out)=>out.writeU32(123));
  native('PostMessageW',(_window,message,key)=>{messages.push({message,key});return true;});
  native('lua_gettop',()=>top);
  native('lua_settop',(_state,value)=>{top=value;calls.push('restore');});
  native('luaL_loadstring',()=>{top++;calls.push('load');if(loadError)throw new Error('native load failed');return 0;});
  native('lua_pcallk',()=>{calls.push('call');return 0;});
  native('lua_tolstring',()=>{const result=ptr(next++);memory.set(result.value,'actual result');return result;});
  native('wglGetCurrentContext',()=>ptr(1));
  native('glGetIntegerv',(_flag,out)=>{for(const [i,value] of [0,0,640,480].entries())memory.set(out.value+i*4,value);});
  native('glReadPixels',()=>calls.push('pixels'));
  const context={Map,Set,Promise,Date:{now:()=>now},ptr,rpc:{exports:{}},send:()=>{},
    Memory:{alloc:()=>ptr(next+=32),allocUtf8String:source=>{const out=ptr(next+=32);memory.set(out.value,source);return out;},
      scanSync:()=>[{address:ptr(50)}]},
    NativeFunction:function(at){return functions.get(at.toString())||(()=>0);},
    Module:{load:module},Process:{id:123,mainModule:{base:ptr(1000),size:2000,path:'C:/game/isaac-ng.exe'},
      attachModuleObserver:observer=>{for(const name of ['Lua5.3.3f.dll','gdi32.dll','opengl32.dll'])observer.onAdded(module(name));}},
    Interceptor:{attach:(at,callbacks)=>{const hook={at:at.toString(),callbacks,active:true,detach(){this.active=false;}};hooks.push(hook);return hook;}},
    setTimeout:(fn,delay)=>timers.push({fn,due:now+delay})};
  vm.runInNewContext(fs.readFileSync(new URL('../../isaac-agent/native_bridge.js',import.meta.url),'utf8'),context);
  const tick=amount=>{now+=amount;for(const timer of [...timers])if(timer.due<=now){timers.splice(timers.indexOf(timer),1);timer.fn();}};
  const invoke=(name,args=[],result=ptr(1))=>{
    for(const hook of hooks.filter(h=>h.active&&h.at===address(name).toString())){
      const state={};hook.callbacks.onEnter?.call(state,args);hook.callbacks.onLeave?.call(state,result);
    }
    return result;
  };
  return {api:context.rpc.exports,hooks,calls,messages,tick,invoke,ptr,
    makeEngineReady:()=>memory.set(60,70),failLoad:()=>{loadError=true;},getTop:()=>top,
    active:name=>hooks.filter(h=>h.active&&h.at===address(name).toString()).length};
}

test('ordinary gameplay has no keyboard or per-Lua-call JavaScript hooks',()=>{
  const f=fixture();
  for(const name of ['GetAsyncKeyState','GetKeyState','GetKeyboardState','lua_pcallk'])assert.equal(f.active(name),0);
  assert.equal(f.api.status().performance.keyboard_hooks,0);
});

test('bounded ordinary menu key affects only its lease, then removes all input hooks',()=>{
  const f=fixture();
  f.api.key('escape','1');
  assert.equal(f.api.status().performance.keyboard_hooks,3);
  assert.equal(f.invoke('GetAsyncKeyState',[f.ptr(27)],f.ptr(0)).toInt32(),0x8000);
  assert.equal(f.invoke('GetKeyState',[f.ptr(13)],f.ptr(0)).toInt32(),0);
  f.tick(141);
  assert.equal(f.invoke('GetKeyState',[f.ptr(27)],f.ptr(0)).toInt32(),0);
  f.tick(4);
  assert.equal(f.api.status().performance.keyboard_hooks,0);
  assert.equal(f.messages.filter(x=>x.message===0x101).length,1);
  assert.throws(()=>f.api.key('shoot','1'),/ordinary/);
});

test('an old release timer cannot release a newer press of the same key',()=>{
  const f=fixture();f.api.key('enter','1');f.tick(100);f.api.key('enter','1');f.tick(45);
  assert.equal(f.messages.filter(x=>x.message===0x101).length,0);
  assert.equal(f.api.status().performance.keyboard_leases,1);
  f.tick(100);
  assert.equal(f.messages.filter(x=>x.message===0x101).length,1);
  assert.equal(f.api.status().performance.keyboard_hooks,0);
});

test('Lua request waits for game render, discovers a late engine and restores its stack',async()=>{
  const f=fixture({engineReady:false});const result=f.api.evaluate('trusted source');
  assert.equal(f.calls.length,0);f.invoke('SwapBuffers');assert.equal(f.calls.length,0);
  f.makeEngineReady();f.invoke('SwapBuffers');assert.equal(await result,'actual result');
  assert.equal(f.getTop(),4);assert.deepEqual(f.calls,['load','call','restore']);
});

test('expired or failed Lua requests cannot execute later or leak stack entries',async()=>{
  const f=fixture();const expired=f.api.evaluate('stale');const rejection=assert.rejects(expired,/expired/);
  f.tick(3001);f.invoke('SwapBuffers');await rejection;assert.equal(f.calls.length,0);
  f.failLoad();const failed=f.api.evaluate('trusted');const failure=assert.rejects(failed,/load failed/);
  f.invoke('SwapBuffers');await failure;assert.equal(f.getTop(),4);
});

test('render timing deduplicates API aliases and never captures pixels without a request',async()=>{
  const f=fixture({aliasSwap:true});assert.equal(f.active('SwapBuffers'),1);
  for(let i=0;i<750;i++){f.tick(1000/60);f.invoke('SwapBuffers');}
  const render=f.api.status().performance.render['gdi32.dll'];
  assert.equal(render.window_frames,600);assert.ok(Math.abs(render.fps-60)<.01);
  assert.equal(f.calls.includes('pixels'),false);
  const capture=f.api.capture('one-shot');f.invoke('SwapBuffers');await capture;
  assert.equal(f.calls.filter(x=>x==='pixels').length,1);
});
