const fs=require('fs'), path=require('path');
const {chromium}=require('playwright-core');
const root=path.resolve(__dirname,'..'),out=path.join(root,'docs/media'),raw=path.join(out,'raw');
const base=(process.env.AVATAR_BASE_URL||'http://127.0.0.1:8010').replace(/\/$/,'');
const executable=process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe';
const galleryOnly=process.argv.includes('--gallery-only');
fs.mkdirSync(raw,{recursive:true});fs.mkdirSync(path.join(root,'cache/tmp'),{recursive:true});
const result={ok:false,captured_at:new Date().toISOString(),source:'actual running studio, without mocked responses',screenshots:[]};
let context,page,video,recordingStarted;
(async()=>{try{
 context=await chromium.launchPersistentContext(path.join(root,'cache/documentation-capture'),{executablePath:executable,headless:true,viewport:{width:1440,height:1050},...(galleryOnly?{}:{recordVideo:{dir:raw,size:{width:1440,height:1050}}}),env:{...process.env,TEMP:path.join(root,'cache/tmp'),TMP:path.join(root,'cache/tmp')},args:['--no-proxy-server','--autoplay-policy=no-user-gesture-required']});
 if(!galleryOnly){
 page=context.pages()[0]||await context.newPage();video=page.video();recordingStarted=Date.now();
 await page.goto(base,{waitUntil:'domcontentloaded',timeout:45000});
 await page.waitForFunction(()=>document.getElementById('serviceStatus')?.textContent==='服务已就绪',null,{timeout:30000});
 await page.locator('#connectBtn').click();
 await page.waitForFunction(()=>window.studio?.connected&&window.studio.transport.metrics().frames>60,null,{timeout:180000});
 await page.screenshot({path:path.join(out,'studio-desktop.png'),fullPage:true});result.screenshots.push('studio-desktop.png');
 await page.locator('#scriptText').fill('你好，欢迎来到直播间，我是林知夏。今天想聊聊校园生活，还是分享最近读到的一本书？你可以在网页写下问题，我会在这里回应你。我们也可以先从一个简单的招呼开始，轻轻挥挥手，让第一次见面变得自然一点。');
 result.screencast_demo_start_seconds=(Date.now()-recordingStarted)/1000;
 await page.locator('#speakBtn').click();
 await page.waitForFunction(()=>document.getElementById('activityLog').textContent.includes('开始播报：'),null,{timeout:90000});
 await page.locator('#motionSelect').selectOption('m01_welcome_right_wave');await page.locator('#playMotionBtn').click();
 await page.waitForFunction(async()=>{const m=await(await fetch('/api/studio/motion')).json();return m.active==='m01_welcome_right_wave';},null,{timeout:18000});
 await page.waitForTimeout(3500);
 result.screencast_gesture_seconds=(Date.now()-recordingStarted)/1000;
 await page.screenshot({path:path.join(out,'studio-speaking.png'),fullPage:true});result.screenshots.push('studio-speaking.png');
 result.live_metrics=await page.evaluate(()=>window.studio.transport.metrics());
 await page.waitForTimeout(5500);
 result.screencast_demo_end_seconds=(Date.now()-recordingStarted)/1000;
 await page.setViewportSize({width:390,height:844});
 await page.screenshot({path:path.join(out,'studio-mobile.png'),fullPage:true});result.screenshots.push('studio-mobile.png');
 await page.waitForFunction(async()=>!(await(await fetch('/api/studio/status')).json()).speaking,null,{timeout:90000});
 await page.evaluate(()=>window.studio.disconnect());
 }
 for(const [route,name,ready] of [['materials','motion-library.png','#clips .clip'],['poses','pose-library.png','#poseGrid .pose-card'],['tests','scenario-tests.png','.test-card']]){
  const tab=await context.newPage();
  try{
   await tab.setViewportSize({width:1440,height:1050});
   await tab.goto(base+'/'+route,{waitUntil:'domcontentloaded',timeout:30000});
   await tab.locator(ready).first().waitFor({timeout:20000});
   // Full-page captures must load images outside the viewport as well.
   await tab.evaluate(()=>document.querySelectorAll('img').forEach(img=>{img.loading='eager';}));
   await tab.waitForFunction(()=>[...document.images].every(img=>img.complete&&img.naturalWidth>0),null,{timeout:90000});
   await tab.waitForTimeout(1800);
   await tab.screenshot({path:path.join(out,name),fullPage:true});result.screenshots.push(name);
  }finally{await tab.close();}
 }
 result.ok=galleryOnly?result.screenshots.length===3:result.live_metrics.width===720&&result.live_metrics.height===1280&&result.live_metrics.audio_energy>.0001&&result.screenshots.length===6;
}catch(error){result.error=error.message;}
finally{
 if(page)try{await page.evaluate(()=>window.studio?.disconnect());}catch{}
 if(context)await context.close();
 if(video)result.raw_screencast=path.relative(root,await video.path()).replaceAll('\\','/');
 fs.writeFileSync(path.join(out,galleryOnly?'gallery-capture-manifest.json':'capture-manifest.json'),JSON.stringify(result,null,2));
 console.log(JSON.stringify(result));if(!result.ok)process.exitCode=1;
}})();
