const api = '/api/mc-maintenance', $ = id => document.getElementById(id);
const labels = { dependencies:'查看保留依据', status:'检查维护条件', preview:'生成维护预览', apply:'执行维护计划', reconcile:'查证当前账本' };
const states = { accepted:'已排队', running:'正在执行', succeeded:'已完成查询', failed:'未完成', interrupted:'运行已中断', cancelled:'已取消排队' };
const outcomes = { not_dispatched:'未发送维护执行', not_applicable:'本作业不执行删除', unknown:'执行结果不确定，请查证当前账本', confirmed_in_current_b_ledger:'当前游戏账本已确认提交', not_found_in_current_b_ledger:'当前账本未找到；不代表历史上从未执行' };
const reasons = {task_unresolved:'未结束或效果未核验任务',recovery:'待恢复任务',disposition:'人工处置引用',world_goal:'活动世界目标',narration:'待完成公开回应',world_registry:'世界记录',world_bases:'基地引用',world_checkpoints:'检查点引用',meta:'元数据引用'};
const countLabels = {events:'旧事件',tasks:'旧任务',task_deliveries:'任务递送记录',task_versions:'任务版本',summary_groups:'汇总分组'};
const errors = {
  MC_MAINTENANCE_NOT_CONFIGURED:'历史维护尚未配置游戏记录位置。可以先返回运行管理，核对服务状态。',
  MC_MAINTENANCE_A_RUNNING:'业务服务仍在运行。正常停止业务服务后再生成预览。',
  MC_MAINTENANCE_A_BUSY:'业务数据库仍被占用。等待停止完成后再检查。',
  GAME_JOURNAL_OWNED:'游戏账本仍被占用。正常退出游戏后再检查。',
  MC_MAINTENANCE_PLAN_EXPIRED:'计划已过期。重新生成预览并核对。',
  MC_MAINTENANCE_A_CHANGED:'业务记录已经改变。重新生成预览。',
  MC_MAINTENANCE_INSTALLATION_CHANGED:'运行文件已经改变。正常重启维护台后重新生成预览。',
  MC_MAINTENANCE_SOURCE_PROBE_TIMEOUT:'源码来源检查超时，未发送维护执行。检查安装目录后再试。',
  MC_MAINTENANCE_INSTALLATION_INVALID:'安装来源检查未通过，未发送维护执行。请检查安装文件。',
  MC_MAINTENANCE_CONSOLE_INTERRUPTED:'维护台在上次运行中中断。原作业不会自动重放。',
  MC_MAINTENANCE_CONSOLE_STOPPED:'维护台已停止，排队作业未执行。',
  MC_MAINTENANCE_CANCEL_BLOCKED:'作业已开始或结束，不能取消排队。请查看实际结果。',
  MC_MAINTENANCE_REQUEST_CONFLICT:'这个请求编号已有不同内容。请查看原作业。',
  MC_MAINTENANCE_QUEUE_FULL:'维护队列已满。等待现有作业完成。',
  MC_MAINTENANCE_CONSOLE_CAPACITY:'作业记录容量已满。先按维护手册归档，原记录不会自动删除。',
  MC_MAINTENANCE_CONSOLE_STORAGE_FAILED:'作业结果未能保存。保留原记录，正常重启维护台后查证。',
  MC_MAINTENANCE_OUTCOME_UNRECORDED:'执行结果未能完整保存。请查证当前账本。'
};
const pendingKey = 'zhixia-mc-maintenance-pending-v1';
let plans = [], jobs = [], through = 0, next = null, selected = '', sending = false, fault = null, confirmedPlan = null;
let planSignature = '', jobSignature = '';
let timer, polling = false, closed = false, controller;
const observed = new Set();
function pending() { try { const v = JSON.parse(localStorage.getItem(pendingKey)); return v && typeof v.request_id === 'string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(v.request_id) ? v : null; } catch { return null; } }
function remember(value) { try { value ? localStorage.setItem(pendingKey, JSON.stringify(value)) : localStorage.removeItem(pendingKey); } catch { /* Server receipts remain authoritative when local storage is unavailable. */ } renderPending(); }
function message(text, error = false) { $('notice').hidden = !text; $('notice').textContent = text; $('notice').classList.toggle('error', error); }
function errorText(value) { return errors[value] || `操作未完成（${value || '连接中断'}）。请保留原记录并检查维护条件。`; }
async function request(path, options = {}) {
  const response = await fetch(api + path, { ...options, cache:'no-store', signal:options.signal });
  const value = await response.json();
  if (!response.ok) throw Object.assign(new Error(errorText(value.code)), { code:value.code, status:response.status });
  return value;
}
const post = (path, value) => request(path, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(value) });
function renderPending() { const value = pending(); $('pending-request').hidden = !value; if (value) $('pending-text').textContent = `原请求 ${value.request_id} 的结果尚未确认。先查询这次请求，页面不会自动重发执行。`; }
function facts(target, entries) { target.replaceChildren(); for (const [name, value] of entries) { const dt = document.createElement('dt'), dd = document.createElement('dd'); dt.textContent = name; dd.textContent = String(value); target.append(dt,dd); } }
function selectedPlan() { return plans.find(p => p.plan_file === selected); }
function canApply(plan) { return !!plan && plan.binding_matches && plan.expires_at_ms > Date.now() && plan.counts.events + plan.counts.tasks > 0 && !sending && !fault && !pending(); }
function renderReview() {
  const plan = selectedPlan(); $('plan-review').hidden = !plan;
  if (!plan) return;
  $('protected-count').textContent = `${plan.protected_tasks} 个任务`;
  facts($('protection-reasons'), Object.entries(plan.protection_counts).map(([key, value]) => [reasons[key] || `关联依据：${key}`, value]));
  if (!Object.keys(plan.protection_counts).length) facts($('protection-reasons'), [['实际扫描结果','没有需要额外保留的任务']]);
  facts($('retention-counts'), Object.entries(countLabels).map(([key, label]) => [label, plan.counts[key]]));
  const expired = plan.expires_at_ms <= Date.now();
  $('plan-expiry').textContent = !plan.binding_matches ? '运行来源已改变。这份计划只能查阅，请重新生成预览。' : expired ? '计划已过期。仍可查证当前账本；执行前请重新生成预览。' : `执行有效期至 ${new Date(plan.expires_at_ms).toLocaleTimeString('zh-CN')}。执行时会再次核对全部依据。`;
  $('plan-id').textContent = plan.plan_file; $('plan-hash').textContent = plan.plan_sha256;
  $('review-apply').disabled = !canApply(plan); $('reconcile').disabled = sending || !plan.binding_matches || !!fault;
}
function renderPlans(value) {
  plans = value.items;
  const picker = $('plan-picker'), signature = JSON.stringify(plans);
  if (planSignature !== signature) {
    picker.replaceChildren(new Option('请选择一份预览计划',''));
    for (const plan of plans) picker.add(new Option(`${new Date(plan.created_at).toLocaleString('zh-CN')} · ${plan.counts.tasks} 个旧任务 / ${plan.counts.events} 条旧事件`, plan.plan_file));
    planSignature = signature;
  }
  if (!plans.some(p => p.plan_file === selected)) selected = '';
  picker.value = selected; $('plan-issues').hidden = !value.issues.length;
  $('plan-issues').textContent = value.issues.length ? `${value.issues.length} 份计划无法读取，原文件已保留。请检查维护记录。` : '';
  renderReview();
}
function button(text, action, secondary = true) { const node = document.createElement('button'); node.textContent = text; if (secondary) node.className = 'secondary'; node.addEventListener('click', action); return node; }
function renderJobs() {
  const signature = JSON.stringify([jobs,next]); if (signature === jobSignature) return; jobSignature = signature;
  const active = document.activeElement, focusJob = active?.closest('[data-job-id]')?.dataset.jobId, focusLabel = active?.tagName === 'BUTTON' ? active.textContent : null;
  const list = $('jobs'); list.replaceChildren(); $('jobs-count').textContent = jobs.length ? `已读取 ${jobs.length} 份记录` : '暂无作业';
  if (!jobs.length) { const li = document.createElement('li'); li.className = 'empty'; li.textContent = '生成维护预览后，可在这里查看作业与结果。'; list.append(li); }
  for (const job of jobs) {
    const li = document.createElement('li'); li.className = 'job-row'; li.dataset.jobId = job.job_id; li.classList.toggle('uncertain', job.outcome === 'unknown');
    const text = document.createElement('div'), title = document.createElement('h3'), status = document.createElement('p'), time = document.createElement('p'), actions = document.createElement('div');
    title.textContent = `${labels[job.action]} · ${job.action === 'apply' && job.state === 'succeeded' ? '已完成查证' : states[job.state]}`;
    status.className = 'status-line'; status.textContent = outcomes[job.outcome] || job.outcome;
    time.className = 'code'; time.textContent = `${new Date(job.created_at).toLocaleString('zh-CN')} · ${job.request_id}`;
    text.append(title,status,time);
    if (job.code) { const detail = document.createElement('p'); detail.className = 'error-line'; detail.textContent = errorText(job.code); text.append(detail); }
    actions.className = 'buttons'; actions.append(button('查看记录', () => showJob(job)));
    if (job.state === 'accepted') actions.append(button('取消排队', async () => { try { await post(`/jobs/${job.job_id}/cancel`,{}); await refresh(); } catch (e) { message(e.message,true); } }));
    if (job.outcome === 'unknown' && job.plan_file) actions.append(button('查证这份计划', () => submit('reconcile',job)));
    if (job.result?.plan_file) actions.append(button('核对这份计划', () => { selected = job.result.plan_file; $('plan-picker').value = selected; renderReview(); $('plans-title').scrollIntoView({block:'start'}); }));
    li.append(text,actions); list.append(li);
  }
  $('more-jobs').hidden = next === null;
  if (focusJob && focusLabel) Array.from(list.querySelectorAll('button')).find(node => node.closest('[data-job-id]')?.dataset.jobId === focusJob && node.textContent === focusLabel)?.focus({preventScroll:true});
}
function showJob(job) {
  const container = $('job-facts'), dl = document.createElement('dl'); dl.className = 'facts';
  facts(dl,[['操作',labels[job.action]],['状态',states[job.state]],['执行结果',outcomes[job.outcome] || job.outcome],['请求编号',job.request_id],['开始时间',job.started_at || '尚未开始'],['结束时间',job.finished_at || '尚未结束']]);
  container.replaceChildren(dl);
  if (job.result) { const pre = document.createElement('pre'); pre.textContent = JSON.stringify(job.result,null,2); container.append(pre); }
  $('job-dialog').showModal();
}
async function findRequest(quiet = false) {
  const value = pending(); if (!value) return;
  try { const job = await request(`/requests/${encodeURIComponent(value.request_id)}`); remember(null); if (!quiet) { message('已找到原请求，按作业记录查看结果。'); await refresh(); } return job; }
  catch (e) { if (!quiet || e.status !== 404) message(e.status === 404 ? '暂未查到原请求。请稍后再查询；页面不会自动重发。' : e.message,true); }
}
async function submit(action, plan = selectedPlan()) {
  if (sending) return;
  if (pending()) { message('请先查询原请求，避免重复操作。',true); return; }
  const id = typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : Array.from(crypto.getRandomValues(new Uint8Array(16)),byte => byte.toString(16).padStart(2,'0')).join('');
  const value = {request_id:`maintenance-${id}`,action};
  if (action === 'apply' || action === 'reconcile') { if (!plan) return; Object.assign(value,{plan_file:plan.plan_file,plan_sha256:plan.plan_sha256}); }
  sending = true; remember(value); renderReview();
  try { const result = await post('/jobs',value); remember(null); message(`已受理：${labels[action]}。以作业实际结果为准。`); await refresh(); return result; }
  catch (e) { message(`${e.message} 请查询原请求。`,true); }
  finally { sending = false; renderReview(); }
}
async function refresh() {
  if (polling || closed || document.hidden) return;
  polling = true; controller = new AbortController();
  try {
    const [state, planPage, page] = await Promise.all(['/state','/plans','/jobs'].map(path => request(path,{signal:controller.signal})));
    fault = state.fault; $('connection').textContent = state.fault ? '记录保存异常' : state.stopping ? '维护台正在停止' : '维护台已连接';
    $('capacity').textContent = `${state.capacity.pending}/${state.capacity.pending_limit} 个待完成作业 · ${state.capacity.jobs}/${state.capacity.job_limit} 份记录`;
    if (state.fault) message(errorText(state.fault),true);
    jobs = [...page.items,...jobs.filter(job => !page.items.some(current => current.job_id === job.job_id))].sort((a,b) => b.seq-a.seq);
    if (!through) { through = page.through; next = page.next_before; }
    for (const job of page.items) {
      if (job.state === 'succeeded' && job.action === 'preview' && job.result?.plan_file && !observed.has(job.job_id)
          && planPage.items.some(plan => plan.plan_file === job.result.plan_file && plan.plan_sha256 === job.result.plan_sha256)) { selected = job.result.plan_file; observed.add(job.job_id); }
    }
    renderPlans(planPage); renderJobs();
    for (const id of ['inspect','dependencies','preview']) $(id).disabled = !!fault || state.stopping;
    if (pending()) await findRequest(true);
  } catch (e) { if (e.name !== 'AbortError') { $('connection').textContent = '维护台连接中断'; message('未能读取维护台。原作业可能仍在运行，恢复连接后请先查询原请求。',true); } }
  finally { polling = false; controller = null; renderPending(); }
}
$('inspect').onclick = () => submit('status'); $('dependencies').onclick = () => submit('dependencies'); $('preview').onclick = () => submit('preview');
$('refresh').onclick = refresh; $('find-request').onclick = () => findRequest(); $('dismiss-request').onclick = () => { remember(null); message('已收起提示，原作业记录仍保留。开始新操作前请核对作业列表。'); renderReview(); };
$('plan-picker').onchange = () => { selected = $('plan-picker').value; renderReview(); };
$('reconcile').onclick = () => submit('reconcile');
$('review-apply').onclick = () => { const plan = selectedPlan(); if (!canApply(plan)) return; confirmedPlan = structuredClone(plan); $('confirm-checked').checked = false; $('confirm-apply').disabled = true; $('confirm-description').textContent = `这份计划拟处理 ${plan.counts.events} 条旧事件、${plan.counts.tasks} 个旧任务，同时保护 ${plan.protected_tasks} 个任务。`; $('apply-dialog').showModal(); };
$('confirm-checked').onchange = () => { $('confirm-apply').disabled = !$('confirm-checked').checked; };
$('apply-dialog').addEventListener('close',() => { const approved = confirmedPlan; confirmedPlan = null; if ($('apply-dialog').returnValue === 'apply' && $('confirm-checked').checked && canApply(approved)) submit('apply',approved); });
$('close-job').onclick = () => $('job-dialog').close();
$('stop-console').onclick = async () => { try { await post('/stop',{}); closed = true; clearInterval(timer); controller?.abort(); $('connection').textContent = '维护台正在停止'; $('stop-console').disabled = true; for (const id of ['inspect','dependencies','preview','review-apply','reconcile']) $(id).disabled = true; message('正在停止维护台。当前作业会先完成，其余排队作业保留中断记录。'); } catch (e) { message(e.message,true); } };
$('more-jobs').onclick = async () => { if (next === null) return; try { const page = await request(`/jobs?through=${through}&before=${next}`); jobs = [...jobs,...page.items.filter(job => !jobs.some(old => old.job_id === job.job_id))]; next = page.next_before; renderJobs(); } catch (e) { message(e.message,true); } };
function schedule() { clearInterval(timer); if (!closed && !document.hidden) { refresh(); timer = setInterval(refresh,1500); } }
document.addEventListener('visibilitychange',() => { if (document.hidden) { clearInterval(timer); controller?.abort(); } else schedule(); });
window.addEventListener('pagehide',() => { closed = true; clearInterval(timer); controller?.abort(); });
window.addEventListener('pageshow',() => { if (closed) { closed = false; schedule(); } });
renderPending(); schedule();
