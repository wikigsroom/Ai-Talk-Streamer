import { createServer } from 'node:http';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { narrationFixture } from './game-narration-fixture.mjs';
import { sourceRoot } from './game-fixture.mjs';
import { MemoryService, validateExtraction } from '../backend/memory/service.mjs';
import { MemoryAdministration } from '../backend/memory/administration.mjs';
import { PlatformPrivacy } from '../backend/platforms/privacy.mjs';
import { PlatformConfig } from '../backend/platforms/config.mjs';
import { eventPrincipal } from '../backend/platforms/events.mjs';
import { digest } from '../backend/dsh-bridge/channel.mjs';

export async function retentionFixture(t) {
  const f = await narrationFixture(t), projection = new Map();
  const port = { mirrorRevision: 0, requestMemorySnapshot: () => null, setNativeMemoryInjection() {}, setVerifiedMirrorRevision() {},
    inspectProjection: id => projection.get(id), async applyPublicProjection(p) { projection.set(p.memory_id, { memory_revision: p.memory_revision, entry: p.action === 'UPSERT' ? { content: p.content, status: 'active' } : null }); return { accepted: true }; } };
  f.memory = new MemoryService(f.db, f.state, f.bridge.policy, port, { audienceSources: request => f.manager.narration.memorySources(request) });
  Object.assign(f.bridge, { memory: f.memory, root: f.folder });
  f.privacy = new PlatformPrivacy(f.bridge); f.bridge.privacy = f.privacy;
  f.admin = new MemoryAdministration(f.folder, f.db, f.state, f.memory, f.bridge.host, async () => {}, {
    planProjection: input => f.privacy.prepare(input), applyProjection: plan => f.privacy.apply(plan), onPrivacyState: () => f.room.emit('snapshot', f.room.snapshot()),
  });
  f.bridge.administration = f.admin;
  f.platforms.config = new PlatformConfig(f.folder);
  f.platforms.config.value.platforms.bilibili.room_id = '100';
  Object.assign(f.platforms.config.value.interaction, { minimum_interval_ms: 0, viewer_cooldown_ms: 0, max_pending: 1000 });
  f.add = async (uid = 'retention-private-A', text = '我喜欢茶。') => {
    const { key } = await f.comment(text, { user_id: uid, nickname: '同名观众' });
    const row = f.platforms.store.get('SELECT * FROM events WHERE event_key=?', key);
    return { key, row, subject: eventPrincipal(row).viewer_id };
  };
  f.seed = (subject, source) => {
    const candidate = validateExtraction({ schema_version: 1, summary: '', open_questions: [], candidate_facts: [{ fact_key: 'preference.drink', value: 'tea', polarity: 'positive', evidence_kind: 'viewer_statement', source_refs: [{ event_id: source.event_id, quote: source.text }], validity: 'persistent_candidate' }] }, [source], subject)[0];
    return f.db.tx(() => f.memory.mergeInTransaction(candidate, 'retention-fixture', 0));
  };
  f.remove = (source, extra = {}) => f.admin.delete(f.bridge.auth.resolve(), { operation_id: 'retention-delete-' + source.key.slice(0, 20), subject_key: source.subject, ...extra });
  f.age = (keys, days = 8) => {
    const old = f.manager.wall() - days * 86400000;
    for (const key of keys) {
      f.platforms.store.run("UPDATE events SET received_at=?,status='OBSERVED' WHERE event_key=?", old, key);
      f.room.store.run('UPDATE messages SET received_at=? WHERE id=?', old, key);
    }
  };
  let sequence = 0;
  f.fillRoom = (count, days = 0) => f.room.store.transaction(() => {
    for (let i = 0; i < count; i++) {
      const key = digest(['retention-fixture', ++sequence]), at = f.manager.wall() - days * 86400000;
      const value = f.room.publicMessage({ event_key: key, platform: 'operator', text: '历史维护测试', occurred_at: at });
      f.room.store.run('INSERT INTO messages(id,event_key,received_at,value) VALUES (?,?,?,?)', key, key, at, JSON.stringify(value));
    }
  });
  f.serve = async () => {
    const files = new Set(['platforms.html', 'platforms.js', 'platforms.css']);
    const server = createServer((req, res) => {
      const url = new URL(req.url, 'http://localhost');
      const send = (value, status = 200) => { res.writeHead(status, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(value)); };
      if (url.pathname.startsWith('/api/dsh/platforms')) {
        void f.platforms.handle(req, res, url, send).catch(error => send({ error: error.code || 'PLATFORM_INTERNAL_ERROR' }, error.status || 500));
      } else if (files.has(url.pathname.slice(1))) {
        const name = url.pathname.slice(1); res.writeHead(200, { 'Content-Type': name.endsWith('.html') ? 'text/html; charset=utf-8' : name.endsWith('.css') ? 'text/css' : 'text/javascript' });
        res.end(readFileSync(join(sourceRoot, 'web', name)));
      } else { res.writeHead(204); res.end(); }
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    t.after(() => new Promise(resolve => { server.closeAllConnections(); server.close(resolve); }));
    f.maintenanceBase = 'http://127.0.0.1:' + server.address().port;
    f.maintenance = async (body, path = '/retention') => {
      const response = await fetch(f.maintenanceBase + '/api/dsh/platforms' + path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      return { status: response.status, value: await response.json() };
    };
    return f.maintenanceBase;
  };
  return f;
}
