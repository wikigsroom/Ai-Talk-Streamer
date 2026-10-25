import { requireValue } from './state.mjs';

// Read committed metadata, never raw event payloads. The database cursor is the
// durable source; the in-process signal merely wakes connected readers.
export class EventSubscriptions {
  constructor(db, state, auth, { heartbeatMs = 15000, maximum = 24 } = {}) {
    this.db = db; this.state = state; this.auth = auth; this.heartbeatMs = heartbeatMs; this.maximum = maximum; this.clients = new Set();
    this.changed = () => { for (const client of this.clients) client.pump(); };
    db.on('event', this.changed);
  }
  subscribe(req, res, principal, parameters) {
    requireValue(['operator','viewer'].includes(principal.role), 'EVENT_SCOPE', 403);
    requireValue(this.clients.size < this.maximum && [...this.clients].filter(client => client.principalId === principal.principal_id).length < 4, 'EVENT_SUBSCRIPTION_LIMIT', 429);
    const raw = req.headers['last-event-id'] || parameters.get('after') || '0';
    requireValue(typeof raw === 'string' && /^\d{1,16}$/.test(raw) && Number.isSafeInteger(Number(raw)), 'EVENT_CURSOR_INVALID', 400);
    let cursor = Number(raw), blocked = false, closed = false, scheduled = false;
    const maximum = this.db.get('SELECT COALESCE(MAX(event_seq),0) n FROM stream_events').n;
    requireValue(cursor <= maximum, 'EVENT_CURSOR_AHEAD', 400);
    const authorized = () => { try { return !this.db.faulted && this.auth.resolve(req.headers)?.principal_id === principal.principal_id; } catch { return false; } };
    const cleanup = () => { if (closed) return; closed = true; clearInterval(timer); this.clients.delete(client); res.off('drain',drain); res.off('close',cleanup); };
    const write = text => { blocked = !res.write(text); return !blocked; };
    const pump = () => {
      if (closed || blocked) return;
      if (!authorized() || this.db.faulted) { cleanup(); res.end(); return; }
      try {
        const rows = this.db.all('SELECT event_seq,event_type,broadcast_id,request_id,utterance_id,runtime_epoch,generation,received_at FROM stream_events WHERE character_id=? AND room_id=? AND event_seq>? ORDER BY event_seq LIMIT 128', ...this.state.characterRoom,cursor);
        for (const row of rows) {
          cursor = row.event_seq;
          const visible = principal.role === 'operator' || row.event_type.startsWith('broadcast.') || row.event_type === 'runtime.started' ||
            row.request_id && this.db.get('SELECT 1 FROM requests WHERE request_id=? AND principal_id=?',row.request_id,principal.principal_id);
          if (visible && !write('id: ' + cursor + '\nevent: state\ndata: ' + JSON.stringify(row) + '\n\n')) return;
        }
        if (rows.length) write('id: ' + cursor + '\nevent: checkpoint\ndata: {}\n\n');
        if (rows.length === 128 && !blocked && !scheduled) { scheduled = true; setImmediate(() => { scheduled = false; pump(); }); }
      } catch { cleanup(); res.end(); }
    };
    const drain = () => { blocked = false; pump(); };
    const client = { principalId:principal.principal_id, pump, close:() => { cleanup(); res.end(); } };
    const timer = setInterval(() => {
      if (!authorized() || this.db.faulted) { client.close(); return; }
      // A slow peer gets no unbounded heartbeat queue. Drain resumes from SQLite.
      if (!blocked && !closed) { try { write(': heartbeat\n\n'); } catch { client.close(); } }
    },this.heartbeatMs); timer.unref();
    this.clients.add(client); res.on('close',cleanup); res.on('drain',drain);
    res.writeHead(200,{'Content-Type':'text/event-stream; charset=utf-8','Cache-Control':'no-store','X-Accel-Buffering':'no','X-Content-Type-Options':'nosniff'});
    res.flushHeaders(); write('retry: 2000\n\n'); pump();
  }
  close() { this.db.off('event',this.changed); for (const client of [...this.clients]) client.close(); }
}
