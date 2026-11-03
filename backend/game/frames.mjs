import { createHash } from 'node:crypto';
import { Worker } from 'node:worker_threads';
import { GameError, ensure, utc } from './errors.mjs';
import { validate } from './protocol.mjs';

export const FRAME_MAX_BYTES = 4 * 1024 * 1024;
const id = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/;
export function jpegSize(bytes) {
  ensure(bytes.length>=4 && bytes[0]===255 && bytes[1]===216 && bytes.at(-2)===255 && bytes.at(-1)===217,'GAME_FRAME_JPEG_INVALID',400);
  let offset=2;
  while(offset<bytes.length-2) {
    ensure(bytes[offset++]===255,'GAME_FRAME_JPEG_INVALID',400);while(bytes[offset]===255)offset++;
    const marker=bytes[offset++];if(marker===218||marker===217)break;
    if(marker===1||marker>=208&&marker<=215)continue;
    ensure(offset+2<=bytes.length,'GAME_FRAME_JPEG_INVALID',400);const length=bytes.readUInt16BE(offset);
    ensure(length>=2&&offset+length<=bytes.length,'GAME_FRAME_JPEG_INVALID',400);
    if([192,193,194].includes(marker)) {ensure(length>=8,'GAME_FRAME_JPEG_INVALID',400);return {height:bytes.readUInt16BE(offset+3),width:bytes.readUInt16BE(offset+5)};}
    offset+=length;
  }
  throw new GameError('GAME_FRAME_JPEG_INVALID',400);
}
function decode(bytes,signal) {
  return new Promise((resolve,reject)=>{
    const worker=new Worker(new URL('./frame-decode-worker.mjs',import.meta.url),{workerData:bytes,
      resourceLimits:{maxOldGenerationSizeMb:96,maxYoungGenerationSizeMb:16,stackSizeMb:4}});
    let settled=false;
    const finish=(error,value)=>{if(settled)return;settled=true;clearTimeout(timer);signal.removeEventListener('abort',abort);void worker.terminate();error?reject(error):resolve(value);};
    const abort=()=>finish(new GameError('GAME_FRAME_CANCELLED',409));
    const timer=setTimeout(()=>finish(new GameError('GAME_FRAME_DECODE_TIMEOUT',504)),3000);
    worker.once('message',value=>finish(value.error?new GameError(value.error,400):null,value));
    worker.once('error',()=>finish(new GameError('GAME_FRAME_JPEG_INVALID',400)));
    worker.once('exit',code=>{if(!settled)finish(new GameError('GAME_FRAME_JPEG_INVALID',400));});
    signal.addEventListener('abort',abort,{once:true});if(signal.aborted)abort();
  });
}
export class FrameStore {
  constructor(manager) {this.manager=manager;this.entries=new Map();this.uploading=false;this.controllers=new Set();}
  prune() {for(const [key,value] of this.entries)if(this.manager.clock()-value.receivedMono>=30000)this.entries.delete(key);}
  clear() {this.entries.clear();for(const controller of this.controllers)controller.abort();}
  context(operationId) {
    const pending=this.manager.pending.get(operationId),state=this.manager.state.requireFresh();
    ensure(this.manager.config.vision.enabled&&['observation','frame'].includes(pending?.queryKind)&&pending.operation.state==='pending','GAME_FRAME_OPERATION_INVALID',409);
    ensure(pending.world===state.world_session_id&&pending.boot===state.bridge_boot_id&&pending.generation===state.connection_generation,'GAME_FRAME_CONTEXT',409);
    ensure(this.manager.clock()<pending.deadline,'GAME_FRAME_EXPIRED',410);return {pending,state};
  }
  metadata(req,frameId) {
    ensure(id.test(frameId),'GAME_REQUEST_INVALID',400);
    ensure(req.headers['content-type']==='image/jpeg'&&!req.headers['content-encoding'],'GAME_FRAME_CONTENT_TYPE',415);
    const header=name=>{const value=req.headers['x-mc-'+name];ensure(typeof value==='string','GAME_FRAME_HEADER_INVALID',400);return value;};
    const numeric=name=>{const value=header(name);ensure(/^(0|[1-9][0-9]{0,15})$/.test(value)&&Number.isSafeInteger(Number(value)),'GAME_FRAME_HEADER_INVALID',400);return Number(value);};
    const value={frame_id:frameId,operation_id:header('operation-id'),boot:header('bridge-boot-id'),world:header('world-session-id'),
      source_seq:numeric('seq'),captured_at:header('captured-at'),width:numeric('width'),height:numeric('height')};
    const old=this.entries.get(frameId),state=this.manager.state.requireFresh();
    let pending;
    if(old) {
      ensure(this.manager.config.vision.enabled&&old.meta.operation_id===value.operation_id,'GAME_FRAME_OPERATION_INVALID',409);
      ensure(JSON.stringify(old.meta)===JSON.stringify(value),'GAME_FRAME_ID_CONFLICT',409);
    } else ({pending}=this.context(value.operation_id));
    ensure(value.boot===state.bridge_boot_id&&value.world===state.world_session_id,'GAME_FRAME_CONTEXT');
    if(pending)ensure(value.source_seq>=pending.admittedSeq&&value.source_seq<=state.seq+50,'GAME_FRAME_SEQUENCE');
    ensure(value.width>=1&&value.width<=1920&&value.height>=1&&value.height<=1080,'GAME_FRAME_DIMENSIONS',413);
    const timestamp=Date.parse(value.captured_at);ensure(/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,9})?Z$/.test(value.captured_at)&&Number.isFinite(timestamp)
      &&(old||this.manager.wall()-timestamp<=2000)&&timestamp<=this.manager.wall()+250,'GAME_FRAME_CAPTURE_TIME',409);
    if(pending)ensure(!pending.frameId||pending.frameId===frameId,'GAME_FRAME_OPERATION_BOUND');
    return value;
  }
  async upload(req,frameId) {
    this.prune();const meta=this.metadata(req,frameId);ensure(!this.uploading,'GAME_FRAME_UPLOAD_BUSY',429);
    const declared=req.headers['content-length'];if(declared!==undefined)ensure(/^[1-9][0-9]*$/.test(declared)&&Number(declared)<=FRAME_MAX_BYTES,'GAME_FRAME_TOO_LARGE',413);
    this.uploading=true;const controller=new AbortController();this.controllers.add(controller);
    const timer=setTimeout(()=>{controller.abort();req.destroy();},4000);
    try {
      const chunks=[];let length=0;
      for await(const chunk of req.iterator({destroyOnReturn:false})) {length+=chunk.length;ensure(length<=FRAME_MAX_BYTES,'GAME_FRAME_TOO_LARGE',413);chunks.push(chunk);}
      ensure(length>0,'GAME_FRAME_JPEG_INVALID',400);const bytes=Buffer.concat(chunks,length),size=jpegSize(bytes);
      ensure(size.width===meta.width&&size.height===meta.height,'GAME_FRAME_DIMENSIONS',400);
      const actual=await decode(bytes,controller.signal);ensure(actual.width===meta.width&&actual.height===meta.height,'GAME_FRAME_DIMENSIONS',400);
      const digest=createHash('sha256').update(bytes).digest('hex'),old=this.entries.get(frameId);
      if(old) {ensure(old.digest===digest&&JSON.stringify(old.meta)===JSON.stringify(meta),'GAME_FRAME_ID_CONFLICT');return old.receipt;}
      const {pending}=this.context(meta.operation_id);
      while(this.entries.size>=2) {const removable=[...this.entries].find(([,entry])=>!entry.pinned);ensure(removable,'GAME_FRAME_CACHE_BUSY',429);this.entries.delete(removable[0]);}
      const receipt={frame_id:frameId,operation_id:meta.operation_id,world_session_id:meta.world,source_seq:meta.source_seq,
        width:meta.width,height:meta.height,content_type:'image/jpeg',byte_length:length,received_at:utc(this.manager.wall()),expires_at:utc(this.manager.wall()+30000)};
      const nativeHands=this.manager.state.frameHands(meta);
      validate('FrameReceipt',receipt);this.entries.set(frameId,{receipt,meta,bytes,digest,nativeHands,receivedMono:this.manager.clock(),pinned:false});pending.frameId=frameId;return receipt;
    } catch(error) {if(error instanceof GameError)throw error;throw new GameError('GAME_FRAME_UPLOAD_FAILED',400);}
    finally {clearTimeout(timer);this.controllers.delete(controller);this.uploading=false;}
  }
  get(frameId) {this.prune();const entry=this.entries.get(frameId);ensure(entry,'GAME_FRAME_NOT_FOUND',404);return entry;}
  claim(operationId,result) {
    const {pending}=this.context(operationId);ensure(pending.frameId===result.frame_id,'GAME_FRAME_OPERATION_BOUND');const entry=this.get(result.frame_id);
    ensure(entry.meta.operation_id===operationId&&entry.meta.source_seq===result.source_seq&&entry.meta.captured_at===result.captured_at
      &&entry.meta.width===result.width&&entry.meta.height===result.height,'GAME_FRAME_RESULT_CONTEXT');
    ensure(this.manager.wall()-Date.parse(entry.meta.captured_at)<=2000,'GAME_FRAME_EXPIRED',410);entry.pinned=true;return entry;
  }
}
