import { createHash } from 'node:crypto';
import { hash } from '../backend/game/store.mjs';
import { canonical } from '../backend/dsh-bridge/channel.mjs';
import { gameFixture, samples, until } from './game-fixture.mjs';

export async function historyFixture(t, options = {}) {
  const f = await gameFixture({ fakeClock: true, ...options }); t.after(() => f.close());
  const game = await f.connect({ features: { journal_history: true } });
  return { f, game };
}
export const historyContext = (f, request_id = 'history-import-test') => ({ request_id,
  bridge_boot_id: f.manager.state.value.bridge_boot_id, world_session_id: f.manager.state.value.world_session_id });
export function historyRecord({ source = 'reliable', id = 1, payload, ...patch } = {}) {
  payload = structuredClone(payload || samples['bridge-game_event'].value.payload);
  const task = source === 'task_versions' ? payload : payload.task;
  const boot = task?.bridge_boot_id || 'boot-old-history', world = (task || payload).world_session_id;
  const type = source === 'task_versions' ? 'task_version' : task ? 'task_update' : 'game_event';
  const stream = source === 'task_versions' ? 'task_versions' : task ? 'task_transitions' : 'events';
  const sequence = source === 'task_versions' ? task.version : payload.delivery_seq;
  const raw = Buffer.from(JSON.stringify(payload));
  return { raw, info: { record_key: hash(source === 'task_versions' ? [task.task_id, task.version] : [boot, world, stream, sequence]),
    source_id: id, source_boot_id: boot, world_session_id: world, stream, sequence, type, recorded_at: 1793332800000,
    acked_at: null, archived_at: null, archive_reason: null,
    payload_sha256: createHash('sha256').update(raw).digest('hex'), payload_bytes: raw.length, ...patch } };
}
export function historyPage(f, query, records = [], { complete = true, through, chunkSize = 24576 } = {}) {
  const params = query.payload.request.params, chunks = []; let after = params.after, offset = params.offset;
  for (const record of records) {
    const bytes = record.raw.subarray(offset, offset + chunkSize), final = offset + bytes.length === record.raw.length;
    chunks.push({ ...record.info, offset, data_base64: bytes.toString('base64'), final });
    if (!final) { offset += bytes.length; break; }
    after = record.info.source_id; offset = 0;
  }
  return { kind: 'journal_history', game_instance_id: f.manager.state.value.game_instance_id,
    world_session_id: f.manager.state.value.world_session_id, based_on_seq: f.manager.state.value.seq,
    source: params.source, after: params.after, offset: params.offset, through: through ?? params.through ?? records.at(-1)?.info.source_id ?? after,
    next_after: after, next_offset: offset, complete: complete && offset === 0, chunks };
}
export async function historyQuery(f, game) {
  f.manager.tick();
  const query = await game.next('query', message => message.payload.request.kind === 'journal_history'
    && f.manager.pending.has(message.payload.operation_id));
  return query;
}
export async function historyReply(f, game, query, result) {
  game.send('query_result', { ...f.manager.operation(query.payload.operation_id), operation_id: query.payload.operation_id, request_id: query.payload.request.request_id,
    state: 'succeeded', result, error: null });
  await until(() => f.manager.operation(query.payload.operation_id).state !== 'pending');
  return f.manager.operation(query.payload.operation_id);
}
export async function finishHistory(f, game, records = [], versions = [], maintenance = {}) {
  const sources = { reliable: records, task_versions: versions, ...maintenance };
  while (f.manager.history.job) {
    const query = await historyQuery(f, game);
    await historyReply(f, game, query, historyPage(f, query, sources[query.payload.request.params.source] || []));
  }
  return f.manager.history.status();
}
export function maintenanceRecord({ source = 'retention_summaries', id = 1, value, instance = 'mc-instance-example' } = {}) {
  const label = { retention_summaries: 'summary', retired_tasks: 'retired', retention_runs: 'run' }[source];
  const payload = structuredClone(samples['maintenance-' + label + '-payload'].value);
  payload.game_instance_id = instance;
  if (value) payload.value = structuredClone(value);
  if (source === 'retention_summaries') payload.source_key = hash(Object.fromEntries(['world_session_id', 'source', 'kind', 'utc_day'].map(key => [key, payload.value[key]])));
  else payload.source_key = payload.value[source === 'retired_tasks' ? 'task_id' : 'run_id'];
  const raw = Buffer.from(canonical(payload)), info = structuredClone(samples['maintenance-' + label + '-chunk'].value);
  for (const key of ['offset', 'data_base64', 'final']) delete info[key];
  Object.assign(info, { source_id: id, payload_sha256: createHash('sha256').update(raw).digest('hex'), payload_bytes: raw.length });
  info.record_key = hash([source, payload.source_key, info.payload_sha256]);
  info.source_boot_id = source === 'retired_tasks' ? payload.value.summary.bridge_boot_id : null;
  info.world_session_id = source === 'retention_runs' ? null : payload.value.world_session_id;
  info.recorded_at = source === 'retention_summaries' ? payload.value.last_recorded_at
    : source === 'retired_tasks' ? payload.value.retired_at : Date.parse(payload.value.completed_at);
  return { raw, info };
}
