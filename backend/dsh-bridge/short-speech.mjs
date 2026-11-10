// Applied only to the Isaac continuous-persona policy. Count Unicode characters,
// including punctuation, before sending anything to the existing TTS pipeline.
export const speechKey = value => String(value || '').normalize('NFKC').toLowerCase().replace(/[\p{P}\p{S}\s]/gu, '');
export function shortSpeech(value, limit = 15) {
  const chars = Array.from(String(value || '').trim());
  if (chars.length <= limit) return chars.join('');
  const head = chars.slice(0, limit).join('');
  const stop = Math.max(head.lastIndexOf('。'), head.lastIndexOf('！'), head.lastIndexOf('？'));
  return stop >= limit / 2 ? head.slice(0, stop + 1) : head.replace(/[，、；：]$/u, '');
}
function grams(text) { return new Set(Array.from(text).slice(1).map((_, i) => Array.from(text).slice(i, i + 2).join(''))); }
export function speechSimilarity(a, b) {
  a = speechKey(a); b = speechKey(b);
  if (!a || !b) return 0;
  if (a === b) return 1;
  if (Math.min(a.length, b.length) >= 5 && (a.includes(b) || b.includes(a))) return .95;
  const x = grams(a), y = grams(b);
  return x.size && y.size ? 2 * [...x].filter(v => y.has(v)).length / (x.size + y.size) : 0;
}
export class SpokenHistory {
  constructor() { this.played = []; this.reserved = new Map(); }
  context() { return { last_spoken: this.played.at(-1)?.text || null, recent_spoken: this.played.slice(-8),
    pending_speech: [...this.reserved.values()], rule: '先回想上一句实际口播；换观察角度，避免重复及换词复读。每次最多15字，含标点；没有新内容可保持安静。' }; }
  reserve(id, text) {
    const prior = [...this.played.slice(-8).map(v => v.text), ...this.reserved.values()];
    if (prior.some(v => speechSimilarity(v, text) >= .78)) return false;
    this.reserved.set(id, text); return true;
  }
  release(id) { this.reserved.delete(id); }
  completed(id, text, at = Date.now()) {
    this.release(id);
    if (!text) return;
    this.played.push({ text, completed_at: at });
    if (this.played.length > 16) this.played.shift();
  }
}
