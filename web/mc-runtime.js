const $ = selector => document.querySelector(selector), prefix = '/api/mc-runtime';
const actions = {start:'启动直播服务',stop:'停止直播服务',status:'检查当前状态',preflight:'检查运行环境'};
const states = {accepted:'已排队',running:'执行中',succeeded:'已完成',failed:'未完成',cancelled:'已取消',interrupted:'已中断'};
const messages = {
  MC_APPLICATION_SERVICES_STARTED_REQUIRED_INTEGRATION_PENDING:'后台服务已启动，直播内容与正式画面仍需核对。',
  MC_APPLICATION_SERVICES_STARTED:'后台服务已启动。', MC_APPLICATION_START_FAILED:'运行环境尚未准备好，请先检查运行环境。',
  MC_APPLICATION_STOP_FAILED:'停止未完成，请检查当前状态并查看操作记录。',
  MC_APPLICATION_STOP_REQUIRES_OFFAIR:'请先结束本场直播，再停止直播服务。',
  MC_APPLICATION_DSH_STOP_STATE_UNAVAILABLE:'暂时无法确认直播状态，保留服务并稍后检查。',
  MC_APPLICATION_ROOT_MISMATCH:'当前管理台与安装目录不匹配，请打开该安装自己的管理台。',
  MC_NATIVE_OPERATION_BUSY:'另一项安装或服务操作正在进行，请等待它结束。',
  MC_APPLICATION_SERVICE_NOT_OWNED_OR_LISTENING:'服务未运行，或尚未确认属于当前安装。',
  MC_APPLICATION_DEPENDENCY_UNAVAILABLE:'暂时无法读取，请检查运行环境。',
  MC_APPLICATION_DEPENDENCY_NOT_READY:'仍在准备，或配置尚未匹配。',
  MC_APPLICATION_CONFIG_UNAVAILABLE:'尚未完成本机配置。', MC_APPLICATION_OFFICIAL_CAPTURE_NOT_VERIFIED:'正式画面采集尚未验证。',
  MC_APPLICATION_MANAGED_SERVICE_STOPPED:'本次停止已完成。',
  MC_APPLICATION_NEW_AVATAR_PACKS_NOT_ACCEPTED:'圆形与横屏两套人物素材尚未制作并验收。',
  MC_APPLICATION_START_TIMEOUT:'服务等待超时，请核对回收结果和当前状态。',
  MC_APPLICATION_SERVICE_EXITED_DURING_START:'启动中的服务退出，请核对回收结果。',
  MC_APPLICATION_VISION_PIN_CHANGED:'视觉文件与已核对版本不一致，请检查本机文件。',
  MC_APPLICATION_VISION_LOCAL_ONLY:'视觉服务地址尚未符合本机运行配置。',
  MC_MAINTENANCE_CONSOLE_STOPPING:'管理台正在关闭，当前作业会先完成。',
  MC_MAINTENANCE_CONSOLE_STORAGE_FAILED:'操作记录暂时无法保存，请先查证已受理的操作。',
  MC_MAINTENANCE_CONSOLE_INTERRUPTED:'管理台曾中断；这条操作不会自动重做。',
  MC_MAINTENANCE_CONSOLE_STOPPED:'管理台关闭前尚未开始这条操作。',
  MC_MAINTENANCE_QUEUE_FULL:'等待中的操作较多，请等待已有操作完成。',
  MC_MAINTENANCE_CONSOLE_CAPACITY:'操作记录已达到容量上限，请整理后再继续。',
  MC_MAINTENANCE_REQUEST_CONFLICT:'这个请求编号对应另一项操作，请先查询原记录。',
  MC_MAINTENANCE_CANCEL_BLOCKED:'该操作已经开始或结束，请查看结果。',
  MC_MAINTENANCE_JOB_NOT_FOUND:'暂未找到原请求，请保留编号后再查询。',
  MC_MAINTENANCE_INSTALLATION_CHANGED:'安装内容已变更，请重新打开管理台后再启动服务。',
  MC_DEVICE_UNAVAILABLE:'未找到符合配置的3080设备。', MC_PREPARATION_FILE_MISSING_OR_LARGE:'原生运行准备尚未完成。',
  MC_RUNTIME_FILES_UNAVAILABLE:'运行文件尚未准备齐全。', MC_PREPARATION_SERVICE_PORT_BUSY:'已有服务占用，请先核对当前状态。'
};
const describe = code => messages[code] || '尚未通过核对，可检查运行环境并查看操作编号。';
const names = {profile:'部署配置',source:'安装来源',game_files:'游戏整合包与资源',device:'运行设备',native:'原生环境',runtime_files:'运行文件',idle:'服务占用'};
let connected=false, closing=false, timer=null, binding=null, pending=null, nextBefore=null, through=0, paged=false;
let sending=false, polling=false, lastObservation=null;
const jobs=new Map(), rows=new Map(), storageKey='mc-runtime-pending-v1';
const node=(tag,text,className)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(className)el.className=className;return el;};
function notice(text,error=false){$('#notice').textContent=text;$('#notice').classList.toggle('error',error);$('#notice').hidden=!text;}
function saved(){try{return JSON.parse(localStorage.getItem(storageKey)||'null');}catch{return null;}}
function save(value){try{value?localStorage.setItem(storageKey,JSON.stringify(value)):localStorage.removeItem(storageKey);}catch{/* Durable server records remain authoritative. */}}
function controls(){for(const id of ['start-services','stop-services','check-status','preflight'])$( `#${id}`).disabled=!connected||closing||sending||!!pending;}
function pendingView(){ $('#pending-request').hidden=!pending;$('#pending-copy').textContent=pending?'请求已保存；如果页面没有收到结果，请查询原请求。':'';controls(); }
async function api(path,body){
  const response=await fetch(prefix+path,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),cache:'no-store',signal:AbortSignal.timeout(20000)});
  const value=await response.json();if(!response.ok){const error=new Error(describe(value.code));error.code=value.code;throw error;}return value;
}
function observe(observation){
  if(!observation||observation.job_id===lastObservation)return;lastObservation=observation.job_id;
  const result=observation.result||{};
  if(result.checks){
    for(const item of document.querySelectorAll('[data-check]')){
      const check=result.checks[item.dataset.check];if(!check)continue;
      const stopped=check.code==='MC_APPLICATION_MANAGED_SERVICE_STOPPED';
      item.dataset.ready=stopped?'stopped':String(check.ready===true);item.querySelector('strong').textContent=stopped?'已停止':check.ready?'已就绪':'待就绪';
      item.querySelector('.service-help').textContent=check.ready?'本次核对通过':describe(check.code);
    }
    $('#readiness').textContent=result.application_ready?'各项已就绪':result.services_ready?'后台已就绪 · 直播待核对':'仍有项目待就绪';
    $('#readiness').dataset.ready=String(result.application_ready===true);
    $('#readiness-copy').textContent=result.application_ready?'本次运行核对通过；正式开播仍以直播操作和验收要求为准。':result.services_ready?'人物、语音、游戏、视觉和接收服务已就绪；正式采集与人物素材验收仍需核对。':'请根据下方结果完成配置，再启动服务或重新核对。';
  }
  if(result.preflight){$('#environment').hidden=false;$('#environment-checks').replaceChildren(...result.preflight.map(item=>{
    const li=node('li');li.append(node('span',names[item.name]||'运行项目'),node('span',item.ready?'已通过':describe(item.code)));return li;}));}
  $('#observation-time').textContent='最近一次操作结果：'+formatTime(observation.finished_at)+'。这是该时刻的核对记录。';
}
function formatTime(value){const date=new Date(value);return Number.isFinite(date.valueOf())?date.toLocaleString('zh-CN',{hour12:false}):'尚未记录时间';}
function finishPending(job){if(pending&&job.request_id===pending.request.request_id){pending=null;save(null);pendingView();}}
function renderJob(job){
  let row=rows.get(job.job_id);const revision=JSON.stringify([job.state,job.outcome,job.code,job.finished_at]);
  if(row?.dataset.revision===revision)return row;
  row=row||node('li');row.className='job-row'+(job.state==='failed'?' failed':'')+(job.outcome==='unknown'?' uncertain':'');
  row.dataset.jobId=job.job_id;row.dataset.revision=revision;
  const copy=node('div'), heading=node('h3',(actions[job.action]||'服务操作')+' · '+(states[job.state]||'待查证'));
  copy.append(heading,node('p',formatTime(job.created_at),'muted'));
  if(job.code)copy.append(node('p',describe(job.code)));
  if(job.outcome==='unknown')copy.append(node('p','实际结果尚未确认。请先检查当前状态，再决定后续操作。'));
  if(job.result?.operation_phase==='ROLLED_BACK')copy.append(node('p',job.result.rollback_complete?'本次新增进程已回收；原有服务保持运行。':'回收尚未确认，请检查当前状态。'));
  if(job.action==='stop'&&job.state==='succeeded')copy.append(node('p','受管游戏、视觉与直播后台已停止。官方直播姬中的外部开播状态请在客户端核对。'));
  const details=node('details'),summary=node('summary','查看操作编号');details.append(summary,node('p','请求：'+job.request_id,'code'),node('p','作业：'+job.job_id,'code'));
  if(job.code)details.append(node('p','结果：'+job.code,'code'));copy.append(details);
  const buttons=node('div',undefined,'buttons');if(job.state==='accepted'){
    const cancel=node('button','取消排队','secondary');cancel.addEventListener('click',async()=>{cancel.disabled=true;try{const result=await api('/jobs/'+job.job_id+'/cancel',{});acceptJob(result);await refresh();}catch(error){notice(error.message,true);cancel.disabled=false;}});buttons.append(cancel);
  }
  row.replaceChildren(copy,buttons);rows.set(job.job_id,row);return row;
}
function renderJobs(){
  const list=$('#jobs');if(!jobs.size){list.replaceChildren(node('li','尚无操作记录','empty'));return;}
  for(const empty of list.querySelectorAll('.empty'))empty.remove();
  let cursor=list.firstChild;for(const job of [...jobs.values()].sort((a,b)=>b.seq-a.seq)){
    const row=renderJob(job);if(row===cursor)cursor=cursor.nextSibling;else list.insertBefore(row,cursor);
  }
}
function acceptJob(job){jobs.set(job.job_id,job);finishPending(job);renderJobs();}
async function refresh(){
  if(polling||closing)return;polling=true;
  try{
    const [state,page]=await Promise.all([api('/state'),api('/jobs')]);connected=true;binding=state.binding_sha256;
    $('#connection').textContent=state.stopping?'管理台正在关闭':'管理台已连接';closing=!!state.stopping;
    $('#maintenance-hint').textContent=state.maintenance_configured?'停播后的历史整理可在历史维护中进行。':'历史维护尚未配置游戏记录位置；运行管理可以独立使用。';
    if(!paged){nextBefore=page.next_before;through=page.through;}
    for(const job of page.items)acceptJob(job);
    observe(state.latest);$('#more-jobs').hidden=!nextBefore;
    if(state.fault)notice(describe(state.fault),true);
  }catch(error){connected=false;$('#connection').textContent='暂时无法连接';notice('无法读取管理台状态。已受理的操作不会因此重新执行。',true);}
  finally{polling=false;controls();schedule();}
}
function schedule(){clearTimeout(timer);if(!closing&&!document.hidden)timer=setTimeout(refresh,1500);}
async function submit(action){
  if(!connected||closing||sending||pending)return;
  sending=true;const request={action,request_id:crypto.randomUUID()};pending={binding,request};save(pending);pendingView();notice('正在提交'+actions[action]+'…');
  try{const result=await api('/jobs',request);acceptJob(result.job);notice(result.duplicate?'已找到原操作记录。':'操作已受理，可以在下方查看结果。');await refresh();}
  catch(error){notice('暂未确认请求是否受理，请查询原请求；不会自动重新提交。',true);}
  finally{sending=false;pendingView();}
}
async function findPending(){
  if(!pending)return;$('#find-request').disabled=true;
  try{const job=await api('/requests/'+encodeURIComponent(pending.request.request_id));acceptJob(job);notice('已找到原操作记录。');await refresh();}
  catch(error){notice(error.message,true);}finally{$('#find-request').disabled=false;}
}
$('#start-services').addEventListener('click',()=>submit('start'));$('#stop-services').addEventListener('click',()=>submit('stop'));
$('#check-status').addEventListener('click',()=>submit('status'));$('#preflight').addEventListener('click',()=>submit('preflight'));
$('#refresh').addEventListener('click',refresh);$('#find-request').addEventListener('click',findPending);
$('#more-jobs').addEventListener('click',async()=>{if(!nextBefore)return;const button=$('#more-jobs');button.disabled=true;try{const page=await api('/jobs?before='+nextBefore+'&through='+through);paged=true;nextBefore=page.next_before;for(const job of page.items)acceptJob(job);button.hidden=!nextBefore;}catch(error){notice(error.message,true);}finally{button.disabled=false;}});
$('#close-console').addEventListener('click',async()=>{const button=$('#close-console');button.disabled=true;try{await api('/close',{});closing=true;clearTimeout(timer);$('#connection').textContent='管理台正在关闭';notice('管理台正在关闭，当前作业会先完成。直播服务继续运行。');controls();}catch(error){notice(error.message,true);button.disabled=false;}});
document.addEventListener('visibilitychange',()=>{if(document.hidden)clearTimeout(timer);else void refresh();});
window.addEventListener('pagehide',()=>{closing=true;clearTimeout(timer);});
window.addEventListener('pageshow',event=>{if(event.persisted){closing=false;void refresh();}});
await refresh();
const original=saved();if(original&&typeof original.request?.request_id==='string'&&actions[original.request.action]){
  if(original.binding===binding){pending=original;pendingView();await findPending();}
  else notice('此地址的安装已变更。旧请求未重新提交，请到原安装核对记录。',true);
}
pendingView();
