'use strict';
// A native LAN reverse connection. Browser access is restricted to this computer.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),crypto=require('node:crypto');
const {wsServer:WebSocketServer}=require('C:/Users/carzy/.codex/skills/binance-square/node_modules/playwright-core/lib/utilsBundle.js');
const root=path.resolve(__dirname,'..'),state=path.join(root,'state/naimei/relay');
const config=JSON.parse(fs.readFileSync(path.join(state,'config.json'),'utf8'));
const staticNames=new Set(['/','/output.html','/health','/naimei.css','/naimei.js','/naimei-output.js','/local-stream.js','/browser-id.js','/dsh-playback.js','/room-client.js','/room-audio.js']);
const allowed=p=>staticNames.has(p)||p==='/api/studio/status'||p==='/api/studio/stream'||p.startsWith('/api/dsh/')||p.startsWith('/api/naimei/')||p.startsWith('/naimei-assets/');
const address=req=>String(req.socket.remoteAddress||'').replace(/^::ffff:/,'');
const local=req=>['127.0.0.1','::1'].includes(address(req));
const host=req=>['127.0.0.1:'+config.port,'localhost:'+config.port].includes(req.headers.host);
const origin=req=>!req.headers.origin||['http://127.0.0.1:'+config.port,'http://localhost:'+config.port].includes(req.headers.origin);
let tunnel=null,serial=0;const pending=new Map(),viewers=new Map();
function send(item){if(tunnel?.readyState!==1)throw Error('奶妹连接尚未就绪');tunnel.send(JSON.stringify(item));}
function rpc(item){return new Promise((resolve,reject)=>{item.id=++serial;const timer=setTimeout(()=>{pending.delete(item.id);reject(Error('奶妹请求超时'));},65000);pending.set(item.id,{resolve:value=>{clearTimeout(timer);resolve(value);},reject:error=>{clearTimeout(timer);reject(error);}});try{send(item);}catch(error){pending.get(item.id).reject(error);pending.delete(item.id);}});}
function packet(id,kind,data=Buffer.alloc(0)){const header=Buffer.alloc(5);header.writeUInt32BE(id);header[4]=kind;return Buffer.concat([header,data]);}
function disconnected(connection){if(tunnel!==connection)return;tunnel=null;for(const item of pending.values())item.reject(Error('奶妹连接已断开'));pending.clear();for(const ws of viewers.values())ws.close(1012,'GPU connection lost');viewers.clear();}
const server=http.createServer(async(req,res)=>{
 if(!local(req)||!host(req)||!origin(req)){res.writeHead(403);res.end();return;}
 const url=new URL(req.url,'http://localhost');
 if(url.pathname==='/_bridge/status'){res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify({connected:tunnel?.readyState===1,viewers:viewers.size,cloud_used:false,character_id:'naimei'}));return;}
 if(!allowed(url.pathname)){res.writeHead(404);res.end();return;}
 if(['GET','HEAD'].includes(req.method)&&(staticNames.has(url.pathname)||url.pathname.startsWith('/naimei-assets/'))){
  const asset=url.pathname.startsWith('/naimei-assets/'),base=path.join(root,asset?'assets/naimei/live-v1':'web');
  let name;try{name=decodeURIComponent(asset?url.pathname.slice('/naimei-assets/'.length):url.pathname==='/'?'naimei.html':url.pathname==='/output.html'?'naimei-output.html':url.pathname.slice(1));}catch{res.writeHead(400);res.end();return;}
  const target=path.resolve(base,name),types={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.json':'application/json; charset=utf-8','.jpg':'image/jpeg','.png':'image/png','.wav':'audio/wav','.mp4':'video/mp4','.srt':'text/plain; charset=utf-8'};
  if(!target.startsWith(base+path.sep)||!types[path.extname(target)]||!fs.existsSync(target)||!fs.statSync(target).isFile()){res.writeHead(404);res.end();return;}
  const size=fs.statSync(target).size,range=req.headers.range?.match(/^bytes=(\d+)-(\d*)$/);let start=0,end=size-1;
  if(range){start=Number(range[1]);end=range[2]?Math.min(Number(range[2]),end):end;if(start>end){res.writeHead(416,{'Content-Range':'bytes */'+size});res.end();return;}}
  res.writeHead(range?206:200,{'Content-Type':types[path.extname(target)],'Content-Length':end-start+1,'Accept-Ranges':'bytes','Cache-Control':'no-store',...(range?{'Content-Range':`bytes ${start}-${end}/${size}`}:{})});
  if(req.method==='HEAD')res.end();else fs.createReadStream(target,{start,end}).pipe(res);return;
 }
 try{let size=0;const chunks=[];for await(const chunk of req){size+=chunk.length;if(size>1024*1024)throw Error('请求过大');chunks.push(chunk);}
  const result=await rpc({type:'http',method:req.method,path:url.pathname+url.search,headers:{'Content-Type':req.headers['content-type']||'',...(req.headers.range?{Range:req.headers.range}:{})},body:Buffer.concat(chunks).toString('base64')});
  res.writeHead(result.status,{...result.headers,'Cache-Control':'no-store'});res.end(Buffer.from(result.body||'','base64'));
 }catch(error){if(!res.headersSent)res.writeHead(503,{'Content-Type':'application/json; charset=utf-8'});res.end(JSON.stringify({error:error.message}));}
});
const wss=new WebSocketServer({noServer:true,maxPayload:64*1024*1024});
server.on('upgrade',(req,socket,head)=>{
 const url=new URL(req.url,'http://localhost');
 if(url.pathname==='/_tunnel'){
  const expected=Buffer.from('Bearer '+config.token),actual=Buffer.from(req.headers.authorization||'');
  if(address(req)!==config.remote_host||actual.length!==expected.length||!crypto.timingSafeEqual(actual,expected)||tunnel?.readyState===1){socket.destroy();return;}
  wss.handleUpgrade(req,socket,head,connection=>{tunnel=connection;connection.on('error',()=>{});connection.on('close',()=>disconnected(connection));connection.on('message',(data,binary)=>{
   if(binary){if(data.length<5)return;const viewer=viewers.get(data.readUInt32BE(0));if(viewer?.readyState!==1)return;if(viewer.bufferedAmount>4*1024*1024){viewer.close(1013,'Slow viewer');return;}const kind=data[4];if(kind===3)viewer.close();else viewer.send(data.subarray(5),{binary:kind===1});}
   else{let item;try{item=JSON.parse(data);}catch{return;}const request=pending.get(item.id);if(!request)return;pending.delete(item.id);if(item.error)request.reject(Error(item.error));else request.resolve(item);}
  });});return;
 }
 if(!local(req)||!host(req)||!origin(req)||url.pathname!=='/api/studio/stream'||viewers.size>=8||tunnel?.readyState!==1){socket.destroy();return;}
 wss.handleUpgrade(req,socket,head,async viewer=>{const id=++serial;viewers.set(id,viewer);viewer.on('error',()=>{});viewer.on('close',()=>{viewers.delete(id);try{send({type:'ws_close',channel:id});}catch{}});viewer.on('message',(data,binary)=>{if(tunnel?.readyState===1)tunnel.send(packet(id,binary?1:2,data));});try{await rpc({type:'ws_open',channel:id,path:url.pathname+url.search});}catch{viewer.close(1011,'Stream unavailable');}});
});
server.on('error',error=>{process.stderr.write(error.stack);process.exitCode=1;});
server.listen(config.port,'0.0.0.0',()=>{fs.writeFileSync(path.join(state,'process.json'),JSON.stringify({pid:process.pid,port:config.port,script:__filename,started:new Date().toISOString()}));process.stdout.write('奶妹导播台 http://127.0.0.1:'+config.port+'/\n');});
function stop(){tunnel?.close();for(const ws of viewers.values())ws.close();server.close(()=>process.exit(0));setTimeout(()=>process.exit(0),2000).unref();}
process.on('SIGINT',stop);process.on('SIGTERM',stop);
