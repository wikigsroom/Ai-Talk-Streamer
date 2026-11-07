from __future__ import annotations

import json
import ipaddress
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .runtime import Controller


_PAGE = r"""<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Isaac × JEV</title>
<style>
body{margin:0;background:#141016;color:#eee;font:14px ui-monospace,Consolas,monospace}main{max-width:1180px;margin:24px auto;padding:0 18px}h1{font-size:23px;color:#90e66d;margin-bottom:4px}h2{font-size:15px;color:#f4c66c}h3{font-size:14px;color:#f4c66c;margin:14px 0 6px}section{background:#211b25;border:1px solid #45384d;border-radius:10px;padding:16px;margin:12px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}.value{color:#aee8ff;white-space:pre-wrap}.ok{color:#90e66d}.bad{color:#ff8f8f}.muted{color:#b4aab9}li{margin:7px 0}small{color:#b4aab9}.tabs{display:flex;gap:8px;margin:18px 0 10px}.tab{border:1px solid #5a4964;background:#211b25;color:#cbbbd2;padding:10px 18px;border-radius:7px;cursor:pointer;font:inherit}.tab.active{background:#90e66d;color:#141016;border-color:#90e66d}.tab-pane{display:none}.tab-pane.active{display:block}.rule-section{border-top:1px solid #3b303f;padding-top:8px}.rule-section:first-child{border-top:0}.rule-list{color:#cfeeff;padding-left:22px}.action-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:6px 24px;color:#cfeeff;padding-left:22px}.table-wrap{overflow:auto;border:1px solid #45384d;border-radius:8px}table{border-collapse:collapse;width:100%;min-width:940px}th,td{border-bottom:1px solid #3b303f;padding:9px;text-align:left;vertical-align:top}th{color:#f4c66c;white-space:nowrap}td{color:#cfeeff}pre{white-space:pre-wrap;word-break:break-word;max-width:430px;max-height:260px;overflow:auto;margin:0;font:12px ui-monospace,Consolas,monospace}.status{margin-left:12px}.provider-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px;margin:12px 0}.provider-card{border:1px solid #51425b;border-radius:8px;padding:12px;background:#18131c}.provider-card.active{border-color:#90e66d;box-shadow:0 0 0 1px #90e66d inset}.provider-card h3{margin:0 0 6px}.provider-card p{margin:5px 0;line-height:1.45}.provider-card code{color:#f4c66c;word-break:break-all}.form-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:10px}.form-grid label{display:flex;flex-direction:column;gap:5px;color:#f4c66c}.form-grid input,.form-grid select{box-sizing:border-box;width:100%;padding:7px;background:#fafafa;color:#141016;border:1px solid #a99ab0;border-radius:4px;font:inherit}.form-grid .checkbox-label{display:flex;flex-direction:row;align-items:center;gap:8px;padding-top:24px}.form-grid .checkbox-label input{width:auto}.button-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:12px}.button-row button{padding:8px 12px;font:inherit;border:1px solid #90e66d;border-radius:5px;cursor:pointer}.button-row button.primary{background:#90e66d;color:#141016}.button-row button.secondary{background:#211b25;color:#eee}
</style><main><h1>ISAAC × JEV · 实时状态</h1><small id="updated">连接中…</small><small class="status" id="debug-count"></small>
<div class="tabs" role="tablist"><button class="tab active" data-tab="decisions" role="tab">决策信息</button><button class="tab" data-tab="experiment" role="tab">模型与实验</button><button class="tab" data-tab="debug" role="tab">Debug 日志</button></div>
<div class="tab-pane active" id="tab-decisions">
<section><h2>系统运行规则（源代码）</h2><div class="value" id="rules-meta">读取当前决策代码中…</div><div id="rule-sections"></div><h3>动作目录</h3><ol class="action-list" id="action-catalog"></ol></section>
<section class="grid"><div>自动控制 <div class="value" id="autopilot">—</div></div><div>游戏帧 <div class="value" id="frame">—</div></div><div>桥接 <div class="value" id="bridge">—</div></div><div>JEV 调用延迟 <div class="value" id="latency">—</div></div><div>策略 / 调用计数 <div class="value" id="policy-metrics">—</div></div><div>请求体大小 <div class="value" id="request-metrics">—</div></div></section>
<section><h2>当前决策</h2><div class="grid"><div>模式 / 动作<div class="value" id="decision">—</div></div><div>角色动作<div class="value" id="role-action">—</div></div><div>移动 / 射击<div class="value" id="input">—</div></div><div>来源 / 置信度<div class="value" id="source">—</div></div><div>门状态<div class="value" id="transition">—</div></div><div>宏观窗口<div class="value" id="macro">—</div></div></div><p class="value" id="reason">—</p></section>
<section><h2>候选与安全过滤</h2><div class="value" id="candidates">等待决策…</div></section>
<section><h2>游戏状态</h2><div class="value" id="state">等待游戏状态…</div></section><section><h2>控制诊断</h2><div class="value" id="diagnostics">—</div></section><section><h2>死亡轨迹与离线调参</h2><div class="value" id="telemetry">—</div></section><section><h2>楼层路线与已知奖励</h2><div class="value" id="floor">尚未发现房间…</div></section><section><h2>最近决策</h2><ol id="history"></ol></section>
</div>
<div class="tab-pane" id="tab-experiment"><section><h2>模型与实验</h2><p class="value">配置文件：config/decision_provider.json（明文保存 API Key；文件已被 Git 忽略，仅本机使用）</p><div class="provider-grid" id="provider-cards"></div><div class="form-grid"><label>正在编辑<select id="provider-select"><option value="jev">官方 Jev</option><option value="bocha">Bocha Jev</option><option value="systemone">System One 自托管</option><option value="local">Local 本地策略</option></select></label><label>下一局模型<select id="next-provider-select"><option value="jev">官方 Jev</option><option value="bocha">Bocha Jev</option><option value="systemone">System One 自托管</option><option value="local">Local 本地策略</option></select></label><label>Shadow 对照<select id="shadow-select"><option value="jev">官方 Jev</option><option value="bocha">Bocha Jev</option><option value="systemone">System One 自托管</option><option value="local">Local 本地策略</option></select></label><label class="checkbox-label">Shadow 启用<input type="checkbox" id="shadow-enabled"></label><label>决策 URL<input id="provider-url"></label><label>健康检查 URL<input id="provider-health-url"></label><label>模型名称<input id="provider-model"></label><label class="checkbox-label">需要鉴权<input type="checkbox" id="provider-auth-required"></label><label>API Key（留空表示保持原值）<input id="provider-key" type="password" autocomplete="off"></label></div><p class="value" id="provider-editing">正在读取配置…</p><div class="button-row"><button class="primary" id="provider-save">保存配置（下一局生效）</button><button class="secondary" id="provider-check">检查当前 Provider</button><span class="value" id="provider-message"></span></div></section><section><h2>统计筛选</h2><div class="grid"><label>Seed <input id="stat-seed"></label><label>Provider <input id="stat-provider"></label><label>Model <input id="stat-model"></label></div><pre id="statistics">等待统计…</pre></section></div>
<div class="tab-pane" id="tab-debug"><section><h2>近期决策与 JEV 调用</h2><p class="value">`jev_request.state` 是脱敏后的最小远程请求；最终执行动作单独显示，不把完整状态误认为请求体。</p><div class="table-wrap"><table><thead><tr><th>时间</th><th>帧 / 房间</th><th>策略 / 来源</th><th>请求摘要</th><th>JEV 返回</th><th>最终执行</th><th>耗时</th></tr></thead><tbody id="debug-log"><tr><td colspan="7">等待决策…</td></tr></tbody></table></div></section></div>
</main>
<script>
const byId=id=>document.getElementById(id), text=(id,v)=>byId(id).textContent=v??'—';
const show=o=>o?JSON.stringify(o):'—';
document.querySelectorAll('.tab').forEach(button=>button.addEventListener('click',()=>{document.querySelectorAll('.tab').forEach(item=>item.classList.toggle('active',item===button));document.querySelectorAll('.tab-pane').forEach(item=>item.classList.toggle('active',item.id===`tab-${button.dataset.tab}`));}));
let renderedRules='';
function renderRules(rules){if(!rules)return;const revision=JSON.stringify(rules.source_revisions);if(revision===renderedRules)return;renderedRules=revision;text('rules-meta',`运行中代码：${rules.source_files?.join('、')||'当前源码'}\n源函数指纹 ${show(rules.source_revisions)}`);const sections=byId('rule-sections');sections.replaceChildren(...(rules.sections||[]).map(section=>{const wrapper=document.createElement('div');wrapper.className='rule-section';const title=document.createElement('h3');title.textContent=section.title;const summary=document.createElement('p');summary.className='value';summary.textContent=section.summary||'';const list=document.createElement('ol');list.className='rule-list';(section.rules||[]).forEach(rule=>{const item=document.createElement('li');item.textContent=rule;list.appendChild(item);});const source=document.createElement('small');source.textContent=`实现函数：${section.source||'—'}`;wrapper.append(title,summary,list,source);return wrapper;}));const actions=byId('action-catalog');actions.replaceChildren(...(rules.actions||[]).map(action=>{const item=document.createElement('li');item.textContent=`${action.label}（${action.id}）`;return item;}));}
function addDebugLogs(logs){const body=byId('debug-log');body.replaceChildren();if(!logs?.length){body.innerHTML='<tr><td colspan="7">尚未产生决策</td></tr>';return;}logs.forEach(x=>{const row=document.createElement('tr');const summary={requested_provider:x.requested_provider||x.provider||'—',model:x.model||'—',policy:x.policy||'local',schema_version:x.schema_version||'—',remote_call:!!x.remote_call,request_bytes:x.request_bytes??0,state_bytes:x.state_bytes??0,estimated_input_tokens:x.estimated_input_tokens??0,candidates:x.candidate_set?.admissible_candidates?.map(item=>item.id)||[]};const response={status:x.status||'—',fallback:x.fallback?'是':'否',fallback_reason:x.fallback_reason||'—',error:x.error||'—',selected_choice:x.output?.action||x.selected_choice||'—',judgments:x.judgments||{}};const execution=x.execution||{action_id:x.action||'—',source:x.source||'—'};const phaseMessage=x.fallback_reason==='not_remote_eligible'?'本阶段不调用远程':(x.fallback?'已回退 Local':'');const cells=[x.recorded_at||'—',`f${x.frame??'—'} / r${x.room_index??'—'}`,`请求：${x.requested_provider||x.provider||'—'}\n执行：${x.execution_source||x.source||'local'}\n${x.policy||'local'} · ${x.status||'—'}${phaseMessage?'\n'+phaseMessage:''}`,JSON.stringify(summary,null,2),JSON.stringify(response,null,2),JSON.stringify(execution,null,2),`${x.remote_latency_ms??x.latency_ms??'—'} ms\n${x.fallback_reason||''}`];cells.forEach((value,index)=>{const cell=document.createElement('td');if(index>=3&&index<=5){const pre=document.createElement('pre');pre.textContent=value;cell.appendChild(pre);}else{cell.textContent=value;}row.appendChild(cell);});body.appendChild(row);});}
function renderRecoveryDiagnostics(s){const current=byId('diagnostics');current.textContent+=`\n停滞 ${s.stall_frames??0} 帧 · 本地重定位未脱困 ${s.local_recovery_failures??0} 次 · 恢复阶段 ${s.recovery_active?'ON':'OFF'}\n恢复原因 ${s.recovery_reason||'—'}\n门重试冷却 ${show(s.door_retry_cooldowns)}\nLua 各方向安全检查 ${show(s.latest_state?.safe_move_directions)}`;const rows=[...byId('debug-log').querySelectorAll('tr')];(s.debug_logs||[]).forEach((log,index)=>{const cell=rows[index]?.cells?.[3];if(!cell)return;const pre=document.createElement('pre');pre.textContent=JSON.stringify({recovery:log.recovery||{},rejected:log.candidate_set?.rejected_candidates||[],applied:log.applied||{},follow_up_outcomes:log.follow_up_outcomes||{}},null,2);cell.appendChild(pre);});}
function refresh(s){const g=s.latest_state||{};renderRules(s.decision_rules);text('autopilot',s.autopilot_enabled?'ON':'OFF');text('frame',s.latest_frame);text('latency',`最近 ${s.last_decision_latency_ms??'—'} ms · 平均 ${s.average_decision_latency_ms??'—'} ms · P95 ${s.p95_decision_latency_ms??'—'} ms`);text('policy-metrics',`请求 Provider ${s.active_provider_name||'—'} / ${s.active_provider_model||'—'}\n${s.policy||'—'} · 远程 ${s.remote_call_count??0} / 本地 ${s.local_decision_count??0}\n远程延迟 ${s.remote_latency_ms??'—'} ms · P95 ${s.remote_latency_p95_ms??'—'} ms\nfallback ${s.fallback_reason||'—'}`);text('request-metrics',`request ${s.request_bytes??0} bytes · state ${s.state_bytes??0} bytes\n估算输入 ${s.estimated_input_tokens??0} tokens`);text('decision',`${s.latest_mode??'—'} / ${s.latest_action??'—'} → ${s.latest_target??'—'}`);text('role-action',s.recent_decisions?.[0]?.action_label||s.latest_action||'—');text('input',`move ${show(s.latest_move)}\nshoot ${show(s.latest_shoot)}\nLua tears ${s.lua_fired_tears}${s.lua_fire_error?'\nLua error: '+s.lua_fire_error:''}`);text('source',`${s.latest_source??'—'} / ${s.latest_confidence??'—'}`);text('macro',`${s.macro_horizon_frames??'—'} 帧窗口 · 剩余 ${s.macro_remaining_frames??'—'} · trace ${s.latest_trace_id??'—'}`);const c=s.latest_candidate_set||{};text('candidates',`policy ${c.policy||'—'} / phase ${c.phase||'—'}\n可选 ${show((c.admissible_candidates||[]).map(x=>x.id))}\n原始 ${show((c.raw_candidates||[]).map(x=>x.id))}\n过滤 ${show(c.rejected_candidates||[])}\nsingle-legal: ${c.single_legal_reason||'—'}\nprobabilities ${show(s.latest_probabilities)}`);text('reason',s.latest_reason??'waiting for game state');text('bridge',`连接 ${s.bridge_connections} · ${s.bridge_received_states} 状态包 · ${s.bridge_received_bytes} bytes${s.bridge_error?'\n错误: '+s.bridge_error:''}`);text('transition',`${s.transition_phase??'—'} · API调用 ${s.transition_attempt??0}（应始终为0）${s.transition_error?'\n错误: '+s.transition_error:''}\nLua 门检查 ${g.transition_gate??'—'} · 距离 ${g.transition_door_distance??'—'}\n反向门保护 ${s.lua_backtrack_guard_active?'ON':'OFF'} · ${s.lua_transition_source_room??'—'}→${s.lua_transition_target_room??'—'} · 入房 ${s.lua_room_entry_age_frames??0} 帧`);text('diagnostics',`动作序列 ${s.action_sequence??0} · 重复 ${s.repeated_action_count??0} · 丢弃旧动作 ${s.stale_actions_discarded??0}\n状态年龄 ${Number(s.state_age_seconds??0).toFixed(2)}s${Number(s.state_age_seconds??0)>3?'（状态已过期，游戏/桥接未继续上报）':''}\n有效动作 ${s.effective_action??'—'}\n已走边 ${show(s.traversed_edges)}\n不可达目标 ${show(s.unreachable_targets)}`);text('state',show(s.latest_state));text('telemetry',`死亡 ${s.telemetry?.episodes_recorded??0} 次\n原因统计 ${show(s.telemetry?.death_counts)}\n日志 ${s.telemetry?.path??'—'}\n最近原因 ${s.telemetry?.last_death?.cause??'—'}\n重开状态 ${g.restart_phase??'—'} · 次数 ${g.restart_count??0}${g.restart_error?'\n错误: '+g.restart_error:''}\n重复动作惩罚 ${s.stall_penalty_count??0} 次${s.stall_penalty_active?'（当前生效）':''}\n当前有效动作 ${s.effective_action??'—'}\n有效原因 ${s.effective_reason??'—'}\n移动反馈 请求 ${show(g.requested_move)} · 实际 ${show(g.resolved_move)} · 位移 ${g.movement_progress??'—'} · ${g.movement_blocked?'被阻挡':'未阻挡'}\n丢弃过期 JEV 决策 ${s.stale_decisions_discarded??0} 次\n当前策略 ${show(s.policy_profile)}`);text('floor',(s.floor_knowledge||[]).map(room=>`房间 ${room.room_index} [${room.room_type||'unknown'}] · ${room.clear?'敌人已清空':'战斗中'} · 障碍: ${room.hazards?.length?room.hazards.map(x=>`${x.kind}#${x.id}`).join(', '):'无'} · 奖励: ${room.rewards.length?room.rewards.join(', '):'当前无可捡奖励'} · 门: ${room.doors.map(door=>`${door.slot}→${door.target_room_index} [${door.room_type||'unknown'}]${door.boss?' [Boss]':''}`).join(', ')||'无'}`).join('\n')||'尚未发现房间…');const history=byId('history');history.replaceChildren(...(s.recent_decisions||[]).map(x=>{const li=document.createElement('li');li.textContent=`f${x.frame}  请求 ${x.requested_provider||'—'}/${x.model||'—'} · 执行 ${x.source||'local'}  ${x.action_label||x.action} → ${x.target||'—'}  (${Number(x.confidence).toFixed(2)})\n${x.reason||''}`;return li}));addDebugLogs(s.debug_logs||[]);text('debug-count',`已记录 ${s.debug_logs?.length??0} 条 · 最近 f${s.latest_debug_frame??'—'} ${s.latest_debug_recorded_at||''}`);text('updated','更新：'+new Date().toLocaleTimeString());byId('updated').className='ok';}
function appendRuntimeDiagnostics(s){const g=s.latest_state||{},resources=g.resources||{},tracking=g.tracking_threats||[];text('bridge',`${byId('bridge').textContent}\n控制器 ${s.controller_version||'—'} · Mod ${s.mod_version||'未连接/旧版'}`);text('input',`${byId('input').textContent}\n射击限制 ${g.fire_block_reason||'idle'} · 胶囊 ${resources.pill_use_result||'idle'} · 饰品 ${resources.trinket_swap_result||'idle'}\n炸弹 ${g.bomb_active?'爆炸等待中':g.bomb_placed?'本房间已放置':'未放置'}${g.bomb_placement_distance>=0?' · 落点距目标 '+g.bomb_placement_distance.toFixed(1)+'px · 撤离 '+show(g.bomb_escape_direction):''}${g.bomb_error?' · 错误 '+g.bomb_error:''}\n追踪鬼炸弹 ${tracking.length?tracking.map(t=>`#${t.id} ${t.distance}px`).join(' · '):'无'}`);}
const providerLabels={jev:'官方 Jev',bocha:'Bocha Jev',systemone:'System One 自托管',local:'Local 本地策略'};
let providerConfig=null;
function healthLabel(value){if(!value)return '尚未检查';if(value.ok)return value.details?.health_check==='endpoint_rejects_get'?'可连接（决策接口仅支持 POST）':`正常 · ${value.latency_ms??'—'} ms`;return `失败 · ${value.error||'未知错误'}`;}
function renderProviderCards(c){const active=c.active_provider,next=c.next_provider,shadow=c.shadow_enabled?c.shadow_provider:'';const cards=byId('provider-cards');cards.replaceChildren(...['jev','bocha','systemone','local'].map(name=>{const p=c.providers?.[name]||{},health=c.health?.[name];const card=document.createElement('article');card.className='provider-card'+(name===active?' active':'');const title=document.createElement('h3');title.textContent=providerLabels[name];const role=document.createElement('p');role.textContent=[name===active?'当前局':'',name===next?'下一局':'',name===shadow?'Shadow':''].filter(Boolean).join(' · ')||'未选中';const model=document.createElement('p');model.innerHTML=`模型：<code>${p.model||'—'}</code>`;const endpoint=document.createElement('p');endpoint.innerHTML=`地址：<code>${p.url||'进程内策略'}</code>`;const key=document.createElement('p');key.textContent=name==='local'?'无需密钥':p.auth_required===false?'无需密钥':`API Key：${p.api_key_configured?'已配置':'未配置'}`;const status=document.createElement('p');status.textContent=`健康：${healthLabel(health)}`;card.append(title,role,model,endpoint,key,status);return card;}));}
function loadProviderEditor(){if(!providerConfig)return;const name=byId('provider-select').value,p=providerConfig.providers?.[name]||{};byId('provider-url').value=p.url||'';byId('provider-health-url').value=p.health_url||'';byId('provider-model').value=p.model||'';byId('provider-auth-required').checked=p.auth_required!==false;byId('provider-key').value='';text('provider-editing',`正在编辑：${providerLabels[name]}（${name}）\n当前模型：${p.model||'—'} · 鉴权：${p.auth_required===false?'关闭':'开启'} · API Key：${p.api_key_configured?'已配置，留空将保持原值':'未配置'}\n保存后仅影响下一局。`);}
async function loadProviderConfig(){try{const r=await fetch('/api/config');providerConfig=await r.json();byId('provider-select').value=providerConfig.next_provider||providerConfig.selected_provider;byId('next-provider-select').value=providerConfig.next_provider||providerConfig.selected_provider;byId('shadow-select').value=providerConfig.shadow_provider||'jev';byId('shadow-enabled').checked=!!providerConfig.shadow_enabled;renderProviderCards(providerConfig);loadProviderEditor();}catch(e){text('provider-message','配置读取失败：'+e);}}
async function saveProviderConfig(){const name=byId('provider-select').value;const values={url:byId('provider-url').value,health_url:byId('provider-health-url').value,model:byId('provider-model').value,auth_required:byId('provider-auth-required').checked};if(byId('provider-key').value)values.api_key=byId('provider-key').value;const body={selected_provider:byId('next-provider-select').value,shadow_enabled:byId('shadow-enabled').checked,shadow_provider:byId('shadow-select').value,providers:{[name]:values}};const r=await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});byId('provider-key').value='';text('provider-message',r.ok?'已保存：下一局使用的模型已更新':await r.text());await loadProviderConfig();}
async function checkProvider(){const name=byId('provider-select').value;const r=await fetch('/api/provider/check',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({provider:name})});const result=await r.json();if(providerConfig){providerConfig.health=providerConfig.health||{};providerConfig.health[name]=result;renderProviderCards(providerConfig);}text('provider-message',`${providerLabels[name]}：${healthLabel(result)}${result.error?'\n'+result.error:''}`);}
byId('provider-select').addEventListener('change',loadProviderEditor);byId('next-provider-select').addEventListener('change',()=>{if(providerConfig){providerConfig.next_provider=byId('next-provider-select').value;renderProviderCards(providerConfig);}});
async function loadStatistics(){const p=new URLSearchParams();[['seed','stat-seed'],['provider','stat-provider'],['model','stat-model']].forEach(([k,id])=>{if(byId(id).value)p.set(k,byId(id).value)});const r=await fetch('/api/statistics?'+p);byId('statistics').textContent=JSON.stringify(await r.json(),null,2);}
byId('provider-save').addEventListener('click',saveProviderConfig);byId('provider-check').addEventListener('click',checkProvider);['stat-seed','stat-provider','stat-model'].forEach(id=>byId(id).addEventListener('change',loadStatistics));loadProviderConfig();loadStatistics();
async function poll(){try{const r=await fetch('/api/status',{cache:'no-store'});if(!r.ok)throw Error(r.status);const status=await r.json();refresh(status);appendRuntimeDiagnostics(status);renderRecoveryDiagnostics(status);}catch(e){text('updated','无法读取控制器：'+e);byId('updated').className='bad';}}poll();setInterval(poll,250);
</script></html>"""


class LocalDashboard:
    """A loopback-only, dependency-free view of the live controller state."""

    def __init__(self, controller: "Controller", host: str = "127.0.0.1", port: int = 9529) -> None:
        if not ipaddress.ip_address(host).is_loopback:
            raise ValueError("dashboard must bind to a loopback address")
        self._controller = controller
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path == "/api/status":
                    compact = parse_qs(parsed.query).get("compact") == ["1"]
                    payload = json.dumps(outer._controller.status(compact=True) if compact else outer._controller.status(), ensure_ascii=False).encode("utf-8")
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                elif parsed.path == "/api/config":
                    payload = json.dumps(outer._controller.provider_config(), ensure_ascii=False).encode("utf-8")
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                elif parsed.path == "/api/statistics":
                    query = parse_qs(parsed.query)
                    filters = {name: values[0] for name, values in query.items() if name in {"seed", "provider", "model"} and values}
                    payload = json.dumps(outer._controller.statistics(filters), ensure_ascii=False).encode("utf-8")
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                elif parsed.path == "/":
                    payload = _PAGE.encode("utf-8")
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path not in {"/api/config", "/api/provider/check", "/api/autopilot"}:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > 65536:
                        raise ValueError("request body must be between 1 and 65536 bytes")
                    if "application/json" not in self.headers.get("Content-Type", ""):
                        raise ValueError("Content-Type must be application/json")
                    body = json.loads(self.rfile.read(length).decode("utf-8"))
                    if not isinstance(body, dict):
                        raise ValueError("request body must be a JSON object")
                    if parsed.path == "/api/config":
                        result = outer._controller.update_provider_config(body)
                    elif parsed.path == "/api/autopilot":
                        if type(body.get("enabled")) is not bool:
                            raise ValueError("enabled must be a boolean")
                        compact = parse_qs(parsed.query).get("compact") == ["1"]
                        result = outer._controller.set_autopilot(body["enabled"], compact=True) if compact else outer._controller.set_autopilot(body["enabled"])
                    else:
                        result = outer._controller.check_provider(str(body.get("provider", "")))
                    payload = json.dumps(result, ensure_ascii=False).encode("utf-8")
                    self.send_response(HTTPStatus.OK)
                except (ValueError, TypeError, json.JSONDecodeError) as error:
                    payload = json.dumps({"error": str(error)}, ensure_ascii=False).encode("utf-8")
                    self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self._server = ThreadingHTTPServer((host, port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}/"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)
