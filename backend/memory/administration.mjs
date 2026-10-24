import { mkdirSync, existsSync, readFileSync, openSync, writeSync, fsyncSync, closeSync, writeFileSync, readdirSync, rmSync, realpathSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { canonical, digest } from '../dsh-bridge/channel.mjs';
import { requireValue } from '../dsh-bridge/state.mjs';
import { inside } from '../dsh-bridge/policy.mjs';
import { id, utc } from './store.mjs';

export class MemoryAdministration {
  constructor(root, db, state, memory, host, onHostRestart) {
    this.root = root; this.db = db; this.state = state; this.memory = memory; this.host = host; this.onHostRestart = onHostRestart;
    this.ledgerFile = join(root, 'state/deletion-ledger.jsonl'); this.ledgerHead = join(root, 'state/deletion-head.json'); this.locked = false;
    this.verifyLedger();
  }
  readLedger() {
    if (!existsSync(this.ledgerFile)) return [];
    const lines = readFileSync(this.ledgerFile, 'utf8').trim().split('\n').filter(Boolean), rows = []; let previous = '0'.repeat(64);
    for (const line of lines) {
      const row = JSON.parse(line), { sha256, ...body } = row;
      requireValue(body.previous_sha256 === previous && digest(body) === sha256, 'DELETION_LEDGER_CORRUPT', 503);
      previous = sha256; rows.push(row);
    }
    return rows;
  }
  verifyLedger() {
    const rows = this.readLedger(), head = rows.at(-1), saved = existsSync(this.ledgerHead) ? JSON.parse(readFileSync(this.ledgerHead, 'utf8')) : null;
    const pending = this.db.get("SELECT COUNT(*) n FROM redaction_outbox WHERE state='PENDING'").n;
    const generation = this.state.room().deletion_generation;
    requireValue(!saved || head && head.generation >= saved.generation, 'DELETION_LEDGER_HEAD_MISSING', 503);
    requireValue(!head || head.generation <= generation, 'RESTORE_REQUIRES_DELETION_REPLAY', 503);
    requireValue(generation === (head?.generation || 0) || pending > 0, 'DELETION_LEDGER_UNAVAILABLE', 503);
    this.flushLedger();
  }
  flushLedger() {
    const rows = this.readLedger(), seen = new Set(rows.map(row => row.operation_id)); let previous = rows.at(-1)?.sha256 || '0'.repeat(64);
    mkdirSync(join(this.root, 'state'), { recursive: true });
    for (const row of this.db.all("SELECT * FROM redaction_outbox WHERE state='PENDING' ORDER BY generation")) {
      if (!seen.has(row.operation_id)) {
        const body = { ...JSON.parse(row.payload_json), operation_id: row.operation_id, generation: row.generation, previous_sha256: previous };
        const sha256 = digest(body), fd = openSync(this.ledgerFile, 'a');
        try { writeSync(fd, canonical({ ...body, sha256 }) + '\n'); fsyncSync(fd); } finally { closeSync(fd); }
        previous = sha256;
      }
      writeFileSync(this.ledgerHead, canonical({ generation: row.generation, sha256: previous }));
      this.db.tx(() => this.db.run("UPDATE redaction_outbox SET state='SYNCED' WHERE operation_id=?", row.operation_id));
    }
  }
  correct(principal, input) {
    requireValue(principal.role === 'operator', 'OPERATOR_REQUIRED', 403);
    requireValue(input.operation_id && Object.hasOwn(input,'value') && typeof input.content === 'string' && input.content.length > 0 && input.content.length <= 160 && ['positive','negative','neutral'].includes(input.polarity), 'CORRECTION_INVALID', 400);
    const hash = digest(input);
    return this.db.tx(() => {
      const applied = this.db.get('SELECT * FROM operation_results WHERE operation_id=?', input.operation_id);
      if (applied) { requireValue(applied.input_sha256 === hash, 'OPERATION_ID_CONFLICT'); return JSON.parse(applied.result_json); }
      const old = this.db.get('SELECT * FROM memory_entries WHERE memory_id=?', input.memory_id);
      requireValue(old && old.revision === input.expected_revision && old.state !== 'deleted', 'MEMORY_REVISION_CONFLICT');
      requireValue(!/^(identity|persona|character)\./.test(old.fact_key), 'PERSONA_REQUIRES_PUBLICATION');
      const seq = this.db.event(this.state.scope({}, { actor_kind: 'operator', actor_id: principal.principal_id }), 'memory.corrected', { text: input.content, value: input.value, partition_key: old.subject_key, memory_id: old.memory_id });
      const event = this.db.get('SELECT * FROM stream_events WHERE event_seq=?', seq);
      for (const conflict of this.db.all("SELECT * FROM memory_entries WHERE subject_key=? AND fact_key=? AND memory_id!=? AND state IN ('active','conflicted')", old.subject_key, old.fact_key, old.memory_id)) this.memory.updateInTransaction(conflict, { state: 'superseded' }, 'operator_conflict_resolution');
      const next = this.memory.updateInTransaction(old, { value_json: canonical(input.value), content: input.content, polarity: input.polarity, state: 'active' }, 'operator_correction', [{ event_seq: seq, payload_sha256: event.payload_sha256, quote: input.content }], input.operation_id);
      this.db.run('INSERT INTO operation_results VALUES (?,?,?,?,?)', input.operation_id, 'correct', hash, canonical(next), utc(this.db.now()));
      return next;
    });
  }
  undo(principal, input) {
    requireValue(principal.role === 'operator', 'OPERATOR_REQUIRED', 403);
    return this.db.tx(() => {
      const revision = this.db.get('SELECT * FROM memory_revisions WHERE operation_id=?', input.operation_id);
      requireValue(revision?.prior_revision, 'UNDO_REVISION_NOT_FOUND', 404);
      const current = this.db.get('SELECT * FROM memory_entries WHERE memory_id=?', revision.memory_id);
      requireValue(current.revision === revision.revision && current.state !== 'deleted', 'UNDO_HAS_LATER_REVISION');
      const prior = this.db.get('SELECT * FROM memory_revisions WHERE memory_id=? AND revision=?', current.memory_id, revision.prior_revision), snapshot = JSON.parse(prior.snapshot_json);
      requireValue(this.memory.sourceValid(snapshot), 'UNDO_SOURCE_NO_LONGER_VALID');
      const other = this.db.get("SELECT memory_id FROM memory_entries WHERE subject_key=? AND fact_key=? AND state='active' AND memory_id!=?", current.subject_key, current.fact_key, current.memory_id);
      requireValue(!other, 'UNDO_WOULD_OVERWRITE_NEW_FACT');
      const sources = this.db.all('SELECT * FROM memory_sources WHERE memory_id=? AND memory_revision=?', snapshot.memory_id, snapshot.revision);
      return this.memory.updateInTransaction(current, { ...snapshot, revision: current.revision, updated_at: current.updated_at }, 'compensating_undo:' + input.operation_id, sources);
    });
  }
  redactInTransaction({ operationId, subject, selectedMemoryId = null, replay = null }) {
    const selected = selectedMemoryId ? this.db.get('SELECT * FROM memory_entries WHERE memory_id=?', selectedMemoryId) : null;
    requireValue(replay || !selectedMemoryId || selected && selected.subject_key === subject, 'MEMORY_NOT_FOUND', 404);
    const allSources = selected ? this.db.all('SELECT DISTINCT event_seq FROM memory_sources WHERE memory_id=?', selectedMemoryId).map(row => row.event_seq) :
      this.db.all("SELECT e.event_seq FROM stream_events e JOIN event_payloads p USING(event_seq) WHERE json_extract(p.payload_json,'$.partition_key')=?", subject).map(row => row.event_seq);
    const seqs = replay ? (replay.event_refs||[]).map(ref=>this.db.get('SELECT event_seq FROM stream_events WHERE event_id=? AND payload_sha256=?',ref.event_id,ref.payload_sha256)?.event_seq).filter(Number.isSafeInteger) : allSources, now = utc(this.db.now());
    requireValue(!replay || Array.isArray(replay.event_refs),'RESTORE_LEDGER_SOURCE_IDENTITIES_REQUIRED');
    const eventSeq = this.db.event(this.state.scope({}, { actor_kind:'operator',actor_id:replay?'restore-redaction':'redaction' }), 'memory.deleted', { subject_key: subject, memory_id: selectedMemoryId, body_redacted: true, replay_generation:replay?.generation??null });
    const nextGeneration = replay?.generation ?? this.state.room().deletion_generation + 1;
    const affected = new Set(selectedMemoryId ? selected ? [selected.memory_id] : [] : this.db.all('SELECT memory_id FROM memory_entries WHERE subject_key=?', subject).map(row => row.memory_id));
    for(const memoryId of replay?.memory_ids||[])if(this.db.get('SELECT 1 FROM memory_entries WHERE memory_id=?',memoryId))affected.add(memoryId);
    for (const seq of seqs) {
      for (const row of this.db.all('SELECT DISTINCT memory_id FROM memory_sources WHERE event_seq=?', seq)) affected.add(row.memory_id);
      this.db.run('UPDATE event_payloads SET payload_json=NULL,redacted_at=? WHERE event_seq=?', now, seq);
      this.db.run("UPDATE memory_sources SET source_quote='' WHERE event_seq=?", seq);
    }
    for (const memoryId of affected) {
      const memory = this.db.get('SELECT * FROM memory_entries WHERE memory_id=?', memoryId);
      if (memory.state !== 'deleted') this.memory.updateInTransaction(memory, { state:'deleted',content:'',value_json:'null' }, 'deletion', []);
      this.db.run("UPDATE memory_revisions SET snapshot_json=? WHERE memory_id=?", canonical({ memory_id:memoryId,redacted:true }), memoryId);
      this.db.run("UPDATE memory_sources SET source_quote='' WHERE memory_id=?", memoryId);
      this.db.run("UPDATE operation_results SET result_json=? WHERE json_extract(result_json,'$.memory_id')=?", canonical({ memory_id:memoryId,redacted:true }), memoryId);
      // Old retry payloads must not retain the deleted body.
      this.db.run("UPDATE mirror_outbox SET payload_json=json_set(payload_json,'$.content',''),state=CASE WHEN action='REMOVE' THEN state ELSE 'SUPERSEDED' END WHERE memory_id=?", memoryId);
    }
    if (!selectedMemoryId) this.db.run('INSERT INTO deletion_fences VALUES (?,?,?,?,?,?) ON CONFLICT(character_id,room_id,subject_key) DO UPDATE SET generation=excluded.generation,event_seq=excluded.event_seq,created_at=excluded.created_at', ...this.state.characterRoom, subject, nextGeneration, eventSeq, now);
    // Summaries/context/chunk result bodies may contain paraphrases. Invalidate
    // their entire partition instead of attempting unsafe string replacement.
    this.db.run("UPDATE summary_versions SET state='redacted',body_json='{}',source_manifest_json='{}' WHERE partition_key=?", subject);
    const sessionIds = [];
    for (const context of this.db.all('SELECT c.*,r.dsh_session_id,r.viewer_id FROM request_contexts c JOIN requests r USING(request_id)')) {
      const manifest = JSON.parse(context.source_manifest_json || '[]');
      if (context.viewer_id === subject || manifest.some(source => seqs.includes(source.event_seq)) || subject === 'public') {
        this.db.run('UPDATE request_contexts SET context_json=NULL,source_manifest_json=NULL,redacted_at=? WHERE request_id=?', now, context.request_id);
        if (context.dsh_session_id) sessionIds.push(context.dsh_session_id);
      }
    }
    for (const job of this.db.all('SELECT * FROM compaction_jobs WHERE partition_key=?', subject)) {
      this.db.run("UPDATE memory_candidates SET body_json='{}',decision='stale',reason='deleted_source' WHERE job_id=?", job.job_id);
      this.db.run("UPDATE job_chunks SET result_json=NULL,state=CASE WHEN state='COMMITTED' THEN state ELSE 'STALE' END WHERE job_id=?", job.job_id);
      this.db.run("UPDATE compaction_jobs SET source_manifest_json='{}',state=CASE WHEN state='COMPLETED' THEN state ELSE 'CANCELLED' END,reason='deleted_source',lease_generation=lease_generation+1 WHERE job_id=?", job.job_id);
    }
    this.db.run("UPDATE memory_proposals SET body_json=NULL,state='DELETED' WHERE subject_key=?", subject);
    this.db.run('UPDATE rooms SET deletion_generation=MAX(deletion_generation,?),memory_revision=memory_revision+1,maintenance_barrier=maintenance_barrier+1 WHERE character_id=? AND room_id=?', nextGeneration, ...this.state.characterRoom);
    const eventRefs=seqs.map(seq=>this.db.get('SELECT event_id,event_seq,payload_sha256 FROM stream_events WHERE event_seq=?',seq));
    const body = { subject_key:subject,memory_id:selectedMemoryId,event_seq:eventSeq,event_seqs:seqs,event_refs:eventRefs,memory_ids:[...affected],session_ids:sessionIds,created_at:now };
    if (!replay) this.db.run("INSERT INTO redaction_outbox VALUES (?,?,?,?,'PENDING',?)", operationId, nextGeneration, subject, canonical(body), now);
    this.db.run("INSERT INTO runtime_meta VALUES ('privacy_redaction_pending',?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json", canonical({ operation_id:operationId,generation:nextGeneration }));
    return { ...body, generation:nextGeneration,operation_id:operationId };
  }
  async delete(principal, input) {
    requireValue(principal.role === 'operator', 'OPERATOR_REQUIRED', 403);
    requireValue(input.operation_id && typeof input.subject_key === 'string' && !this.locked, 'DELETION_INPUT_OR_LOCK');
    this.locked = true;
    try {
      const previous = this.db.get('SELECT * FROM redaction_outbox WHERE operation_id=?', input.operation_id);
      const active = this.state.active(); if (active) this.state.cancel(active.request_id, 'redaction');
      const result = previous ? { ...JSON.parse(previous.payload_json), operation_id:previous.operation_id,generation:previous.generation } : this.db.tx(() => this.redactInTransaction({ operationId:input.operation_id,subject:input.subject_key,selectedMemoryId:input.memory_id || null }));
      this.flushLedger();
      await this.onHostRestart(result.session_ids);
      await this.memory.project();
      this.db.tx(() => this.db.run("DELETE FROM runtime_meta WHERE key='privacy_redaction_pending'"));
      return { operation_id:result.operation_id,generation:result.generation,deleted_count:result.memory_ids.length,sessions_purged:result.session_ids.length };
    } finally { this.locked = false; }
  }
  async backup() {
    requireValue(!this.state.current() && !this.locked && !this.host.active.size, 'BACKUP_REQUIRES_OFFAIR');
    this.locked = true;
    try {
      this.flushLedger(); await this.host.port.flush(); await this.host.ctx.sessionPersistence?.flush();
      const directory = inside(this.root, 'backups/dsh-' + Date.now()); mkdirSync(directory, { recursive:true });
      const backup = this.db.backup(join(directory,'state.sqlite3'));
      // Humanity is a rebuildable mirror; only its approved persona and
      // publication receipt need exporting after flush, not an unsound JSON copy.
      const persona = this.host.port.readPersona(); writeFileSync(join(directory,'persona.json'),canonical(persona));
      const manifest = { schema_version:2,created_at:utc(this.db.now()),method:'sqlite_vacuum_into_plus_flushed_persona_export',
        database:{file:'state.sqlite3',sha256:backup.sha256},persona_sha256:digest(persona),room:this.state.room(),
        deletion_head:this.readLedger().at(-1)?.sha256 || null,policy_version:this.state.policy.policy_version,
        dsh:'0.2.0-rc.2',humanity:'0.1.17',connector:'stream-humanity-v1',humanity_projection:'rebuild_from_canonical' };
      writeFileSync(join(directory,'manifest.json'),canonical(manifest)); return { backup_id:directory.split(/[\\/]/).at(-1),manifest };
    } finally { this.locked=false; }
  }
}

export function purgeSessionBodies(root, dshHome, sessionIds) {
  const sessionsRoot=inside(root,join(dshHome,'sessions'));
  if(!existsSync(sessionsRoot))return;
  for(const project of readdirSync(sessionsRoot,{withFileTypes:true})) {
    if(!project.isDirectory()||project.isSymbolicLink())continue;
    for(const sessionId of sessionIds) {
      requireValue(/^[A-Za-z0-9_-]+$/.test(sessionId),'SESSION_ID_INVALID');
      const target=inside(sessionsRoot,join(project.name,sessionId));
      if(!existsSync(target))continue;
      inside(sessionsRoot,realpathSync(target));
      rmSync(target,{recursive:true});
    }
  }
}
