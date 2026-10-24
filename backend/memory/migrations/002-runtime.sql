BEGIN IMMEDIATE;
CREATE TABLE runtime_meta (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
CREATE TABLE principals (
  principal_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE,
  role TEXT NOT NULL CHECK(role IN ('operator','viewer','media')),
  viewer_id TEXT, display_name TEXT NOT NULL, revoked_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE personas (
  persona_version TEXT PRIMARY KEY, document_json TEXT NOT NULL, approved_hash TEXT NOT NULL,
  publication_state TEXT NOT NULL CHECK(publication_state IN ('PENDING','PUBLISHED','REJECTED')),
  created_at TEXT NOT NULL, published_at TEXT
);
CREATE TABLE request_contexts (
  request_id TEXT PRIMARY KEY REFERENCES requests(request_id), persona_version TEXT NOT NULL,
  provider_revision TEXT NOT NULL, context_json TEXT, source_manifest_json TEXT,
  redacted_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE playback_history (
  lease_id TEXT PRIMARY KEY, broadcast_id TEXT NOT NULL REFERENCES broadcasts(broadcast_id),
  consumer_id TEXT NOT NULL, authority_epoch INTEGER NOT NULL, runtime_epoch INTEGER NOT NULL,
  expires_at TEXT NOT NULL, revoked_at TEXT
);
CREATE TABLE playback_observations (
  lease_id TEXT NOT NULL REFERENCES playback_history(lease_id), utterance_id TEXT NOT NULL REFERENCES utterances(utterance_id),
  receipt_sequence INTEGER NOT NULL DEFAULT -1, played_samples INTEGER NOT NULL DEFAULT 0,
  natural_end INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(lease_id,utterance_id)
);
CREATE TABLE cancel_barriers (
  barrier_id TEXT PRIMARY KEY, request_id TEXT NOT NULL REFERENCES requests(request_id),
  runtime_epoch INTEGER NOT NULL, generation INTEGER NOT NULL,
  expires_at TEXT NOT NULL, acked_at TEXT
);
CREATE TABLE memory_proposals (
  proposal_id TEXT PRIMARY KEY, request_id TEXT REFERENCES requests(request_id), subject_key TEXT NOT NULL,
  body_json TEXT, created_event_seq INTEGER NOT NULL REFERENCES stream_events(event_seq),
  state TEXT NOT NULL CHECK(state IN ('PENDING','REVIEWED','REJECTED','DELETED'))
);
CREATE TABLE job_runtime (
  job_id TEXT PRIMARY KEY REFERENCES compaction_jobs(job_id), deletion_generation INTEGER NOT NULL,
  model_call_count INTEGER NOT NULL DEFAULT 0, worker_revision INTEGER NOT NULL DEFAULT 0,
  statistics_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE redaction_outbox (
  operation_id TEXT PRIMARY KEY, generation INTEGER NOT NULL, subject_key TEXT NOT NULL,
  payload_json TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('PENDING','SYNCED')),
  created_at TEXT NOT NULL
);
CREATE TABLE operation_results (
  operation_id TEXT PRIMARY KEY, operation TEXT NOT NULL, input_sha256 TEXT NOT NULL,
  result_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX principal_live ON principals(role,revoked_at);
INSERT INTO schema_migrations VALUES (2,'__APPLIED_AT__','__MIGRATION_SHA256__');
PRAGMA user_version = 2;
COMMIT;
