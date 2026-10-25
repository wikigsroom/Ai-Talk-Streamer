import { canonical, digest } from '../dsh-bridge/channel.mjs';
import { requireValue } from '../dsh-bridge/state.mjs';

const STATES = new Set(['active','proposed','conflicted','superseded','retracted','archived','deleted']);

// A continuation is valid only for the same filters and unchanged canonical
// memory revision. Retrying a stale page cannot silently skip or repeat facts.
export function memoryPage(db, state, parameters) {
  const limit = Number(parameters.get('limit') || 50);
  requireValue(Number.isSafeInteger(limit) && limit >= 1 && limit <= 200, 'MEMORY_PAGE_LIMIT', 400);
  const filters = Object.fromEntries(['subject_key','state','fact_key'].map(key => [key, parameters.get(key) || null]));
  requireValue(Object.values(filters).every(value => value === null || value.length <= 160) && (!filters.state || STATES.has(filters.state)), 'MEMORY_FILTER_INVALID', 400);
  const scope = digest({ character_room: state.characterRoom, filters, limit });
  const revision = state.room().memory_revision;
  let cursor;
  if (parameters.has('cursor')) {
    try {
      const raw = parameters.get('cursor');
      requireValue(raw.length <= 1200 && /^[A-Za-z0-9_-]+$/.test(raw), 'MEMORY_CURSOR_INVALID', 400);
      cursor = JSON.parse(Buffer.from(raw, 'base64url').toString('utf8'));
    } catch { requireValue(false, 'MEMORY_CURSOR_INVALID', 400); }
    requireValue(cursor?.scope === scope && typeof cursor.updated_at === 'string' && cursor.updated_at.length <= 40 && typeof cursor.memory_id === 'string' && cursor.memory_id.length <= 120, 'MEMORY_CURSOR_INVALID', 400);
    requireValue(cursor.revision === revision, 'MEMORY_PAGE_CHANGED');
  }
  const where = ['character_id=?','room_id=?'], args = [...state.characterRoom];
  for (const [key, value] of Object.entries(filters)) if (value !== null) { where.push(key + '=?'); args.push(value); }
  if (cursor) { where.push('(updated_at<? OR (updated_at=? AND memory_id<?))'); args.push(cursor.updated_at,cursor.updated_at,cursor.memory_id); }
  const rows = db.all('SELECT * FROM memory_entries WHERE ' + where.join(' AND ') + ' ORDER BY updated_at DESC,memory_id DESC LIMIT ?', ...args,limit + 1);
  const entries = rows.slice(0,limit), last = entries.at(-1);
  const next = rows.length > limit ? Buffer.from(canonical({scope,revision,updated_at:last.updated_at,memory_id:last.memory_id})).toString('base64url') : null;
  return { entries, revision, next_cursor: next, limit, filters };
}
