import { canonical, digest } from '../dsh-bridge/channel.mjs';
import { requireValue } from '../dsh-bridge/state.mjs';
import { id, utc } from './store.mjs';
import { validateExtraction, EXTRACT_SCHEMA } from './service.mjs';

export function localParts(millis, timezone) {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', weekday: 'short', hourCycle: 'h23' }).formatToParts(new Date(millis));
  const value = Object.fromEntries(parts.map(part => [part.type, part.value]));
  return { date: `${value.year}-${value.month}-${value.day}`, time: `${value.hour}:${value.minute}`, weekday: { Mon:1,Tue:2,Wed:3,Thu:4,Fri:5,Sat:6,Sun:7 }[value.weekday] };
}
export class MaintenanceScheduler {
  constructor(db, state, memory, policy, model) {
    this.db = db; this.state = state; this.memory = memory; this.policy = policy; this.model = model;
    this.busy = false; this.catchup = true; this.lastMinute = null; this.runningAbort = null;
  }
  reserveModel({ jobId = null, requestId = null, inputHash, providerRevision, maxTokens, foreground = false }) {
    return this.db.tx(() => {
      const today = localParts(this.db.now(), this.policy.maintenance.timezone).date;
      if (!foreground) {
        const count = this.db.get("SELECT COUNT(*) AS n FROM model_attempts WHERE budget_scope='maintenance' AND quota_local_date=? AND status!='FAILED_BEFORE_SEND'", today).n;
        requireValue(count < this.policy.maintenance.max_model_calls_per_day, 'MODEL_DAILY_BUDGET');
        const runtime = this.db.get('SELECT * FROM job_runtime WHERE job_id=?', jobId);
        requireValue(runtime.model_call_count < this.policy.maintenance.max_model_calls_per_run, 'MODEL_RUN_BUDGET');
        this.db.run('UPDATE job_runtime SET model_call_count=model_call_count+1 WHERE job_id=?', jobId);
      }
      const attempt = id('attempt');
      this.db.run("INSERT INTO model_attempts(attempt_id,job_id,request_id,budget_scope,quota_local_date,input_sha256,provider_revision,reserved_output_tokens,status,created_at) VALUES (?,?,?,?,?,?,?,?,'RESERVED',?)", attempt, jobId, requestId, foreground ? 'foreground' : 'maintenance', today, inputHash, providerRevision, maxTokens, utc(this.db.now()));
      return attempt;
    });
  }
  settleModel(attempt, usage, sent, failed = false) {
    this.db.tx(() => this.db.run('UPDATE model_attempts SET status=?,input_tokens=?,output_tokens=? WHERE attempt_id=?',
      !sent && failed ? 'FAILED_BEFORE_SEND' : usage ? 'SETTLED' : 'USAGE_UNKNOWN', usage?.inputTokens ?? usage?.input_tokens ?? null, usage?.outputTokens ?? usage?.output_tokens ?? null, attempt));
  }
  scheduleOccurrences() {
    const now = this.db.now(), minute = Math.floor(now / 60000);
    if (!this.catchup && minute === this.lastMinute) return;
    const start = this.catchup ? Math.ceil((now - this.policy.maintenance.catch_up_window_ms) / 60000) : minute;
    this.catchup = false; this.lastMinute = minute;
    for (let cursor = start; cursor <= minute; cursor++) {
      const parts = localParts(cursor * 60000, this.policy.maintenance.timezone), kinds = [];
      if (parts.time === this.policy.maintenance.daily_local_time) kinds.push('daily_merge');
      if (parts.time === this.policy.maintenance.weekly_local_time && parts.weekday === this.policy.maintenance.weekly_iso_weekday) kinds.push('weekly_maintenance');
      for (const kind of kinds) this.db.tx(() => {
        if (this.db.get('SELECT 1 FROM schedule_occurrences WHERE schedule_id=? AND occurrence_local_date=? AND policy_version=?', kind, parts.date, this.policy.policy_version)) return;
        const broadcasts = this.db.all("SELECT * FROM broadcasts WHERE state='ENDED' ORDER BY ended_at");
        let created = 0;
        for (const broadcast of broadcasts) {
          if (kind === 'daily_merge') {
            const pending = this.db.get("SELECT COUNT(*) AS n FROM compaction_jobs WHERE broadcast_id=? AND state NOT IN ('COMPLETED','CANCELLED','FAILED')", broadcast.broadcast_id).n;
            const done = this.db.get("SELECT MAX(consumed_through_seq) AS n FROM compaction_jobs WHERE broadcast_id=? AND state='COMPLETED'", broadcast.broadcast_id).n ?? 0;
            if (pending || done >= broadcast.ended_event_seq) continue;
          }
          if (kind === 'weekly_maintenance') continue; // Version-based maintenance below, never rescan raw chat.
          created += this.state.enqueueJobsInTransaction(broadcast.broadcast_id, broadcast.ended_event_seq, broadcast.source_revision,
            broadcast.consolidation_not_before > utc(now) ? broadcast.consolidation_not_before : utc(now), kind, parts.date).length;
        }
        if (kind === 'weekly_maintenance' && !this.state.current()) created += this.weeklyInTransaction(parts.date);
        this.db.run('INSERT INTO schedule_occurrences VALUES (?,?,?,?,?,?)', kind, parts.date, this.policy.policy_version, null, created ? `QUEUED:${created}` : this.state.current() ? 'DEFERRED_LIVE' : 'SKIPPED_NO_CHANGES', utc(now));
      });
    }
    // A weekly occurrence reached during a broadcast remains a durable obligation.
    if (!this.state.current()) {
      for (const occurrence of this.db.all("SELECT * FROM schedule_occurrences WHERE schedule_id='weekly_maintenance' AND result='DEFERRED_LIVE'")) this.db.tx(() => {
        const changed = this.weeklyInTransaction(occurrence.occurrence_local_date);
        this.db.run('UPDATE schedule_occurrences SET result=? WHERE schedule_id=? AND occurrence_local_date=? AND policy_version=?', changed ? 'COMPLETED_INCREMENTAL' : 'SKIPPED_NO_CHANGES', occurrence.schedule_id, occurrence.occurrence_local_date, occurrence.policy_version);
      });
    }
  }
  weeklyInTransaction(date) {
    const room = this.state.room(), key = 'weekly_memory_revision';
    const last = this.db.get('SELECT value_json FROM runtime_meta WHERE key=?', key);
    if (Number(last?.value_json ?? -1) === room.memory_revision) return 0;
    const rows = this.db.all("SELECT * FROM memory_entries WHERE state='active'");
    for (const memory of rows) if (!this.memory.sourceValid(memory) || memory.valid_until && memory.valid_until <= utc(this.db.now())) this.memory.updateInTransaction(memory, { state: 'archived' }, 'weekly_source_or_expiry');
    const partitions = [...new Set(rows.map(row => row.subject_key))];
    for (const partition of partitions) {
      const revisions = rows.filter(row => row.subject_key === partition).map(row => ({ memory_id: row.memory_id, revision: row.revision }));
      const inputHash = digest(revisions), end = this.db.get('SELECT COALESCE(MAX(event_seq),1) AS n FROM stream_events').n;
      this.db.run("INSERT OR IGNORE INTO summary_versions VALUES (?,?,?,NULL,?,'period',1,?,1,?,?,?,?, 'active',?)", id('sum'), ...this.state.characterRoom, partition, end,
        canonical({ memory_revisions: revisions, deletion_generation: room.deletion_generation }), this.policy.policy_version, inputHash,
        canonical({ date, memory_revisions: revisions, method: 'incremental_index_and_source_audit', raw_chat_rescan: false }), utc(this.db.now()));
    }
    this.db.run('INSERT INTO runtime_meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json', key, String(this.state.room().memory_revision));
    return partitions.length;
  }
  claim() {
    return this.db.tx(() => {
      const now = utc(this.db.now());
      this.db.run("UPDATE compaction_jobs SET state='RETRY_WAIT',owner_id=NULL,lease_generation=lease_generation+1,reason='lease_expired',not_before=? WHERE state='RUNNING' AND lease_expires_at<=?", now, now);
      if (this.state.current()) {
        this.db.run("UPDATE compaction_jobs SET state='DEFERRED',reason='live' WHERE state IN ('PENDING','PAUSED','RETRY_WAIT') AND not_before<=?", now); return null;
      }
      const job = this.db.get("SELECT * FROM compaction_jobs WHERE state IN ('PENDING','DEFERRED','PAUSED','RETRY_WAIT') AND not_before<=? ORDER BY created_at,job_id LIMIT 1", now);
      if (!job) return null;
      const broadcast = this.db.get('SELECT * FROM broadcasts WHERE broadcast_id=?', job.broadcast_id);
      if (!broadcast || broadcast.state !== 'ENDED' || broadcast.source_revision !== job.source_revision) {
        this.db.run("UPDATE compaction_jobs SET state='CANCELLED',reason='source_changed' WHERE job_id=?", job.job_id); return null;
      }
      if (broadcast.consolidation_not_before > now) { this.db.run("UPDATE compaction_jobs SET state='DEFERRED',reason='quiet_window',not_before=? WHERE job_id=?", broadcast.consolidation_not_before, job.job_id); return null; }
      const runtime = this.db.get('SELECT * FROM job_runtime WHERE job_id=?', job.job_id), room = this.state.room();
      if (runtime.deletion_generation !== room.deletion_generation) {
        this.db.run("UPDATE compaction_jobs SET state='CANCELLED',reason='deletion_fence' WHERE job_id=?", job.job_id); return null;
      }
      const manifest = this.memory.eligibleEvents(job.broadcast_id, job.partition_key, { start: job.source_start_seq, end: job.source_end_seq }).map(source => ({ event_seq: source.event_seq, event_id: source.event_id, payload_sha256: source.payload_sha256, observation_revision: source.observation_revision }));
      if (job.source_manifest_json !== '{}' && canonical(JSON.parse(job.source_manifest_json)) !== canonical(manifest)) {
        this.db.run("UPDATE compaction_jobs SET state='CANCELLED',reason='manifest_changed' WHERE job_id=?", job.job_id); return null;
      }
      this.db.run("UPDATE compaction_jobs SET state='RUNNING',owner_id=?,lease_generation=lease_generation+1,lease_expires_at=?,maintenance_barrier=?,reason=NULL,source_manifest_json=? WHERE job_id=?", this.db.ownerId, utc(this.db.now() + this.policy.maintenance.lease_timeout_ms), room.maintenance_barrier, canonical(manifest), job.job_id);
      this.db.run('UPDATE job_runtime SET model_call_count=0,worker_revision=worker_revision+1 WHERE job_id=?', job.job_id);
      return this.db.get('SELECT * FROM compaction_jobs WHERE job_id=?', job.job_id);
    });
  }
  assertLease(job) {
    const live = this.db.get('SELECT * FROM compaction_jobs WHERE job_id=?', job.job_id), room = this.state.room(), runtime = this.db.get('SELECT * FROM job_runtime WHERE job_id=?', job.job_id);
    requireValue(live?.state === 'RUNNING' && live.owner_id === this.db.ownerId && live.lease_generation === job.lease_generation && Date.parse(live.lease_expires_at) > this.db.now() && room.maintenance_barrier === job.maintenance_barrier && !this.state.current(), 'MAINTENANCE_FENCED');
    requireValue(runtime.deletion_generation === room.deletion_generation && this.db.get('SELECT source_revision FROM broadcasts WHERE broadcast_id=?', job.broadcast_id).source_revision === job.source_revision, 'MAINTENANCE_SOURCE_STALE');
  }
  chunk(job) {
    const events = this.memory.eligibleEvents(job.broadcast_id, job.partition_key, { start: job.source_start_seq, end: job.source_end_seq });
    const fresh = [], old = events.filter(event => event.event_seq <= job.consumed_through_seq).slice(-this.policy.maintenance.overlap_events).map(event => ({ ...event, read_only_overlap: true }));
    let bytes = Buffer.byteLength(canonical(old));
    for (const event of events.filter(event => event.event_seq > job.consumed_through_seq)) {
      const size = Buffer.byteLength(canonical(event));
      if (fresh.length >= this.policy.maintenance.chunk_max_events || fresh.length && bytes + size > this.policy.maintenance.chunk_max_utf8_bytes) break;
      fresh.push(event); bytes += size;
    }
    const remaining = events.filter(event => event.event_seq > (fresh.at(-1)?.event_seq ?? job.consumed_through_seq));
    const end = remaining.length ? fresh.at(-1).event_seq : job.source_end_seq;
    return { sources: [...old, ...fresh], fresh, start: job.consumed_through_seq + 1, end, inputHash: digest({ job_id: job.job_id, partition: job.partition_key, sources: [...old, ...fresh], source_revision: job.source_revision, deletion_generation: this.state.room().deletion_generation }) };
  }
  async runJob(job) {
    let heartbeat, abort = new AbortController(); this.runningAbort = abort;
    try {
      heartbeat = setInterval(() => {
        try { this.db.tx(() => { this.assertLease(job); this.db.run('UPDATE compaction_jobs SET lease_expires_at=? WHERE job_id=?', utc(this.db.now() + this.policy.maintenance.lease_timeout_ms), job.job_id); }); }
        catch { abort.abort(); }
      }, this.policy.maintenance.lease_heartbeat_ms);
      heartbeat.unref();
      for (;;) {
        this.assertLease(job);
        if (job.consumed_through_seq >= job.source_end_seq) {
          await this.memory.project();
          requireValue(this.db.get("SELECT COUNT(*) n FROM mirror_outbox WHERE state NOT IN ('APPLIED','SUPERSEDED')").n===0,'PROJECTION_LAG');
          this.db.tx(() => {
            this.assertLease(job);
            const segments=this.db.all("SELECT * FROM summary_versions WHERE broadcast_id=? AND partition_key=? AND summary_kind='segment' AND source_revision=? AND state='active' ORDER BY source_start_seq",job.broadcast_id,job.partition_key,job.source_revision);
            const refs=segments.map(row=>({summary_id:row.summary_id,input_sha256:row.input_sha256,source_start_seq:row.source_start_seq,source_end_seq:row.source_end_seq}));
            const body={method:'bounded_segment_navigation',summary:segments.map(row=>JSON.parse(row.body_json).summary).join('\n').slice(0,1600),open_questions:[...new Set(segments.flatMap(row=>JSON.parse(row.body_json).open_questions||[]))].slice(-5),source_summary_ids:refs.map(row=>row.summary_id),not_independent_fact_evidence:true};
            this.db.run("INSERT OR IGNORE INTO summary_versions VALUES (?,?,?,?,?,'broadcast',?,?,?,?,?,?,?,'active',?)",id('sum'),...this.state.characterRoom,job.broadcast_id,job.partition_key,job.source_start_seq,job.source_end_seq,job.source_revision,canonical(refs),this.policy.policy_version,digest(refs),canonical(body),utc(this.db.now()));
            this.db.run("UPDATE compaction_jobs SET state='COMPLETED',stage='DONE',reason=NULL,owner_id=NULL,lease_expires_at=NULL WHERE job_id=?", job.job_id);
          });
          return;
        }
        const chunk = this.chunk(job), chunkIndex = this.db.get("SELECT COUNT(*) AS n FROM job_chunks WHERE job_id=? AND state='COMMITTED'", job.job_id).n;
        const previous = this.db.get('SELECT * FROM job_chunks WHERE job_id=? AND chunk_index=?', job.job_id, chunkIndex);
        requireValue(!previous || previous.input_sha256 === chunk.inputHash, 'CHUNK_INPUT_CHANGED');
        this.db.tx(() => this.db.run("INSERT INTO job_chunks(job_id,chunk_index,input_sha256,source_start_seq,source_end_seq,state,attempt_count) VALUES (?,?,?,?,?,'PENDING',1) ON CONFLICT(job_id,chunk_index) DO UPDATE SET attempt_count=attempt_count+1,state='PENDING'", job.job_id, chunkIndex, chunk.inputHash, chunk.start, chunk.end));
        let result = { schema_version: 1, summary: '该分区无新增合格来源。', open_questions: [], candidate_facts: [] };
        if (chunk.fresh.length) result = await this.model({ job, chunk, schema: EXTRACT_SCHEMA, signal: AbortSignal.any([abort.signal, AbortSignal.timeout(this.policy.maintenance.model_timeout_ms)]) });
        const candidates = validateExtraction(result, chunk.sources, job.partition_key);
        for (const candidate of candidates) requireValue(candidate.sources.some(source => !source.read_only_overlap), 'OVERLAP_NOT_NEW_EVIDENCE');
        this.commit(job, chunk, chunkIndex, result, candidates);
        job = this.db.get('SELECT * FROM compaction_jobs WHERE job_id=?', job.job_id);
      }
    } catch (error) {
      this.db.tx(() => {
        const current = this.db.get('SELECT * FROM compaction_jobs WHERE job_id=?', job.job_id);
        if (!current || current.lease_generation !== job.lease_generation || current.state !== 'RUNNING') return;
        const unavailable=error.code==='CHANNEL_COMPATIBILITY_REQUIRED';
        const attempt = current.attempt_count + (unavailable?0:1), budget = /BUDGET/.test(error.code || error.message), fenced = /FENCED|STALE/.test(error.code || error.message);
        const wait = budget ? 3600000 : Math.min(this.policy.maintenance.backoff_max_ms, this.policy.maintenance.backoff_initial_ms * 2 ** (attempt - 1));
        this.db.run('UPDATE compaction_jobs SET state=?,reason=?,attempt_count=?,owner_id=NULL,lease_expires_at=NULL,not_before=? WHERE job_id=?', unavailable?'DEFERRED':fenced ? 'PAUSED' : attempt >= this.policy.maintenance.max_attempts_per_chunk && !budget ? 'FAILED' : budget ? 'DEFERRED' : 'RETRY_WAIT', unavailable?'channel_unavailable':budget ? 'budget' : fenced ? 'live_or_source_barrier' : error.code==='PROJECTION_LAG' ? 'projection_lag' : 'extraction_failed', attempt, utc(this.db.now() + (unavailable?60000:wait)), job.job_id);
      });
    } finally { clearInterval(heartbeat); if (this.runningAbort === abort) this.runningAbort = null; }
  }
  commit(job, chunk, index, result, candidates) {
    return this.db.tx(() => {
      this.assertLease(job);
      const previous = this.db.get('SELECT * FROM job_chunks WHERE job_id=? AND chunk_index=?', job.job_id, index);
      if (previous?.state === 'COMMITTED') {requireValue(previous.input_sha256===chunk.inputHash,'CHUNK_REPLAY_CONFLICT');return JSON.parse(previous.result_json);}
      const actual = this.chunk(job); requireValue(actual.inputHash === chunk.inputHash, 'CHUNK_SOURCE_CHANGED');
      const decisions = [];
      for (const candidate of candidates) {
        const decision = this.memory.mergeInTransaction(candidate, job.job_id, index); decisions.push(decision);
        const key = digest([job.job_id,index,candidate.fact_key,candidate.value,candidate.source_refs]);
        this.db.run('INSERT OR IGNORE INTO memory_candidates VALUES (?,?,?,?,?,?,?,?)', 'candidate-' + key, job.job_id, index, key, job.partition_key, canonical(candidate), decision.decision, decision.reason);
      }
      const manifest = chunk.sources.map(e => ({ event_seq: e.event_seq, payload_sha256: e.payload_sha256, observation_revision: e.observation_revision, read_only_overlap: !!e.read_only_overlap }));
      this.db.run("INSERT OR IGNORE INTO summary_versions VALUES (?,?,?,?,?,'segment',?,?,?,?,?,?,?,'active',?)", id('sum'), ...this.state.characterRoom, job.broadcast_id, job.partition_key, chunk.start, chunk.end, job.source_revision, canonical(manifest), this.policy.policy_version, chunk.inputHash, canonical({ summary: result.summary, open_questions: result.open_questions, source_refs: manifest }), utc(this.db.now()));
      const statistics = { scanned: chunk.fresh.length, candidates: candidates.length, decisions };
      this.db.run("UPDATE job_chunks SET state='COMMITTED',result_json=?,committed_at=? WHERE job_id=? AND chunk_index=?", canonical(statistics), utc(this.db.now()), job.job_id, index);
      this.db.run("UPDATE compaction_jobs SET consumed_through_seq=?,stage='PROJECTING',attempt_count=0 WHERE job_id=?", chunk.end, job.job_id);
      this.db.run('UPDATE job_runtime SET statistics_json=? WHERE job_id=?', canonical(statistics), job.job_id);
      this.db.event(this.state.scope({ broadcast_id: job.broadcast_id }, { actor_kind: 'scheduler', actor_id: job.job_id }), 'memory.chunk_committed', { chunk_index: index, consumed_through_seq: chunk.end, candidate_count: candidates.length });
      return statistics;
    });
  }
  async tick() {
    this.scheduleOccurrences();
    if (this.state.current()) this.runningAbort?.abort();
    if (this.busy) return;
    const job = this.claim(); if (!job) return;
    this.busy = true;
    try { await this.runJob(job); } finally { this.busy = false; }
  }
  close() { this.runningAbort?.abort(); }
}
