import { readFileSync } from 'node:fs';
import { resolve, relative, isAbsolute, sep } from 'node:path';

export const POLICY_VERSION = 'dsh-live-v1.0';
export const CONNECTOR_VERSION = 'stream-humanity-v1';

export function inside(root, candidate) {
  const base = resolve(root), target = resolve(base, candidate);
  const diff = relative(base, target);
  if (diff === '..' || diff.startsWith('..' + sep) || isAbsolute(diff)) {
    throw new Error('PATH_OUTSIDE_PROJECT');
  }
  return target;
}

const templateUrl = new URL('../../docs/dsh-humanity/examples/bridge-policy.example.json', import.meta.url);
export const policyTemplate = JSON.parse(readFileSync(templateUrl, 'utf8'));
function freezeTree(value) {
  for (const child of Object.values(value)) if (child && typeof child === 'object') freezeTree(child);
  return Object.freeze(value);
}

function sameShape(value, shape, path = 'policy') {
  if (shape !== null && typeof shape === 'object' && !Array.isArray(shape)) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('CONFIG_OBJECT:' + path);
    for (const key of Object.keys(value)) if (!(key in shape)) throw new Error('CONFIG_UNKNOWN:' + path + '.' + key);
    for (const key of Object.keys(shape)) {
      if (!(key in value)) throw new Error('CONFIG_MISSING:' + path + '.' + key);
      sameShape(value[key], shape[key], path + '.' + key);
    }
  } else if (typeof value !== typeof shape || (typeof value === 'number' && (!Number.isSafeInteger(value) || value < 0))) {
    throw new Error('CONFIG_TYPE:' + path);
  }
}

export function loadPolicy(root, file) {
  const shape = structuredClone(policyTemplate);
  delete shape.example_only;
  const policy = file ? JSON.parse(readFileSync(inside(root, file), 'utf8')) : structuredClone(shape);
  sameShape(policy, shape);
  if (policy.schema_version !== 1 || policy.policy_version !== POLICY_VERSION) throw new Error('CONFIG_VERSION');
  if(policy.versions.dsh_candidate!=='0.2.0-rc.2'||policy.versions.humanity_base!=='0.1.17'||policy.versions.allow_unpinned_dependencies||!policy.versions.runtime_validation_required||!policy.versions.humanity_connector_patch_required)throw new Error('CONFIG_VERSION_LOCK');
  if(policy.identity.character_id!=='female-a'||policy.identity.room_id!=='room-main'||policy.identity.anonymous_cross_broadcast_memory||policy.identity.viewer_identity_source!=='server_verified_principal'||policy.identity.character_source!=='configs/characters/female-a.json')throw new Error('CONFIG_IDENTITY_SCOPE');
  if (policy.deployment.mode !== 'native_windows' || policy.deployment.bridge_host !== '127.0.0.1' || policy.deployment.management_host !== '127.0.0.1') throw new Error('CONFIG_DEPLOYMENT');
  if (policy.conversation.session_strategy !== 'per_request_standard' || policy.conversation.active_requests_per_room !== 1 || policy.playback.authorities_per_broadcast !== 1 || policy.maintenance.concurrency !== 1) throw new Error('CONFIG_SINGLE_OWNER');
  if (policy.memory.canonical_store !== 'sqlite' || policy.memory.humanity_projection !== 'public_only') throw new Error('CONFIG_MEMORY_OWNER');
  if (policy.memory.native_humanity_mutation_tools_in_live_agent || policy.memory.native_humanity_evolution || policy.memory.native_humanity_dream || policy.memory.allow_vector_gpu_model || policy.memory.allow_automatic_persona_changes || policy.memory.allow_automatic_conflict_overwrite) throw new Error('CONFIG_MEMORY_INVARIANT');
  if (policy.maintenance.scheduler !== 'bridge_persistent_jobs' || policy.maintenance.commit_during_live || policy.maintenance.allow_raw_dsh_session_scan || policy.maintenance.automatic_historical_backfill) throw new Error('CONFIG_SCHEDULER_INVARIANT');
  if (!policy.playback.require_contiguous_samples || !policy.playback.require_natural_end || policy.playback.accept_partial_text_without_alignment || policy.playback.media_protocol !== 2) throw new Error('CONFIG_PLAYBACK_INVARIANT');
  if (policy.conversation.silent_stateless_fallback || policy.conversation.speak_intermediate_model_text) throw new Error('CONFIG_CONVERSATION_INVARIANT');
  if (!policy.storage.sqlite_foreign_keys || policy.storage.network_filesystem || policy.storage.automatic_raw_event_deletion || !policy.storage.deletion_fences_required_for_restore) throw new Error('CONFIG_STORAGE_INVARIANT');
  if(policy.storage.sqlite_journal_mode!=='WAL'||policy.storage.sqlite_synchronous!=='FULL'||policy.storage.sqlite_busy_timeout_ms!==5000||!policy.storage.backup_before_migration||policy.playback.evidence_level!=='consumer_playout'||!policy.memory.read_canonical_if_projection_lags)throw new Error('CONFIG_FIXED_INVARIANT');
  const c = policy.conversation, m = policy.maintenance, p = policy.playback;
  if (c.pending_queue_limit < 1 || c.pending_queue_limit > 20 || c.final_speech_max_chars < 1 || c.final_speech_max_chars > 500 || c.max_memory_tool_rounds > 2 || c.max_memory_tool_rounds < 1 || c.context_max_estimated_tokens < 1000 || c.context_max_estimated_tokens > 16000) throw new Error('CONFIG_CONVERSATION_RANGE');
  if (m.model_timeout_ms >= m.lease_timeout_ms || m.lease_heartbeat_ms * 2 >= m.lease_timeout_ms || m.chunk_max_events < 1 || m.chunk_max_utf8_bytes < 1024 || m.max_attempts_per_chunk < 1 || m.max_attempts_per_chunk > 5 || m.max_model_calls_per_run < 1 || m.max_model_calls_per_day < 1 || m.poll_interval_ms < 1000) throw new Error('CONFIG_MAINTENANCE_RANGE');
  if (p.heartbeat_interval_ms < 250 || p.lease_timeout_ms < p.heartbeat_interval_ms * 3 || p.progress_interval_ms < 100 || p.drain_timeout_ms < 1) throw new Error('CONFIG_PLAYBACK_RANGE');
  if(c.max_output_tokens<1||c.max_output_tokens>2048||c.model_timeout_ms<1000||c.tts_timeout_ms<1000||m.weekly_iso_weekday<1||m.weekly_iso_weekday>7||m.max_output_tokens_per_call<1||m.max_output_tokens_per_call>2048)throw new Error('CONFIG_BUDGET_RANGE');
  if(policy.memory.fact_content_max_chars!==160||policy.memory.source_quote_max_chars!==300)throw new Error('CONFIG_EVIDENCE_FORMAT');
  new Intl.DateTimeFormat('en', { timeZone: m.timezone }).format(new Date());
  for (const time of [m.daily_local_time, m.weekly_local_time]) if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(time)) throw new Error('CONFIG_SCHEDULE_TIME');
  inside(root, policy.deployment.state_relative_path);
  inside(root, policy.deployment.dsh_home_relative_path);
  inside(root, policy.identity.character_source);
  return freezeTree(policy);
}
