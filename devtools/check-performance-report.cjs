// Inspect the delivered static report. All browser tabs are closed in finally.
const fs=require('fs'),path=require('path'),assert=require('assert');
const {pathToFileURL}=require('url');const {chromium}=require('playwright-core');
const root=path.resolve(__dirname,'..'),report=path.join(root,'docs/analysis/2026-10-27');
const out=process.env.REPORT_QA_DIR||path.join(root,'outputs/performance-report-qa');fs.mkdirSync(out,{recursive:true});
const data=JSON.parse(fs.readFileSync(path.join(report,'data/evidence.json'),'utf8'));
let browser;const result={ok:false,checks:[],errors:[],browser_closed:false};
(async()=>{try{
 assert.equal(data.requests.length,32);assert.equal(data.requests.filter(r=>r.status==='COMPLETED').length,31);
 const publicRows=data.requests.filter(r=>r.cohort==='public');assert.equal(publicRows.length,7);
 for(const row of data.requests){assert(Math.abs(row.moss_wall_s/row.audio_seconds-row.moss_rtf)<.0001);assert(row.tts_adapter_s>=row.moss_wall_s);assert(Math.abs(row.dispatch_queue_s+row.llm_or_echo_s+row.tts_adapter_s+row.buffer_to_receipt_s-row.collector_to_first_s)<.001);if(row.status==='COMPLETED'){assert.equal(row.valid_samples,row.played_samples);assert(row.natural_end);assert(row.collector_to_complete_s>row.collector_to_first_s)}else assert.equal(row.collector_to_complete_s,null)}
 const mean=key=>publicRows.reduce((n,r)=>n+r[key],0)/publicRows.length;
 assert(Math.abs(mean('collector_to_first_s')-34.10342857)<.00001);assert(Math.abs(mean('collector_to_complete_s')-44.40257143)<.00001);result.checks.push('32 records; recomputed public means; valid samples and completion states');
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--no-proxy-server']});
 const page=await browser.newPage({viewport:{width:1440,height:1050}});page.on('pageerror',e=>result.errors.push(e.message));
 await page.goto(process.env.REPORT_QA_URL||pathToFileURL(path.join(report,'report.html')).href,{waitUntil:'load'});await page.waitForFunction(()=>window.reportReady);
 assert.equal(await page.locator('#requests-table tbody tr').count(),7);await page.selectOption('#case-select','R03');assert((await page.textContent('#journey-case')).startsWith('R03'));
 await page.selectOption('#cohort','all');assert.equal(await page.locator('#requests-table tbody tr').count(),32);
 await page.selectOption('#case-select','H04');assert((await page.textContent('#journey-end')).includes('未确认'));
 await page.selectOption('#cohort','official');assert.equal(await page.locator('#requests-table tbody tr').count(),5);await page.selectOption('#case-select','C01');assert((await page.textContent('#case-note')).includes('Echo'));
 await page.selectOption('#cohort','public');await page.selectOption('#case-select','R06');
 const initial=await page.textContent('#sim-result');await page.locator('#sim-length').fill('80');assert.notEqual(await page.textContent('#sim-result'),initial);await page.locator('#sim-length').fill('50');
 assert(await page.evaluate(()=>[...document.images].every(img=>img.complete&&img.naturalWidth>0)));
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));result.checks.push('cohort filters, UNKNOWN state, Echo label, simulator and all six images');
 await page.screenshot({path:path.join(out,'report-desktop.png'),fullPage:false});
 await page.locator('#journey').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'report-timeline.png'),fullPage:false});
 await page.setViewportSize({width:390,height:844});await page.evaluate(()=>scrollTo(0,0));assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:path.join(out,'report-mobile.png'),fullPage:false});result.checks.push('1440px and 390px viewports have no document overflow');
 await page.close();assert.equal(result.errors.length,0);result.ok=true;
}catch(e){result.errors.push(e.stack||e.message);process.exitCode=1}finally{if(browser){await browser.close();result.browser_closed=true}fs.writeFileSync(path.join(out,'validation.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));}})();
