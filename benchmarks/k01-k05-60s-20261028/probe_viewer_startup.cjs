const fs=require('fs'),path=require('path');
const root=[process.env.AI_TALK_STREAMER_REPO,path.resolve(__dirname,'../../Ai-Talk-Streamer'),path.resolve(__dirname,'../..')].filter(Boolean).find(p=>fs.existsSync(path.join(p,'node_modules/playwright-core'))),{chromium}=require(path.join(root,'node_modules/playwright-core'));
(async()=>{let browser;try{
 browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--disable-gpu']});
 const context=await browser.newContext();await context.addInitScript(()=>{
  window.__benchmarkPageTest=true;window.__mediaEvents=[];
  for(const name of ['play','playing','pause','waiting','seeking','seeked','error'])document.addEventListener(name,event=>{
   const m=event.target;if(m instanceof HTMLMediaElement)window.__mediaEvents.push({event:name,id:m.id,at:performance.now(),time:m.currentTime,paused:m.paused,seeking:m.seeking,ready:m.readyState});
  },true);
 });
 const page=await context.newPage();await page.goto('http://127.0.0.1:8037/');await page.waitForSelector('#rows tr');await page.locator('#play').click();await page.waitForTimeout(5000);
 const result=await page.evaluate(()=>({note:document.getElementById('play-note').textContent,media:['master','va','vb'].map(id=>{const m=document.getElementById(id);return{id,time:m.currentTime,paused:m.paused,seeking:m.seeking,ready:m.readyState}}),events:window.__mediaEvents}));
 const folder=process.argv.includes('--after')?'browser-after-startup-fix':'browser-before-startup-fix';
 const out=path.resolve(root,'../outputs/lipsync-k01-k05-60s-20261028/diagnostics/'+folder+'/startup-event-trace.json');fs.mkdirSync(path.dirname(out),{recursive:true});fs.writeFileSync(out,JSON.stringify(result,null,2));console.log(JSON.stringify(result));await context.close();
}finally{if(browser)await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
