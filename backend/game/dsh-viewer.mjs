import { createRequire } from 'node:module';
import { join, dirname } from 'node:path';
import { createServer } from 'node:http';
import { EventEmitter } from 'node:events';

// A read-only Prismarine view. NeoForge registry IDs are connection-specific;
// translate the outgoing display palettes by name without touching bot.world.
// Unavailable mod models use magenta concrete so they are visibly uncertain.
export async function startDshViewer(bot,extras,port,log){
 const require=createRequire(join(extras,'package.json'));
 const express=require('express'),{Server}=require('socket.io');
 // Import the server-side world adapter directly. The viewer barrel also loads
 // node-canvas for offline entity rendering, which this browser view does not use.
 const {WorldView}=require('prismarine-viewer/viewer/lib/worldView');
 const vanilla=require('minecraft-data')('1.21.1');
 const app=express(),http=createServer(app),io=new Server(http),clients=new Set();
 const dir=dirname(require.resolve('prismarine-viewer/package.json'));
 app.use(express.static(join(dir,'public')));
 const stateCache=new Map(),biomeCache=new Map();let unknown=0;
 function state(id){
  if(stateCache.has(id))return stateCache.get(id);
  const source=bot.registry.blocksByStateId[id],name=source?.name?.replace(/^minecraft:/,'');
  const target=vanilla.blocksByName[name];let mapped;
  if(target){const offset=id-source.minStateId;mapped=target.minStateId+Math.min(Math.max(0,offset),target.maxStateId-target.minStateId)}
  else{mapped=source?.boundingBox==='empty'?vanilla.blocksByName.air.defaultState:vanilla.blocksByName.magenta_concrete.defaultState;unknown++}
  stateCache.set(id,mapped);return mapped;
 }
 function biome(id){if(!biomeCache.has(id)){const name=bot.registry.biomes[id]?.name?.replace(/^minecraft:/,'');biomeCache.set(id,vanilla.biomesByName[name]?.id??vanilla.biomesByName.plains.id)}return biomeCache.get(id)}
 function palette(raw,mapper){const value=JSON.parse(raw);if(value.type==='single')value.value=mapper(value.value);else if(value.type==='indirect')value.palette=value.palette.map(mapper);else throw Error('MC_VIEWER_DIRECT_PALETTE_UNSUPPORTED');return JSON.stringify(value)}
 function chunk(raw){const c=JSON.parse(raw);c.sections=c.sections.map(raw=>{const s=JSON.parse(raw);s.data=palette(s.data,state);return JSON.stringify(s)});c.biomes=c.biomes.map(raw=>palette(raw,biome));return JSON.stringify(c)}
 io.on('connection',socket=>{
  clients.add(socket);socket.emit('version','1.21.1');
  const proxy=new EventEmitter();proxy.emit=(name,data)=>{
   try{if(name==='loadChunk')data={...data,chunk:chunk(data.chunk)};if(name==='blockUpdate')data={...data,stateId:state(data.stateId)};socket.emit(name,data)}
   catch(e){log('viewer.encode_failed',{code:e.message});socket.disconnect(true)}return true;
  };
  const view=new WorldView(bot.world,5,bot.entity.position,proxy);
  const position=()=>{socket.emit('position',{pos:bot.entity.position,yaw:bot.entity.yaw,pitch:bot.entity.pitch,addMesh:true});view.updatePosition(bot.entity.position)};
  view.listenToBot(bot);void view.init(bot.entity.position).then(position).catch(e=>log('viewer.init_failed',{code:e.message}));
  bot.on('move',position);
  socket.on('disconnect',()=>{bot.off('move',position);view.removeListenersFromBot(bot);clients.delete(socket)});
  log('viewer.client_connected',{clients:clients.size});
 });
 await new Promise((resolve,reject)=>{http.once('error',reject);http.listen(port,'127.0.0.1',resolve)});
 return {close:()=>new Promise(resolve=>{io.close();http.close(resolve)}),status:()=>({clients:clients.size,mapped_states:stateCache.size,unknown_mod_states:unknown})};
}
