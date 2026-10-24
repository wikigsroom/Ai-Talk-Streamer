-- Design artifact only. This file is not wired into the current application.
-- A reviewed migration runner must apply it in a project-local native SQLite database.
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = FULL;
PRAGMA busy_timeout = 5000;

BEGIN IMMEDIATE;

CREATE TABLE schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL,
  migration_sha256 TEXT NOT NULL CHECK(length(migration_sha256) = 64)
);

CREATE TABLE rooms (
  character_id TEXT NOT NULL,
  room_id TEXT NOT NULL,
  runtime_epoch INTEGER NOT NULL DEFAULT 0 CHECK(runtime_epoch >= 0),
  generation INTEGER NOT NULL DEFAULT 0 CHECK(generation >= 0),
  maintenance_barrier INTEGER NOT NULL DEFAULT 0 CHECK(maintenance_barrier >= 0),
  memory_revision INTEGER NOT NULL DEFAULT 0 CHECK(memory_revision >= 0),
  deletion_generation INTEGER NOT NULL DEFAULT 0 CHECK(deletion_generation >= 0),
  PRIMARY KEY(character_id, room_id)
);

CREATE TABLE broadcasts (
  broadcast_id TEXT PRIMARY KEY,
  character_id TEXT NOT NULL,
  room_id TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('CREATED','STARTING','LIVE','PAUSED','DRAINING','RECOVERING','ENDED','FAILED')),
  runtime_epoch INTEGER NOT NULL CHECK(runtime_epoch >= 0),
  revision INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1),
  source_revision INTEGER NOT NULL DEFAULT 1 CHECK(source_revision >= 1),
  delivery_context_revision INTEGER NOT NULL DEFAULT 0 CHECK(delivery_context_revision >= 0),
  persona_version TEXT NOT NULL,
  started_at TEXT,
  ended_at TEXT,
  ended_event_seq INTEGER,
  consolidation_not_before TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(broadcast_id, character_id, room_id),
  FOREIGN KEY(character_id, room_id) REFERENCES rooms(character_id, room_id),
  CHECK(state != 'ENDED' OR (ended_at IS NOT NULL AND ended_event_seq IS NOT NULL))
);
CREATE UNIQUE INDEX one_active_broadcast_per_room ON broadcasts(character_id, room_id)
WHERE state IN ('STARTING','LIVE','PAUSED','DRAINING','RECOVERING');

CREATE TABLE stream_events (
  event_seq INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL UNIQUE,
  event_type TEXT NOT NULL,
  character_id TEXT NOT NULL,
  room_id TEXT NOT NULL,
  broadcast_id TEXT,
  request_id TEXT,
  utterance_id TEXT,
  runtime_epoch INTEGER NOT NULL CHECK(runtime_epoch >= 0),
  generation INTEGER CHECK(generation >= 0),
  source_revision INTEGER NOT NULL CHECK(source_revision >= 1),
  actor_kind TEXT NOT NULL CHECK(actor_kind IN ('viewer','operator','model','media','playback','scheduler','system')),
  actor_id TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  received_at TEXT NOT NULL,
  payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256) = 64),
  FOREIGN KEY(character_id, room_id) REFERENCES rooms(character_id, room_id),
  FOREIGN KEY(broadcast_id, character_id, room_id) REFERENCES broadcasts(broadcast_id, character_id, room_id)
);
CREATE INDEX event_scan ON stream_events(character_id, room_id, event_seq);
CREATE INDEX event_broadcast ON stream_events(broadcast_id, event_seq);

CREATE TABLE event_payloads (
  event_seq INTEGER PRIMARY KEY REFERENCES stream_events(event_seq),
  payload_json TEXT,
  redacted_at TEXT,
  CHECK((payload_json IS NOT NULL AND redacted_at IS NULL) OR (payload_json IS NULL AND redacted_at IS NOT NULL))
);

CREATE TABLE requests (
  request_id TEXT PRIMARY KEY,
  broadcast_id TEXT NOT NULL,
  character_id TEXT NOT NULL,
  room_id TEXT NOT NULL,
  principal_id TEXT NOT NULL,
  viewer_id TEXT,
  mode TEXT NOT NULL CHECK(mode IN ('chat','echo')),
  status TEXT NOT NULL CHECK(status IN ('RECEIVED','QUEUED','THINKING','TEXT_READY','SYNTHESIZING','AUDIO_READY','BUFFERING','PLAYING','COMPLETED','CANCELLED','INTERRUPTED','UNKNOWN','FAILED','EXPIRED','REJECTED')),
  idempotency_key TEXT NOT NULL,
  input_sha256 TEXT NOT NULL CHECK(length(input_sha256) = 64),
  runtime_epoch INTEGER NOT NULL,
  generation INTEGER,
  revision INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1),
  input_event_seq INTEGER REFERENCES stream_events(event_seq),
  dsh_session_id TEXT UNIQUE,
  created_at TEXT NOT NULL,
  queue_expires_at TEXT NOT NULL,
  active_deadline_at TEXT,
  retry_of TEXT REFERENCES requests(request_id),
  UNIQUE(character_id, room_id, principal_id, idempotency_key),
  FOREIGN KEY(broadcast_id, character_id, room_id) REFERENCES broadcasts(broadcast_id, character_id, room_id)
);
CREATE UNIQUE INDEX one_active_request_per_room ON requests(character_id, room_id)
WHERE status IN ('THINKING','TEXT_READY','SYNTHESIZING','AUDIO_READY','BUFFERING','PLAYING');

CREATE TABLE utterances (
  utterance_id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL REFERENCES requests(request_id),
  segment_index INTEGER NOT NULL DEFAULT 0 CHECK(segment_index >= 0),
  status TEXT NOT NULL CHECK(status IN ('TEXT_READY','SYNTHESIZING','AUDIO_READY','BUFFERING','PLAYING','COMPLETED','CANCELLED','INTERRUPTED','UNKNOWN','FAILED')),
  runtime_epoch INTEGER NOT NULL,
  generation INTEGER NOT NULL,
  text_sha256 TEXT NOT NULL CHECK(length(text_sha256) = 64),
  audio_sha256 TEXT CHECK(audio_sha256 IS NULL OR length(audio_sha256) = 64),
  sample_rate INTEGER NOT NULL DEFAULT 16000 CHECK(sample_rate > 0),
  valid_sample_count INTEGER CHECK(valid_sample_count >= 0),
  contiguous_played_samples INTEGER NOT NULL DEFAULT 0 CHECK(contiguous_played_samples >= 0),
  observation_revision INTEGER NOT NULL DEFAULT 1,
  completion_event_seq INTEGER REFERENCES stream_events(event_seq),
  cancel_barrier_id TEXT,
  UNIQUE(request_id, segment_index),
  CHECK(valid_sample_count IS NULL OR contiguous_played_samples <= valid_sample_count),
  CHECK(status != 'COMPLETED' OR (valid_sample_count IS NOT NULL AND contiguous_played_samples = valid_sample_count AND completion_event_seq IS NOT NULL))
);

CREATE TABLE playback_leases (
  broadcast_id TEXT PRIMARY KEY REFERENCES broadcasts(broadcast_id),
  consumer_id TEXT NOT NULL,
  lease_id TEXT NOT NULL UNIQUE,
  authority_epoch INTEGER NOT NULL CHECK(authority_epoch >= 1),
  runtime_epoch INTEGER NOT NULL,
  expires_at TEXT NOT NULL,
  revoked_at TEXT
);
CREATE TABLE media_manifests (
  utterance_id TEXT NOT NULL REFERENCES utterances(utterance_id),
  transport_instance_id TEXT NOT NULL,
  map_revision INTEGER NOT NULL CHECK(map_revision >= 1),
  ranges_json TEXT NOT NULL,
  manifest_sha256 TEXT NOT NULL CHECK(length(manifest_sha256) = 64),
  persisted_through_sample INTEGER NOT NULL CHECK(persisted_through_sample >= 0),
  final INTEGER NOT NULL CHECK(final IN (0,1)),
  PRIMARY KEY(utterance_id, transport_instance_id, map_revision)
);
CREATE TABLE playback_receipts (
  receipt_id TEXT PRIMARY KEY,
  utterance_id TEXT NOT NULL REFERENCES utterances(utterance_id),
  lease_id TEXT NOT NULL,
  authority_epoch INTEGER NOT NULL,
  runtime_epoch INTEGER NOT NULL,
  receipt_sequence INTEGER NOT NULL CHECK(receipt_sequence >= 0),
  contiguous_played_samples INTEGER NOT NULL CHECK(contiguous_played_samples >= 0),
  natural_end INTEGER NOT NULL CHECK(natural_end IN (0,1)),
  accepted INTEGER NOT NULL CHECK(accepted IN (0,1)),
  reason TEXT NOT NULL,
  received_at TEXT NOT NULL,
  UNIQUE(lease_id, receipt_sequence)
);

CREATE TABLE memory_entries (
  memory_id TEXT PRIMARY KEY,
  character_id TEXT NOT NULL,
  room_id TEXT NOT NULL,
  visibility TEXT NOT NULL CHECK(visibility IN ('public','viewer')),
  subject_key TEXT NOT NULL,
  fact_key TEXT NOT NULL,
  value_json TEXT NOT NULL,
  content TEXT NOT NULL,
  polarity TEXT NOT NULL CHECK(polarity IN ('positive','negative','neutral')),
  state TEXT NOT NULL CHECK(state IN ('proposed','active','conflicted','superseded','archived','retracted','deleted')),
  revision INTEGER NOT NULL CHECK(revision >= 1),
  evidence_kind TEXT NOT NULL CHECK(evidence_kind IN ('viewer_statement','completed_playout','operator_correction','fictional_setting','agent_inference')),
  valid_from TEXT,
  valid_until TEXT,
  pinned INTEGER NOT NULL DEFAULT 0 CHECK(pinned IN (0,1)),
  updated_at TEXT NOT NULL,
  FOREIGN KEY(character_id, room_id) REFERENCES rooms(character_id, room_id),
  CHECK((visibility = 'public' AND subject_key = 'public') OR (visibility = 'viewer' AND subject_key != 'public'))
);
CREATE INDEX memory_partition ON memory_entries(character_id, room_id, visibility, subject_key, state, fact_key);
CREATE UNIQUE INDEX one_active_fact ON memory_entries(character_id, room_id, visibility, subject_key, fact_key)
WHERE state = 'active';

CREATE TABLE memory_revisions (
  memory_id TEXT NOT NULL REFERENCES memory_entries(memory_id),
  revision INTEGER NOT NULL CHECK(revision >= 1),
  operation_id TEXT NOT NULL UNIQUE,
  operation TEXT NOT NULL,
  snapshot_json TEXT NOT NULL,
  prior_revision INTEGER,
  created_at TEXT NOT NULL,
  PRIMARY KEY(memory_id, revision)
);
CREATE TABLE memory_sources (
  memory_id TEXT NOT NULL,
  memory_revision INTEGER NOT NULL,
  event_seq INTEGER NOT NULL REFERENCES stream_events(event_seq),
  observation_revision INTEGER,
  source_quote TEXT NOT NULL,
  evidence_sha256 TEXT NOT NULL CHECK(length(evidence_sha256) = 64),
  PRIMARY KEY(memory_id, memory_revision, event_seq),
  FOREIGN KEY(memory_id, memory_revision) REFERENCES memory_revisions(memory_id, revision)
);

CREATE TABLE summary_versions (
  summary_id TEXT PRIMARY KEY,
  character_id TEXT NOT NULL,
  room_id TEXT NOT NULL,
  broadcast_id TEXT REFERENCES broadcasts(broadcast_id),
  partition_key TEXT NOT NULL,
  summary_kind TEXT NOT NULL CHECK(summary_kind IN ('rolling','segment','broadcast','period')),
  source_start_seq INTEGER NOT NULL,
  source_end_seq INTEGER NOT NULL,
  source_revision INTEGER NOT NULL,
  source_manifest_json TEXT NOT NULL DEFAULT '{}',
  policy_version TEXT NOT NULL,
  input_sha256 TEXT NOT NULL CHECK(length(input_sha256) = 64),
  body_json TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('active','superseded','invalidated','redacted')),
  created_at TEXT NOT NULL,
  FOREIGN KEY(character_id, room_id) REFERENCES rooms(character_id, room_id),
  CHECK(source_end_seq >= source_start_seq),
  UNIQUE(character_id, room_id, partition_key, summary_kind, input_sha256, policy_version)
);

CREATE TABLE compaction_jobs (
  job_id TEXT PRIMARY KEY,
  job_key TEXT NOT NULL UNIQUE,
  job_kind TEXT NOT NULL CHECK(job_kind IN ('post_broadcast','daily_merge','weekly_maintenance','mirror_reconcile','rebuild')),
  character_id TEXT NOT NULL,
  room_id TEXT NOT NULL,
  broadcast_id TEXT REFERENCES broadcasts(broadcast_id),
  partition_key TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  source_revision INTEGER NOT NULL,
  source_manifest_json TEXT NOT NULL DEFAULT '{}',
  state TEXT NOT NULL CHECK(state IN ('PENDING','DEFERRED','RUNNING','PAUSED','RETRY_WAIT','FAILED','COMPLETED','CANCELLED')),
  stage TEXT NOT NULL,
  source_start_seq INTEGER NOT NULL,
  source_end_seq INTEGER NOT NULL,
  consumed_through_seq INTEGER NOT NULL,
  owner_id TEXT,
  lease_generation INTEGER NOT NULL DEFAULT 0,
  lease_expires_at TEXT,
  maintenance_barrier INTEGER NOT NULL,
  not_before TEXT NOT NULL,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  reason TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(character_id, room_id) REFERENCES rooms(character_id, room_id),
  CHECK(source_start_seq <= consumed_through_seq + 1 AND consumed_through_seq <= source_end_seq)
);
CREATE INDEX runnable_jobs ON compaction_jobs(state, not_before, created_at);

CREATE TABLE job_chunks (
  job_id TEXT NOT NULL REFERENCES compaction_jobs(job_id),
  chunk_index INTEGER NOT NULL CHECK(chunk_index >= 0),
  input_sha256 TEXT NOT NULL CHECK(length(input_sha256) = 64),
  source_start_seq INTEGER NOT NULL,
  source_end_seq INTEGER NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('PENDING','EXTRACTED','VALIDATED','COMMITTED','STALE','FAILED')),
  result_json TEXT,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  committed_at TEXT,
  PRIMARY KEY(job_id, chunk_index),
  CHECK(source_end_seq >= source_start_seq)
);
CREATE TABLE memory_candidates (
  candidate_id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL,
  chunk_index INTEGER NOT NULL,
  candidate_key TEXT NOT NULL UNIQUE,
  subject_key TEXT NOT NULL,
  body_json TEXT NOT NULL,
  decision TEXT NOT NULL CHECK(decision IN ('proposed','accepted','rejected','conflicted','stale')),
  reason TEXT NOT NULL,
  FOREIGN KEY(job_id, chunk_index) REFERENCES job_chunks(job_id, chunk_index)
);

CREATE TABLE mirror_outbox (
  operation_id TEXT PRIMARY KEY,
  memory_id TEXT NOT NULL,
  memory_revision INTEGER NOT NULL,
  action TEXT NOT NULL CHECK(action IN ('UPSERT','ARCHIVE','REMOVE')),
  payload_json TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('PENDING','APPLYING','APPLIED','RETRY_WAIT','FAILED','SUPERSEDED')),
  attempts INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TEXT NOT NULL,
  humanity_entry_id TEXT,
  humanity_dedupe_key TEXT,
  applied_at TEXT,
  UNIQUE(memory_id, memory_revision, action),
  FOREIGN KEY(memory_id, memory_revision) REFERENCES memory_revisions(memory_id, revision)
);

CREATE TABLE model_attempts (
  attempt_id TEXT PRIMARY KEY,
  job_id TEXT REFERENCES compaction_jobs(job_id),
  request_id TEXT REFERENCES requests(request_id),
  budget_scope TEXT NOT NULL CHECK(budget_scope IN ('foreground','maintenance')),
  quota_local_date TEXT NOT NULL,
  input_sha256 TEXT NOT NULL CHECK(length(input_sha256) = 64),
  provider_revision TEXT NOT NULL,
  reserved_output_tokens INTEGER NOT NULL CHECK(reserved_output_tokens >= 0),
  input_tokens INTEGER CHECK(input_tokens >= 0),
  output_tokens INTEGER CHECK(output_tokens >= 0),
  status TEXT NOT NULL CHECK(status IN ('RESERVED','SENT','SETTLED','USAGE_UNKNOWN','FAILED_BEFORE_SEND')),
  created_at TEXT NOT NULL
);
CREATE INDEX model_budget ON model_attempts(budget_scope, quota_local_date, status);

CREATE TABLE deletion_fences (
  character_id TEXT NOT NULL,
  room_id TEXT NOT NULL,
  subject_key TEXT NOT NULL,
  generation INTEGER NOT NULL CHECK(generation >= 1),
  event_seq INTEGER NOT NULL REFERENCES stream_events(event_seq),
  created_at TEXT NOT NULL,
  PRIMARY KEY(character_id, room_id, subject_key),
  FOREIGN KEY(character_id, room_id) REFERENCES rooms(character_id, room_id)
);
CREATE TABLE schedule_occurrences (
  schedule_id TEXT NOT NULL,
  occurrence_local_date TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  job_id TEXT REFERENCES compaction_jobs(job_id),
  result TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(schedule_id, occurrence_local_date, policy_version)
);

CREATE TRIGGER no_event_metadata_update BEFORE UPDATE ON stream_events
BEGIN SELECT RAISE(ABORT, 'event metadata is append-only'); END;
CREATE TRIGGER no_event_metadata_delete BEFORE DELETE ON stream_events
BEGIN SELECT RAISE(ABORT, 'event metadata is append-only'); END;

PRAGMA user_version = 1;
COMMIT;
