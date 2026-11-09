"""Durable, causal game facts for narration, separate from viewer memory."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from .common import AdmissionError, canonical, digest, inside


class GameEvents:
    def __init__(self, root, *, clock=time.time):
        self.clock = clock
        self.path = inside(root, 'state/issac-stream/game-events.sqlite3')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS events(
            seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,
            run_id TEXT NOT NULL,room_id TEXT NOT NULL,expires REAL NOT NULL,
            priority INTEGER NOT NULL,body TEXT NOT NULL,
            delivery TEXT NOT NULL DEFAULT 'pending',nonce TEXT,request_id TEXT);
          CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS event_delivery ON events(delivery,priority,seq);
        ''')
        self.previous = None
        self.source_instance = None
        self.current_run = None
        self.current_room = None
        self.last_metadata_at = 0
        # Interrupted speech is unknown. It must never be replayed automatically.
        self.db.execute("UPDATE events SET delivery='interrupted_unknown' WHERE delivery IN ('reserved','accepted')")
        self.db.commit()

    @staticmethod
    def identities(snapshot):
        identity = snapshot.get('identity') or {}
        if any(identity.get(k) is None for k in ('controller','seed','restart','bridge','room','stage')):
            raise AdmissionError('COMPLETE_NATIVE_EVENT_IDENTITY_REQUIRED')
        run = digest({k: identity[k] for k in ('controller','seed','restart','bridge')})
        return run, digest({k: identity.get(k) for k in ('room','stage','stage_type','dimension','visit')}), identity

    def emit(self, snapshot, kind, facts, *, priority=50, ttl=10, proof=None):
        run, room, identity = self.identities(snapshot)
        body = {'event_id': digest([run, room, snapshot.get('frame'), kind, facts, proof]),
                'run_id': run, 'room_id': room, 'bridge_instance': identity['bridge'],
                'observed_at': self.clock(), 'expires_at': self.clock()+ttl,
                'type': kind, 'facts': deepcopy(facts), 'source': 'verified_native_game_state',
                'confidence': 'observed', 'frame': snapshot.get('frame'),
                'execution_receipt': deepcopy(proof), 'memory_scope': 'ephemeral_game_not_viewer'}
        with self.lock:
            nested = self.db.in_transaction
            self.db.execute('INSERT OR IGNORE INTO events(id,run_id,room_id,expires,priority,body) VALUES(?,?,?,?,?,?)',
                            (body['event_id'], run, room, body['expires_at'], priority, canonical(body)))
            if not nested:
                self.db.commit()
        return body

    def ingest(self, snapshot, strategy_events=()):
        run, room, identity = self.identities(snapshot)
        with self.lock, self.db:
            previous = self.previous
            self.current_run, self.current_room = run, room
            self.db.execute("UPDATE events SET delivery='expired' WHERE delivery='pending' AND (expires<? OR run_id<>? OR room_id<>?)",
                            (self.clock(), run, room))
            if previous and self.identities(previous)[0] == run:
                old_room = previous.get('room', {})
                new_room = snapshot.get('room', {})
                if room != self.identities(previous)[1]:
                    self.emit(snapshot, 'room_entered', {'room_type': new_room.get('type'),
                              'room_clear': new_room.get('clear')}, ttl=15)
                elif new_room.get('clear') and not old_room.get('clear'):
                    self.emit(snapshot, 'room_cleared', {'room_type': new_room.get('type')}, priority=40, ttl=15)
                if new_room.get('dead') and not old_room.get('dead'):
                    self.emit(snapshot, 'player_died', {'dead': True}, priority=5, ttl=20)
                if new_room.get('paused') != old_room.get('paused'):
                    self.emit(snapshot, 'pause_changed', {'paused': new_room.get('paused'),
                              'pause_ack': new_room.get('pause_ack')}, ttl=5)
                old_hp, new_hp = previous.get('health', {}), snapshot.get('health', {})
                old_total = sum(old_hp.get(k) or 0 for k in ('red_hearts','soul_hearts'))
                new_total = sum(new_hp.get(k) or 0 for k in ('red_hearts','soul_hearts'))
                if new_total != old_total and new_hp.get('exact'):
                    self.emit(snapshot, 'health_changed', {'before_half_hearts': old_total,
                              'after_half_hearts': new_total, 'cause': 'unconfirmed'},
                              priority=15 if new_total <= 2 else 50, ttl=12)
                if (snapshot.get('inventory_known') and previous.get('inventory_known')
                        and snapshot.get('inventory_revision') != previous.get('inventory_revision')):
                    before = {x['id']: x.get('count',1) for x in previous.get('inventory',[])}
                    gained = [x for x in snapshot.get('inventory',[]) if x.get('count',1) > before.get(x['id'],0)]
                    self.emit(snapshot, 'inventory_changed', {'gained': gained,
                              'current_revision': snapshot.get('inventory_revision')}, priority=20, ttl=15)
                old_boss = bool(previous.get('bosses'))
                if snapshot.get('bosses') and not old_boss:
                    self.emit(snapshot, 'boss_encountered', {'bosses':[{'type':x.get('type'), 'variant':x.get('variant')}
                              for x in snapshot['bosses']]}, priority=25, ttl=12)
            elif (snapshot.get('frame') is not None and 0 <= snapshot['frame'] <= 120
                  and not snapshot.get('room',{}).get('dead')):
                self.emit(snapshot, 'run_started', {'seed':identity['seed'], 'goal':'已观察的合法路线'}, priority=30)
            # A receipt is narrated with its original status; accepted is never
            # upgraded to success, and missing causal identity is discarded.
            for row in strategy_events:
                if row.get('identity') != identity:
                    continue
                receipt = row.get('receipt')
                if not isinstance(receipt, dict) or receipt.get('status') not in {
                        'accepted','observed','succeeded','failed','expired','rejected','cancelled','indeterminate'}:
                    continue
                self.emit(snapshot, 'plan_'+receipt['status'],
                          {'status':receipt['status'], 'reason':receipt.get('reason'),
                           'effect':receipt.get('effect'), 'cost':receipt.get('cost')},
                          priority=20 if receipt['status']=='succeeded' else 60, ttl=12, proof=receipt)
            self.previous = deepcopy(snapshot)
            # Actual changed facts above still commit synchronously. The
            # diagnostic frame watermark needs one durable update per second,
            # not a FULL fsync in every native state/response round trip.
            now=self.clock()
            if not previous or self.identities(previous)[1]!=room or now-self.last_metadata_at>=1:
                self.db.execute('INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)',
                                ('last_observation',canonical({'run':run,'room':room,'identity':identity,'frame':snapshot.get('frame')})))
                self.last_metadata_at=now

    def reserve(self):
        with self.lock, self.db:
            self.db.execute("UPDATE events SET delivery='expired' WHERE delivery='pending' AND expires<?", (self.clock(),))
            if self.db.execute("SELECT 1 FROM events WHERE delivery IN ('reserved','accepted')").fetchone():
                return None
            row = self.db.execute("SELECT seq,body FROM events WHERE delivery='pending' AND run_id=? AND room_id=? ORDER BY priority,seq LIMIT 1",
                                  (self.current_run,self.current_room)).fetchone()
            if not row:
                return None
            nonce = uuid.uuid4().hex
            self.db.execute("UPDATE events SET delivery='reserved',nonce=? WHERE seq=?",(nonce,row[0]))
            return {'nonce':nonce,'event':json.loads(row[1])}

    def accepted(self, nonce, request_id):
        if not isinstance(request_id, str) or not request_id or len(request_id)>160:
            raise AdmissionError('ACTUAL_SPEECH_REQUEST_ID_REQUIRED')
        with self.lock, self.db:
            row=self.db.execute("SELECT seq FROM events WHERE nonce=? AND delivery='reserved'",(nonce,)).fetchone()
            if not row:
                raise AdmissionError('GAME_EVENT_DELIVERY_NOT_RESERVED')
            self.db.execute("UPDATE events SET delivery='accepted',request_id=? WHERE seq=?",(request_id,row[0]))

    def playback_receipt(self, request_id, receipt):
        if (receipt.get('authority') != 'official_source' or receipt.get('request_id') != request_id
                or receipt.get('actual_pcm_samples',0)<=0 or receipt.get('completed') is not True):
            raise AdmissionError('ACTUAL_OFFICIAL_PLAYBACK_RECEIPT_REQUIRED')
        with self.lock, self.db:
            self.db.execute("UPDATE events SET delivery='spoken' WHERE request_id=? AND delivery='accepted'",(request_id,))

    def abandon(self, nonce):
        with self.lock, self.db:
            self.db.execute("UPDATE events SET delivery='cancelled_not_replayed' WHERE nonce=? AND delivery IN ('reserved','accepted')",(nonce,))

    def read(self, after=0, limit=80):
        if type(after) is not int or type(limit) is not int or after<0 or not 1<=limit<=200:
            raise AdmissionError('EVENT_CURSOR_OR_LIMIT_INVALID')
        with self.lock:
            rows=self.db.execute('SELECT seq,body,delivery FROM events WHERE seq>? ORDER BY seq LIMIT ?', (after,limit)).fetchall()
            return {'events':[{'seq':x[0],**json.loads(x[1]),'delivery':x[2]} for x in rows],
                    'cursor':rows[-1][0] if rows else after}

    def close(self):
        with self.lock:
            self.db.close()
