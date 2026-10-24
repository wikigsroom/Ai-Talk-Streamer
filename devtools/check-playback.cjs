/* Native Chromium regression: continuous PCM under arrival jitter and JPEG pressure.
 * Usage: node devtools/check-playback.cjs --browser <chrome.exe> [--baseline <old.js>] [--output <report.json>]
 * All sockets are simulated in this test; no inference service is modified.
 */
'use strict';
const fs=require('fs'),path=require('path'),{chromium}=require('playwright-core');
const args=process.argv.slice(2),option=name=>{const index=args.indexOf(name);return index<0?null:args[index+1]};
const executablePath=option('--browser');if(!executablePath)throw Error('Provide --browser with a native Chrome or Edge executable.');
const current=path.resolve(__dirname,'../web/local-stream.js'),baseline=option('--baseline');
(async()=>{
 let browser;const results=[];
 try{
  browser=await chromium.launch({executablePath,headless:true,args:['--autoplay-policy=no-user-gesture-required']});
  for(const [version,filename] of [...(baseline?[['baseline',baseline]]:[]),['current',current]]){
   for(const scenario of ['arrival-jitter','slow-image-decoder',...(version==='current'?['audio-only-packets']:[])]){
    const context=await browser.newContext({viewport:{width:800,height:900}});
    try{
     const page=await context.newPage();
     await page.setContent('<video autoplay playsinline muted style="height:800px"></video>');
     await page.addScriptTag({path:filename});
     const result=await page.evaluate(async scenario=>{
      const ctx=new AudioContext();await ctx.resume();
      const images=[],canvas=document.createElement('canvas');canvas.width=720;canvas.height=1280;
      const paint=canvas.getContext('2d');
      for(let i=0;i<4;i++){paint.fillStyle=['#235070','#753850','#217853','#785233'][i];paint.fillRect(0,0,720,1280);paint.fillStyle='white';paint.font='200px sans-serif';paint.fillText(String(i),150,700);images.push(new Uint8Array(await(await new Promise(r=>canvas.toBlob(r,'image/jpeg',.86))).arrayBuffer()))}
      const nativeBitmap=window.createImageBitmap;
      if(scenario==='slow-image-decoder')window.createImageBitmap=async(...args)=>{await new Promise(r=>setTimeout(r,90));return nativeBitmap(...args)};
      const schedule=[],nativeStart=AudioBufferSourceNode.prototype.start;
      AudioBufferSourceNode.prototype.start=function(at,...args){if(this.buffer)schedule.push({at,now:this.context.currentTime,duration:this.buffer.duration});return nativeStart.call(this,at,...args)};
      let alive=true,timer;
      window.WebSocket=class {
       static OPEN=1;
       constructor(){this.readyState=1;this.sequence=0;this.started=performance.now();timer=setTimeout(()=>this.pump(),1)}
       pump(){
        if(!alive)return;
        const elapsed=performance.now()-this.started,phase=elapsed%2000;
        const held=scenario==='arrival-jitter'&&phase>=1000&&phase<1200;
        if(!held){
         const last=Math.floor(elapsed/40);
         while(this.sequence<=last){
          const seq=this.sequence++,jpg=scenario==='audio-only-packets'&&seq%4!==0?new Uint8Array(0):images[seq%4],packet=new ArrayBuffer(12+jpg.length+1280),view=new DataView(packet);
          view.setUint32(0,seq,true);view.setUint32(4,jpg.length,true);view.setUint32(8,16000,true);
          new Uint8Array(packet,12,jpg.length).set(jpg);
          for(let i=0;i<640;i++)view.setInt16(12+jpg.length+i*2,Math.round(2000*Math.sin(2*Math.PI*800*i/16000)),true);
          this.onmessage?.({data:packet});
         }
        }
        timer=setTimeout(()=>this.pump(),4);
       }
       close(){alive=false;this.readyState=3;clearTimeout(timer)}
      };
      const transport=new LocalAvatarStream(ctx),stream=await transport.connect(),video=document.querySelector('video');
      video.srcObject=stream;transport.attachVideo?.(video);await video.play();
      const presented=[];function frame(now){presented.push(now);if(alive)video.requestVideoFrameCallback(frame)}video.requestVideoFrameCallback(frame);
      const input=ctx.createMediaStreamSource(stream),meter=ctx.createScriptProcessor(1024,1,1),mute=ctx.createGain();mute.gain.value=0;
      let total=0,silent=0,run=0,longest=0;
      meter.onaudioprocess=event=>{
       if(!schedule.length||ctx.currentTime<schedule[0].at+.5)return;
       const samples=event.inputBuffer.getChannelData(0);let power=0;
       for(const value of samples)power+=value*value;
       total+=samples.length;
       if(Math.sqrt(power/samples.length)<.001){silent+=samples.length;run+=samples.length;longest=Math.max(longest,run)}else run=0;
      };
      input.connect(meter);meter.connect(mute);mute.connect(ctx.destination);
      await new Promise(r=>setTimeout(r,8000));
      const metrics=transport.metrics(),gaps=schedule.slice(1).map((v,i)=>({now:v.now,gap:(v.at-schedule[i].at-schedule[i].duration)*1000})).filter(v=>v.now>=2);
      transport.close();input.disconnect();meter.disconnect();mute.disconnect();await ctx.close();
      return {metrics,presented_fps:(presented.length-1)/(presented.at(-1)-presented[0])*1000,audio_gap_count:gaps.filter(v=>v.gap>1).length,audio_gap_max_ms:Math.max(0,...gaps.map(v=>v.gap)),captured_audio_seconds:total/ctx.sampleRate,captured_silent_ms:silent/ctx.sampleRate*1000,captured_longest_silence_ms:longest/ctx.sampleRate*1000};
     },scenario);
     results.push({version,scenario,...result});
    }finally{await context.close()}
   }
  }
 }finally{await browser?.close()}
 const ok=results.filter(v=>v.version==='current').every(v=>v.audio_gap_count===0&&v.captured_audio_seconds>4&&v.captured_longest_silence_ms<50&&v.metrics.decode_errors===0);
 const report={ok,scope:'Synthetic continuous tone; 200 ms arrival holds, 90 ms JPEG decodes, and audio-only packets. Does not establish speech naturalness or physical audio-device output.',results};
 if(option('--output'))fs.writeFileSync(option('--output'),JSON.stringify(report,null,2));
 console.log(JSON.stringify(report));if(!ok)process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1});
