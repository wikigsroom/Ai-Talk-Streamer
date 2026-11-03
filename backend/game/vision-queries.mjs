import { randomUUID } from 'node:crypto';
import { ensure, utc } from './errors.mjs';

const ID = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/;
const SCOPE = ['world_session_id', 'bridge_boot_id', 'connection_generation'];
const terminal = operation => ['succeeded', 'failed'].includes(operation.state);

// A vision inference can exceed one SDK tool call. Admission returns promptly;
// the existing operation deadline, single slot and native frame binding own the
// accepted job. Only handles admitted through this tool can be read/cancelled.
export class VisionQueries {
  tick() {
    const m=this.manager,status=m.vision.provider.status?.(),state=m.state.view();
    if(!status?.ready||!m.config.enabled||!m.config.vision.enabled||!m.config.planner.enabled||
      state.mode!=='AUTO'||state.freshness!=='fresh'||state.screen!=='gameplay'||this.observerRunning)return;
    const observe=async()=>{
      if(this.observerOperation) {
        const operation=this.observerOperation;this.observerOperation=null;
        try {const value=this.invoke({operation_id:operation},{});if(value.state==='pending'||value.state==='running')this.observerOperation=operation;}
        catch { /* Session changes and expired captures cannot become current observations. */ }
        return;
      }
      if(m.vision.busy||m.clock()-(this.lastObservedAt??-Infinity)<status.observe_interval_ms)return;
      this.lastObservedAt=m.clock();
      const value=this.invoke({purpose:'screen'},{});this.observerOperation=value.operation_id;
    };
    this.observerRunning=true;
    const run=()=>observe().catch(error=>{m.publish('vision',{state:'failed',code:error.code||'GAME_VISION_PROVIDER_FAILED'});})
      .finally(()=>{this.observerRunning=false;});
    if(m.bridge.background)m.bridge.background('game_visual_observation',run);else void run();
  }
  constructor(manager) { this.manager = manager; this.handles = new Map(); }
  prune() {
    for (const [id, handle] of this.handles) if (this.manager.clock() >= handle.expires) this.handles.delete(id);
  }
  sameScope(handle, state) { return SCOPE.every(key => handle.scope[key] === state[key]); }
  summary() {
    this.prune(); const state = this.manager.state.view();
    if (state.freshness !== 'fresh') return null;
    const handle = [...this.handles.values()].reverse().find(value => this.sameScope(value, state));
    if (!handle) return null;
    const operation = this.manager.operation(handle.id);
    return { ...this.view(handle,operation),
      read_tool: 'game_request_observation', rule: 'pending不是观察结果；用operation_id读取，成功结果仍是带捕获时间的历史视觉推断。' };
  }
  view(handle, operation) {
    const result = operation.result ? structuredClone(operation.result) : null;
    if (result) result.age_ms = Math.max(0, this.manager.wall() - Date.parse(result.captured_at));
    return { operation_id: handle.id, kind: 'observation', world_session_id: handle.scope.world_session_id,
      purpose: handle.purpose, state: operation.state, error: operation.error, result,
      expires_at: handle.expires_at, poll_after_ms: terminal(operation) ? null : 1000,
      rule: result ? '这是捕获时刻的历史视觉推断，不能覆盖更新的原生事实或证明任务完成。' :
        '尚无视觉结果；等待后续请求或规划轮，再用operation_id读取，不连续轮询，不把pending说成已看到。' };
  }
  invoke(args, context) {
    const m = this.manager;
    const state = m.state.requireFresh(); this.prune();
    if (args.operation_id !== undefined) {
      ensure(typeof args.operation_id === 'string' && ID.test(args.operation_id) && args.purpose === undefined &&
        (args.cancel === undefined || typeof args.cancel === 'boolean'), 'GAME_REQUEST_INVALID', 400);
      const handle = this.handles.get(args.operation_id); ensure(handle, 'GAME_VISION_HANDLE_NOT_FOUND', 404);
      ensure(this.sameScope(handle, state), 'GAME_WORLD_CHANGED');
      let operation = m.operation(handle.id);
      if (args.cancel === true && !terminal(operation)) operation = m.finishOperation(operation, null, 'GAME_VISION_CANCELLED');
      return this.view(handle, operation);
    }
    ensure(['building', 'screen', 'text'].includes(args.purpose) && args.cancel === undefined, 'GAME_REQUEST_INVALID', 400);
    ensure(!context.signal?.aborted, 'GAME_PLAN_CANCELLED');
    // Evict completed handles only. Pending jobs are never silently replaced.
    if (this.handles.size >= 8) for (const [id] of this.handles) {
      if (terminal(m.operation(id))) { this.handles.delete(id); break; }
    }
    ensure(this.handles.size < 8, 'GAME_QUEUE_FULL', 429);
    const operation = m.query({ request_id: 'vision-' + randomUUID(), bridge_boot_id: state.bridge_boot_id,
      world_session_id: state.world_session_id, kind: 'observation', params: { purpose: args.purpose } });
    const ttl = m.config.vision.timeout_ms + 30000;
    const handle = { id: operation.operation_id, purpose: args.purpose,
      scope: Object.fromEntries(SCOPE.map(key => [key, state[key]])),
      expires: m.clock() + ttl, expires_at: utc(m.wall() + ttl) };
    this.handles.set(handle.id, handle);
    return this.view(handle, operation);
  }
}
