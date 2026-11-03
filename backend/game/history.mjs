import { randomUUID, createHash } from 'node:crypto';
import { canonical } from '../dsh-bridge/channel.mjs';
import { GameError, ensure, utc } from './errors.mjs';
import { validate } from './protocol.mjs';
import { hash } from './store.mjs';
import { MAINTENANCE_HISTORY_SOURCES, validateMaintenanceHistory, maintenanceHistorySummary } from './history-maintenance.mjs';

export const HISTORY_LIMITS = Object.freeze({ entries: 200000, payload_bytes: 256 * 1024 * 1024,
  import_jobs: 256, page_bytes: 48 * 1024, chunk_bytes: 24 * 1024, record_bytes: 131072 });
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const metadata = chunk => Object.fromEntries(Object.entries(chunk).filter(([key]) => !['offset', 'data_base64', 'final'].includes(key)));
const immutable = value => Object.fromEntries(Object.entries(value).filter(([key]) => !['source_id', 'acked_at', 'archived_at', 'archive_reason'].includes(key)));

/** A historical projection has no path to live task state, ACKs, narration or Humanity. */
export class GameHistory {
  constructor(manager) {
    this.manager = manager; this.store = manager.store; this.job = null;
    this.store.transaction(() => {
      for (const row of this.store.all("SELECT value FROM objects WHERE kind='history_import' AND json_extract(value,'$.state')='running'")) {
        const job = JSON.parse(row.value); Object.assign(job, { state: 'interrupted', reason: 'GAME_HISTORY_HOST_RESTART',
          operation_id: null, updated_at: this.now() }); this.store.put('history_import', job);
      }
      this.store.run('DELETE FROM history_partial');
    });
  }
  now() { return utc(this.manager.wall()); }
  totals() {
    const instance = this.store.meta('bound_instance', null);
    const value = this.store.get('SELECT count(*) records,coalesce(sum(payload_bytes),0) bytes FROM bridge_history WHERE instance=?', instance);
    return { records: value.records, payload_bytes: value.bytes };
  }
  status() { return { latest_import: structuredClone(this.job || this.store.list('history_import', { limit: 1 }).items[0] || null),
    totals: this.totals(), limits: HISTORY_LIMITS, current_import_running: !!this.job }; }
  publish() { this.manager.publish('history', this.status()); }
  start(request) {
    validate('HistoryImportRequest', request);
    const previous = this.store.replay('history-import', request); if (previous) return previous;
    const state = this.manager.checkContext(request);
    ensure(this.manager.capabilities?.features.journal_history, 'GAME_CAPABILITY_UNAVAILABLE', 503);
    ensure(state.mode !== 'AUTO' && state.inputs_released && !this.manager.tasks.active(), 'GAME_HISTORY_MODE_BLOCKED');
    ensure(!this.job, 'GAME_HISTORY_BUSY');
    ensure(this.store.get("SELECT count(*) n FROM objects WHERE kind='history_import'").n < HISTORY_LIMITS.import_jobs, 'GAME_HISTORY_IMPORT_LIMIT', 503);
    const job = { history_import_id: 'history-' + randomUUID(), state: 'running', reason: null,
      game_instance_id: state.game_instance_id, bridge_boot_id: state.bridge_boot_id,
      world_session_id: state.world_session_id, connection_generation: state.connection_generation,
      source: 'reliable', after: 0, offset: 0, through: null, operation_id: null,
      source_order: ['reliable', 'task_versions', ...(this.manager.capabilities.features.journal_maintenance_history ? MAINTENANCE_HISTORY_SOURCES : [])],
      scanned_records: 0, imported_records: 0, duplicate_records: 0, pages: 0, received_bytes: 0,
      created_at: this.now(), updated_at: this.now() };
    this.store.transaction(() => this.store.remember('history-import', request, 'history_import', job));
    this.job = job; this.publish(); return structuredClone(job);
  }
  stoppedContext(job) {
    const state = this.manager.state.view();
    ensure(state.connected && state.freshness === 'fresh', 'GAME_HISTORY_CONNECTION_UNAVAILABLE', 503);
    ensure(state.game_instance_id === job.game_instance_id && state.bridge_boot_id === job.bridge_boot_id
      && state.world_session_id === job.world_session_id && state.connection_generation === job.connection_generation, 'GAME_HISTORY_CONTEXT_CHANGED');
    ensure(state.mode !== 'AUTO' && state.inputs_released && !this.manager.tasks.active(), 'GAME_HISTORY_MODE_BLOCKED');
  }
  tick() {
    if (!this.job) return;
    try {
      this.stoppedContext(this.job); if (this.job.operation_id) return;
      const request = { request_id: this.job.history_import_id + '-p' + this.job.pages,
        bridge_boot_id: this.job.bridge_boot_id, world_session_id: this.job.world_session_id,
        kind: 'journal_history', params: { source: this.job.source, after: this.job.after,
          offset: this.job.offset, through: this.job.through, limit: 20 } };
      const operation = this.manager.query(request, { historyImportId: this.job.history_import_id });
      this.job.operation_id = operation.operation_id; this.job.updated_at = this.now();
      this.store.put('history_import', this.job); this.publish();
    } catch (error) {
      if (!(error instanceof GameError) || error.code === 'GAME_STORE_OWNER_LOST') throw error;
      this.stop(error.code, 'failed');
    }
  }
  stop(reason, state = 'interrupted') {
    const job = this.job; if (!job) return;
    this.job = null;
    const operation = job.operation_id ? this.manager.pending.get(job.operation_id)?.operation : null;
    Object.assign(job, { state, reason, operation_id: null, updated_at: this.now() });
    this.store.transaction(() => { this.store.put('history_import', job); this.store.run('DELETE FROM history_partial WHERE import_id=?', job.history_import_id); });
    if (operation) this.manager.finishOperation(operation, null, reason);
    this.publish();
  }
  operationFailed(pending, error) {
    if (this.job?.history_import_id === pending?.historyImportId && this.job.operation_id === pending.operation.operation_id)
      this.stop(error, 'failed');
  }
  cancel(id, request) {
    validate('ReconcileRequest', request);
    const existing = this.store.object('history_import', id);
    ensure(existing, 'GAME_HISTORY_IMPORT_NOT_FOUND', 404);
    if (existing.state !== 'running') return existing;
    ensure(this.job?.history_import_id === id, 'GAME_HISTORY_IMPORT_CHANGED');
    this.stop('GAME_HISTORY_CANCELLED', 'cancelled');
    return this.store.object('history_import', id);
  }
  accept(result, pending) {
    validate('JournalHistoryResult', result);
    ensure(this.job && this.job.history_import_id === pending.historyImportId
      && this.job.operation_id === pending.operation.operation_id, 'GAME_HISTORY_IMPORT_CHANGED');
    this.stoppedContext(this.job);
    const job = structuredClone(this.job), params = pending.historyParams;
    ensure(result.game_instance_id === job.game_instance_id && result.world_session_id === job.world_session_id
      && result.source === params.source && result.after === params.after && result.offset === params.offset
      && (params.through === null || params.through === result.through)
      && result.through >= result.after && result.chunks.length <= params.limit, 'GAME_HISTORY_PAGE_CONTEXT');
    let after = params.after, offset = params.offset, bytes = 0;
    this.store.transaction(() => {
      let partial = this.store.get('SELECT value FROM history_partial WHERE import_id=?', job.history_import_id);
      partial = partial ? JSON.parse(partial.value) : null;
      let total = this.totals();
      for (const chunk of result.chunks) {
        const data = Buffer.from(chunk.data_base64, 'base64'); bytes += data.length;
        ensure(data.length > 0 && data.length <= HISTORY_LIMITS.chunk_bytes && data.toString('base64') === chunk.data_base64
          && bytes <= HISTORY_LIMITS.page_bytes, 'GAME_HISTORY_CHUNK_SIZE');
        ensure(chunk.source_id > after && chunk.source_id <= result.through && chunk.offset === offset, 'GAME_HISTORY_CHUNK_ORDER');
        if (partial) ensure(partial.metadata.source_id === chunk.source_id && canonical(immutable(partial.metadata)) === canonical(immutable(metadata(chunk))), 'GAME_HISTORY_CHUNK_CHANGED');
        else ensure(offset === 0, 'GAME_HISTORY_PARTIAL_MISSING');
        const buffer = Buffer.concat([partial ? Buffer.from(partial.buffer, 'base64') : Buffer.alloc(0), data]);
        ensure(buffer.length === offset + data.length && buffer.length <= chunk.payload_bytes && buffer.length <= HISTORY_LIMITS.record_bytes
          && chunk.final === (buffer.length === chunk.payload_bytes), 'GAME_HISTORY_CHUNK_LENGTH');
        if (!chunk.final) {
          ensure(result.chunks.at(-1) === chunk, 'GAME_HISTORY_CHUNK_ORDER');
          partial = { metadata: partial?.metadata || metadata(chunk), buffer: buffer.toString('base64') }; offset = buffer.length; continue;
        }
        ensure(sha(buffer) === chunk.payload_sha256, 'GAME_HISTORY_PAYLOAD_HASH');
        let payload;
        try { payload = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(buffer)); }
        catch { throw new GameError('GAME_HISTORY_PAYLOAD_INVALID', 400); }
        const info = partial?.metadata || metadata(chunk);
        this.validatePayload(job, info, payload);
        const oldRow = this.store.get('SELECT value,payload_hash FROM bridge_history WHERE instance=? AND source=? AND record_key=?', job.game_instance_id, job.source, info.record_key);
        const previous = oldRow ? JSON.parse(oldRow.value) : null;
        if (previous) ensure(oldRow.payload_hash === info.payload_sha256 && canonical(immutable(previous.metadata)) === canonical(immutable(info)), 'GAME_HISTORY_RECORD_CONFLICT');
        else {
          ensure(total.records < HISTORY_LIMITS.entries && total.payload_bytes + buffer.length <= HISTORY_LIMITS.payload_bytes, 'GAME_HISTORY_CAPACITY', 503);
          total.records++; total.payload_bytes += buffer.length;
        }
        const value = { game_instance_id: job.game_instance_id, source: job.source, record_key: info.record_key,
          metadata: previous?.metadata || info, payload, first_projected_at: previous?.first_projected_at || this.now(), last_projected_at: this.now(),
          metadata_conflict: previous?.metadata_conflict || false };
        if (previous) for (const key of ['acked_at', 'archived_at', 'archive_reason']) {
          if (value.metadata[key] === null) value.metadata[key] = info[key];
          else if (info[key] !== null && value.metadata[key] !== info[key]) value.metadata_conflict = true;
        }
        this.store.run('INSERT INTO bridge_history VALUES(?,?,?,?,?,?,?) ON CONFLICT(instance,source,record_key) DO UPDATE SET value=excluded.value',
          job.game_instance_id, job.source, info.record_key, info.world_session_id ?? '', info.payload_sha256, buffer.length, canonical(value));
        job.scanned_records++; if (previous) job.duplicate_records++; else job.imported_records++;
        after = chunk.source_id; offset = 0; partial = null;
      }
      ensure(after === result.next_after && offset === result.next_offset && after <= result.through
        && (!result.complete || offset === 0 && after === result.through) && (result.complete || result.chunks.length > 0), 'GAME_HISTORY_CURSOR_INVALID');
      if (partial) this.store.run('INSERT INTO history_partial VALUES(?,?) ON CONFLICT(import_id) DO UPDATE SET value=excluded.value', job.history_import_id, canonical(partial));
      else this.store.run('DELETE FROM history_partial WHERE import_id=?', job.history_import_id);
      Object.assign(job, { after, offset, through: result.through, pages: job.pages + 1,
        received_bytes: job.received_bytes + bytes, operation_id: null, updated_at: this.now() });
      if (result.complete) {
        ensure(!partial, 'GAME_HISTORY_CURSOR_INVALID');
        const sources = job.source_order || ['reliable', 'task_versions'], index = sources.indexOf(job.source);
        ensure(index >= 0, 'GAME_HISTORY_PAGE_CONTEXT');
        if (index + 1 < sources.length) Object.assign(job, { source: sources[index + 1], after: 0, offset: 0, through: null });
        else Object.assign(job, { state: 'completed', reason: null });
      }
      this.store.put('history_import', job);
    });
    this.job = job.state === 'running' ? job : null; this.publish();
    return { kind: 'journal_history', imported_records: job.imported_records, scanned_records: job.scanned_records,
      source: result.source, complete: result.complete, import_state: job.state, history_import_id: job.history_import_id };
  }
  validatePayload(job, info, payload) {
    if (MAINTENANCE_HISTORY_SOURCES.includes(job.source)) return validateMaintenanceHistory(job, info, payload);
    if (job.source === 'task_versions') {
      validate('Task', payload);
      ensure(info.type === 'task_version' && info.stream === 'task_versions' && info.sequence === payload.version
        && info.record_key === hash([payload.task_id, payload.version]) && info.acked_at === null && info.archived_at === null && info.archive_reason === null, 'GAME_HISTORY_RECORD_CONTEXT');
    } else {
      ensure(info.type !== 'task_version' && info.stream === (info.type === 'game_event' ? 'events' : 'task_transitions'), 'GAME_HISTORY_RECORD_CONTEXT');
      validate(info.type === 'game_event' ? 'HistoryEventPayload' : 'HistoryTaskPayload', payload);
      ensure(payload.delivery_seq === info.sequence && info.record_key === hash([info.source_boot_id, info.world_session_id, info.stream, info.sequence]), 'GAME_HISTORY_RECORD_CONTEXT');
      if (info.type === 'task_update') ensure(payload.transition_seq === payload.task.version, 'GAME_HISTORY_RECORD_CONTEXT');
    }
    const task = job.source === 'task_versions' ? payload : payload.task;
    ensure((task || payload).world_session_id === info.world_session_id, 'GAME_HISTORY_RECORD_CONTEXT');
    if (task) ensure(task.bridge_boot_id === info.source_boot_id && task.game_instance_id === job.game_instance_id, 'GAME_HISTORY_RECORD_CONTEXT');
  }
  page({ limit = 20, cursor, kind } = {}) {
    ensure(Number.isInteger(limit) && limit >= 1 && limit <= 100, 'GAME_REQUEST_INVALID', 400);
    const filters = { events: "AND source='reliable' AND json_extract(value,'$.metadata.type')='game_event'",
      task_deliveries: "AND source='reliable' AND json_extract(value,'$.metadata.type')='task_update'", task_versions: "AND source='task_versions'",
      retention_summaries: "AND source='retention_summaries'", retired_tasks: "AND source='retired_tasks'", retention_runs: "AND source='retention_runs'" };
    ensure(kind === undefined || Object.hasOwn(filters, kind), 'GAME_REQUEST_INVALID', 400);
    ensure(!cursor || /^[1-9][0-9]{0,15}$/.test(cursor) && Number.isSafeInteger(Number(cursor)), 'GAME_CURSOR_INVALID', 400);
    const rows = this.store.all(`SELECT rowid,value FROM bridge_history WHERE instance=? AND rowid<? ${filters[kind] || ''} ORDER BY rowid DESC LIMIT ?`,
      this.store.meta('bound_instance', null), cursor ? Number(cursor) : Number.MAX_SAFE_INTEGER, limit + 1);
    return { items: rows.slice(0, limit).map(row => this.summary(JSON.parse(row.value))), next_cursor: rows.length > limit ? String(rows[limit - 1].rowid) : null };
  }
  summary(value) {
    if (MAINTENANCE_HISTORY_SOURCES.includes(value.source)) {
      const { payload, ...metadata } = value;
      return { ...metadata, summary: maintenanceHistorySummary(payload) };
    }
    const task = value.source === 'task_versions' ? value.payload : value.payload.task;
    const { payload, ...metadata } = value;
    return { ...metadata, summary: task ? { kind: 'task', task_id: task.task_id, version: task.version, state: task.state, effect_status: task.effect_status, skill: task.goal.skill }
      : { kind: 'event', event_id: payload.event_id, event_kind: payload.kind, severity: payload.severity, occurred_at: payload.occurred_at } };
  }
  entry(key) {
    ensure(/^[0-9a-f]{64}$/.test(key), 'GAME_REQUEST_INVALID', 400);
    const row = this.store.get('SELECT value FROM bridge_history WHERE instance=? AND record_key=? ORDER BY rowid DESC LIMIT 1', this.store.meta('bound_instance', null), key);
    ensure(row, 'GAME_HISTORY_NOT_FOUND', 404); return JSON.parse(row.value);
  }
}
