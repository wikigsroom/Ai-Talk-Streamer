import { ensure } from './errors.mjs';
import { validate } from './protocol.mjs';
import { hash } from './store.mjs';

export const MAINTENANCE_HISTORY_SOURCES = Object.freeze(['retention_summaries', 'retired_tasks', 'retention_runs']);
const types = { retention_summaries: 'retention_summary', retired_tasks: 'retired_task', retention_runs: 'retention_run' };

/** Observed historical versions only. Never a task recovery or execution proof. */
export function validateMaintenanceHistory(job, info, payload) {
  validate('JournalMaintenancePayload', payload);
  ensure(payload.game_instance_id === job.game_instance_id && payload.source === job.source
    && info.stream === job.source && info.type === types[job.source] && info.sequence === 0
    && info.acked_at === null && info.archived_at === null && info.archive_reason === null
    && info.record_key === hash([job.source, payload.source_key, info.payload_sha256]), 'GAME_HISTORY_RECORD_CONTEXT');
  const value = payload.value;
  let world = null, boot = null, recorded;
  if (job.source === 'retention_summaries') {
    world = value.world_session_id; recorded = value.last_recorded_at;
    ensure(value.first_recorded_at <= value.last_recorded_at
      && [value.first_recorded_at, value.last_recorded_at].every(at => Number.isFinite(new Date(at).getTime()))
      && [value.first_recorded_at, value.last_recorded_at].every(at => new Date(at).toISOString().slice(0, 10) === value.utc_day)
      && payload.source_key === hash({ world_session_id: world, source: value.source, kind: value.kind, utc_day: value.utc_day }), 'GAME_HISTORY_RECORD_CONTEXT');
  } else if (job.source === 'retired_tasks') {
    const summary = value.summary;
    world = value.world_session_id; boot = summary.bridge_boot_id; recorded = value.retired_at;
    ensure(payload.source_key === value.task_id && summary.task_id === value.task_id && summary.world_session_id === world
      && Date.parse(summary.created_at) <= Date.parse(summary.updated_at)
      && Date.parse(summary.updated_at) <= recorded, 'GAME_HISTORY_RECORD_CONTEXT');
  } else {
    recorded = Date.parse(value.completed_at);
    ensure(payload.source_key === value.run_id && value.game_instance_id === job.game_instance_id, 'GAME_HISTORY_RECORD_CONTEXT');
  }
  ensure(info.world_session_id === world && info.source_boot_id === boot && info.recorded_at === recorded, 'GAME_HISTORY_RECORD_CONTEXT');
}

export function maintenanceHistorySummary(payload) {
  const value = payload.value;
  if (payload.source === 'retention_summaries') return { kind: 'retention_summary', category: value.source,
    event_kind: value.kind, utc_day: value.utc_day, count: value.count,
    first_recorded_at: value.first_recorded_at, last_recorded_at: value.last_recorded_at };
  if (payload.source === 'retired_tasks') return { kind: 'retired_task', task_id: value.task_id,
    version: value.summary.version, state: value.summary.state, effect_status: value.summary.effect_status,
    skill: value.summary.skill, retired_at: value.retired_at };
  return { kind: 'retention_run', run_id: value.run_id, completed_at: value.completed_at,
    counts: value.counts, originals_in_backup: value.originals_in_backup };
}
