'use strict';
class RoomAudioMixer {
  constructor(context, destination, room, { audible = true } = {}) {
    this.context = context; this.room = room; this.audible = audible; this.slots = []; this.error = null; this.ducked = false; this.closed = false;
    this.speech = context.createGain(); this.musicGain = context.createGain(); this.master = context.createGain(); this.limiter = context.createDynamicsCompressor();
    this.limiter.threshold.value = -3; this.limiter.knee.value = 3; this.limiter.ratio.value = 12; this.limiter.attack.value = 0.003; this.limiter.release.value = 0.18;
    this.speech.connect(this.master); this.musicGain.connect(this.master); this.master.connect(this.limiter); this.limiter.connect(destination);
    this.audio = document.createElement('audio'); this.audio.preload = 'metadata'; this.audio.crossOrigin = 'anonymous'; this.audio.hidden = true;
    this.audio.addEventListener('error', () => { this.error = 'BGM_MEDIA_ERROR_' + (this.audio.error?.code || 'UNKNOWN'); this.retryAt = performance.now() + 3000; });
    this.audio.addEventListener('loadedmetadata', () => { this.sync(true); });
    this.audioSource = context.createMediaElementSource(this.audio); this.audioSource.connect(this.musicGain);
    this.changed = () => this.sync(); room.addEventListener('change', this.changed);
    this.timer = setInterval(() => this.tick(), 50); this.sync();
  }
  expectedPosition() {
    const state = this.room.state, music = state?.music, track = state?.tracks.find(t => t.id === music?.track_id); if (!track) return 0;
    let p = music.position + (music.playing ? Math.max(0, (this.room.now() - state.server_time) / 1000) : 0);
    if (music.repeat === 'one') p %= track.duration; return Math.max(0, Math.min(track.duration - 0.02, p));
  }
  sync(force = false) {
    if (this.closed || !this.room.state) return;
    const { settings, music, tracks } = this.room.state, track = tracks.find(t => t.id === music.track_id), t = this.context.currentTime;
    this.master.gain.setTargetAtTime(settings.audio.muted || !this.audible ? 0 : 1, t, 0.025);
    this.speech.gain.setTargetAtTime(settings.audio.speech_volume, t, 0.025);
    if (!this.audible || !track) { this.audio.pause(); return; }
    if (track.id !== this.trackId || (this.audio.error && performance.now() >= (this.retryAt || 0))) { this.trackId = track.id; this.retryAt = performance.now() + 3000; this.audio.src = track.url; this.audio.load(); this.error = null; force = true; }
    this.audio.loop = music.repeat === 'one';
    if (this.audio.readyState >= 1 && (force || music.version !== this.version || performance.now() - (this.lastSync || 0) > 5000)) {
      const expected = this.expectedPosition(); if (Math.abs(this.audio.currentTime - expected) > (force || music.version !== this.version ? 0.08 : 0.75)) try { this.audio.currentTime = expected; } catch { this.error = 'BGM_SEEK_FAILED'; }
      this.lastSync = performance.now();
    }
    this.version = music.version;
    if (music.playing && !settings.audio.muted && this.audio.paused) this.audio.play().then(() => { this.error = null; }).catch(e => { this.error = e.name === 'NotAllowedError' ? 'BGM_AUTOPLAY_BLOCKED' : 'BGM_MEDIA_ERROR_' + (this.audio.error?.code || 'UNKNOWN'); });
    else if (!music.playing || settings.audio.muted) this.audio.pause();
  }
  schedule(source, metadata, at, rate) {
    if (!metadata || source._dshCancelled) return;
    for (const r of metadata.ranges || []) if (r.sample_count > 0) this.slots.push({ start: at + r.packet_offset / rate, end: at + (r.packet_offset + r.sample_count) / rate, sample_start: r.sample_start || 0, total: metadata.valid_sample_count || r.sample_count, rate, request_id: metadata.request_id, source });
    if (this.slots.length > 600) this.slots = this.slots.slice(-600);
  }
  tick() {
    if (this.closed) return; const now = this.context.currentTime, settings = this.room.state?.settings.audio;
    if (this.audible && this.audio.error && this.room.connected && performance.now() >= (this.retryAt || 0)) this.sync(true);
    this.slots = this.slots.filter(s => s.end >= now - 0.05 && !s.source._dshCancelled);
    const slot = this.slots.find(s => s.start <= now + 0.035 && s.end >= now);
    const duck = !!slot && settings?.ducking === true, target = (settings?.music_volume || 0) * (duck ? settings.duck_level : 1);
    if (target !== this.targetGain) { this.musicGain.gain.setTargetAtTime(target, now, ((duck ? settings?.attack_ms : settings?.release_ms) || 150) / 3000); this.targetGain = target; }
    this.ducked = duck;
    const request = slot?.request_id || null;
    this.progress = slot ? Math.max(0, Math.min(1, (slot.sample_start + Math.max(0, now - slot.start) * slot.rate) / slot.total)) : 0;
    const bucket = Math.floor(this.progress * 100);
    if (request !== this.speakingRequest || bucket !== this.progressBucket) { this.speakingRequest = request; this.progressBucket = bucket; window.dispatchEvent(new CustomEvent('room-speech', { detail: { request_id: request, progress: this.progress } })); }
  }
  clear() { this.slots = []; if (this.speakingRequest) { this.speakingRequest = null; window.dispatchEvent(new CustomEvent('room-speech', { detail: { request_id: null } })); } }
  metrics() { return { track_id: this.trackId || null, current_time: this.audio.currentTime || 0, music_playing: !this.audio.paused, music_gain: this.musicGain.gain.value, speech_gain: this.speech.gain.value, ducked: this.ducked, muted: !!this.room.state?.settings.audio.muted, speaking_request_id: this.speakingRequest || null, speech_progress: this.progress || 0, audio_state: this.context.state, config_revision: this.room.state?.revision || 0, error: this.error }; }
  close() { if (this.closed) return; this.closed = true; clearInterval(this.timer); this.clear(); this.room.removeEventListener('change', this.changed); this.audio.pause(); this.audio.removeAttribute('src'); this.audio.load(); this.audioSource.disconnect(); this.speech.disconnect(); this.musicGain.disconnect(); this.master.disconnect(); this.limiter.disconnect(); }
}
window.RoomAudioMixer = RoomAudioMixer;
