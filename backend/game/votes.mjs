import { randomUUID } from 'node:crypto';
import { validate } from './protocol.mjs';
import { ensure, utc } from './errors.mjs';

export class VoteService {
  constructor(manager) { this.manager = manager; this.store = manager.store; }
  get(id) { const value = this.store.object('vote', id); ensure(value, 'GAME_VOTE_NOT_FOUND', 404); return value; }
  page(params = {}) {
    const room = this.manager.roomId(), world = this.manager.state.value.world_session_id;
    return room && world ? this.store.list('vote', { ...params, room, world }) : { items: [], next_cursor: null };
  }
  active() { const row = this.store.get("SELECT value FROM objects WHERE kind='vote' AND json_extract(value,'$.state')='active' LIMIT 1"); return row ? JSON.parse(row.value) : null; }
  create(request) {
    validate('VoteCreate', request);
    const roomId = this.manager.roomId(); ensure(typeof roomId === 'string' && roomId.length, 'GAME_PLATFORM_ROOM_UNAVAILABLE', 503);
    const scope = 'vote-create:' + roomId, replay = this.store.replay(scope, request); if (replay) return { value: replay, duplicate: true };
    this.manager.checkContext(request); ensure(!this.active(), 'GAME_VOTE_ACTIVE');
    ensure(new Set(request.options.map(o => o.option_id)).size === request.options.length, 'GAME_VOTE_OPTIONS_NOT_UNIQUE', 400);
    const state = this.manager.state.requireFresh();
    const value = { vote_id: 'vote-' + randomUUID(), room_id: roomId, world_id: state.world_id,
      world_session_id: state.world_session_id, revision: 1, tally_version: 0, title: request.title,
      options: request.options.map(o => ({ ...o, votes: 0 })), state: 'active', created_at: utc(this.manager.wall()),
      expires_at: utc(this.manager.wall() + request.duration_seconds * 1000), winning_option_id: null,
      tied: false, suggestion_id: null, task_id: null, reason: null };
    validate('Vote', value); this.store.transaction(() => this.store.remember(scope, request, 'vote', value));
    this.manager.publish('vote', value); return { value, duplicate: false };
  }
  cast(event) {
    const vote = this.active(); if (!vote || event.hidden || event.test || event.type !== 'comment') return false;
    if (this.manager.wall() >= Date.parse(vote.expires_at)) { this.finish(vote); return false; }
    const now = this.manager.wall();
    if (vote.room_id !== this.manager.roomId() || event.platform !== 'bilibili' || String(event.room_id) !== vote.room_id ||
        typeof event.user_key !== 'string' || !event.user_key.length || event.user_key.length > 300 ||
        typeof event.event_key !== 'string' || !event.event_key.length || event.event_key.length > 240 ||
        typeof event.text !== 'string' || event.text.length > 1500 || !Number.isFinite(event.occurred_at) || !Number.isFinite(event.received_at) ||
        event.occurred_at < Date.parse(vote.created_at) || event.occurred_at >= Date.parse(vote.expires_at) ||
        now - event.occurred_at > 30000 || event.occurred_at > now + 2000 || now - event.received_at > 30000 || event.received_at > now + 2000) return false;
    // An option ID is an exact, bounded command. Ordinary chat is never parsed
    // as a model instruction or counted using a nickname as an identity.
    const match = String(event.text).trim().match(/^(?:投票\s+|#)([A-Za-z0-9][A-Za-z0-9_.:-]{0,127})$/u);
    if (!match) return false;
    const option = vote.options.find(o => o.option_id === match[1]); if (!option) return false;
    const changed = this.store.transaction(() => {
      const inserted = this.store.run('INSERT OR IGNORE INTO vote_ballots VALUES(?,?,?,?)', vote.vote_id, event.user_key, event.event_key, option.option_id);
      if (!inserted.changes) return false;
      option.votes++; vote.tally_version++; this.store.put('vote', vote); return true;
    });
    if (changed) this.manager.publish('vote', vote); return changed;
  }
  withdrawSources(ids) {
    if (!ids.length) return 0;
    const marks = ids.map(() => '?').join(','), ballots = this.store.all(`SELECT * FROM vote_ballots WHERE event_id IN (${marks})`, ...ids);
    const votes = new Map();
    this.store.transaction(() => {
      for (const ballot of ballots) {
        const vote = votes.get(ballot.vote_id) || this.get(ballot.vote_id);
        this.store.run('DELETE FROM vote_ballots WHERE event_id=?', ballot.event_id);
        votes.set(ballot.vote_id, vote);
      }
      for (const vote of votes.values()) {
        const tally = new Map(this.store.all('SELECT option_id,COUNT(*) total FROM vote_ballots WHERE vote_id=? GROUP BY option_id', vote.vote_id).map(row => [row.option_id, row.total]));
        for (const option of vote.options) option.votes = tally.get(option.option_id) || 0;
        vote.tally_version++;
        // A closed result cannot silently choose a different goal after approval.
        // Preserve any task/effect link, invalidate further promotion/dispatch.
        if (vote.state === 'closed') Object.assign(vote, { state: 'cancelled', winning_option_id: null, tied: false, revision: vote.revision + 1, reason: 'PLATFORM_SOURCE_REMOVED' });
        this.store.put('vote', vote);
      }
    });
    for (const vote of votes.values()) {
      if (vote.state === 'cancelled' && vote.suggestion_id) this.manager.suggestions.withdraw(this.manager.suggestions.get(vote.suggestion_id));
      this.manager.publish('vote', vote);
    }
    return ballots.length;
  }
  reconcileSources() {
    const ballots = this.store.all('SELECT vote_id,user_key,event_id FROM vote_ballots');
    const messages = this.manager.audienceSources.messages(ballots.map(row => row.event_id)), votes = new Map(), removed = [];
    for (const ballot of ballots) {
      const vote = votes.get(ballot.vote_id) || this.get(ballot.vote_id); votes.set(ballot.vote_id, vote);
      const message = messages.get(ballot.event_id);
      if (!this.manager.audienceSources.visible(message, vote.room_id) || message.user_key !== ballot.user_key) removed.push(ballot.event_id);
    }
    // Bound SQL parameter count independently of the number of retained ballots.
    for (let offset = 0; offset < removed.length; offset += 200) this.withdrawSources(removed.slice(offset, offset + 200));
    return removed.length;
  }
  promote(id, request) {
    validate('VoteSuggestionRequest', request); this.manager.requireEnabled();
    const scope = 'vote-suggestion:' + id, replay = this.store.replay(scope, request);
    if (replay) return { value: replay, duplicate: true };
    this.manager.checkContext(request);
    const vote = this.get(id);
    ensure(vote.revision === request.expected_revision, 'GAME_VOTE_CONFLICT');
    ensure(vote.room_id === this.manager.roomId() && vote.world_session_id === request.world_session_id, 'GAME_WORLD_CHANGED');
    ensure(vote.state === 'closed' && vote.winning_option_id, 'GAME_VOTE_WINNER_REQUIRED');
    ensure(this.manager.wall() < Date.parse(vote.expires_at) + 120000, 'GAME_VOTE_RESULT_EXPIRED');
    if (vote.suggestion_id) return { value: this.manager.suggestions.get(vote.suggestion_id), duplicate: true };
    const option = vote.options.find(value => value.option_id === vote.winning_option_id);
    const pending = this.manager.suggestions.pending();
    ensure(pending.length < 64, 'GAME_AUDIENCE_QUEUE_FULL', 429);
    let value;
    this.store.transaction(() => {
      value = this.manager.suggestions.create(option.goal, ['vote:' + vote.vote_id], { publish: false,
        origin: { kind: 'vote', platform: 'bilibili', room_id: vote.room_id, vote_id: vote.vote_id } });
      this.store.remember(scope, request, 'suggestion', value);
      this.store.put('vote', { ...vote, revision: vote.revision + 1, suggestion_id: value.suggestion_id });
    });
    this.manager.publish('suggestion', value); this.manager.publish('vote', this.get(id)); return { value, duplicate: false };
  }
  finish(vote) {
    const maximum = Math.max(...vote.options.map(o => o.votes));
    const winners = vote.options.filter(o => o.votes === maximum);
    vote.state = 'closed'; vote.revision++; vote.tied = winners.length > 1;
    vote.winning_option_id = vote.tied ? null : winners[0].option_id;
    vote.reason = vote.tied ? 'TIED_OPERATOR_DECISION_REQUIRED' : null;
    this.store.put('vote', vote); this.manager.publish('vote', vote); return vote;
  }
  close(id, request) {
    validate('VoteClose', request);
    const scope = 'vote-close:' + id, replay = this.store.replay(scope, request); if (replay) return replay;
    let vote = this.get(id); ensure(vote.revision === request.expected_revision, 'GAME_VOTE_CONFLICT');
    ensure(vote.state === 'active' || (vote.state === 'closed' && vote.tied && !vote.winning_option_id), 'GAME_VOTE_CLOSED');
    if (request.selected_option_id) {
      const maximum = Math.max(...vote.options.map(o => o.votes));
      const winners = vote.options.filter(o => o.votes === maximum);
      ensure(winners.length > 1 && winners.some(o => o.option_id === request.selected_option_id), 'GAME_VOTE_INVALID_TIE_SELECTION', 400);
    }
    this.store.transaction(() => {
      if (request.action === 'cancel') Object.assign(vote, { state: 'cancelled', tied: false, winning_option_id: null,
        suggestion_id: null, task_id: null, revision: vote.revision + 1 });
      else {
        if (vote.state === 'active') {
          const maximum = Math.max(...vote.options.map(o => o.votes));
          const winners = vote.options.filter(o => o.votes === maximum);
          Object.assign(vote, { state: 'closed', tied: winners.length > 1,
            winning_option_id: winners.length === 1 ? winners[0].option_id : null });
        }
        vote.revision++; if (request.selected_option_id) vote.winning_option_id = request.selected_option_id;
      }
      vote.reason = request.reason; this.store.remember(scope, request, 'vote', vote);
    });
    this.manager.publish('vote', vote); return vote;
  }
  tick() {
    const vote = this.active();
    if (vote && (this.manager.wall() >= Date.parse(vote.expires_at) || vote.world_session_id !== this.manager.state.value.world_session_id || vote.room_id !== this.manager.roomId())) {
      if (vote.world_session_id !== this.manager.state.value.world_session_id || vote.room_id !== this.manager.roomId()) {
        Object.assign(vote, { state: 'cancelled', revision: vote.revision + 1, reason: vote.room_id !== this.manager.roomId() ? 'ROOM_CHANGED' : 'WORLD_CHANGED' });
        this.store.put('vote', vote); this.manager.publish('vote', vote);
      } else this.finish(vote);
    }
  }
}
