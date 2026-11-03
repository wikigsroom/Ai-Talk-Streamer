import { randomUUID } from 'node:crypto';
import { canonical } from '../dsh-bridge/channel.mjs';
import { planningState, planningStateRead } from './model-state.mjs';
import { MindcraftNativePlanner, mindcraftThreatened } from './mindcraft/native-planner.mjs';

export class GamePlanner {
  constructor(manager) {
    this.manager = manager; this.running = null; this.scope = null; this.lastCall = -Infinity; this.checks = new Map();
    this.mindcraft = new MindcraftNativePlanner(manager);
    this.autostart = null;
    this.emergencyCall = false;
    this.lastEmergency = -Infinity;
    this.respawnAttempts = [];
    this.suspendedScope = null;
    this.threatCancellation = null;
    this.onState = state => {
      if (state.mode !== 'AUTO' || state.freshness !== 'fresh' || this.scope &&
          Object.keys(this.scope).some(key => state[key] !== this.scope[key])) this.cancel();
      else if (this.threatened(state) && !this.emergencyCall && !state.active_task_id && !manager.tasks.active()) this.cancel();
    };
    manager.on('state', this.onState);
  }
  cancel() { this.running?.abort(); }
  threatened(state) {
    return this.manager.config.planner.engine === 'mindcraft_native' && mindcraftThreatened(state);
  }
  suspendAutostart() {
    if (!this.manager.config.planner.enabled || !this.manager.config.planner.autostart) return;
    const state=this.manager.stateView();
    const scope=canonical([state.bridge_boot_id,state.world_session_id,state.connection_generation]);
    this.suspendedScope = scope;
    if (this.autostart?.scope !== scope) this.autostart={scope,since:this.manager.clock(),attempts:0,operation:null,suspended:true};
    else this.autostart.suspended=true;
  }
  retryAutostart() {
    // Keep the explicit/physical stop fence and attempt budget. A verified
    // transient revocation may only request a new handshake after fresh data.
    if (this.autostart) Object.assign(this.autostart,{operation:null,suspended:false,since:this.manager.clock()});
  }
  startSession(state) {
    const m = this.manager;
    if (!m.config.enabled || !m.config.planner.enabled || !m.config.planner.autostart ||
        m.bridge.administration?.locked || state.freshness !== 'fresh' || !state.world_session_id ||
        !m.bridge.health?.().persona_injection_ready) return;
    const dead = state.screen === 'death' && state.player?.health === 0 && m.capabilities?.features?.autonomous_respawn === true;
    if (this.suspendedScope === canonical([state.bridge_boot_id,state.world_session_id,state.connection_generation])) return;
    const scope = canonical([state.bridge_boot_id,state.world_session_id,state.connection_generation,dead ? 'dead' : 'alive']);
    if (this.autostart?.scope !== scope) this.autostart = {scope,since:m.clock(),attempts:0,suspended:false,operation:null};
    const row = this.autostart;
    if (row.operation) {
      const operation = m.operation(row.operation);
      if (operation.state === 'succeeded') { row.suspended = true; return; }
      if (!['failed','cancelled'].includes(operation.state)) return;
      row.operation = null; row.since = m.clock();
    }
    if (row.suspended || row.attempts >= 3 || m.clock()-row.since < 3000 || state.mode !== 'PAUSED' ||
        !state.inputs_released || state.active_task_id || m.tasks.active() || !(dead || state.player?.health > 0) ||
        !['gameplay','menu',...(dead ? ['death'] : [])].includes(state.screen)) return;
    this.respawnAttempts = this.respawnAttempts.filter(at => m.clock() - at < 600000);
    if (dead && this.respawnAttempts.length >= 3) return;
    row.attempts++;
    try {
      row.operation = m.control({request_id:'agent-autostart-' + randomUUID(),target_mode:'AUTO',reason:dead ? 'AGENT_MINDCRAFT_NORMAL_RESPAWN' : 'AGENT_MINDCRAFT_SESSION_AUTOSTART',
        bridge_boot_id:state.bridge_boot_id,world_session_id:state.world_session_id,expected_control_epoch:state.control_epoch}).operation_id;
      if (dead) this.respawnAttempts.push(m.clock());
      m.publish('mindcraft',{state:'starting_session',attempt:row.attempts,operation_id:row.operation});
    } catch(error) { row.since=m.clock(); m.publish('mindcraft',{state:'start_retry',error:error.code || 'GAME_AUTOSTART_FAILED'}); }
  }
  checkContext(state) {
    return canonical({ world: state.world_session_id, boot: state.bridge_boot_id, generation: state.connection_generation,
      epoch: state.control_epoch, position: state.player?.position, inventory: state.inventory });
  }
  rememberCheck(goal, operation, admitted) {
    const state = this.manager.stateView();
    if (state.freshness !== 'fresh' || this.checkContext(admitted) !== this.checkContext(state) ||
        operation.state !== 'succeeded' || operation.result?.allowed !== false) return;
    // Quantity does not establish a new route to the same gather source.
    const key = canonical(goal.skill === 'gather' ? { ...goal, count: 1 } : goal);
    this.checks.delete(key);
    this.checks.set(key, { context: this.checkContext(state), at: this.manager.clock(),
      fact: { goal: structuredClone(goal), allowed: false, reason: String(operation.result.reason || 'not_confirmed').slice(0, 240),
        operation_id: operation.operation_id, source_seq: operation.result.based_on_seq ?? state.seq } });
    while (this.checks.size > 6) this.checks.delete(this.checks.keys().next().value);
  }
  recentChecks(state) {
    const context = this.checkContext(state), now = this.manager.clock();
    for (const [key, row] of this.checks) if (state.freshness !== 'fresh' || row.context !== context || now - row.at >= 120000) this.checks.delete(key);
    return [...this.checks.values()].slice(-3).map(row => ({ ...structuredClone(row.fact), age_ms: Math.max(0, now - row.at) }));
  }
  interruptForThreat(state) {
    const m = this.manager, task = m.tasks.active();
    if (!task) { this.threatCancellation = null; return; }
    if (!m.config.enabled || !m.config.planner.enabled || !this.threatened(state) ||
        state.mode !== 'AUTO' || state.freshness !== 'fresh' || !state.automation_ready || !m.lease ||
        m.bridge.administration?.locked || !m.capabilities?.skills?.includes('cancel') ||
        !m.config.control.enabled_skills.includes('cancel')) return;
    // Keep eating and the current checked escape running. Ordinary production
    // must release its actual native task before a new escape may be admitted.
    if (task.goal?.skill === 'use_item' && task.goal.purpose === 'eat' ||
        this.mindcraft.pending?.task_id === task.task_id && this.mindcraft.pending.emergencyRetreat) return;
    const scope = canonical([state.bridge_boot_id,state.world_session_id,state.connection_generation,state.control_epoch,task.task_id]);
    if (this.threatCancellation?.scope === scope) return;
    this.cancel();
    this.threatCancellation = { scope, operation_id:null };
    const operation = m.cancel(task.task_id, { request_id:'agent-threat-cancel-' + randomUUID(), reason:'AGENT_EMERGENCY_THREAT' });
    this.threatCancellation = { scope, operation_id:operation.operation_id };
    m.publish('planner', { state:'cancelling_for_threat',task_id:task.task_id,operation_id:operation.operation_id,based_on_seq:state.seq });
  }
  async tick() {
    const m = this.manager, state = m.stateView(), host = m.bridge.host;
    const emergency = this.threatened(state);
    this.startSession(state);
    try { this.interruptForThreat(state); }
    catch (error) { m.publish('planner', { state:'threat_cancel_failed',error:error.code || 'GAME_THREAT_CANCEL_FAILED' }); return; }
    if (this.running || m.bridge.administration?.locked || !m.config.enabled || !m.config.planner.enabled || !m.lease || state.mode !== 'AUTO' || !state.automation_ready ||
        m.tasks.active() || state.active_task_id || !host || !m.bridge.health?.().persona_injection_ready ||
        m.clock() - (emergency ? this.lastEmergency : this.lastCall) < (emergency ? 500 : m.config.planner.min_interval_ms)) return;
    const objective = state.world_ledger.world_goals.find(goal => goal.status === 'active');
    // A completed executor still needs the following observation. Do not ask a
    // model to replace, duplicate or skip an approved step during that interval.
    if (!emergency && objective && (objective.last_review_session_id !== state.world_session_id || objective.next_step?.state !== 'pending')) return;
    const controller = new AbortController(); this.running = controller; this.lastCall = m.clock();
    this.emergencyCall = emergency;
    if (emergency) this.lastEmergency = m.clock();
    this.scope = Object.fromEntries(['world_session_id', 'control_epoch', 'bridge_boot_id', 'connection_generation'].map(key => [key, state[key]]));
    const context = { purpose: 'game_plan', worldSessionId: state.world_session_id, controlEpoch: state.control_epoch,
      signal: AbortSignal.any([controller.signal, AbortSignal.timeout(m.config.planner.max_call_ms)]) };
    try {
      if (emergency) {
        this.mindcraft.current(state);
        if (this.mindcraft.settle(state)) await this.mindcraft.retreat(context, state);
        return;
      }
      if (objective) {
        const reference = { goal_id: objective.goal_id, step_id: objective.next_step.step_id, expected_revision: objective.revision };
        const task = await m.tools.invoke('game_start_task', { goal: objective.next_step.goal }, { ...context, worldGoalRef: reference });
        m.publish('planner', { state: 'idle', action_task_id: task.task_id, world_goal_id: reference.goal_id, step_id: reference.step_id });
        return;
      }
      const proposals = m.suggestions.pending(m.config.planner.candidate_limit)
        .filter(s => s.state === 'accepted' && m.wall() < Date.parse(s.expires_at) && m.suggestions.sourceAvailable(s));
      if (m.config.planner.engine === 'mindcraft_native' && !proposals.length && await this.mindcraft.bootstrap(context)) return;
      const initialGame = planningState(state), recentChecks = this.recentChecks(state), recentTasks = m.tasks.planningOutcomes(state);
      const result = await host.generate({ sessionId: 'mc-plan-' + randomUUID(), snapshot: m.bridge.channel.snapshot(),
        purpose: 'game_plan', input: 'recent_task_results是同一世界、原生桥和控制会话内最近五分钟的真实终态，最多三项，包含失败原因和effect_status；这是历史执行结果，不是当前库存、位置或成功保证。unknown和partial不能当作verified。没有新状态或路线依据时，不重复失败目标；不要将连续短导航当作生产成果。优先推进已批准世界目标next_step，处理必要生存动作。执行已采纳建议时，game_start_task须传suggestion_id及相同goal；未审核建议、平票不执行。没有目标或已采纳建议时，可选择一个必要的少量生存补给动作；采集新增1至4个，不循环囤积。当前观测、库存和账本已提供，无需重复读取；nearby_food仅是有限范围和采样时间内的食物来源，不是库存或可达保证。缺食物时可检查成熟作物或掉落物，小麦需合成面包；空列表不代表远处无食物。支持targeted_planting时，可用原生planting_sites的明确空格坐标补种四种作物；每次消耗一个种子或作物，采收、补种与进食分别核验，先保证食物储备，不猜空地或播种成功。先game_check_action，再调用一个固定技能。recent_action_checks是同一位置、库存和控制会话中近期真实拒绝，仍是历史检查；没有新依据时考虑其他可行物品或技能，不改数量反复检查同一不可达资源。needs_review、blocked等待核对，历史完成不等于当前库存或效果。视觉pending须等待后续规划轮，用operation_id读结果，不能在本轮连续轮询。采用Agent＋Mindcraft自主游玩，不依赖人工接管。construction提供有限范围内可见工作台/熔炉和候选放置空格；仅对明确位置检查并放置，候选不是成功承诺。工作台已在附近时直接使用；库存里有工作台时先放置，再制作工具。需要物品时先用game_plan_item按总库存目标拆解依赖，再对返回的next_goal检查并执行。navigation.frontiers是绑定当前位置、有限时效和搜索预算的可达候选，仍须game_check_action；附近出现敌对实体时优先向远离威胁的候选navigate，不能在原地反复装备物品等待挨打。撤离后重新读取状态和账本，不等待人工接管。缺少资源时，优先检查新鲜navigation.frontiers，再依据当前位置尝试小范围navigate并核验路线；拒绝后换方向或换可行目标。动作失败后读取真实任务及新观测，不能重复提交旧请求、无限囤积或把未知效果当成功。仅在仍无安全可执行动作时有界等待下一轮，不要求人工操作。',
        context: canonical({ game: initialGame, capabilities: m.capabilities, suggestions: proposals,
          ...(m.config.planner.engine === 'mindcraft_native' && this.mindcraft.lastPlan ? {mindcraft_plan:this.mindcraft.lastPlan} : {}),
          ...(recentChecks.length ? { recent_action_checks: recentChecks } : {}),
          ...(recentTasks.length ? { recent_task_results: recentTasks } : {}),
          ...(m.tools.observationSummary() ? { vision_observation: m.tools.observationSummary() } : {}) }), signal: context.signal,
        toolCatalogue: m.tools.catalogue('game_plan'), tools: async (name, args, execution) => {
          const admitted = name === 'game_check_action' ? m.stateView() : null;
          const value = await m.tools.invoke(name, args,
            { ...context, signal: execution?.signal ? AbortSignal.any([context.signal, execution.signal]) : context.signal });
          if (name === 'game_get_state') return planningStateRead(initialGame, m.stateView());
          if (name === 'game_check_action') {
            if (!context.signal.aborted) this.rememberCheck(args.goal, value, admitted);
            return { operation_id: value.operation_id, state: value.state, result: value.result, error: value.error };
          }
          return value;
        },
        onCall: m.bridge.onCall?.({ maxTokens: 512 }), onProbe: probe => m.bridge.recordProbe?.(probe), maxTokens: 512 });
      if (!context.signal.aborted && m.state.value.world_session_id === context.worldSessionId && m.state.value.control_epoch === context.controlEpoch)
        m.publish('planner', { state: 'idle', session_id: result.session_id, action_task_id: m.tasks.active()?.task_id || null,
          recent_task_result_ids: recentTasks.map(task => task.task_id) });
    } catch (error) {
      const cancelled = controller.signal.aborted || ['MODEL_CANCELLED', 'MODEL_PREEMPTED', 'GAME_PLAN_CANCELLED',
        'GAME_PLAN_SUPERSEDED_BY_SPEECH', 'GAME_QUERY_CANCELLED'].includes(error.code || error.message);
      m.publish('planner', { state: cancelled ? 'cancelled' : 'waiting', error: error.code || 'GAME_PLANNER_FAILED' });
    }
    finally { if (this.running === controller) { this.running = null; this.scope = null; this.emergencyCall = false; } }
  }
  close() { this.cancel(); this.manager.off('state', this.onState); }
}
