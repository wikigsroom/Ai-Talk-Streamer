import { EventEmitter } from 'node:events';
import { id, utc } from '../memory/store.mjs';
import { canonical, digest } from './channel.mjs';

export const ACTIVE_REQUESTS = ['THINKING','TEXT_READY','SYNTHESIZING','AUDIO_READY','BUFFERING','PLAYING'];
export const TERMINAL_REQUESTS = ['COMPLETED','CANCELLED','INTERRUPTED','UNKNOWN','FAILED','EXPIRED','REJECTED'];
export const ACTIVE_BROADCASTS = ['STARTING','LIVE','PAUSED','DRAINING','RECOVERING'];
export class StreamError extends Error {
  constructor(code, status = 409) { super(code); this.code = code; this.status = status; }
}
export const requireValue = (condition, code, status) => { if (!condition) throw new StreamError(code, status); };
const activeSQL = "('THINKING','TEXT_READY','SYNTHESIZING','AUDIO_READY','BUFFERING','PLAYING')";
const openSQL = "('STARTING','LIVE','PAUSED','DRAINING','RECOVERING')";

export class StreamState extends EventEmitter {
  constructor(store, policy, personaVersion) {
    super(); this.db = store; this.policy = policy; this.personaVersion = personaVersion;
    this.character = policy.identity.character_id; this.roomId = policy.identity.room_id;
    this.characterRoom = [this.character, this.roomId];
    this.db.tx(() => {
      this.db.run('INSERT OR IGNORE INTO rooms(character_id,room_id) VALUES (?,?)', ...this.characterRoom);
      this.db.run('UPDATE rooms SET runtime_epoch=runtime_epoch+1,generation=generation+1,maintenance_barrier=maintenance_barrier+1 WHERE character_id=? AND room_id=?', ...this.characterRoom);
      const room = this.room();
      this.db.run('UPDATE playback_leases SET revoked_at=?', utc(this.db.now()));
      this.db.run('UPDATE playback_history SET revoked_at=? WHERE revoked_at IS NULL', utc(this.db.now()));
      const pending = this.db.all(`SELECT * FROM requests WHERE status IN ${activeSQL} OR status='QUEUED'`);
      for (const request of pending) {
        this.db.run("UPDATE requests SET status='UNKNOWN',revision=revision+1 WHERE request_id=?", request.request_id);
        this.db.run("UPDATE utterances SET status='UNKNOWN',observation_revision=observation_revision+1 WHERE request_id=? AND status!='COMPLETED'", request.request_id);
        this.db.event(this.scope({ ...request, runtime_epoch: room.runtime_epoch }), 'request.recovered_unknown', { prior_status: request.status, reason: 'process_takeover' });
      }
      this.db.run(`UPDATE broadcasts SET state='RECOVERING',runtime_epoch=?,revision=revision+1 WHERE state IN ${openSQL}`, room.runtime_epoch);
      this.db.run("UPDATE compaction_jobs SET state='RETRY_WAIT',reason='owner_recovery',owner_id=NULL,lease_generation=lease_generation+1,not_before=?,lease_expires_at=NULL WHERE state='RUNNING'", utc(this.db.now()));
      this.db.run("UPDATE model_attempts SET status='USAGE_UNKNOWN' WHERE status IN ('RESERVED','SENT')");
      this.db.event(this.scope(), 'runtime.started', { owner_id: this.db.ownerId });
    });
  }
  room() { return this.db.get('SELECT * FROM rooms WHERE character_id=? AND room_id=?', ...this.characterRoom); }
  current() { return this.db.get(`SELECT * FROM broadcasts WHERE character_id=? AND room_id=? AND state IN ${openSQL} ORDER BY created_at DESC LIMIT 1`, ...this.characterRoom); }
  active() { return this.db.get(`SELECT * FROM requests WHERE character_id=? AND room_id=? AND status IN ${activeSQL}`, ...this.characterRoom); }
  scope(row = {}, actor = { actor_kind: 'system', actor_id: 'bridge' }) {
    const room = this.room();
    return { character_id: this.character, room_id: this.roomId, runtime_epoch: row.runtime_epoch ?? room.runtime_epoch,
      generation: row.generation ?? room.generation, broadcast_id: row.broadcast_id ?? null,
      source_revision: row.source_revision ?? this.db.get('SELECT source_revision FROM broadcasts WHERE broadcast_id=?', row.broadcast_id ?? '')?.source_revision ?? 1,
      request_id: row.request_id ?? null, utterance_id: row.utterance_id ?? null, ...actor };
  }
  lease(broadcastId) { return this.db.get('SELECT * FROM playback_leases WHERE broadcast_id=?', broadcastId); }
  leaseResponse(lease) { return {...lease, playback_timing: {heartbeat_interval_ms:this.policy.playback.heartbeat_interval_ms,progress_interval_ms:this.policy.playback.progress_interval_ms}}; }
  authorityReady(broadcastId) {
    const lease = this.lease(broadcastId);
    return !!lease && !lease.revoked_at && lease.runtime_epoch === this.room().runtime_epoch && Date.parse(lease.expires_at) > this.db.now();
  }
  createBroadcast(principal) {
    requireValue(principal.role === 'operator', 'OPERATOR_REQUIRED', 403);
    return this.db.tx(() => {
      requireValue(!this.current(), 'BROADCAST_ALREADY_OPEN');
      const room = this.room(), broadcastId = id('bc'), now = utc(this.db.now());
      this.db.run('UPDATE rooms SET maintenance_barrier=maintenance_barrier+1 WHERE character_id=? AND room_id=?', ...this.characterRoom);
      this.db.run("UPDATE compaction_jobs SET state='PAUSED',owner_id=NULL,lease_generation=lease_generation+1,reason='live_barrier' WHERE state='RUNNING'");
      this.db.run("INSERT INTO broadcasts(broadcast_id,character_id,room_id,state,runtime_epoch,persona_version,created_at) VALUES (?,?,?,'CREATED',?,?,?)", broadcastId, ...this.characterRoom, room.runtime_epoch, this.personaVersion, now);
      this.db.event(this.scope({ broadcast_id: broadcastId }, { actor_kind: 'operator', actor_id: principal.principal_id }), 'broadcast.created', { persona_version: this.personaVersion });
      this.db.run("UPDATE broadcasts SET state='STARTING',revision=revision+1 WHERE broadcast_id=?", broadcastId);
      return this.current();
    });
  }
  controlTarget(expected) {
    const broadcast = this.current();
    if (expected) requireValue(broadcast?.broadcast_id === expected.broadcast_id && broadcast.revision === expected.expected_revision, 'BROADCAST_REVISION_CONFLICT');
    return broadcast;
  }
  readyBroadcast(broadcastId, healthy, expected) {
    return this.db.tx(() => {
      const broadcast = this.controlTarget(expected);
      requireValue(broadcast?.broadcast_id === broadcastId && ['STARTING','RECOVERING','PAUSED'].includes(broadcast.state), 'BROADCAST_NOT_STARTABLE');
      requireValue(healthy && this.authorityReady(broadcastId), 'DEPENDENCIES_NOT_READY', 503);
      if (broadcast.state !== 'STARTING') this.db.run('UPDATE rooms SET runtime_epoch=runtime_epoch+1,generation=generation+1,maintenance_barrier=maintenance_barrier+1 WHERE character_id=? AND room_id=?', ...this.characterRoom);
      const epoch = this.room().runtime_epoch;
      if (epoch !== broadcast.runtime_epoch) {
        this.db.run('UPDATE playback_leases SET revoked_at=? WHERE broadcast_id=?', utc(this.db.now()), broadcastId);
        this.db.run('UPDATE playback_history SET revoked_at=? WHERE broadcast_id=? AND revoked_at IS NULL', utc(this.db.now()), broadcastId);
      }
      this.db.run("UPDATE broadcasts SET state='LIVE',runtime_epoch=?,revision=revision+1,started_at=COALESCE(started_at,?) WHERE broadcast_id=?", epoch, utc(this.db.now()), broadcastId);
      this.db.event(this.scope({ broadcast_id: broadcastId }), 'broadcast.live', { resumed: broadcast.state !== 'STARTING', authority_reclaim_required: epoch !== broadcast.runtime_epoch });
      return this.current();
    });
  }
  pause(principal, expected) {
    requireValue(principal.role === 'operator', 'OPERATOR_REQUIRED', 403);
    this.controlTarget(expected);
    const active = this.active(); if (active) this.cancel(active.request_id, 'paused');
    return this.db.tx(() => {
      const broadcast = this.controlTarget(expected); requireValue(broadcast?.state === 'LIVE', 'BROADCAST_NOT_LIVE');
      this.db.run("UPDATE broadcasts SET state='PAUSED',revision=revision+1 WHERE broadcast_id=?", broadcast.broadcast_id);
      this.db.event(this.scope(broadcast), 'broadcast.paused', {}); return this.current();
    });
  }
  end(principal, expected) {
    requireValue(principal.role === 'operator', 'OPERATOR_REQUIRED', 403);
    const broadcast = this.controlTarget(expected);
    if (!broadcast) return { already_ended: true };
    return this.db.tx(() => {
      if (broadcast.state !== 'DRAINING') {
        this.db.run("UPDATE broadcasts SET state='DRAINING',revision=revision+1 WHERE broadcast_id=?", broadcast.broadcast_id);
        this.db.event(this.scope(broadcast), 'broadcast.draining', { deadline_at: utc(this.db.now() + this.policy.playback.drain_timeout_ms) });
        for (const queued of this.db.all("SELECT * FROM requests WHERE broadcast_id=? AND status='QUEUED'", broadcast.broadcast_id)) this.terminalInTransaction(queued, 'CANCELLED', 'broadcast_ending');
      }
      return this.current();
    });
  }
  finishEnd() {
    return this.db.tx(() => {
      const broadcast = this.current(); requireValue(broadcast?.state === 'DRAINING' && !this.active(), 'BROADCAST_NOT_DRAINED');
      const now = utc(this.db.now()), notBefore = utc(this.db.now() + this.policy.maintenance.post_broadcast_quiet_ms);
      const seq = this.db.event(this.scope(broadcast), 'broadcast.ended', { evidence_level: 'consumer_playout' });
      this.db.run("UPDATE broadcasts SET state='ENDED',revision=revision+1,ended_at=?,ended_event_seq=?,consolidation_not_before=? WHERE broadcast_id=?", now, seq, notBefore, broadcast.broadcast_id);
      this.db.run('UPDATE playback_leases SET revoked_at=? WHERE broadcast_id=?', now, broadcast.broadcast_id);
      this.db.run('UPDATE playback_history SET revoked_at=? WHERE broadcast_id=? AND revoked_at IS NULL', now, broadcast.broadcast_id);
      this.enqueueJobsInTransaction(broadcast.broadcast_id, seq, broadcast.source_revision, notBefore, 'post_broadcast');
      return this.db.get('SELECT * FROM broadcasts WHERE broadcast_id=?', broadcast.broadcast_id);
    });
  }
  enqueueJobsInTransaction(broadcastId, end, revision, notBefore, kind, scheduleKey = '') {
    const events = this.db.all("SELECT e.event_seq,p.payload_json FROM stream_events e JOIN event_payloads p USING(event_seq) WHERE e.broadcast_id=? AND e.event_seq<=? AND e.event_type IN ('input.accepted','playback.completed') AND p.redacted_at IS NULL ORDER BY event_seq", broadcastId, end);
    const partitions = new Set(events.map(e => JSON.parse(e.payload_json).partition_key || 'public'));
    if (!partitions.size) partitions.add('public');
    const room = this.room(), created = [];
    for (const partition of partitions) {
      const jobKey = digest([kind, broadcastId, partition, revision, this.policy.policy_version, scheduleKey]);
      const jobId = 'job-' + jobKey.slice(0, 32), start = events[0]?.event_seq ?? end;
      this.db.run(`INSERT OR IGNORE INTO compaction_jobs(job_id,job_key,job_kind,character_id,room_id,broadcast_id,partition_key,policy_version,source_revision,state,stage,source_start_seq,source_end_seq,consumed_through_seq,maintenance_barrier,not_before,created_at) VALUES (?,?,?,?,?,?,?,?,?,'PENDING','MANIFEST',?,?,?,?,?,?)`,
        jobId, jobKey, kind, ...this.characterRoom, broadcastId, partition, this.policy.policy_version, revision, start, end, start - 1, room.maintenance_barrier, notBefore, utc(this.db.now()));
      this.db.run('INSERT OR IGNORE INTO job_runtime(job_id,deletion_generation) VALUES (?,?)', jobId, room.deletion_generation);
      created.push(jobId);
    }
    return created;
  }
  accept(principal, { text, mode = 'chat', idempotency_key: key, public_input: isPublic = false }) {
    requireValue(typeof text === 'string' && text.trim().length > 0 && text.length <= this.policy.conversation.input_max_chars && ['chat','echo'].includes(mode) && typeof key === 'string' && key.length >= 8 && key.length <= 120, 'INPUT_INVALID', 400);
    const partition = principal.role === 'operator' && isPublic ? 'public' : principal.viewer_id;
    requireValue(!!partition, 'VIEWER_IDENTITY_REQUIRED', 401);
    const hash = digest({ text, mode, partition });
    return this.db.tx(() => {
      const existing = this.db.get('SELECT * FROM requests WHERE character_id=? AND room_id=? AND principal_id=? AND idempotency_key=?', ...this.characterRoom, principal.principal_id, key);
      if (existing) { requireValue(existing.input_sha256 === hash, 'IDEMPOTENCY_CONFLICT'); return { ...existing, duplicate: true }; }
      const broadcast = this.current(); requireValue(broadcast?.state === 'LIVE', 'BROADCAST_NOT_LIVE');
      const pending = this.db.get("SELECT COUNT(*) AS n FROM requests WHERE broadcast_id=? AND status='QUEUED'", broadcast.broadcast_id).n;
      requireValue(pending < this.policy.conversation.pending_queue_limit, 'QUEUE_FULL', 429);
      const request = { request_id: id('req'), broadcast_id: broadcast.broadcast_id, runtime_epoch: this.room().runtime_epoch };
      const seq = this.db.event(this.scope(request, { actor_kind: principal.role === 'operator' ? 'operator' : 'viewer', actor_id: principal.principal_id }), 'input.accepted', { text: text.trim(), partition_key: partition, viewer_id: partition === 'public' ? null : partition, mode, verified_principal: principal.principal_id });
      this.db.run(`INSERT INTO requests(request_id,broadcast_id,character_id,room_id,principal_id,viewer_id,mode,status,idempotency_key,input_sha256,runtime_epoch,input_event_seq,created_at,queue_expires_at) VALUES (?,?,?,?,?,?,?,'QUEUED',?,?,?,?,?,?)`,
        request.request_id, broadcast.broadcast_id, ...this.characterRoom, principal.principal_id, partition === 'public' ? null : partition, mode, key, hash, request.runtime_epoch, seq, utc(this.db.now()), utc(this.db.now() + this.policy.conversation.queued_input_ttl_ms));
      return this.request(request.request_id);
    });
  }
  request(requestId) { return this.db.get('SELECT * FROM requests WHERE request_id=?', requestId); }
  input(request) { return this.db.payload(request.input_event_seq); }
  activate() {
    return this.db.tx(() => {
      const broadcast = this.current(); if (!broadcast || broadcast.state !== 'LIVE' || this.active() || !this.authorityReady(broadcast.broadcast_id)) return null;
      const pending = this.db.all("SELECT * FROM requests WHERE broadcast_id=? AND status='QUEUED' ORDER BY input_event_seq", broadcast.broadcast_id);
      for (const row of pending) {
        if (Date.parse(row.queue_expires_at) <= this.db.now()) { this.terminalInTransaction(row, 'EXPIRED', 'queue_ttl'); continue; }
        this.db.run('UPDATE rooms SET generation=generation+1 WHERE character_id=? AND room_id=?', ...this.characterRoom);
        const room = this.room();
        this.db.run("UPDATE requests SET status='THINKING',runtime_epoch=?,generation=?,revision=revision+1,active_deadline_at=?,dsh_session_id=? WHERE request_id=?", room.runtime_epoch, room.generation, utc(this.db.now() + this.policy.conversation.active_request_deadline_ms), 'dsh-' + row.request_id, row.request_id);
        const active = this.request(row.request_id);
        this.db.event(this.scope(active), 'request.thinking', { dsh_session_id: active.dsh_session_id }); return active;
      }
      return null;
    });
  }
  matches(requestId, epoch, generation) {
    const request = this.request(requestId), room = this.room();
    return !!request && ACTIVE_REQUESTS.includes(request.status) && request.runtime_epoch === epoch && request.generation === generation && room.runtime_epoch === epoch && room.generation === generation;
  }
  textReady(requestId, text, epoch, generation) {
    requireValue(typeof text === 'string' && text.trim() && text.length <= this.policy.conversation.final_speech_max_chars, 'FINAL_SPEECH_INVALID', 422);
    return this.db.tx(() => {
      requireValue(this.matches(requestId, epoch, generation), 'STALE_GENERATION');
      const request = this.request(requestId), utteranceId = id('utt');
      requireValue(request.status === 'THINKING', 'TEXT_ALREADY_FINAL');
      this.db.run("INSERT INTO utterances(utterance_id,request_id,status,runtime_epoch,generation,text_sha256) VALUES (?,?,'SYNTHESIZING',?,?,?)", utteranceId, requestId, epoch, generation, digest(text));
      this.db.run("UPDATE requests SET status='SYNTHESIZING',revision=revision+1 WHERE request_id=?", requestId);
      this.db.event(this.scope({ ...request, utterance_id: utteranceId }), 'utterance.text_ready', { text, text_sha256: digest(text), partition_key: request.viewer_id || 'public' });
      return { ...request, utterance_id: utteranceId, runtime_epoch: epoch, generation, text };
    });
  }
  audioReady(input) {
    return this.db.tx(() => {
      const utterance = this.db.get('SELECT * FROM utterances WHERE utterance_id=?', input.utterance_id);
      requireValue(utterance && this.matches(utterance.request_id, input.runtime_epoch, input.generation), 'STALE_GENERATION');
      requireValue(Number.isSafeInteger(input.valid_sample_count) && input.valid_sample_count > 0 && /^[a-f0-9]{64}$/.test(input.audio_sha256), 'AUDIO_MANIFEST_INVALID', 400);
      if (utterance.valid_sample_count !== null) {
        requireValue(utterance.valid_sample_count === input.valid_sample_count && utterance.audio_sha256 === input.audio_sha256, 'AUDIO_MANIFEST_CONFLICT');
        return { accepted: true, duplicate: true };
      }
      this.db.run("UPDATE utterances SET status='AUDIO_READY',valid_sample_count=?,audio_sha256=? WHERE utterance_id=?", input.valid_sample_count, input.audio_sha256, input.utterance_id);
      this.db.run("UPDATE requests SET status='AUDIO_READY',revision=revision+1 WHERE request_id=?", utterance.request_id);
      this.db.event(this.scope({ ...this.request(utterance.request_id), utterance_id: input.utterance_id }), 'utterance.audio_ready', { valid_sample_count: input.valid_sample_count, audio_sha256: input.audio_sha256 });
      return { accepted: true };
    });
  }
  claimAuthority(principal, broadcastId, consumerId, replace = false) {
    requireValue(principal.role === 'operator', 'OPERATOR_REQUIRED', 403);
    requireValue(typeof consumerId === 'string' && consumerId.length >= 8 && consumerId.length <= 100, 'CONSUMER_INVALID', 400);
    const oldLease=this.lease(broadcastId),oldRequest=this.active();let cancelled=null;
    if(this.current()?.broadcast_id===broadcastId&&oldLease&&!oldLease.revoked_at&&oldRequest&&(replace||!this.authorityReady(broadcastId))) {
      cancelled=oldRequest;this.cancel(oldRequest.request_id,'authority_changed');
    }
    return this.db.tx(() => {
      const broadcast = this.current(); requireValue(broadcast?.broadcast_id === broadcastId, 'BROADCAST_NOT_OPEN');
      const previous = this.lease(broadcastId), now = utc(this.db.now());
      if (this.authorityReady(broadcastId) && previous.consumer_id === consumerId && !replace) return this.leaseResponse(previous);
      requireValue(!this.authorityReady(broadcastId) || replace, 'AUTHORITY_ALREADY_HELD');
      if (previous && !previous.revoked_at) {
        if(cancelled){this.db.run("UPDATE requests SET status='UNKNOWN',revision=revision+1 WHERE request_id=?",cancelled.request_id);this.db.run("UPDATE utterances SET status='UNKNOWN' WHERE request_id=?",cancelled.request_id);}
        const active = this.active(); if (active) this.terminalInTransaction(active, 'UNKNOWN', 'authority_changed');
        this.db.run('UPDATE playback_history SET revoked_at=? WHERE lease_id=?', now, previous.lease_id);
        this.db.run('UPDATE rooms SET runtime_epoch=runtime_epoch+1,generation=generation+1 WHERE character_id=? AND room_id=?', ...this.characterRoom);
        this.db.run('UPDATE broadcasts SET runtime_epoch=?,revision=revision+1 WHERE broadcast_id=?', this.room().runtime_epoch, broadcastId);
      }
      const leaseId = id('lease'), epoch = this.room().runtime_epoch, authorityEpoch = (previous?.authority_epoch || 0) + 1, expires = utc(this.db.now() + this.policy.playback.lease_timeout_ms);
      this.db.run('INSERT INTO playback_leases(broadcast_id,consumer_id,lease_id,authority_epoch,runtime_epoch,expires_at) VALUES (?,?,?,?,?,?) ON CONFLICT(broadcast_id) DO UPDATE SET consumer_id=excluded.consumer_id,lease_id=excluded.lease_id,authority_epoch=excluded.authority_epoch,runtime_epoch=excluded.runtime_epoch,expires_at=excluded.expires_at,revoked_at=NULL', broadcastId, consumerId, leaseId, authorityEpoch, epoch, expires);
      this.db.run('INSERT INTO playback_history VALUES (?,?,?,?,?,?,NULL)', leaseId, broadcastId, consumerId, authorityEpoch, epoch, expires);
      this.db.event(this.scope({ broadcast_id: broadcastId }), 'playback.authority_acquired', { consumer_id: consumerId, lease_id: leaseId, authority_epoch: authorityEpoch });
      return this.leaseResponse(this.lease(broadcastId));
    });
  }
  heartbeat(leaseId, consumerId) {
    return this.db.tx(() => {
      const lease = this.db.get('SELECT * FROM playback_leases WHERE lease_id=?', leaseId);
      requireValue(lease && lease.consumer_id === consumerId && this.authorityReady(lease.broadcast_id), 'PLAYBACK_LEASE_EXPIRED');
      const until = utc(this.db.now() + this.policy.playback.lease_timeout_ms);
      this.db.run('UPDATE playback_leases SET expires_at=? WHERE lease_id=?', until, leaseId);
      this.db.run('UPDATE playback_history SET expires_at=? WHERE lease_id=?', until, leaseId);
      return { expires_at: until, runtime_epoch: lease.runtime_epoch };
    });
  }
  mediaMap(input) {
    return this.db.tx(() => {
      const utterance = this.db.get('SELECT * FROM utterances WHERE utterance_id=?', input.utterance_id);
      requireValue(utterance && this.matches(utterance.request_id, input.runtime_epoch, input.generation), 'STALE_GENERATION');
      requireValue(input.request_id===utterance.request_id&&input.valid_sample_count===utterance.valid_sample_count,'MEDIA_UTTERANCE_MISMATCH',400);
      requireValue(utterance.valid_sample_count !== null && typeof input.transport_instance_id === 'string' && Array.isArray(input.ranges) && input.ranges.length > 0 && input.ranges.length <= 100, 'MEDIA_MAP_INVALID', 400);
      const duplicate = this.db.get('SELECT * FROM media_manifests WHERE utterance_id=? AND transport_instance_id=? AND manifest_sha256=?', input.utterance_id, input.transport_instance_id, digest(input.ranges));
      if (duplicate) { requireValue(duplicate.final === (input.final ? 1 : 0), 'MEDIA_MAP_DUPLICATE_CONFLICT'); return { persisted:true,map_revision:duplicate.map_revision,persisted_through_sample:duplicate.persisted_through_sample,duplicate:true }; }
      const previous = this.db.get('SELECT * FROM media_manifests WHERE utterance_id=? AND transport_instance_id=? ORDER BY map_revision DESC LIMIT 1', input.utterance_id, input.transport_instance_id);
      let through = previous?.persisted_through_sample ?? 0;
      let lastRange=previous?JSON.parse(previous.ranges_json).at(-1):null;
      for (const range of input.ranges) {
        requireValue(Number.isSafeInteger(range.packet_seq) && range.packet_seq >= 0 && range.sample_start === through && Number.isSafeInteger(range.packet_offset)&&range.packet_offset>=0&&range.packet_offset+range.sample_count<=640&&(!lastRange||range.packet_seq>lastRange.packet_seq||range.packet_seq===lastRange.packet_seq&&range.packet_offset===lastRange.packet_offset+lastRange.sample_count)&&Number.isSafeInteger(range.sample_count) && range.sample_count > 0 && range.sample_count <= 640 && through + range.sample_count <= utterance.valid_sample_count, 'MEDIA_RANGE_GAP', 400);
        through += range.sample_count;
        lastRange=range;
      }
      requireValue(!input.final || through === utterance.valid_sample_count, 'MEDIA_MAP_FINAL_INVALID');
      const revision = (previous?.map_revision ?? 0) + 1, manifestHash = digest(input.ranges);
      this.db.run('INSERT INTO media_manifests VALUES (?,?,?,?,?,?,?)', input.utterance_id, input.transport_instance_id, revision, canonical(input.ranges), manifestHash, through, input.final ? 1 : 0);
      this.db.run("UPDATE utterances SET status='BUFFERING' WHERE utterance_id=? AND status IN ('AUDIO_READY','BUFFERING')", input.utterance_id);
      this.db.run("UPDATE requests SET status='BUFFERING' WHERE request_id=? AND status IN ('AUDIO_READY','BUFFERING')", utterance.request_id);
      return { persisted: true, map_revision: revision, persisted_through_sample: through };
    });
  }
  receipt(principal, input) {
    requireValue(principal.role === 'operator', 'OPERATOR_REQUIRED', 403);
    return this.db.tx(() => {
      const utterance = this.db.get('SELECT * FROM utterances WHERE utterance_id=?', input.utterance_id);
      requireValue(utterance && Number.isSafeInteger(input.receipt_sequence) && input.receipt_sequence >= 0 && Number.isSafeInteger(input.contiguous_played_samples), 'RECEIPT_INVALID', 400);
      const prior = this.db.get('SELECT * FROM playback_receipts WHERE lease_id=? AND receipt_sequence=?', input.lease_id, input.receipt_sequence);
      if (prior) { requireValue(prior.utterance_id === input.utterance_id && prior.contiguous_played_samples === input.contiguous_played_samples && prior.natural_end === (input.natural_end ? 1 : 0), 'RECEIPT_IDEMPOTENCY_CONFLICT'); return { accepted: !!prior.accepted, reason: prior.reason, duplicate: true }; }
      const request = this.request(utterance.request_id), lease = this.lease(request.broadcast_id);
      const observation = this.db.get('SELECT * FROM playback_observations WHERE lease_id=? AND utterance_id=?', input.lease_id, input.utterance_id);
      const manifest = this.db.get('SELECT * FROM media_manifests WHERE utterance_id=? AND transport_instance_id=? ORDER BY map_revision DESC LIMIT 1', input.utterance_id, input.transport_instance_id ?? '');
      let reason = 'accepted';
      if (!lease || lease.lease_id !== input.lease_id || lease.consumer_id !== input.consumer_id || lease.authority_epoch !== input.authority_epoch || !this.authorityReady(request.broadcast_id)) reason = 'authority_invalid';
      else if (input.runtime_epoch !== utterance.runtime_epoch || input.generation !== utterance.generation || !this.matches(request.request_id, input.runtime_epoch, input.generation)) reason = 'stale_generation';
      else if (!manifest || input.contiguous_played_samples < 0 || input.contiguous_played_samples > manifest.persisted_through_sample) reason = 'unmapped_samples';
      else if (observation && (input.receipt_sequence <= observation.receipt_sequence || input.contiguous_played_samples < observation.played_samples)) reason = 'receipt_regression';
      else if (input.natural_end && (input.contiguous_played_samples !== utterance.valid_sample_count || !manifest.final)) reason = 'not_natural_complete';
      const accepted = reason === 'accepted';
      this.db.run('INSERT INTO playback_receipts VALUES (?,?,?,?,?,?,?,?,?,?,?)', input.receipt_id || id('receipt'), input.utterance_id, input.lease_id || '', input.authority_epoch || 0, input.runtime_epoch || 0, input.receipt_sequence, input.contiguous_played_samples, input.natural_end ? 1 : 0, accepted ? 1 : 0, reason, utc(this.db.now()));
      if (!accepted) return { accepted, reason };
      this.db.run('INSERT INTO playback_observations VALUES (?,?,?,?,?) ON CONFLICT(lease_id,utterance_id) DO UPDATE SET receipt_sequence=excluded.receipt_sequence,played_samples=excluded.played_samples,natural_end=excluded.natural_end', input.lease_id, input.utterance_id, input.receipt_sequence, input.contiguous_played_samples, input.natural_end ? 1 : 0);
      this.db.run("UPDATE utterances SET status='PLAYING',contiguous_played_samples=? WHERE utterance_id=?", input.contiguous_played_samples, input.utterance_id);
      this.db.run("UPDATE requests SET status='PLAYING' WHERE request_id=?", request.request_id);
      if (input.natural_end) {
        const textEvent = this.db.get("SELECT event_seq FROM stream_events WHERE utterance_id=? AND event_type='utterance.text_ready'", input.utterance_id), text = this.db.payload(textEvent.event_seq).text;
        const seq = this.db.event(this.scope({ ...request, utterance_id: input.utterance_id }, { actor_kind: 'playback', actor_id: input.consumer_id }), 'playback.completed', { text, text_sha256: utterance.text_sha256, valid_sample_count: utterance.valid_sample_count, partition_key: request.viewer_id || 'public', lease_id: input.lease_id, evidence_level: 'consumer_playout' });
        this.db.run("UPDATE utterances SET status='COMPLETED',completion_event_seq=? WHERE utterance_id=?", seq, input.utterance_id);
        this.db.run("UPDATE requests SET status='COMPLETED',revision=revision+1 WHERE request_id=?", request.request_id);
        this.db.run('UPDATE broadcasts SET delivery_context_revision=delivery_context_revision+1 WHERE broadcast_id=?', request.broadcast_id);
      }
      return { accepted, reason, completed: !!input.natural_end };
    });
  }
  terminalInTransaction(request, status, reason) {
    requireValue(TERMINAL_REQUESTS.includes(status), 'TERMINAL_STATUS_INVALID');
    if (TERMINAL_REQUESTS.includes(this.request(request.request_id).status)) return;
    this.db.run('UPDATE requests SET status=?,revision=revision+1 WHERE request_id=?', status, request.request_id);
    this.db.run("UPDATE utterances SET status=?,observation_revision=observation_revision+1 WHERE request_id=? AND status!='COMPLETED'", ['EXPIRED','REJECTED'].includes(status) ? 'CANCELLED' : status, request.request_id);
    this.db.event(this.scope(request), 'request.' + status.toLowerCase(), { reason, partial_text_eligible: false });
  }
  fail(requestId, reason) {
    return this.stop(requestId, reason, 'FAILED');
  }
  cancel(requestId, reason = 'operator_stop') {
    return this.stop(requestId, reason);
  }
  stop(requestId, reason, failureStatus) {
    const barrier = this.db.tx(() => {
      const request = this.request(requestId); requireValue(request, 'REQUEST_NOT_FOUND', 404);
      if (TERMINAL_REQUESTS.includes(request.status)) return { already_terminal: true };
      if (request.status === 'QUEUED') { this.terminalInTransaction(request, failureStatus || 'CANCELLED', reason); return { already_terminal: true, queued_cancelled: true }; }
      const utterance = this.db.get('SELECT * FROM utterances WHERE request_id=?', requestId);
      const status = failureStatus || ((utterance?.contiguous_played_samples || 0) > 0 ? 'INTERRUPTED' : 'CANCELLED');
      const barrierId = id('cancel');
      this.db.run('UPDATE rooms SET generation=generation+1 WHERE character_id=? AND room_id=?', ...this.characterRoom);
      this.terminalInTransaction(request, status, reason);
      this.db.run('INSERT INTO cancel_barriers VALUES (?,?,?,?,?,NULL)', barrierId, requestId, request.runtime_epoch, request.generation || 0, utc(this.db.now() + this.policy.playback.cancel_ack_window_ms));
      if (utterance) this.db.run('UPDATE utterances SET cancel_barrier_id=? WHERE utterance_id=?', barrierId, utterance.utterance_id);
      this.db.event(this.scope(request), 'playback.cancel_barrier', { barrier_id: barrierId, request_id: requestId, new_generation: this.room().generation, reason });
      return { barrier_id: barrierId, request_id: requestId, runtime_epoch: request.runtime_epoch, generation: request.generation, new_generation: this.room().generation };
    });
    if (!barrier.already_terminal) this.emit('cancel', barrier);
    return barrier;
  }
  cancelAck(principal, input) {
    requireValue(principal.role === 'operator', 'OPERATOR_REQUIRED', 403);
    return this.db.tx(() => {
      const barrier = this.db.get('SELECT * FROM cancel_barriers WHERE barrier_id=?', input.barrier_id);
      requireValue(barrier && Date.parse(barrier.expires_at) >= this.db.now(), 'CANCEL_ACK_EXPIRED');
      if (barrier.acked_at) return { duplicate: true };
      const request = this.request(barrier.request_id), utterance = this.db.get('SELECT * FROM utterances WHERE request_id=?', request.request_id);
      const lease = this.db.get('SELECT * FROM playback_history WHERE lease_id=?', input.lease_id);
      requireValue(lease && lease.broadcast_id === request.broadcast_id && lease.consumer_id === input.consumer_id && lease.runtime_epoch === barrier.runtime_epoch, 'CANCEL_ACK_AUTHORITY');
      const manifest = utterance && this.db.get('SELECT * FROM media_manifests WHERE utterance_id=? AND transport_instance_id=? ORDER BY map_revision DESC LIMIT 1', utterance.utterance_id, input.transport_instance_id || '');
      const count = input.contiguous_played_samples;
      requireValue(Number.isSafeInteger(count) && count >= 0 && (!count || manifest && count <= manifest.persisted_through_sample), 'CANCEL_ACK_UNMAPPED');
      const observed = utterance && this.db.get('SELECT * FROM playback_observations WHERE lease_id=? AND utterance_id=?', input.lease_id, utterance.utterance_id);
      requireValue(!observed || count >= observed.played_samples, 'CANCEL_ACK_REGRESSION');
      if (utterance && count > 0 && ['CANCELLED','INTERRUPTED','UNKNOWN','FAILED'].includes(utterance.status)) {
        const status = utterance.status === 'FAILED' ? 'FAILED' : 'INTERRUPTED';
        this.db.run('UPDATE utterances SET status=?,contiguous_played_samples=?,observation_revision=observation_revision+1 WHERE utterance_id=?', status, count, utterance.utterance_id);
        this.db.run('UPDATE requests SET status=?,revision=revision+1 WHERE request_id=?', status, request.request_id);
      }
      this.db.run('UPDATE cancel_barriers SET acked_at=? WHERE barrier_id=?', utc(this.db.now()), barrier.barrier_id);
      this.db.event(this.scope(request, { actor_kind: 'playback', actor_id: input.consumer_id }), 'playback.cancel_acknowledged', { barrier_id: input.barrier_id, played_samples: count, partial_text_eligible: false });
      const broadcast = this.db.get('SELECT * FROM broadcasts WHERE broadcast_id=?', request.broadcast_id);
      if (broadcast.state === 'ENDED') {
        this.db.run('UPDATE broadcasts SET source_revision=source_revision+1,revision=revision+1,consolidation_not_before=? WHERE broadcast_id=?', utc(this.db.now() + this.policy.maintenance.post_broadcast_quiet_ms), broadcast.broadcast_id);
        this.enqueueJobsInTransaction(broadcast.broadcast_id, broadcast.ended_event_seq, broadcast.source_revision + 1, utc(this.db.now() + this.policy.maintenance.post_broadcast_quiet_ms), 'post_broadcast');
      }
      return { accepted: true, completed: false };
    });
  }
  tick() {
    const request = this.active();
    if (request && Date.parse(request.active_deadline_at) <= this.db.now()) this.fail(request.request_id, 'REQUEST_DEADLINE_EXCEEDED');
    else if (request && !this.authorityReady(request.broadcast_id)) {
      this.cancel(request.request_id, 'authority_lost');
      this.db.tx(() => {this.db.run("UPDATE requests SET status='UNKNOWN' WHERE request_id=?", request.request_id);this.db.run("UPDATE utterances SET status='UNKNOWN' WHERE request_id=?",request.request_id);});
    }
    const broadcast = this.current();
    if (broadcast?.state === 'DRAINING') {
      const event = this.db.get("SELECT event_seq FROM stream_events WHERE broadcast_id=? AND event_type='broadcast.draining' ORDER BY event_seq DESC LIMIT 1", broadcast.broadcast_id);
      const deadline = event && this.db.payload(event.event_seq).deadline_at;
      if (this.active() && deadline && Date.parse(deadline) <= this.db.now()) this.cancel(this.active().request_id, 'drain_timeout');
      if (!this.active()) this.finishEnd();
    }
  }
  status() { return { room: this.room(), broadcast: this.current() ?? null, active_request: this.active() ?? null,
    queued: this.db.all("SELECT request_id,status,created_at,queue_expires_at FROM requests WHERE status='QUEUED' ORDER BY input_event_seq"),
    authority_ready: this.current() ? this.authorityReady(this.current().broadcast_id) : false };
  }
}
