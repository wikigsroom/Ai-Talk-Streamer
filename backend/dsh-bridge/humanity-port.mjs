// Installed beside Humanity 0.1.17's lib/index.js by the reviewed patch installer.
// These relative imports deliberately resolve within that fixed upstream package.
import { createHash } from 'node:crypto';
import { createMemoryEntry, buildDedupeKey } from './memory/model.js';
import { renderMemoryBlock } from './memory/render.js';
import { MEMORY_GUIDANCE } from './memory/inject.js';

const hash = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
const canonical = value => Array.isArray(value) ? '['+value.map(canonical).join(',')+']' : value!==null&&typeof value==='object' ? '{'+Object.keys(value).sort().map(key=>JSON.stringify(key)+':'+canonical(value[key])).join(',')+'}' : JSON.stringify(value);
const documentHash = value => createHash('sha256').update(canonical(value)).digest('hex');
const projectKey = 'stream:project-persona';
const mappingKey = memoryId => 'stream:projection:' + memoryId;

export function createStreamConnector(ctx, state) {
  let injectionEnabled = false;
  let mirrorRevision = 0;
  let serial = Promise.resolve();
  const requireStore = () => {
    if (!state.store || !state.persona?.section?.attached) throw new Error('HUMANITY_NOT_READY');
    return state.store;
  };
  const enqueue = action => {
    const next = serial.then(action);
    serial = next.catch(() => {});
    return next;
  };
  const port = {
    connectorVersion: 'stream-humanity-v1',
    get injectionEnabled() { return injectionEnabled; },
    get mirrorRevision() { return mirrorRevision; },
    probe() {
      return {
        connector_version: port.connectorVersion,
        store_ready: !!state.store,
        persona_ready: !!state.persona?.section?.attached,
        injection_enabled: injectionEnabled,
        mirror_revision: mirrorRevision,
        live_guard: process.env.STREAM_LIVE_MODE === '1',
      };
    },
    readPersona() {
      const store = requireStore();
      return { document: state.persona.section.read(), publication: store.documents.read(projectKey)?.value ?? null };
    },
    publishPersona(input) {
      return enqueue(async () => {
        const store = requireStore();
        if (input.character_id !== 'female-a' || input.room_id !== 'room-main' || !input.operation_id || !input.persona_version || documentHash(input.document) !== input.approved_hash) throw new Error('PERSONA_PUBLICATION_INVALID');
        const current = store.documents.read(projectKey)?.value;
        if (current?.operation_id === input.operation_id) {
          if (current.approved_hash !== input.approved_hash) {
            if(documentHash(state.persona.section.read())!==input.approved_hash)throw new Error('PERSONA_OPERATION_CONFLICT');
            const normalized={...current,approved_hash:input.approved_hash,hash_format:'canonical-json-sha256'};
            await store.documents.write(projectKey,normalized);return normalized;
          }
          return current;
        }
        if (input.expected_version !== (current?.persona_version ?? null)) throw new Error('PERSONA_VERSION_CONFLICT');
        await state.persona.section.write(input.document, 'user', input.validation_options);
        const receipt = {
          operation_id: input.operation_id, persona_version: input.persona_version,
          approved_hash: input.approved_hash, character_id: input.character_id,
          room_id: input.room_id, published_at: new Date().toISOString(),
        };
        await store.documents.write(projectKey, receipt);
        return receipt;
      });
    },
    setNativeMemoryInjection({ enabled, expectedMirrorRevision }) {
      if (!Number.isSafeInteger(expectedMirrorRevision) || expectedMirrorRevision < 0) throw new Error('PROJECTION_REVISION_INVALID');
      if (enabled && expectedMirrorRevision !== mirrorRevision) throw new Error('PROJECTION_NOT_CAUGHT_UP');
      injectionEnabled = enabled;
    },
    setVerifiedMirrorRevision(revision) {
      if (!Number.isSafeInteger(revision) || revision < mirrorRevision) throw new Error('PROJECTION_REVISION_REGRESSION');
      mirrorRevision = revision;
    },
    inspectProjection(memoryId) {
      const store = requireStore(), mapping = store.documents.read(mappingKey(memoryId))?.value;
      if (!mapping) return null;
      return { ...mapping, entry: mapping.dedupe_key ? store.memory.get(mapping.dedupe_key) ?? null : null };
    },
    requestMemorySnapshot(references=[]) {
      const entries=[];
      if(injectionEnabled)for(const reference of references.slice(0,3)) {
        const projection=port.inspectProjection(reference.memory_id);
        if(projection?.memory_revision===reference.revision&&projection.entry?.status==='active')entries.push(projection.entry);
      }
      const block=renderMemoryBlock(entries,300,new Date().toISOString());
      return {text:[MEMORY_GUIDANCE,block].filter(Boolean).join('\n\n'),memory_ids:entries.filter(entry=>block.includes(entry.content)).map(entry=>entry.id.replace(/^stream:/,'')),mirror_revision:mirrorRevision};
    },
    applyPublicProjection(input) {
      return enqueue(async () => {
        const store = requireStore();
        if (input.visibility !== 'public' || input.subject_key !== 'public' || input.character_id !== 'female-a' || input.room_id !== 'room-main') throw new Error('PROJECTION_PARTITION');
        if (!input.operation_id || !input.memory_id || !Number.isSafeInteger(input.memory_revision) || input.memory_revision < 1 || !['UPSERT', 'ARCHIVE', 'REMOVE'].includes(input.action)) throw new Error('PROJECTION_OPERATION');
        injectionEnabled = false;
        const operationKey = 'stream:operation:' + input.operation_id;
        const inputHash = hash(input);
        const previousOperation = store.documents.read(operationKey)?.value;
        if (previousOperation && previousOperation.input_hash !== inputHash) throw new Error('PROJECTION_OPERATION_CONFLICT');
        if (previousOperation?.state === 'APPLIED') {
          const projection = port.inspectProjection(input.memory_id);
          if (projection?.memory_revision > input.memory_revision) return { ...previousOperation.receipt, superseded: true };
          if (input.action !== 'UPSERT' || projection?.entry?.content === input.content && projection?.entry?.status === 'active') return previousOperation.receipt;
          // A lost/corrupted mirror is repaired from the same durable intent.
        }
        const previous = store.documents.read(mappingKey(input.memory_id))?.value;
        if (previous && previous.memory_revision > input.memory_revision) return { operation_id: input.operation_id, superseded: true };
        // Persist an intent before touching entries; recovery reuses the same ids/key.
        const key = input.action === 'UPSERT' ? buildDedupeKey('long-term', input.content) + '#stream:' + input.memory_id : input.action === 'ARCHIVE' ? previous?.dedupe_key ?? null : null;
        const journal = { state: 'PENDING', input_hash: inputHash, prior_key: previousOperation?.prior_key ?? previous?.dedupe_key ?? null, target_key: key };
        await store.documents.write(operationKey, journal);
        if (journal.prior_key && journal.prior_key !== key) await store.memory.delete(journal.prior_key);
        let entry = null;
        if (input.action === 'UPSERT') {
          entry = createMemoryEntry({
            id: 'stream:' + input.memory_id, scope: 'long-term', content: input.content,
            tags: input.tags ?? [], importance: 3, confidence: 1, sensitive: false,
            pinned: !!input.pinned, origin: 'user-stated', sourceSessionId: input.source_session_id || 'stream-public',
            sourceMessageId: input.source_event_id || '', ownerId: '', status: 'active', confirmedVia: 'workbench',
          });
          entry = { ...entry, dedupeKey: key };
          await store.memory.put(key, entry);
          if (hash(store.memory.get(key)) !== hash(entry)) throw new Error('PROJECTION_WRITE_VERIFICATION');
        } else if (input.action === 'ARCHIVE' && key) {
          const current = store.memory.get(key);
          if (current) {
            entry = { ...current, status: 'archived', archivedAt: new Date().toISOString() };
            await store.memory.put(key, entry);
          }
        }
        const mapping = {
          operation_id: input.operation_id, memory_id: input.memory_id, memory_revision: input.memory_revision,
          dedupe_key: key, entry_id: entry?.id ?? null, content_hash: input.action === 'UPSERT' ? hash(input.content) : null,
          state: input.action === 'UPSERT' ? 'active' : input.action === 'REMOVE' ? 'deleted' : 'archived',
        };
        await store.documents.write(mappingKey(input.memory_id), mapping);
        const receipt = { ...mapping, applied: true };
        await store.documents.write(operationKey, { ...journal, state: 'APPLIED', receipt });
        await state.memory?.refresh();
        return receipt;
      });
    },
    routeWorkbenchIntent() { throw new Error('WORKBENCH_READ_ONLY_USE_STREAM_MANAGEMENT'); },
    async flush() { await serial; },
  };
  return port;
}
