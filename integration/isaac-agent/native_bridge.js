// Isaac-only native Lua bridge. Never changes achievement, save, or gameplay flags.
// Work executes at the original game Lua/render boundaries; restore the Lua stack.
let luaState = null;
let api = null;
let executing = false;
let pending = [];
let installed = [];
let counters = { calls: 0, failures: 0 };
let graphics = null;
let frameRequests = [];
let engineSlot = null;
let luaNativeModule = null;
const luaNative = Object.fromEntries(['state','executing','pending','calls','javascript'].map(name=>[name,Memory.alloc(8)]));
luaNative.state.writePointer(ptr(0));
for(const name of ['executing','pending','calls','javascript'])luaNative[name].writeU32(0);
const luaNativeLeave = new NativeCallback(()=>{drain();},'void',[]);
const frameHooks = new Set();
const renderSources = new Map();
const kernel32 = Module.load('kernel32.dll');
const clockValue = Memory.alloc(8), clockFrequency = Memory.alloc(8);
const queryClock = new NativeFunction(kernel32.getExportByName('QueryPerformanceCounter'),'bool',['pointer'],'stdcall');
new NativeFunction(kernel32.getExportByName('QueryPerformanceFrequency'),'bool',['pointer'],'stdcall')(clockFrequency);
const clockHz = clockFrequency.readS64().toNumber();
function nowMs() { queryClock(clockValue); return clockValue.readS64().toNumber()*1000/clockHz; }
function renderSample(name) {
  const now=nowMs();
  let sample=renderSources.get(name);
  if(!sample){sample={count:0,last:null,intervals:[]};renderSources.set(name,sample);}
  if(sample.last!==null){sample.intervals.push(now-sample.last);if(sample.intervals.length>600)sample.intervals.shift();}
  sample.last=now;sample.count++;
}
function renderStatus() {
  return Object.fromEntries([...renderSources].map(([name,sample])=>{
    const sorted=[...sample.intervals].sort((a,b)=>a-b), total=sample.intervals.reduce((a,b)=>a+b,0);
    return [name,{count:sample.count,window_frames:sorted.length,window_seconds:total/1000,
      fps:total>0?sample.intervals.length*1000/total:null,
      interval_ms_p50:sorted.length?sorted[Math.floor((sorted.length-1)*.5)]:null,
      interval_ms_p95:sorted.length?sorted[Math.floor((sorted.length-1)*.95)]:null,
      interval_ms_max:sorted.length?sorted[sorted.length-1]:null,
      last_age_ms:sample.last===null?null:Math.max(0,nowMs()-sample.last)}];
  }));
}
// Process-scoped ordinary keyboard input for menus/pause. Never activates a desktop window.
const keyboardLeases = new Map();
const keyboardCounters = {async:0,state:0,messages:0};
let keyboardHooks = [];
const user32 = Module.load('user32.dll');
function installKeyboardHooks() {
  if(keyboardHooks.length)return;
  for(const apiName of ['GetAsyncKeyState','GetKeyState']) {
    const address=user32.findExportByName(apiName);
    if(address)keyboardHooks.push(Interceptor.attach(address,{onEnter(args){this.key=args[0].toInt32();},onLeave(result){
      if((keyboardLeases.get(this.key)?.until??0)>Date.now()){result.replace(ptr(0x8000));keyboardCounters.async++;}
    }}));
  }
  const address=user32.findExportByName('GetKeyboardState');
  if(address)keyboardHooks.push(Interceptor.attach(address,{onEnter(args){this.buffer=args[0];},onLeave(result){
    if(result.toInt32())for(const [key,lease] of keyboardLeases)if(lease.until>Date.now()){
      this.buffer.add(key).writeU8(0x80);keyboardCounters.state++;
    }
  }}));
}
function ordinaryKey(name, hwnd) {
  const codes={enter:13,escape:27,left:37,up:38,right:39,down:40,space:32};
  const code=codes[name];if(!code)throw new Error('Only ordinary menu/pause keys are allowed');
  const window=ptr(hwnd);
  const processId=Memory.alloc(4);
  new NativeFunction(user32.getExportByName('GetWindowThreadProcessId'),'uint',['pointer','pointer'],'stdcall')(window,processId);
  if(processId.readU32()!==Process.id)throw new Error('Window belongs to another process');
  const lease={until:Date.now()+140};
  installKeyboardHooks();
  keyboardLeases.set(code,lease);
  const post=new NativeFunction(user32.getExportByName('PostMessageW'),'bool',['pointer','uint','uint','uint'],'stdcall');
  post(window,0x100,code,1);keyboardCounters.messages++;
  setTimeout(()=>{
    // An older timer must not release a newer press of the same key.
    if(keyboardLeases.get(code)===lease){
      post(window,0x101,code,0xc0000001);keyboardLeases.delete(code);
    }
    if(!keyboardLeases.size){for(const hook of keyboardHooks)hook.detach();keyboardHooks=[];}
  },145);
  return {key:name,process:Process.id,duration_ms:140,foreground_changed:false};
}
function drainFrames() {
  while(frameRequests.length && frameRequests[0].expires<Date.now())frameRequests.shift().reject(new Error('Frame request expired'));
  if (!graphics || frameRequests.length === 0 || graphics.context().isNull()) return;
  const request=frameRequests.shift();
  try {
    const viewport=Memory.alloc(16);
    graphics.integer(0x0ba2,viewport);
    const x=viewport.readS32(), y=viewport.add(4).readS32();
    const width=viewport.add(8).readS32(), height=viewport.add(12).readS32();
    if(width<1||height<1||width>4096||height>4096) throw new Error('Invalid game viewport');
    const pixels=Memory.alloc(width*height*4);
    graphics.pixels(x,y,width,height,0x1908,0x1401,pixels);
    send({event:'native_frame',id:request.id,width,height},pixels.readByteArray(width*height*4));
    request.resolve({id:request.id,width,height});
  } catch(error) { request.reject(error); }
}
function notify(value) { send(value); }
function refreshLuaState() {
  if(!api||!engineSlot)return;
  const engine=engineSlot.readPointer();
  if(engine.isNull()){luaState=null;return;}
  const candidate=engine.add(0x18).readPointer();
  if(candidate.isNull()){luaState=null;return;}
  const top=api.top(candidate);
  luaState=top>=0&&top<100?candidate:null;
}
function expireLuaRequests() {
  while(pending.length && pending[0].expires<=Date.now())pending.shift().reject(new Error('Native request expired before execution'));
  luaNative.pending.writeU32(pending.length?1:0);
}
function drain() {
  expireLuaRequests();
  const actual=luaNative.state.readPointer();
  if(!actual.isNull())luaState=actual;
  if (executing || !api || !luaState || pending.length === 0) return;
  executing = true;
  luaNative.executing.writeU32(1);
  const request = pending.shift();
  const top = api.top(luaState);
  try {
    const source = Memory.allocUtf8String(request.source);
    let code = api.load(luaState, source);
    if (code === 0) code = api.call(luaState, 0, 1, 0, 0, ptr(0));
    const result = api.string(luaState, -1, ptr(0));
    const value = result.isNull() ? null : result.readUtf8String();
    counters.calls++;
    if (code !== 0) { counters.failures++; request.reject(new Error(value || `Lua error ${code}`)); }
    else request.resolve(value);
  } catch (error) { counters.failures++; request.reject(error); }
  finally {
    api.settop(luaState, top);executing=false;luaNative.executing.writeU32(0);
    luaNative.pending.writeU32(pending.length?1:0);
  }
}
function installLua(module) {
  if (api || !/^lua5\.3/i.test(module.name)) return;
  function bind(name, result, parameters) {
    return new NativeFunction(module.getExportByName(name), result, parameters, 'mscdecl');
  }
  api = {
    top: bind('lua_gettop', 'int', ['pointer']),
    settop: bind('lua_settop', 'void', ['pointer', 'int']),
    load: bind('luaL_loadstring', 'int', ['pointer', 'pointer']),
    call: bind('lua_pcallk', 'int', ['pointer', 'int', 'int', 'int', 'int', 'pointer']),
    string: bind('lua_tolstring', 'pointer', ['pointer', 'int', 'pointer'])
  };
  for (const name of ['lua_newstate', 'luaL_newstate']) {
    const address = module.findExportByName(name);
    if (address) Interceptor.attach(address, {onLeave(value) {
      if (!value.isNull()) { luaState=value;luaNative.state.writePointer(value);notify({event:'lua_state', address:value.toString()}); }
    }});
  }
  // Preserve the proven original Lua-state capture and execution ordering.
  // Hot game callbacks stay entirely native unless a trusted request is queued.
  luaNativeModule=new CModule(`
    #include <gum/guminterceptor.h>
    extern gpointer volatile state_slot;
    extern volatile guint32 executing_flag;
    extern volatile guint32 pending_flag;
    extern volatile guint32 call_count;
    extern volatile guint32 javascript_count;
    extern void leave_ready(void);
    void on_enter(GumInvocationContext *context) {
      call_count++;
      if (!executing_flag) state_slot=gum_invocation_context_get_nth_argument(context,0);
    }
    void on_leave(GumInvocationContext *context) {
      if (pending_flag && !executing_flag) {javascript_count++;leave_ready();}
    }
  `,{state_slot:luaNative.state,executing_flag:luaNative.executing,pending_flag:luaNative.pending,
      call_count:luaNative.calls,javascript_count:luaNative.javascript,leave_ready:luaNativeLeave},
    {toolchain:'internal'});
  Interceptor.attach(module.getExportByName('lua_pcallk'),{onEnter:luaNativeModule.on_enter,onLeave:luaNativeModule.on_leave});
  installed.push(module.name);
  notify({event:'lua_api', module:module.name});
}
function installFrame(module) {
  if (!/^(gdi32|opengl32)\.dll$/i.test(module.name)) return;
  if(module.name.toLowerCase()==='opengl32.dll') graphics={
    context:new NativeFunction(module.getExportByName('wglGetCurrentContext'),'pointer',[],'stdcall'),
    integer:new NativeFunction(module.getExportByName('glGetIntegerv'),'void',['uint','pointer'],'stdcall'),
    pixels:new NativeFunction(module.getExportByName('glReadPixels'),'void',['int','int','int','int','uint','uint','pointer'],'stdcall')
  };
  const address = module.findExportByName(module.name.toLowerCase() === 'gdi32.dll' ? 'SwapBuffers' : 'wglSwapBuffers');
  if (address && !frameHooks.has(address.toString())) {
    frameHooks.add(address.toString());
    Interceptor.attach(address, {onEnter() { renderSample(module.name); drain(); drainFrames(); }});
    installed.push('frame:'+module.name);
  }
}
Process.attachModuleObserver({onAdded(module) { installLua(module); installFrame(module); }});
// This build delay-loads Lua through its own loader. Locate only the published
// LuaEngine singleton signature, then use the game's exact bundled Lua ABI.
if (!api) Module.load(Process.mainModule.path.replace(/[^\\/]+$/, 'Lua5.3.3f.dll'));
const engineMatches = Memory.scanSync(Process.mainModule.base, Process.mainModule.size,
  '8b 0d ?? ?? ?? ?? c7 45 dc 01 00 00 00');
if (engineMatches.length === 1) {
  engineSlot = engineMatches[0].address.add(2).readPointer();
  refreshLuaState();
}
rpc.exports = {
  status() { return {pid:Process.id, lua:luaState ? luaState.toString() : null, installed, counters, keyboardCounters,
    performance:{clock:'QueryPerformanceCounter',render:renderStatus(),keyboard_hooks:keyboardHooks.length,
      keyboard_leases:keyboardLeases.size,lua_pcall_hooks:luaNativeModule?1:0,lua_hook_implementation:'native_c',
      lua_native_calls:luaNative.calls.readU32(),lua_javascript_returns:luaNative.javascript.readU32(),
      lua_execution_point:'original_lua_return_and_render_boundaries',
      pending_evaluations:pending.length,pending_captures:frameRequests.length}}; },
  key(name,hwnd) {return ordinaryKey(name,hwnd);},
  evaluate(source) { return new Promise((resolve,reject) => {
    pending.push({source,resolve,reject,expires:Date.now()+3000});
    luaNative.pending.writeU32(1);setTimeout(expireLuaRequests,3000);
  }); },
  capture(id) {return new Promise((resolve,reject)=>frameRequests.push({id,resolve,reject,expires:Date.now()+2500}));},
  progress() {
    const matches=Memory.scanSync(Process.mainModule.base,Process.mainModule.size,'a1 ?? ?? ?? ?? 8b 80 ?? ?? ?? ?? 83 e8 00');
    if(matches.length!==1) return {error:'Manager signature is not unique',matches:matches.length};
    const manager=matches[0].address.add(1).readPointer().readPointer();
    if(manager.isNull())return {ready:false,reason:'game_manager_not_ready'};
    const data=manager.add(0x14);
    return {manager:manager.toString(),slot:manager.add(0x10).readU32(),readonly:!!data.add(1).readU8(),
      womb_unlocked:!!data.add(0x38+4).readU8(),
      // Repentance 1.7.9b layout, from REPENTOGON 1.0.12e (not Repentance+).
      mom_heart_kills:data.add(0x2b8+4).readS32(),
      satan_kills:data.add(0x2b8+13*4).readS32(),
      unlocked_count:Array.from({length:638},(_,i)=>data.add(0x38+i).readU8()).filter(Boolean).length};
  }
};
