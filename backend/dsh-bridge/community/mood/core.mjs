// Derived from dsh-feiyu-mood by Yuuyuko-uu; full license in this directory.
// Adaptation: supplied clock, game evidence instead of private-partner judgment,
// existing GameStore persistence, bounded timeline, no updater/widget/extra LLM.
export const DIMS=['happy','calm','sweet','heartache','worry','sad','jealous'];
const clamp=(n,a,b)=>Math.min(b,Math.max(a,n));
export function createMood(now) { return {mood:70,dims:Object.fromEntries(DIMS.map(k=>[k,0])),lastDecayAt:now,timeline:[]}; }
export function decay(s,now,halfHours=3) {
  const ageMin=Math.max(0,now-s.lastDecayAt)/60000;
  if(ageMin<1)return s;
  const half=clamp(Number(halfHours)||12,1,168)*60;
  const km=1-Math.exp(-(Math.LN2*ageMin)/half);
  s.mood=s.mood+(70-s.mood)*km;
  const ke=1-Math.exp(-(Math.LN2*ageMin)/90);
  for(const k of DIMS)s.dims[k]=Math.max(0,s.dims[k]*(1-ke));
  s.lastDecayAt=now;return s;
}
export function applyDelta(s,delta,now) {
  const saturated=(s.mood>=85&&delta.moodDelta>0)||(s.mood<=40&&delta.moodDelta<0);
  const factor=saturated ? .5 : 1;
  const step=Math.round(delta.moodDelta*factor/3);
  s.mood=clamp(s.mood+step,0,100);
  for(const k of DIMS)s.dims[k]=clamp(s.dims[k]+(delta.dims[k]||0),0,100);
  s.lastReason=delta.reason;s.lastConfidence=delta.confidence;s.updatedAt=s.lastDecayAt=now;
  s.timeline=[...s.timeline,{at:now,mood:s.mood,delta:step,reason:delta.reason,dims:{...s.dims},source_id:delta.source_id}].slice(-32);
  return s;
}
