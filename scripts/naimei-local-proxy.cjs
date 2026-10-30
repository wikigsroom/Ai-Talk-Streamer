'use strict';
// Native loopback access for browser AudioContext; streams HTTP and WebSocket.
const http=require('node:http'),net=require('node:net');
const upstream={host:'192.168.196.209',port:8052};
const server=http.createServer((req,res)=>{
 const proxy=http.request({...upstream,path:req.url,method:req.method,headers:{...req.headers,host:upstream.host+':'+upstream.port}},response=>{
  res.writeHead(response.statusCode,response.headers);response.pipe(res);
 });
 proxy.on('error',()=>{if(!res.headersSent)res.writeHead(502,{'Content-Type':'application/json'});res.end('{"error":"NAIMEI_REMOTE_UNAVAILABLE"}')});
 req.on('aborted',()=>proxy.destroy());res.on('close',()=>proxy.destroy());req.pipe(proxy);
});
server.on('upgrade',(req,socket,head)=>{
 const remote=net.connect(upstream.port,upstream.host,()=>{
  const headers={...req.headers,host:upstream.host+':'+upstream.port};
  remote.write(req.method+' '+req.url+' HTTP/1.1\r\n'+Object.entries(headers).map(([k,v])=>k+': '+v).join('\r\n')+'\r\n\r\n');
  if(head.length)remote.write(head);socket.pipe(remote);remote.pipe(socket);
 });
 remote.on('error',()=>socket.destroy());socket.on('error',()=>remote.destroy());
 socket.on('close',()=>remote.destroy());remote.on('close',()=>socket.destroy());
});
server.listen(8952,'127.0.0.1',()=>process.stdout.write('Naimei studio http://127.0.0.1:8952/\n'));
