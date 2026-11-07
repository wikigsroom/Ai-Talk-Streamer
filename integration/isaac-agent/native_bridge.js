// Isaac-only native Lua bridge. Never changes achievement, save, or gameplay flags.
// Work executes on the game's own render thread; the Lua stack is always restored.
let luaState = null;
let api = null;
let executing = false;
let pending = [];
let installed = [];
let counters = { calls: 0, failures: 0 };
let graphics = null;
let frameRequests = [];
// Process-scoped ordinary keyboard input for menus/pause. Never activates a desktop window.
const keyboardLeases = new Map();
const keyboardCounters = {async:0,state:0,messages:0};
const user32 = Module.load('user32.dll');
for(const apiName of ['GetAsyncKeyState','GetKeyState']) {
  const address=user32.findExportByName(apiName);
  if(address)Interceptor.attach(address,{onEnter(args){this.key=args[0].toInt32();},onLeave(result){
    if((keyboardLeases.get(this.key)??0)>Date.now()){result.replace(ptr(0x8000));keyboardCounters.async++;}
  }});
}
const getKeyboardState=user32.findExportByName('GetKeyboardState');
if(getKeyboardState)Interceptor.attach(getKeyboardState,{onEnter(args){this.buffer=args[0];},onLeave(result){
  if(result.toInt32())for(const [key,until] of keyboardLeases)if(until>Date.now()){
    this.buffer.add(key).writeU8(0x80);keyboardCounters.state++;
  }
}});
function ordinaryKey(name, hwnd) {
  const codes={enter:13,escape:27,left:37,up:38,right:39,down:40};
  const code=codes[name];if(!code)throw new Error('Only ordinary menu/pause keys are allowed');
  const window=ptr(hwnd);
  const processId=Memory.alloc(4);
  new NativeFunction(user32.getExportByName('GetWindowThreadProcessId'),'uint',['pointer','pointer'],'stdcall')(window,processId);
  if(processId.readU32()!==Process.id)throw new Error('Window belongs to another process');
  keyboardLeases.set(code,Date.now()+140);
  const post=new NativeFunction(user32.getExportByName('PostMessageW'),'bool',['pointer','uint','uint','uint'],'stdcall');
  post(window,0x100,code,1);keyboardCounters.messages++;
  setTimeout(()=>post(window,0x101,code,0xc0000001),145);
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
function drain() {
  while(pending.length && pending[0].expires<Date.now())pending.shift().reject(new Error('Native request expired before execution'));
  if (executing || !api || !luaState || pending.length === 0) return;
  executing = true;
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
  finally { api.settop(luaState, top); executing = false; }
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
      if (!value.isNull()) { luaState = value; notify({event:'lua_state', address:value.toString()}); }
    }});
  }
  Interceptor.attach(module.getExportByName('lua_pcallk'), {
    onEnter(args) { if (!executing) luaState = args[0]; },
    onLeave() { drain(); }
  });
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
  if (address) { Interceptor.attach(address, {onEnter() { drain(); drainFrames(); }}); installed.push('frame:'+module.name); }
}
Process.attachModuleObserver({onAdded(module) { installLua(module); installFrame(module); }});
// This build delay-loads Lua through its own loader. Locate only the published
// LuaEngine singleton signature, then use the game's exact bundled Lua ABI.
if (!api) Module.load(Process.mainModule.path.replace(/[^\\/]+$/, 'Lua5.3.3f.dll'));
const engineMatches = Memory.scanSync(Process.mainModule.base, Process.mainModule.size,
  '8b 0d ?? ?? ?? ?? c7 45 dc 01 00 00 00');
if (engineMatches.length === 1) {
  const engine = engineMatches[0].address.add(2).readPointer().readPointer();
  if (!engine.isNull()) {
    const candidate = engine.add(0x18).readPointer();
    if (!candidate.isNull()) {
      const top = api.top(candidate);
      if (top >= 0 && top < 100) luaState = candidate;
    }
  }
}
rpc.exports = {
  status() { return {pid:Process.id, lua:luaState ? luaState.toString() : null, installed, counters, keyboardCounters}; },
  key(name,hwnd) {return ordinaryKey(name,hwnd);},
  evaluate(source) { return new Promise((resolve,reject) => pending.push({source,resolve,reject,expires:Date.now()+3000})); },
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
