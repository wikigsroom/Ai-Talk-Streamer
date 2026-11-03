import { playerSafety } from './mc-player-safety.mjs';
const $ = id => document.getElementById(id), apiBase = '/api/dsh/game';
const labels = { PAUSED:'已暂停', AUTO:'自动游玩', MANUAL_COMMENTARY:'人工游玩', draft:'待批准', active:'进行中', needs_review:'待复核', blocked:'待处理', completed:'已完成', archived:'已归档', pending:'待执行', running:'执行中', awaiting_observation:'等待观测', accepted:'已受理', succeeded:'成功', failed:'失败', cancelled:'已取消', verified:'已验证', partial:'部分生效', unknown:'结果未知', required:'待核对', querying:'核对中', waiting_terminal:'等待结束', missing:'账本缺失', conflict:'记录冲突', unsupported:'暂不支持核对', operator_closed:'人工确认未知', closed_unknown:'人工确认未知', reopened:'已重新拦截', observed:'观测中', unobserved:'当前不可观测', ended:'观测会话结束', gather:'采集', craft:'合成', use_item:'使用物品', navigate:'移动', return_base:'回基地' };
const model = { state:null, health:null, synchronized:false, configuration:null, capabilities:null, goals:[], sessions:[], tasks:[], bases:[], checkpoints:[], worlds:[], suggestions:[], votes:[], narration:[], narrationScheduler:null, narrationSettingsDirty:false, audience:null, audienceKey:null, world:null, worldRecord:null, selection:null, cursors:{}, busy:false };
Object.assign(model,{intents:[],intentSettingsDirty:false});
try { const saved=sessionStorage.getItem('mc-control.world'); if(saved&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(saved)) model.selection=saved; } catch {}
let viewRevision=0;
const text = value => labels[value] || value || '—', uid = () => 'operator-' + crypto.randomUUID();
const node = (tag, value, cls) => { const el = document.createElement(tag); if (value !== undefined) el.textContent = value; if (cls) el.className = cls; return el; };
const time = value => value ? new Date(value).toLocaleString('zh-CN', { hour12:false }) : '未记录';
const fresh = () => model.synchronized && !model.health?.storage_error && model.state?.connected && model.state.freshness === 'fresh';
const currentView = () => !!model.world && model.world === model.state?.world_id;
const stopped = () => currentView() && !!model.worldRecord && fresh() && model.state.mode !== 'AUTO' && model.state.inputs_released && !model.state.automation_ready && !model.state.active_task_id;
const context = () => ({ request_id:uid(), bridge_boot_id:model.state.bridge_boot_id, world_session_id:model.state.world_session_id });
const showNotice = value => { $('notice').textContent = value; $('notice').hidden = !value; };
const errors = { GAME_STATE_STALE:'游戏观测已过期，请等待新的观测。', GAME_DISCONNECTED:'游戏连接已断开。', GAME_STORAGE_ERROR:'游戏服务存储异常，请查看连接与故障记录，恢复后重新核对游戏状态。', GAME_WORLD_GOAL_BUSY:'请先暂停操作，等待游戏确认输入已释放且当前任务已停止。', GAME_DISPOSITION_BRIDGE_BUSY:'请先暂停并等待游戏确认当前任务为空。', GAME_DISPOSITION_CONFLICT:'任务版本已变化，请刷新后重新核对。', GAME_DISPOSITION_OBSERVATION_CHANGED:'游戏观测已变化，请刷新后重新核对。', GAME_WORLD_GOAL_CONFLICT:'目标已更新，请刷新后重新复核。', GAME_WORLD_GOAL_UNKNOWN_EFFECT:'请先核对该步骤关联任务，记录未知结果后再允许重新规划。', GAME_WORLD_GOAL_RETRY_REQUIRED:'请先处理未完成的任务或允许阻塞步骤重新规划。', GAME_RECOVERY_REQUIRED:'仍有执行结果待核对，请先处理任务记录。', GAME_DISABLED:'MC 功能尚未启用。', GAME_TASK_BUSY:'仍有任务待完成或核对。', GAME_CAPABILITY_UNAVAILABLE:'游戏端尚未提供这项能力。' };
Object.assign(errors, { GAME_SUGGESTION_CONFLICT:'建议已更新，请刷新后重新复核。', GAME_SUGGESTION_EXPIRED:'这项建议已过期，请根据当前游戏重新提议。', GAME_SUGGESTION_NOT_ACCEPTED:'请先复核并采纳这项建议。', GAME_SUGGESTION_SOURCE_UNAVAILABLE:'建议来源已被屏蔽、移除或已切换房间，请重新核对。', GAME_MODE_BLOCKED:'请先明确允许自动游玩，并等待游戏端确认。', GAME_AUDIENCE_BUSY:'已有一项建议正在核验，请等待结果。', GAME_PRECONDITION_FAILED:'当前游戏条件不满足目标，请查看现况后再决定。', GAME_VOTE_ACTIVE:'已有投票进行中，请先结束或取消。', GAME_VOTE_CONFLICT:'投票已更新，请刷新后再操作。', GAME_VOTE_WINNER_REQUIRED:'请先结束投票，并明确选择平票结果。', GAME_VOTE_RESULT_EXPIRED:'投票结果已过时，请按当前游戏重新发起。', GAME_PLATFORM_ROOM_UNAVAILABLE:'请先在平台连接页保存 B 站房间。', GAME_QUERY_CANCELLED:'游戏控制或观测已变化，本次核验已取消。', GAME_IDEMPOTENCY_CONFLICT:'这次操作的内容已变化，请刷新后重新提交。' });
Object.assign(errors, { GAME_WORLD_CONFLICT:'世界或基地记录已更新，请刷新后再核对。', GAME_WORLD_CHANGED:'当前游戏世界已变化，请返回实况重新核对。', GAME_BASE_ARCHIVED:'这处基地已归档，请选择其他基地。', GAME_WORLD_VIEW_CHANGED:'查看的世界已变化，请重新打开记录。', GAME_WORLD_NOT_FOUND:'这份世界记录已不存在，请返回当前实况。' });
function explain(error) { return errors[error.message] || window.McTaskFailures.describe(error.message)?.detail || '操作未完成：' + error.message; }
async function api(path, body) { const response = await fetch(apiBase + path, { method:body === undefined ? 'GET':'POST', headers:body === undefined ? {}:{'Content-Type':'application/json'}, ...(body === undefined ? {}:{body:JSON.stringify(body)}), cache:'no-store' }); const value = await response.json(); if (!response.ok) throw new Error(value.error || String(response.status)); return value; }
function action(label, handler, { disabled = false, secondary = true } = {}) { const button = node('button', label, secondary ? 'secondary':''); button.type = 'button'; button.disabled = disabled || model.busy; button.addEventListener('click', () => run(handler)); return button; }
function renderAll() { renderState();renderWorldBrowser();renderGoals();renderSessions();renderTasks();renderAudience();renderIntents();renderNarration();renderHistory();renderPlaySettings();renderClientFacts(); }
let playSettingsDirty=false;
function renderPlaySettings(){
  const value=model.configuration,form=$('play-settings-form'),settings=value?.settings;
  $('play-settings-fields').disabled=model.busy||!value||!!model.health?.storage_error;
  $('play-settings-state').textContent=value?`设置版本 ${value.revision}`:'正在读取';
  if(!settings||playSettingsDirty)return;
  form.dataset.revision=value.revision;form.elements.enabled.checked=settings.enabled;
  form.elements.planner.checked=settings.planner.enabled;
  form.elements.autostart.checked=!!settings.planner.autostart;
  form.elements.avatar_variant.value=settings.programme.avatar_variant;
  form.elements.comment_mode.value=settings.programme.comment_mode;
  for(const input of form.querySelectorAll('[name=skill]'))input.checked=settings.control.enabled_skills.includes(input.value);
}
function renderClientFacts(){
  const state=model.state,details=state?.details,box=$('client-facts-inventory');box.replaceChildren();
  $('client-facts-state').textContent=!fresh()?'等待新鲜观测':details?'现场已同步':'等待详细信息';
  if(!fresh()||!details){$('client-facts-copy').textContent='等待游戏提供新鲜的界面、背包和环境信息。';return;}
  const risks=[];if(details.hazards.on_fire)risks.push('着火');if(details.hazards.in_lava)risks.push('熔岩');if(details.hazards.in_water)risks.push('水中');
  $('client-facts-copy').textContent=`${details.gui.title||'游戏画面'} · ${details.environment.raining?'下雨':'无雨'} · 附近敌人 ${details.nearby_hostiles.length}${details.hostiles_truncated?'以上':''} · ${risks.join('、')||'当前未报告上述危险'}`;
  for(const [label,slots] of [['背包',details.inventory_slots],['当前容器',details.gui.slots]]){
    const group=node('section');group.append(node('h3',label));const used=slots.filter(slot=>slot.count>0);
    if(!used.length)group.append(node('p','没有当前可见物品','muted'));
    for(const slot of used)group.append(node('p',`槽位 ${slot.slot} · ${slot.item_id} × ${slot.count}${slot.max_damage===null?'':` · 耐久 ${slot.max_damage-slot.damage}/${slot.max_damage}`}`));box.append(group);
  }
}
Object.assign(errors,{GAME_INTENT_CONFLICT:'这条建议已更新，请刷新后重新核对。',GAME_INTENT_CLOSED:'这条建议已处理，请查看最新记录。',GAME_INTENT_EXPIRED:'建议已超过有效时间，请观众重新提出。',GAME_INTENT_CONTEXT_CHANGED:'房间或游戏世界已变化，请重新提出建议。',GAME_INTENT_DISABLED:'自然语言建议当前已关闭。',GAME_INTENT_SOURCE_REMOVED:'原弹幕已撤回、删除或屏蔽。'});
const intentLabels={pending:'等待理解',interpreting:'正在理解',clarification:'等待补充',proposed:'已生成待审核建议',ignored:'普通聊天',failed:'理解未完成',cancelled:'已取消',expired:'已过期',superseded:'已收到补充'};
let selectedIntent,intentsExpanded=false;
function renderIntents() {
  const settings=model.configuration?.settings.audience_intents,status=model.audience?.natural_language,form=$('intent-settings-form');
  if(settings&&!model.intentSettingsDirty){form.elements.enabled.checked=settings.enabled;form.dataset.revision=model.configuration.revision;}
  form.querySelector('button[type=submit]').disabled=model.busy||!model.configuration||!!model.health?.storage_error;
  $('intent-status').textContent=!status?.enabled?'当前关闭':!status.model_ready?'等待对话模型就绪':`${status.running?'正在理解 · ':''}${status.pending} / ${status.pending_limit} 条待处理`;
  const box=$('intents');box.replaceChildren();
  const values=model.intents.filter(value=>$('intent-filter').value==='all'||['pending','interpreting','clarification'].includes(value.state));
  if(!values.length)box.append(node('p','观众可用自然说法提出玩法建议；缺少的信息会先询问补充。','empty'));
  for(const value of values) {
    const card=node('article',undefined,'audience-card');card.dataset.intent=value.audience_intent_id;
    const head=node('div',undefined,'section-head');head.append(node('h4',value.goal?goalLabel(value.goal):value.question||'观众的玩法建议'),node('span',intentLabels[value.state]||value.state,'badge'));card.append(head);
    card.append(node('p',`${value.source_event_ids.length} 条来源 · 截止 ${time(value.expires_at)}`,'muted'));
    if(value.state==='proposed')card.append(node('p','请在弹幕建议中复核。当前尚未采纳或执行。','muted'));
    if(value.state==='failed')card.append(node('p','本次未能理解，可请观众重新提出。','muted'));
    if(['pending','interpreting','clarification'].includes(value.state)) {
      const disabled=!fresh()||!settings?.enabled||Date.parse(value.expires_at)<=Date.parse(model.audience?.server_time||0);
      const buttons=node('div',undefined,'buttons');buttons.append(action('补全为待审核建议',()=>openIntent(value),{disabled}),
        action('忽略此条',()=>api('/audience/intents/'+value.audience_intent_id+'/decision',{request_id:uid(),expected_revision:value.revision,action:'dismiss'}),{disabled}));card.append(buttons);
    }
    box.append(card);
  }
  $('more-intents').hidden=!model.cursors.intents;$('more-intents').disabled=model.busy;
  $('refresh-intents').disabled=model.busy;$('intent-page-hint').textContent=intentsExpanded?'已展开较早记录。查看最新建议请刷新理解记录。':'';
}
const intentContextMatches=value=>value.room_id===model.audience?.room_id&&value.world_session_id===model.state?.world_session_id;
function mergeIntents(page,reset=false){if(reset)intentsExpanded=false;const values=page.items.filter(intentContextMatches),byId=new Map(values.map(value=>[value.audience_intent_id,value]));model.intents=intentsExpanded?model.intents.map(value=>byId.get(value.audience_intent_id)||value):values;if(!intentsExpanded)model.cursors.intents=page.next_cursor;}
function openIntent(value) {
  selectedIntent=structuredClone(value);$('intent-error').textContent='';$('intent-context').textContent=value.question||'请按原观众的意思补全目标。';
  const editor=$('intent-goal');editor.replaceChildren();
  const skill=selectField(editor,'建议目标','vote_skill',[['gather','采集物品'],['craft','合成物品'],['use_item','使用物品'],['navigate','移动到坐标'],['return_base','回到基地']]),params=node('div');editor.append(params);editor.goalParams=params;
  function fields(){params.replaceChildren();
    if(['gather','craft'].includes(skill.value))inputField(params,'物品 ID','item_id','');
    if(['gather','craft'].includes(skill.value)){const count=inputField(params,skill.value==='gather'?'额外采集数量':'新增产物数量','count','','number');count.min=1;count.max=4096;}
    if(skill.value==='use_item')itemUseFields(params);
    if(skill.value==='return_base')inputField(params,'已登记的基地 ID','base_id',model.state?.world_ledger?.active_base?.base_id||'');
    if(skill.value==='navigate'){for(const key of ['dimension','x','y','z'])inputField(params,key==='dimension'?'维度':key.toUpperCase(),key,'',key==='dimension'?'text':'number');const radius=inputField(params,'到达半径','radius','','number');radius.min=.5;radius.max=8;radius.step=.5;}
  }
  skill.addEventListener('change',fields);fields();$('intent-dialog').showModal();
}
Object.assign(model,{historyStatus:null,historyEntries:[],historyKind:'',historyError:null});
Object.assign(errors,{GAME_HISTORY_MODE_BLOCKED:'请先暂停游戏操作，并等待输入释放与当前任务结束。',GAME_HISTORY_BUSY:'已有历史导入正在进行。',GAME_HISTORY_CONTEXT_CHANGED:'游戏连接或世界已变化，请重新导入。',GAME_HISTORY_IMPORT_LIMIT:'导入记录已达到容量上限，请先维护历史记录。'});
const historyReasons={GAME_HISTORY_DISCONNECTED:'游戏已断线，已保留导入完成的记录。',GAME_HISTORY_CONTEXT_CHANGED:'游戏世界或连接已变化，本次导入已中止。',GAME_HISTORY_CONNECTION_UNAVAILABLE:'游戏观测已过期，请等待新观测后重新导入。',GAME_HISTORY_MODE_BLOCKED:'游戏已恢复操作，本次导入已中止。',GAME_HISTORY_MODE_CHANGED:'已恢复自动游玩，本次导入已中止。',GAME_HISTORY_CANCELLED:'本次导入已取消，已完成的记录继续保留。',GAME_HISTORY_HOST_RESTART:'服务已重启，请重新开始导入。',GAME_HISTORY_CAPACITY:'历史容量已满，请维护历史记录后再导入。',GAME_OPERATION_TIMEOUT:'游戏端未及时返回历史，请核对连接后重新导入。'};
const historyTypes={game_event:'游戏事件',task_update:'任务递送记录',task_version:'任务版本',retention_summary:'保留汇总',retired_task:'任务防重记录',retention_run:'维护结果'};
const historySources={reliable:'事件与递送记录',task_versions:'全部任务版本',retention_summaries:'保留汇总',retired_tasks:'任务防重记录',retention_runs:'维护结果'};
const historyMaintenance=entry=>['retention_summaries','retired_tasks','retention_runs'].includes(entry.source);
function historyTitle(summary) {
  if(summary.kind==='retention_summary')return `${summary.utc_day} · ${summary.category==='task'?'任务':'事件'} ${text(summary.event_kind)} · ${summary.count} 条`;
  if(summary.kind==='retired_task')return `${text(summary.skill)} · v${summary.version} · 任务防重记录`;
  if(summary.kind==='retention_run')return `维护完成 · 事件 ${summary.counts.events} 条、任务 ${summary.counts.tasks} 条`;
  return summary.kind==='task'?`${text(summary.skill)} · v${summary.version} · ${text(summary.state)}`:summary.event_kind;
}
const historyContextLabel=entry=>historyMaintenance(entry)?`${entry.metadata.world_session_id||'跨世界维护'} · 历史存档`:`${entry.metadata.world_session_id} · 原序号 ${entry.metadata.sequence}`;
let historyRevision=0,historyDetailRevision=0,historyExpanded=false;
function renderHistory() {
  const status=model.historyStatus,job=status?.latest_import,active=status?.current_import_running;
  $('history-count').textContent=status?`已存 ${status.totals.records} 条历史`:'等待历史记录';
  $('history-refresh').disabled=model.busy;
  $('history-import').disabled=model.busy||!fresh()||model.state.mode==='AUTO'||!model.state.inputs_released||!!model.state.active_task_id||!model.capabilities?.features.journal_history||!!active;
  $('history-cancel').hidden=!active;$('history-cancel').disabled=model.busy||!!model.health?.storage_error;
  let progress=job?(active?`正在读取${historySources[job.source]||'历史'}，已核对 ${job.scanned_records} 条，新增 ${job.imported_records} 条，重复 ${job.duplicate_records} 条。关闭本页后仍会继续。`:
    job.state==='completed'?`导入完成：核对 ${job.scanned_records} 条，新增 ${job.imported_records} 条，重复 ${job.duplicate_records} 条。`:
    historyReasons[job.reason]||'导入未完成，请核对连接或查看原文后重新导入。'):'暂停游戏操作并等待输入释放后，可从游戏端导入历史。查询历史不会重放任务。';
  if(model.historyError)progress='历史暂时无法读取，请核对服务连接后重试。';
  if(historyExpanded&&!model.historyError)progress+=' 最新记录可点“刷新列表”查看。';
  $('history-progress').textContent=progress;
  const list=$('history-entries');list.replaceChildren();
  if(!model.historyEntries.length)list.append(node('li','尚无导入记录。连接游戏并暂停操作后，可导入其保存的历史。','empty'));
  for(const entry of model.historyEntries) {
    const info=entry.metadata,summary=entry.summary,row=node('li',undefined,'history-row');row.dataset.history=entry.record_key;
    const copy=node('div'),title=historyTitle(summary);
    const disposition=historyMaintenance(entry)?`读取于 ${time(entry.last_projected_at)}`:`${info.acked_at!==null?'已确认':info.archived_at!==null?'已归档':'尚未确认'}${entry.metadata_conflict?' · 确认信息存在差异，保留原记录':''}`;
    copy.append(node('strong',title),node('p',`${historyTypes[info.type]} · ${historyContextLabel(entry)}`,'code'),
      node('p',`${time(info.recorded_at)} · ${disposition}`,'muted'));
    row.append(copy,action('查看原文',()=>openHistory(entry.record_key)));list.append(row);
  }
  $('more-history').hidden=!model.cursors.history;$('more-history').disabled=model.busy;
}
function historyPath(cursor) {const query=new URLSearchParams();if(model.historyKind)query.set('kind',model.historyKind);if(cursor)query.set('cursor',cursor);return '/history/entries'+(query.size?'?'+query:'');}
async function refreshHistory({reset=false,cursor}={}) {
  const revision=historyRevision;
  try {
    const [status,page]=await Promise.all([api('/history/status'),api(historyPath(cursor))]);
    if(revision!==historyRevision)return;
    const old=reset?[]:model.historyEntries,byKey=new Map(page.items.map(item=>[item.record_key,item]));
    const expanded=historyExpanded&&!reset;
    model.historyEntries=cursor?[...old,...page.items.filter(item=>!old.some(previous=>previous.record_key===item.record_key))]:expanded?old.map(item=>byKey.get(item.record_key)||item):page.items;
    if(cursor||!expanded)model.cursors.history=page.next_cursor;
    if(cursor)historyExpanded=true;
    model.historyStatus=status;model.historyError=null;
  } catch(error) {if(revision!==historyRevision)return;model.historyError=error.message;}
  renderHistory();
}
async function openHistory(key) {
  const revision=++historyDetailRevision,entry=await api('/history/entries/'+key);if(revision!==historyDetailRevision)return;
  $('history-view-heading').textContent=historyTypes[entry.metadata.type]+'原文';
  $('history-view-context').textContent=historyContextLabel(entry);
  $('history-view-record').textContent=JSON.stringify(entry,null,2);$('history-view-dialog').showModal();
}
const narrationReasons={QUEUE_REPLACED:'队列已满，本条已让出位置。',OPERATOR_CANCEL:'导播已取消此条回应。',VIEWER_COOLDOWN:'短时间内的重复提问已略过。',HOST_RESTART:'服务已重启，旧回应不再补播。',HOST_SHUTDOWN:'服务已停止，本条未确认播完。',GAME_NARRATION_EXPIRED:'已超过回应有效时间。',GAME_NARRATION_SOURCE_REMOVED:'来源已删除或屏蔽，本条已停止。',GAME_NARRATION_FACTS_CHANGED:'游戏信息已变化，旧回应已停止并重新核对。',GAME_NARRATION_WORLD_CHANGED:'游戏世界或房间已变化，本条已停止。',GAME_NARRATION_BROADCAST_CHANGED:'节目已变更，旧回应已停止。',GAME_NARRATION_STATE_STALE:'游戏信息暂未更新，本条已停止。',GAME_NARRATION_DISABLED:'游戏互动已停用。',GAME_NARRATION_LINK_MISSING:'回应记录不完整，本条已停止。',REQUEST_CANCELLED:'相关口播已取消。',PLAYBACK_COMPLETION_UNPROVEN:'尚无有效的正式播完记录。'};
Object.assign(errors,{GAME_NARRATION_CONFLICT:'回应记录已更新，请刷新后重新操作。',GAME_NARRATION_NOT_FOUND:'这条回应记录已不存在，请刷新列表。'});
Object.assign(errors,{GAME_CONFIG_CONFLICT:'设置已被其他操作更新。请先载入当前设置，再核对修改。'});
Object.assign(errors,{PLATFORM_SOURCE_REMOVED:'关联留言已撤回或屏蔽，相关建议或投票结果已取消；此前游戏效果仍按实际记录保留。'});
Object.assign(narrationReasons,{CRITICAL_EVENT_PREEMPTED:'因严重游戏危险，本条回应已中断。',CRITICAL_CANCEL_UNCONFIRMED:'危险提醒已请求停止上一条回应，停止结果尚未确认。'});
const narrationNumberFields=['merge_window_ms','aging_step_ms','topic_cooldown_ms','interrupt_fresh_ms','interrupt_cooldown_ms'];
function renderNarrationSettings() {
  const form=$('narration-settings-form'),settings=model.configuration?.settings.narration;
  $('narration-settings-fields').disabled=model.busy||!model.synchronized||!settings;
  if(settings&&!model.narrationSettingsDirty) {
    form.dataset.revision=model.configuration.revision;
    for(const name of ['enabled','critical_interrupt'])form.elements[name].checked=settings[name];
    for(const name of narrationNumberFields)form.elements[name].value=settings[name]/1000;
  }
  const scheduler=model.narrationScheduler,next=model.narration.find(item=>item.narration_id===scheduler?.next_narration_id);
  let status=settings?.enabled===false?'自动回应已关闭':next?'下一条回应已安排，等待当前口播结束。':'等待新的互动。';
  if(scheduler?.last_interruption)status+=scheduler.last_interruption.status==='cancel_requested'?' 最近一次危险提醒已请求中断普通回应。':' 最近一次中断尚未确认，请核对声音。';
  $('narration-scheduling').textContent=status;
}
function renderNarration() {
  renderNarrationSettings();
  const box=$('narration');box.replaceChildren();
  const states={pending:'等待安排',submitting:'正在排队',queued:'已进入口播队列',thinking:'正在生成',synthesizing:'正在准备声音',playing:'正在播出',answered:'已回答',expired:'已过期',discarded:'已丢弃',cancelled:'已取消',failed:'失败',unknown:'播放结果未知'};
  const kinds={question:'弹幕问题',gift:'礼物回应',task_result:'游戏任务结果',suggestion_result:'建议反馈',vote_result:'投票结果',game_event:'重要游戏事件'};
  const open=['pending','submitting','queued','thinking','synthesizing','playing'];
  $('narration-count').textContent=`${model.narration.filter(item=>open.includes(item.state)).length} 条处理中 · 上限 16`;
  if(!model.narration.length)box.append(node('p','尚无回应候选。','empty'));
  for(const item of model.narration) {
    const card=node('article',undefined,'audience-card');card.dataset.narration=item.narration_id;
    const head=node('div',undefined,'section-head');head.append(node('h3',kinds[item.kind]||'节目回应'),node('span',states[item.state]||item.state,'badge'));card.append(head);
    card.append(node('p',item.source_preview||'来源已移除','message-content'),node('p',`创建 ${time(item.created_at)} · 有效至 ${time(item.expires_at)}`,'muted'));
    if(item.source_ids?.length>1)card.append(node('p',`已合并 ${item.source_ids.length} 条相同主题记录`,'muted'));
    if(item.state==='pending')card.append(node('p',`已等待 ${Math.floor((item.waiting_ms||0)/1000)} 秒${item.cooldown_remaining_ms?' · 等待主题间隔':''}`,'muted'));
    if(item.reason)card.append(node('p',errors[item.reason]||narrationReasons[item.reason]||'本条回应已停止，请查看播出记录。','muted'));
    const details=node('details'),summary=node('summary','查看来源与播出记录');details.append(summary,node('p',item.source_id,'code'));
    for(const id of (item.source_ids||[]).filter(id=>id!==item.source_id))details.append(node('p',id,'code'));
    if(item.preempted_by)details.append(node('p','危险提醒记录：'+item.preempted_by,'code'));
    if(item.reason)details.append(node('p',item.reason,'code'));
    for(const id of item.request_ids)details.append(node('p',id,'code'));card.append(details);
    if(open.includes(item.state))card.append(action('取消回应',async()=>{await api('/narration/'+item.narration_id+'/cancel',{expected_revision:item.revision,reason:'导播取消此条回应'});showNotice('已取消该回应；已进入声音的内容按实际取消回执核对。');},{disabled:!model.synchronized}));
    box.append(card);
  }
  $('more-narration').hidden=!model.cursors.narration;
}
async function run(handler, reload = true) { if (model.busy) return; model.busy = true; renderAll(); try { await handler(); if(reload) await refresh(); } catch (error) { showNotice(explain(error)); } finally { model.busy = false; renderAll(); } }
async function waitOperation(operation) { for (let attempt=0; attempt<16; attempt++) { const value = await api('/operations/' + operation.operation_id); if (value.state === 'failed') throw new Error(value.error); if (value.state === 'succeeded') return value; await new Promise(resolve => setTimeout(resolve,500)); } throw new Error('游戏端尚未确认；请刷新记录后核对。'); }
function renderDiagnostics() {
  const health=model.health,summary=$('game-diagnostics-summary'),copy=$('game-diagnostics-copy');
  if(!health){summary.textContent='等待诊断';copy.textContent='正在获取本次服务运行的记录。';$('game-diagnostics-details').hidden=true;return;}
  const fault=health.last_fault||health.last_protocol_error;
  summary.textContent=health.storage_error?'服务故障待恢复':fault?'有历史故障记录':health.connected?'连接正常':'等待游戏连接';
  summary.classList.toggle('warn',!!health.storage_error||!!fault);
  copy.textContent=health.storage_error?'游戏服务已停止派发，请检查故障记录并恢复服务；游戏端是否释放输入仍以实际确认为准。':fault?`最近记录于 ${time(fault.at)}。恢复后请按新鲜观测重新确认操作。`:'以下记录仅覆盖本次服务运行；服务重启后重新记录。';
  const records={last_fault:health.last_fault,last_protocol_error:health.last_protocol_error,last_disconnect:health.last_disconnect,last_bridge_message:health.last_bridge_message,slowest_bridge_message:health.slowest_bridge_message};
  $('game-diagnostics-details').hidden=!Object.values(records).some(Boolean);
  $('game-diagnostics-record').textContent=JSON.stringify(records,null,2);
}
function renderState() { renderDiagnostics(); const s=model.state, world=s?.world_ledger?.world; $('world-heading').textContent=world?.local_label || '等待游戏连接';
  const safety=playerSafety(s,{synchronized:model.synchronized&&!model.health?.storage_error});
  $('player-safety').hidden=!safety;$('player-safety').dataset.severity=safety?.severity||'';
  for(const field of ['title','copy','action'])$('player-safety-'+field).textContent=safety?.[field]||'';
  $('world-context').textContent=s?.world_id ? `${s.world_id} · 观测序号 ${s.seq ?? '—'} · ${time(s.observed_at)}`:'尚无可用观测';
  $('world-vitals').textContent=s?.player ? `生命 ${s.player.health ?? '未知'} · 饱食 ${s.player.food ?? '未知'} · 世界会话 ${s.world_session_id}`:'';
  $('mode').textContent=text(s?.mode); $('connection').textContent=!model.synchronized ? (s?'同步中断，实际状态待确认':'正在连接'):fresh() ? '观测已同步':s?.connected ? '等待新鲜观测':'游戏未连接'; $('connection').classList.toggle('warn',!fresh());
  for(const button of document.querySelectorAll('[data-mode]')) button.disabled=model.busy || !model.synchronized || !s?.connected || (button.dataset.mode==='AUTO' && (!fresh() || !currentView() || !(s.screen==='gameplay'||s.screen==='menu'&&model.capabilities?.features.autonomous_resume===true) || !(s.player?.health>0)));
  $('new-goal').disabled=!stopped() || model.busy; $('new-vote').disabled=!fresh() || !currentView() || !model.audience?.room_id || model.votes.some(v=>v.state==='active') || model.busy;
  $('control-help').textContent=currentView()?'模式以游戏端确认为准；批准目标不会开启自动操作。':'上方控制属于当前实况。查看历史期间暂停自动授权，返回当前实况后再操作。';
  $('rename-world').disabled=!model.worldRecord || model.busy; $('new-base').disabled=!stopped() || s?.screen!=='gameplay' || model.busy;
  $('new-checkpoint').disabled=!stopped() || model.busy; $('follow-world').disabled=model.selection===null || model.busy;
  document.querySelector('.audience').hidden=!currentView(); }
function renderGoals() { const box=$('goals'); box.replaceChildren(); if(!model.goals.length) box.append(node('p','尚未登记目标','empty'));
  for(const goal of model.goals) { const card=node('article',undefined,'goal-card'); card.dataset.goal=goal.goal_id; const head=node('div',undefined,'section-head'); head.append(node('h3',goal.title),node('span',text(goal.status),'badge')); card.append(head);
    card.append(node('p',`${goal.steps.filter(s=>s.state==='completed').length} / ${goal.steps.length} 步完成 · 修订 ${goal.revision}`,'progress')); const list=node('ol');
    for(const step of goal.steps) { const item=node('li',`${step.label} · ${text(step.state)}`); if(step.proof) item.append(node('small',`完成证明：${time(step.proof.observed_at)} / #${step.proof.seq} · ${step.proof.source==='observation'?'实际观测满足条件':'任务验证并由观测确认'}`)); if(step.reason) item.append(node('small',window.McTaskFailures.describe(step.reason)?.label || step.reason)); list.append(item); } card.append(list);
    if(goal.reason) card.append(node('p',goal.reason,'muted')); const buttons=node('div',undefined,'buttons');
    const options=goal.status==='archived'||goal.status==='completed' ? []:[...(['draft','needs_review','blocked'].includes(goal.status)?[['activate','复核并批准']]:[]), ...(goal.steps.some(s=>s.state==='blocked')?[['retry_step','允许重新规划']]:[]), ...(goal.status==='active'?[['pause','暂停目标']]:[]), ['archive','归档目标']];
    for(const [kind,label] of options) buttons.append(action(label,()=>openDecision(goal,kind,label),{disabled:!stopped()})); card.append(buttons); box.append(card); }
  $('more-goals').hidden=!model.cursors.goals; }
function renderSessions() { const box=$('sessions'); box.replaceChildren(); $('session-count').textContent=`已载入 ${model.sessions.length} 条`;
  if(!model.sessions.length) box.append(node('p','等待首次观测','empty'));
  for(const session of model.sessions) { const item=node('article',undefined,'session'); item.append(node('h3',text(session.status)),node('p',session.world_session_id,'muted'),node('p',`${time(session.first_observed_at)} → ${time(session.last_observed_at)}`,'muted'),node('p',session.source==='legacy_registry'?'旧登记导入，缺少完整会话证据':`已保存序号 ${session.last_seq} · 连接次数 ${session.connection_count}`,'muted')); box.append(item); } $('more-sessions').hidden=!model.cursors.sessions; }
function renderTasks() { const box=$('tasks'); box.replaceChildren(); if(!model.tasks.length) { const row=node('tr'), cell=node('td','尚无任务记录','empty'); cell.colSpan=4; row.append(cell); box.append(row); }
  for(const task of model.tasks) { const row=node('tr'); row.dataset.task=task.task_id; const name=node('td',text(task.goal.skill)); name.append(node('small',task.task_id),node('small',`${task.world_id} / v${task.version}`)); const state=node('td',text(task.state)); state.append(node('small',text(task.effect_status)));
    if(task.reason) {
      const failure=window.McTaskFailures.describe(task.reason);
      if(failure) state.append(node('strong',failure.label),node('small',failure.detail),node('small',failure.action));
      const detail=node('details');detail.append(node('summary','原因编号'),node('small',task.reason,'code'));state.append(detail);
    }
    const recovery=node('td',task.disposition ? text(task.disposition.status):text(task.recovery?.status)); if(task.disposition) recovery.append(node('small',task.disposition.reason)); else if(task.recovery?.last_error) recovery.append(node('small',task.recovery.last_error)); const buttons=node('td',undefined,'task-actions');
    if(!['succeeded','failed','cancelled'].includes(task.state)) buttons.append(action('核对账本',async()=>{await waitOperation(await api('/tasks/'+task.task_id+'/reconcile',{request_id:uid()}));},{disabled:!stopped()}));
    const terminal=['failed','cancelled'].includes(task.state), eligible=task.effect_status!=='verified' && task.disposition?.status!=='closed_unknown' && (terminal || ['missing','conflict'].includes(task.recovery?.status));
    if(eligible) buttons.append(action('记录未知结果',()=>openDisposition(task),{disabled:!stopped()})); row.append(name,state,recovery,buttons); box.append(row); } $('more-tasks').hidden=!model.cursors.tasks; }
const goalLabel = goal => `${text(goal.skill)} ${goal.item_id || goal.base_id || (goal.target ? `${goal.target.x}, ${goal.target.y}, ${goal.target.z}`:'')}${goal.count ? (goal.skill==='gather'?' · 额外采集 ':goal.skill==='craft'?' · 新增产物 ':' × ')+goal.count:''}${goal.purpose==='eat'?' · 进食':goal.purpose==='activate'&&goal.target?` · 补种 ${goal.target.x}, ${goal.target.y}, ${goal.target.z}`:''}`;
const suggestionLabel = value => ({proposed:'待审核',accepted:'已采纳',rejected:'已拒绝',expired:'已过期',converted:'已关联任务',cancelled:'已取消'})[value];
const liveSuggestion = value => ['proposed','accepted'].includes(value.state) && Date.parse(value.expires_at)>Date.parse(model.audience?.server_time||0);
function canDispatch(value) { return currentView() && liveSuggestion(value) && value.state==='accepted' && fresh() && model.state.mode==='AUTO' && model.state.automation_ready &&
  !model.state.active_task_id && !model.tasks.some(task=>!['succeeded','failed','cancelled'].includes(task.state)&&task.disposition?.status!=='closed_unknown') &&
  model.capabilities?.skills.includes(value.goal.skill) && model.configuration?.settings.control.enabled_skills.includes(value.goal.skill); }
let selectedSuggestion, suggestionDecision;
function openSuggestion(value, kind) { selectedSuggestion=structuredClone(value); suggestionDecision=kind;
  $('suggestion-title').textContent={accept:'采纳建议',reject:'拒绝建议',cancel:'取消建议'}[kind];
  $('suggestion-context').textContent=`${goalLabel(value.goal)} · 修订 ${value.revision}。采纳后仍需核验执行，不会切换游戏控制模式。`;
  $('suggestion-form').reset();$('suggestion-error').textContent='';$('suggestion-dialog').showModal(); }
function renderSuggestions() {
  const box=$('suggestions'), values=model.suggestions.filter(value=>$('suggestion-filter').value==='all'||liveSuggestion(value));box.replaceChildren();
  if(!values.length)box.append(node('p',$('suggestion-filter').value==='all'?'尚无建议记录。':'等待观众提出建议，或将投票结果生成建议。','empty'));
  for(const value of values) {
    const card=node('article',undefined,'audience-card');card.dataset.suggestion=value.suggestion_id;
    const head=node('div',undefined,'section-head');head.append(node('h4',goalLabel(value.goal)),node('span',suggestionLabel(value.state),'badge'));card.append(head);
    card.append(node('p',`${value.origin?.kind==='vote'?'来自投票':'来自弹幕'} · 累计 ${value.support_count||value.source_event_ids.length} 条来源合并 · 截止 ${time(value.expires_at)}`,'muted'));
    if(value.origin?.kind==='audience') {
      const s=value.support;
      const detail=!s||s.source_availability==='unavailable'?'当前支持待核对':`当前有效 ${s.visible_events} 条 · 可识别账号 ${s.visible_viewers} 个${s.unidentified_events?` · 身份未知 ${s.unidentified_events} 条`:''}`;
      const coverage=s?.coverage==='legacy_partial'?' · 历史来源不完整':s?.coverage==='retained_window_expired'?' · 支持明细已过保留期':'';
      card.append(node('p',detail+coverage+(s?.tracked_events>=4096?' · 本建议来源已达上限':''),'muted'));
    }
    if(value.reason)card.append(node('p',value.reason,'muted'));
    const feedback=model.audience?.feedback.find(item=>item.suggestion_id===value.suggestion_id), task=model.tasks.find(item=>item.task_id===value.task_id);
    if(feedback||task) { const result=feedback||task, info=node('div',`${text(result.state)} · ${text(result.effect_status)}`,'audience-result');
      if(result.recovery_status||task?.recovery)info.append(node('p',`账本核对：${text(result.recovery_status||task.recovery.status)}`,'muted'));
      if(result.reason)info.append(node('p',result.reason,'muted'));
      for(const evidence of result.evidence||[])info.append(node('p',`观测 #${evidence.seq} · ${evidence.summary}`,'muted'));
      const reply=model.narration.find(item=>item.kind==='task_result'&&item.source_id===value.task_id);
      const speechState=feedback?.speech_status||reply?.state||'not_scheduled';
      info.append(node('p',speechState==='answered'?'结果回应已播完':speechState==='not_scheduled'?'尚未安排口播':'结果回应：'+({pending:'等待安排',submitting:'正在提交',queued:'排队中',thinking:'生成中',synthesizing:'准备声音',playing:'播出中',expired:'已过期',cancelled:'已取消',discarded:'已丢弃',failed:'失败',unknown:'播放结果未知'}[speechState]||speechState),'muted'));card.append(info); }
    if(value.task_id)card.append(node('p',value.task_id,'code'));
    const buttons=node('div',undefined,'buttons');
    if(liveSuggestion(value)) {
      if(value.state==='proposed') { buttons.append(action('采纳',()=>openSuggestion(value,'accept'),{disabled:!fresh()}),action('拒绝',()=>openSuggestion(value,'reject'),{disabled:!fresh()})); }
      if(value.state==='accepted')buttons.append(action('核验并执行',async()=>{const operation=await api('/suggestions/'+value.suggestion_id+'/dispatch',{...context(),expected_control_epoch:model.state.control_epoch,expected_revision:value.revision});await waitOperation(operation);showNotice('任务已受理，执行结果以游戏端反馈为准。');},{disabled:!canDispatch(value),secondary:false}));
      buttons.append(action('取消建议',()=>openSuggestion(value,'cancel'),{disabled:!fresh()}));
    }
    if(value.task_id)buttons.append(action('查看任务',()=>{const row=[...$('tasks').children].find(row=>row.dataset.task===value.task_id);if(row){row.classList.add('task-focus');row.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'center'});}else showNotice('请在任务记录中加载更早任务并核对。');}));
    card.append(buttons);box.append(card);
  } $('more-suggestions').hidden=!model.cursors.suggestions;
}
function renderVotes() {
  const box=$('votes');box.replaceChildren();if(!model.votes.length)box.append(node('p','先创建一场投票，邀请观众决定接下来的方向。','empty'));
  for(const vote of model.votes) { const card=node('article',undefined,'audience-card');card.dataset.vote=vote.vote_id;
    const head=node('div',undefined,'section-head');head.append(node('h4',vote.title),node('span',{active:'投票中',closed:vote.tied&&!vote.winning_option_id?'平票待选择':'投票已结束',cancelled:'已取消'}[vote.state],'badge'));card.append(head);
    const total=vote.options.reduce((sum,option)=>sum+option.votes,0), options=node('div',undefined,'vote-options');
    for(const option of vote.options) {const line=node('div',undefined,'vote-option'),fill=node('i',undefined,'vote-fill');fill.style.width=(total?option.votes/total*100:0)+'%';line.append(fill,node('span',`#${option.option_id} ${option.label}${vote.winning_option_id===option.option_id?' · 已选择':''}`),node('span',`${option.votes} 票`));options.append(line);}card.append(options,node('p',`${total} 票 · 截止 ${time(vote.expires_at)}`,'muted'));
    if(vote.reason)card.append(node('p',vote.reason,'muted'));
    const buttons=node('div',undefined,'buttons'), close=async(actionKind,selected)=>api('/votes/'+vote.vote_id+'/close',{request_id:uid(),expected_revision:vote.revision,action:actionKind,reason:selected?'导播明确选择平票选项 '+selected:actionKind==='cancel'?'导播取消投票':'导播结束投票',...(selected?{selected_option_id:selected}:{})});
    if(vote.state==='active')buttons.append(action('结束投票',()=>close('close')),action('取消投票',()=>close('cancel')));
    if(vote.state==='closed'&&vote.tied&&!vote.winning_option_id) {const maximum=Math.max(...vote.options.map(option=>option.votes));for(const option of vote.options.filter(option=>option.votes===maximum))buttons.append(action('平票选择：'+option.label,()=>close('close',option.option_id)));}
    if(vote.state==='closed'&&vote.winning_option_id&&!vote.suggestion_id)buttons.append(action('生成待审核建议',async()=>{await api('/votes/'+vote.vote_id+'/suggestion',{...context(),expected_revision:vote.revision});showNotice('投票结果已生成建议，请复核后采纳。');},{disabled:!fresh(),secondary:false}));
    if(vote.suggestion_id)card.append(node('p',vote.task_id?'胜出选项已关联任务，结果见对应建议。':'胜出选项已生成建议。','progress'));
    card.append(buttons);box.append(card);
  } $('more-votes').hidden=!model.cursors.votes;
}
function renderAudience() { $('audience-room').textContent=model.audience?.room_id?'B 站 · '+model.audience.room_id:'等待 B 站房间';const budget=model.audience?.support_budget;$('audience-hint').textContent=(model.audience?.command_hint||'')+(budget&&budget.tracked_events>=budget.total_limit?'；建议来源已满，待历史明细清理后继续接收。':'');renderSuggestions();renderVotes(); }
const positionLabel = position => position ? `${position.dimension} · ${position.x}, ${position.y}, ${position.z}` : '位置未知';
function renderWorldBrowser() {
  const picker=$('world-picker'), options=[['','跟随当前实况'],...model.worlds.map(world=>[world.world_id,world.world_id===model.worldRecord?.world_id?model.worldRecord.local_label:world.local_label])];
  const current=model.state?.world_ledger?.world;
  if(current&&!options.some(([id])=>id===current.world_id))options.push([current.world_id,current.local_label]);
  if(model.selection&&!options.some(([id])=>id===model.selection)) options.push([model.selection,model.worldRecord?.local_label||model.selection]);
  const signature=JSON.stringify(options);
  if(picker.dataset.signature!==signature) { picker.replaceChildren(); for(const [id,label] of options) { const option=node('option',label);option.value=id;picker.append(option); } picker.dataset.signature=signature; }
  picker.value=model.selection||'';
  $('more-worlds').hidden=!model.cursors.worlds;
  const world=model.worldRecord, live=currentView()&&fresh();
  $('view-kind').textContent=world?(live?'当前实况':'历史记录'):'等待世界记录';$('view-kind').classList.toggle('history',!!world&&!live);
  $('view-world-label').textContent=world?.local_label||'尚无世界记录';
  $('view-world-context').textContent=world?`${world.world_id} · 修订 ${world.revision} · 最近观测 ${time(world.last_seen)}`:'';
  $('view-help').textContent=!world?'连接游戏后，世界记录会自动登记。选择记录不会打开存档或切换游戏。':live?
    '正在查看当前世界。登记基地、选择活动基地和保存检查点均不会移动人物。':
    `以下为历史记录；当前实况仍是 ${model.state?.world_ledger?.world?.local_label||'未连接'}。返回当前实况并停控后，才能登记基地或批准游戏目标。`;
  const bases=$('bases');bases.replaceChildren();
  if(!model.bases.length) bases.append(node('p','尚无基地记录。暂停游戏操作后，可登记当前观测位置。','empty'));
  for(const base of model.bases) {
    const active=world?.active_base_id===base.base_id, card=node('article',undefined,'record-card'+(active?' active-base':''));card.dataset.base=base.base_id;
    const head=node('div',undefined,'section-head');head.append(node('h4',base.label),node('span',base.archived?'已归档':active?'活动基地':'已登记','badge'));card.append(head);
    card.append(node('p',positionLabel(base.position),'code'),node('p',`范围 ${base.radius} 格 · 观测 #${base.based_on_seq} · ${time(base.observed_at)}`,'muted'));
    if(!base.archived) { const buttons=node('div',undefined,'buttons');
      if(!active)buttons.append(action('设为活动基地',()=>openBaseDecision(base,'select'),{disabled:!stopped()}));
      buttons.append(action('归档基地',()=>openBaseDecision(base,'archive'),{disabled:!stopped()}));card.append(buttons);
    } bases.append(card);
  }
  const checkpoints=$('checkpoints');checkpoints.replaceChildren();
  if(!model.checkpoints.length)checkpoints.append(node('p','尚无检查点。停控后可记录当前观测，供下次开播复核。','empty'));
  for(const checkpoint of model.checkpoints) { const card=node('article',undefined,'record-card');card.dataset.checkpoint=checkpoint.checkpoint_id;
    card.append(node('h4',checkpoint.reason),node('p',time(checkpoint.created_at),'muted'),node('p',`观测 #${checkpoint.snapshot.seq} · ${positionLabel(checkpoint.snapshot.player?.position)}`,'code'),
      action('查看检查点',()=>openCheckpoint(checkpoint.checkpoint_id)));
    checkpoints.append(card);
  }
  for(const kind of ['bases','checkpoints'])$('more-'+kind).hidden=!model.cursors[kind];
}
function closeWorldDialogs() { for(const id of ['goal','decision','disposition','suggestion','vote','world-label','base','base-decision','checkpoint','checkpoint-view']) { const dialog=$(id+'-dialog');if(dialog.open)dialog.close(); } }
async function chooseWorld(id) {
  if(model.busy)return;viewRevision++;model.selection=id||null;model.world=model.selection||model.state?.world_id||null;model.worldRecord=null;
  try { if(model.selection)sessionStorage.setItem('mc-control.world',model.selection);else sessionStorage.removeItem('mc-control.world'); } catch {}
  for(const kind of ['goals','sessions','tasks','bases','checkpoints']) {model[kind]=[];model.cursors[kind]=null;}
  closeWorldDialogs();showNotice('');renderState();renderWorldBrowser();renderGoals();renderSessions();renderTasks();await refresh();
}
let recordEdit;
function captureRecord(kind, base) {
  if(!model.worldRecord||(kind!=='label'&&!stopped()))throw new Error('GAME_WORLD_GOAL_BUSY');
  recordEdit={kind,world:structuredClone(model.worldRecord),base:base?structuredClone(base):null,context:context(),viewRevision};
}
function requireRecord() {
  if(!recordEdit||recordEdit.world.world_id!==model.world||recordEdit.viewRevision!==viewRevision)throw new Error('GAME_WORLD_VIEW_CHANGED');
  if(recordEdit.kind!=='label'&&(!stopped()||recordEdit.context.bridge_boot_id!==model.state.bridge_boot_id||recordEdit.context.world_session_id!==model.state.world_session_id))throw new Error('GAME_WORLD_CHANGED');
  return recordEdit;
}
function openBaseDecision(base,kind) {
  captureRecord(kind,base);$('base-decision-title').textContent=kind==='select'?'选择活动基地':'归档基地';
  $('base-decision-description').textContent=kind==='select'?`将“${base.label}”设为当前世界的活动基地。人物仍留在原地；返回基地需要另行提交游戏任务。`:
    `将“${base.label}”归档，保留历史位置。${model.worldRecord.active_base_id===base.base_id?'活动基地引用将清空。':''}归档不会拆除游戏中的建筑。`;
  $('base-decision-error').textContent='';$('base-decision-dialog').showModal();
}
async function openCheckpoint(id) {
  const revision=viewRevision,world=model.world,checkpoint=await api('/checkpoints/'+id);
  if(viewRevision!==revision||model.world!==world||checkpoint.world_id!==world)return;
  const snapshot=checkpoint.snapshot,p=snapshot.player,box=$('checkpoint-view-facts');box.replaceChildren();
  for(const value of [`保存于 ${time(checkpoint.created_at)} · 观测 #${snapshot.seq}`,`位置 ${positionLabel(p?.position)}`,
    `生命 ${p?.health??'未知'} / ${p?.max_health??'未知'} · 饱食 ${p?.food??'未知'}`,`保存时模式 ${text(snapshot.mode)} · 输入已释放`,
    `观测会话 ${checkpoint.world_session_id}`])box.append(node('p',value));
  $('checkpoint-view-heading').textContent=checkpoint.reason;const inventory=$('checkpoint-view-inventory');inventory.replaceChildren();
  if(!snapshot.inventory.length)inventory.append(node('li','当时未记录到库存物品。'));
  for(const stack of snapshot.inventory)inventory.append(node('li',`${stack.item_id} × ${stack.count}`));
  $('checkpoint-view-refs').textContent=`关联 ${checkpoint.base_refs.length} 处基地、${checkpoint.task_refs.length} 项历史任务。检查点不包含 Minecraft 存档备份。`;
  $('checkpoint-view-id').textContent=checkpoint.checkpoint_id;$('checkpoint-view-dialog').showModal();
}
function pagePath(kind,cursor) {
  const path=['tasks','suggestions','votes','worlds','narration'].includes(kind)?'/'+kind:'/worlds/'+model.world+'/'+kind;
  const query=new URLSearchParams();if(kind==='tasks'&&model.world)query.set('world_id',model.world);if(cursor)query.set('cursor',cursor);
  return path+(query.size?'?'+query:'');
}
let refreshFlight, refreshAgain=false;
function mergePage(kind,page,reset=false) { const old=reset?[]:model[kind], key={goals:'goal_id',sessions:'world_session_id',tasks:'task_id',suggestions:'suggestion_id',votes:'vote_id',worlds:'world_id',bases:'base_id',checkpoints:'checkpoint_id',narration:'narration_id',intents:'audience_intent_id'}[kind], ids=new Set(page.items.map(value=>value[key]));
  model[kind]=[...page.items,...old.filter(value=>!ids.has(value[key]))]; if(reset||old.length<=20) model.cursors[kind]=page.next_cursor; }
async function refresh() { if(refreshFlight) { refreshAgain=true; return refreshFlight; } refreshFlight=(async()=>{ do { refreshAgain=false;
    const revision=viewRevision;
    const historyRequest=refreshHistory();
    let root;
    try { root=await Promise.all(['/state','/config','/capabilities','/suggestions','/votes','/worlds','/narration','/audience/intents'].map(path=>api(path).catch(error=>{if(path==='/capabilities'&&error.message==='GAME_DISCONNECTED')return null;throw error;}))); }
    catch(error) { await historyRequest;if(revision!==viewRevision){refreshAgain=true;continue;}throw error; }
    await historyRequest;
    if(revision!==viewRevision){refreshAgain=true;continue;}
    const [state,configuration,capabilities,suggestions,votes,worlds,narration,intents]=root;
    const world=model.selection||state.world_id,empty=()=>({items:[],next_cursor:null});
    let scoped;
    try { scoped=world?await Promise.all([api('/worlds/'+world),...['goals','sessions','bases','checkpoints'].map(kind=>api('/worlds/'+world+'/'+kind)),api('/tasks?world_id='+encodeURIComponent(world))]):[null,empty(),empty(),empty(),empty(),empty()]; }
    catch(error) { if(revision!==viewRevision){refreshAgain=true;continue;}Object.assign(model,{state,configuration,capabilities});throw error; }
    if(revision!==viewRevision){refreshAgain=true;continue;}
    const worldChanged=model.world!==world,audienceKey=state.world_session_id+':'+state.audience?.room_id,audienceChanged=model.audienceKey!==audienceKey;
    if(worldChanged)closeWorldDialogs();
    Object.assign(model,{state,synchronized:true,configuration,capabilities,world,worldRecord:scoped[0],audience:state.audience,audienceKey});
    for(const [index,kind] of ['goals','sessions','bases','checkpoints','tasks'].entries())mergePage(kind,scoped[index+1],worldChanged);
    mergePage('worlds',worlds);mergePage('suggestions',suggestions,audienceChanged);mergePage('votes',votes,audienceChanged);
    mergeIntents(intents,audienceChanged);if(audienceChanged)$('intent-dialog').close();
    model.narrationScheduler=narration.scheduler;
    const activeIds=new Set(narration.active_items.map(item=>item.narration_id));mergePage('narration',{...narration,items:[...narration.active_items,...narration.items.filter(item=>!activeIds.has(item.narration_id))]});
    renderAll();
  } while(refreshAgain); })(); try { await refreshFlight; } catch(error) { model.synchronized=false;renderAll();throw error; } finally { refreshFlight=null; } }
let selectedGoal,selectedDecision,selectedTask,dispositionRequest;
function openDecision(goal,kind,label) { selectedGoal=structuredClone(goal); selectedDecision=kind; $('decision-title').textContent=label; $('decision-description').textContent=`${goal.title} · 修订 ${goal.revision}。本次决定只对当前世界会话有效，旧任务不会重放。`; $('decision-form').reset(); $('decision-error').textContent=''; $('decision-dialog').showModal(); }
function openDisposition(task) { selectedTask=structuredClone(task); dispositionRequest={...context(),expected_control_epoch:model.state.control_epoch,based_on_seq:model.state.seq,expected_task_version:task.version,expected_recovery_revision:task.recovery?.revision||0,acknowledge_unknown:true}; $('disposition-form').reset(); $('disposition-error').textContent=''; $('disposition-context').textContent=`${task.task_id} / v${task.version} · 观测 #${model.state.seq}`; $('disposition-dialog').showModal(); }
function inputField(parent,label,name,value,type='text') { const wrapper=node('label',label), input=node('input'); Object.assign(input,{name,value,type,required:true}); wrapper.append(input); parent.append(wrapper); return input; }
function selectField(parent,label,name,options) { const wrapper=node('label',label), select=node('select'); select.name=name; select.setAttribute('aria-label',label); for(const [value,title] of options) { const option=node('option',title); option.value=value; select.append(option); } wrapper.append(select); parent.append(wrapper); return select; }
function itemUseFields(parent,onPlant=()=>{}) {
  const purpose=selectField(parent,'用途','purpose',[['eat','进食'],['equip','装备'],['activate','放置方块'],['plant','补种作物']]);
  purpose.querySelector('option[value=plant]').disabled=model.capabilities?.features.targeted_planting!==true;
  const details=node('div');parent.append(details);
  function fields() {
    details.replaceChildren();
    if(purpose.value!=='plant'){inputField(details,'物品 ID','item_id','minecraft:apple');return;}
    selectField(details,'选择作物','item_id',[['minecraft:wheat_seeds','小麦种子'],['minecraft:carrot','胡萝卜'],['minecraft:potato','土豆'],['minecraft:beetroot_seeds','甜菜种子']]);
    const sites=fresh()?(model.state?.details?.nearby_food?.planting_sites||[]):[];
    const site=selectField(details,'补种位置','plant_site',[['',sites.length?'请选择位置':'附近暂无可补种位置'],
      ...sites.map(row=>[JSON.stringify(row.position),`X ${row.position.x} · Y ${row.position.y} · Z ${row.position.z}`])]);
    site.required=true;
    details.append(node('p','一次补种消耗一个种子或作物；执行前会重新核对位置和库存。','hint'));
    onPlant();
  }
  purpose.addEventListener('change',fields);fields();
}
function readItemUse(parent) {
  const purpose=field(parent,'purpose');
  if(purpose!=='plant')return {purpose};
  const value=field(parent,'plant_site');if(!value)throw new Error('请先选择当前可补种的位置。');
  return {purpose:'activate',target:JSON.parse(value)};
}
function positionFields(parent) { inputField(parent,'维度','dimension','minecraft:overworld'); const grid=node('div',undefined,'position-grid'); parent.append(grid); for(const axis of ['x','y','z']) inputField(grid,axis.toUpperCase(),axis,axis==='y'?64:0,'number'); }
function addStep() { if($('step-list').children.length>=16) return; const editor=node('fieldset',undefined,'step-editor'); editor.dataset.step=uid(); const legend=node('legend','目标步骤'); editor.append(legend); inputField(editor,'步骤名称','label','').maxLength=100;
  const skill=selectField(editor,'执行技能','skill',[['gather','采集物品'],['craft','合成物品'],['use_item','使用物品'],['navigate','移动到坐标'],['return_base','回到基地']]), params=node('div'); editor.append(params);
  function goalFields() { params.replaceChildren(); if(['gather','craft'].includes(skill.value)) inputField(params,'物品 ID','item_id','minecraft:oak_log'); if(['gather','craft'].includes(skill.value)) { const count=inputField(params,skill.value==='gather'?'额外采集数量':'新增产物数量','count',4,'number'); count.min=1; count.max=4096; }
    if(skill.value==='use_item') itemUseFields(params,()=>{condition.value='task_verified';conditionFields();}); if(skill.value==='return_base') inputField(params,'已登记的基地 ID','base_id',model.state?.world_ledger?.active_base?.base_id||''); if(skill.value==='navigate') { positionFields(params); const radius=inputField(params,'到达半径','radius',2,'number'); radius.min=.5; radius.max=8; radius.step=.5; } }
  skill.addEventListener('change',goalFields); goalFields(); const condition=selectField(editor,'完成条件','condition',[['inventory_at_least','背包数量达到要求'],['position_within','实际位置到达范围'],['food_at_least','实际饱食度达到要求'],['task_verified','任务有已验证的成功证据']]), fields=node('div'); editor.append(fields);
  function conditionFields() { fields.replaceChildren(); if(condition.value==='inventory_at_least') { inputField(fields,'物品 ID','condition_item','minecraft:oak_log'); const count=inputField(fields,'至少持有','condition_count',4,'number'); count.min=1; count.max=4096; } if(condition.value==='position_within') { positionFields(fields); const radius=inputField(fields,'完成范围半径','radius',3,'number'); radius.min=.5; radius.max=128; radius.step=.5; } if(condition.value==='food_at_least') { const food=inputField(fields,'至少饱食度','food',18,'number'); food.min=1; food.max=20; } }
  condition.addEventListener('change',conditionFields); conditionFields(); const remove=action('移除步骤',()=>editor.remove()); editor.append(remove); editor.goalParams=params; editor.conditionParams=fields; $('step-list').append(editor); }
const field = (scope,name) => scope.querySelector(`[name="${name}"]`).value;
const position = scope => ({dimension:field(scope,'dimension'),x:Number(field(scope,'x')),y:Number(field(scope,'y')),z:Number(field(scope,'z'))});
function readStep(editor) { const skill=field(editor,'skill'),params=editor.goalParams,goal={skill}; if(['gather','craft','use_item'].includes(skill)) goal.item_id=field(params,'item_id'); if(['gather','craft'].includes(skill)) goal.count=Number(field(params,'count')); if(skill==='use_item') Object.assign(goal,readItemUse(params)); if(skill==='return_base') goal.base_id=field(params,'base_id'); if(skill==='navigate') Object.assign(goal,{target:position(params),radius:Number(field(params,'radius'))});
  const kind=field(editor,'condition'),fields=editor.conditionParams,condition={kind}; if(kind==='inventory_at_least') Object.assign(condition,{item_id:field(fields,'condition_item'),count:Number(field(fields,'condition_count'))}); if(kind==='food_at_least') condition.food=Number(field(fields,'food')); if(kind==='position_within') Object.assign(condition,{target:position(fields),radius:Number(field(fields,'radius'))}); return {step_id:editor.dataset.step,label:field(editor,'label'),goal,condition}; }
function bindForm(id,handler) { $(id+'-form').addEventListener('submit',async event=>{event.preventDefault(); const submit=event.submitter; submit.disabled=true; $(id+'-error').textContent=''; try { await handler(event.target); $(id+'-dialog').close(); await refresh(); } catch(error) { $(id+'-error').textContent=explain(error); } finally { submit.disabled=false; } }); }
let voteSequence=0, voteContext;
function addVoteOption() {
  if($('vote-options').children.length>=5)return;const index=++voteSequence,editor=node('fieldset',undefined,'step-editor vote-editor');editor.dataset.option=String(index);editor.append(node('legend',`选项 #${index}`));
  inputField(editor,'选项名称','option_label',index===1?'先收集木材':index===2?'先准备木板':'').maxLength=60;
  const skill=selectField(editor,'投票目标','vote_skill',[['gather','采集物品'],['craft','合成物品'],['use_item','使用物品'],['navigate','移动到坐标'],['return_base','回到基地']]),params=node('div');editor.append(params);if(index===2)skill.value='craft';
  function fields() {params.replaceChildren();if(['gather','craft'].includes(skill.value))inputField(params,'物品 ID','item_id',skill.value==='craft'?'minecraft:oak_planks':'minecraft:oak_log');
    if(['gather','craft'].includes(skill.value)){const count=inputField(params,skill.value==='gather'?'额外采集数量':'新增产物数量','count',4,'number');count.min=1;count.max=4096;}
    if(skill.value==='use_item')itemUseFields(params);
    if(skill.value==='return_base')inputField(params,'已登记的基地 ID','base_id',model.state?.world_ledger?.active_base?.base_id||'');
    if(skill.value==='navigate'){positionFields(params);const radius=inputField(params,'到达半径','radius',2,'number');radius.min=.5;radius.max=8;radius.step=.5;}}
  skill.addEventListener('change',fields);fields();editor.goalParams=params;
  editor.append(action('移除选项',()=>{editor.remove();$('add-vote-option').disabled=false;},{secondary:true}));$('vote-options').append(editor);$('add-vote-option').disabled=$('vote-options').children.length>=5;
}
function voteGoal(editor) {const skill=field(editor,'vote_skill'),params=editor.goalParams,goal={skill};if(['gather','craft','use_item'].includes(skill))goal.item_id=field(params,'item_id');if(['gather','craft'].includes(skill))goal.count=Number(field(params,'count'));if(skill==='use_item')Object.assign(goal,readItemUse(params));if(skill==='return_base')goal.base_id=field(params,'base_id');if(skill==='navigate')Object.assign(goal,{target:position(params),radius:Number(field(params,'radius'))});return goal;}
bindForm('world-label',async form=>{const edit=requireRecord(),label=form.elements.label.value;if(!label.trim())throw new Error('请填写世界名称。');return api('/worlds/'+edit.world.world_id+'/label',{request_id:edit.context.request_id,expected_revision:edit.world.revision,local_label:label});});
bindForm('base',async form=>{const edit=requireRecord(),label=form.elements.label.value;if(!label.trim())throw new Error('请填写基地名称。');return api('/worlds/'+edit.world.world_id+'/bases',{...edit.context,expected_world_revision:edit.world.revision,label,radius:Number(form.elements.radius.value)});});
bindForm('checkpoint',async form=>{const edit=requireRecord(),reason=form.elements.reason.value;if(!reason.trim())throw new Error('请填写检查点说明。');return api('/worlds/'+edit.world.world_id+'/checkpoints',{...edit.context,reason});});
bindForm('base-decision',async()=>{const edit=requireRecord(),request={request_id:edit.context.request_id,expected_revision:edit.base.revision,expected_world_revision:edit.world.revision};if(edit.kind==='select')Object.assign(request,edit.context);return api('/worlds/'+edit.world.world_id+'/bases/'+edit.base.base_id+'/'+edit.kind,request);});
bindForm('suggestion',async form=>api('/suggestions/'+selectedSuggestion.suggestion_id+'/decision',{request_id:uid(),expected_revision:selectedSuggestion.revision,action:suggestionDecision,reason:form.elements.reason.value}));
bindForm('intent',async()=>api('/audience/intents/'+selectedIntent.audience_intent_id+'/decision',{request_id:uid(),expected_revision:selectedIntent.revision,action:'resolve',goal:voteGoal($('intent-goal'))}));
bindForm('vote',async form=>{if(!fresh()||voteContext.bridge_boot_id!==model.state.bridge_boot_id||voteContext.world_session_id!==model.state.world_session_id)throw new Error('游戏世界已变化，请关闭后重新创建投票。');const options=[...$('vote-options').children].map(editor=>({option_id:editor.dataset.option,label:field(editor,'option_label'),goal:voteGoal(editor)}));if(options.length<2)throw new Error('请至少设置两个选项。');await api('/votes',{...voteContext,title:form.elements.title.value,duration_seconds:Number(form.elements.duration.value),options});});
bindForm('goal',async form=>{if(!stopped()) throw new Error('GAME_WORLD_GOAL_BUSY'); const steps=[...$('step-list').children].map(readStep); if(!steps.length) throw new Error('请至少添加一个步骤。'); await api('/worlds/'+model.world+'/goals',{...context(),expected_world_revision:model.state.world_ledger.world.revision,title:form.elements.title.value,description:form.elements.description.value,steps});});
bindForm('decision',async form=>api('/world-goals/'+selectedGoal.goal_id+'/decision',{...context(),expected_revision:selectedGoal.revision,action:selectedDecision,reason:form.elements.reason.value}));
bindForm('disposition',async form=>{const state=await api('/state'); if(state.bridge_boot_id!==dispositionRequest.bridge_boot_id || state.world_session_id!==dispositionRequest.world_session_id || state.control_epoch!==dispositionRequest.expected_control_epoch) throw new Error('GAME_DISPOSITION_OBSERVATION_CHANGED'); return api('/tasks/'+selectedTask.task_id+'/disposition',{...dispositionRequest,based_on_seq:state.seq,reason:form.elements.reason.value});});
$('new-goal').addEventListener('click',()=>{$('goal-form').reset();$('goal-error').textContent='';$('step-list').replaceChildren();addStep();$('goal-dialog').showModal();});
$('new-vote').addEventListener('click',()=>{voteContext=context();voteSequence=0;$('vote-form').reset();$('vote-error').textContent='';$('vote-options').replaceChildren();addVoteOption();addVoteOption();$('vote-dialog').showModal();});
$('add-vote-option').addEventListener('click',addVoteOption);$('suggestion-filter').addEventListener('change',renderSuggestions);
$('add-step').addEventListener('click',addStep); for(const close of document.querySelectorAll('[data-close]')) close.addEventListener('click',()=>$(close.dataset.close).close());
for(const button of document.querySelectorAll('[data-mode]')) button.addEventListener('click',()=>run(async()=>{const operation=await api('/control',{...context(),target_mode:button.dataset.mode,expected_control_epoch:model.state.control_epoch,reason:'后台操作者明确切换'}); await waitOperation(operation); showNotice('游戏端已确认模式切换。');}));
$('refresh').addEventListener('click',()=>run(refresh));
$('narration-settings-form').addEventListener('input',()=>{model.narrationSettingsDirty=true;});
$('narration-settings-form').addEventListener('submit',event=>{event.preventDefault();const form=event.currentTarget;if(!form.reportValidity())return;run(async()=>{
  const narration={enabled:form.elements.enabled.checked,critical_interrupt:form.elements.critical_interrupt.checked};
  for(const name of narrationNumberFields)narration[name]=Number(form.elements[name].value)*1000;
  await api('/config',{expected_revision:Number(form.dataset.revision),patch:{narration}});model.narrationSettingsDirty=false;showNotice('回应调度设置已应用。');
});});
$('reset-narration-settings').addEventListener('click',()=>{model.narrationSettingsDirty=false;renderNarrationSettings();});
$('intent-settings-form').addEventListener('input',()=>{model.intentSettingsDirty=true;});
$('intent-settings-form').addEventListener('submit',event=>{event.preventDefault();const form=event.currentTarget;run(async()=>{await api('/config',{expected_revision:Number(form.dataset.revision),patch:{audience_intents:{enabled:form.elements.enabled.checked}}});model.intentSettingsDirty=false;showNotice('自然语言建议设置已应用。');});});
$('reset-intent-settings').addEventListener('click',()=>{model.intentSettingsDirty=false;renderIntents();});
$('play-settings-form').addEventListener('input',()=>{playSettingsDirty=true;});
$('play-settings-reset').addEventListener('click',()=>{playSettingsDirty=false;renderPlaySettings();});
$('play-settings-form').addEventListener('submit',event=>{event.preventDefault();const form=event.currentTarget;
  if(!form.reportValidity())return;run(async()=>{
    await api('/config',{expected_revision:Number(form.dataset.revision),patch:{enabled:form.elements.enabled.checked,
      planner:{enabled:form.elements.planner.checked,engine:'mindcraft_native',autostart:form.elements.autostart.checked},control:{enabled_skills:[...form.querySelectorAll('[name=skill]:checked')].map(input=>input.value)},
      programme:{avatar_variant:form.elements.avatar_variant.value,comment_mode:form.elements.comment_mode.value}}});
    playSettingsDirty=false;showNotice('游玩设置已保存；自动操作模式以游戏端确认为准。');
  });
});
$('intent-filter').addEventListener('change',renderIntents);
$('refresh-intents').addEventListener('click',()=>run(async()=>{intentsExpanded=false;model.intents=[];model.cursors.intents=null;await refresh();},false));
$('more-intents').addEventListener('click',()=>run(async()=>{const key=model.audienceKey,page=await api('/audience/intents?cursor='+encodeURIComponent(model.cursors.intents));if(key!==model.audienceKey||page.items.some(value=>!intentContextMatches(value)))return;const ids=new Set(model.intents.map(value=>value.audience_intent_id));model.intents.push(...page.items.filter(value=>!ids.has(value.audience_intent_id)));model.cursors.intents=page.next_cursor;intentsExpanded=true;renderIntents();},false));
$('world-picker').addEventListener('change',event=>{if(model.busy){event.target.value=model.selection||'';return;}chooseWorld(event.target.value).catch(error=>showNotice(explain(error)));});
$('follow-world').addEventListener('click',()=>chooseWorld(null).catch(error=>showNotice(explain(error))));
$('rename-world').addEventListener('click',()=>{captureRecord('label');$('world-label-form').reset();$('world-label-form').elements.label.value=recordEdit.world.local_label;$('world-label-error').textContent='';$('world-label-dialog').showModal();});
$('new-base').addEventListener('click',()=>{captureRecord('base');$('base-form').reset();$('base-error').textContent='';$('base-location').textContent=positionLabel(model.state.player?.position);$('base-dialog').showModal();});
$('new-checkpoint').addEventListener('click',()=>{captureRecord('checkpoint');$('checkpoint-form').reset();$('checkpoint-error').textContent='';$('checkpoint-dialog').showModal();});
for(const kind of ['goals','sessions','tasks','suggestions','votes','worlds','bases','checkpoints']) $('more-'+kind).addEventListener('click',()=>run(async()=>{const revision=viewRevision,world=model.world,page=await api(pagePath(kind,model.cursors[kind]));if(revision!==viewRevision||world!==model.world)return;const key={goals:'goal_id',sessions:'world_session_id',tasks:'task_id',suggestions:'suggestion_id',votes:'vote_id',worlds:'world_id',bases:'base_id',checkpoints:'checkpoint_id'}[kind],ids=new Set(model[kind].map(value=>value[key]));model[kind].push(...page.items.filter(value=>!ids.has(value[key])));model.cursors[kind]=page.next_cursor;({goals:renderGoals,sessions:renderSessions,tasks:renderTasks,suggestions:renderSuggestions,votes:renderVotes,worlds:renderWorldBrowser,bases:renderWorldBrowser,checkpoints:renderWorldBrowser})[kind]();},false));
 $('history-refresh').addEventListener('click',()=>run(async()=>{historyRevision++;historyExpanded=false;model.historyEntries=[];model.cursors.history=null;await refreshHistory({reset:true});},false));
 $('history-import').addEventListener('click',()=>run(async()=>{await api('/history/imports',context());await refreshHistory();}));
 $('history-cancel').addEventListener('click',()=>run(async()=>{const job=model.historyStatus?.latest_import;if(job)await api('/history/imports/'+job.history_import_id+'/cancel',{request_id:uid()});await refreshHistory();}));
 $('history-filter').addEventListener('change',()=>{historyRevision++;historyExpanded=false;model.historyKind=$('history-filter').value;model.historyEntries=[];model.cursors.history=null;renderHistory();void refreshHistory({reset:true});});
 $('more-history').addEventListener('click',()=>run(()=>refreshHistory({cursor:model.cursors.history}),false));
let timer; const events=new EventSource(apiBase+'/events');
events.addEventListener('history',event=>{model.historyStatus=JSON.parse(event.data);renderHistory();schedule();});
events.addEventListener('narration',()=>schedule());
events.addEventListener('audience_intent',event=>{const value=JSON.parse(event.data);if(intentContextMatches(value)){const index=model.intents.findIndex(old=>old.audience_intent_id===value.audience_intent_id);if(index>=0&&model.intents[index].revision<=value.revision)model.intents[index]=value;}renderIntents();schedule();});
$('more-narration').addEventListener('click',()=>run(async()=>{const page=await api(pagePath('narration',model.cursors.narration)),ids=new Set(model.narration.map(item=>item.narration_id));model.narration.push(...page.items.filter(item=>!ids.has(item.narration_id)));model.cursors.narration=page.next_cursor;renderNarration();},false));
events.addEventListener('snapshot',event=>{const value=JSON.parse(event.data);if(value.health)model.health=value.health;renderDiagnostics();schedule()}); for(const type of ['state','task','world','world_goal','world_session','base','checkpoint','health','operation','suggestion','vote']) events.addEventListener(type,event=>{const kind={task:'tasks',world_goal:'goals',world_session:'sessions',base:'bases',checkpoint:'checkpoints',suggestion:'suggestions',vote:'votes'}[type]; if(kind) {const value=JSON.parse(event.data),key={task:'task_id',world_goal:'goal_id',world_session:'world_session_id',base:'base_id',checkpoint:'checkpoint_id',suggestion:'suggestion_id',vote:'vote_id'}[type];model[kind]=model[kind].map(old=>old[key]===value[key]?value:old);}if(type==='health'){model.health=JSON.parse(event.data);if(model.health.storage_error)model.synchronized=false;renderAll()}schedule();});
function schedule() { if(timer) return; timer=setTimeout(()=>{timer=null;refresh().catch(error=>showNotice(explain(error)));},400); }
events.onerror=()=>{model.synchronized=false;renderAll();};
const freshnessTimer=setInterval(()=>{if(model.state) refresh().catch(error=>showNotice(explain(error)));},5000);
window.addEventListener('pagehide',()=>{events.close();clearTimeout(timer);clearInterval(freshnessTimer);});
renderAll();refresh().catch(error=>showNotice(explain(error)));
