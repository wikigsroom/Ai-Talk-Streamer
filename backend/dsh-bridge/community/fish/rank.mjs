// Derived from dsh-fish-memory by Yuuyuko-uu. See the full adjacent LICENSE.
// Adaptation: score only evidence-validated, partition-filtered MemoryService rows.
// No additional store, extraction, writes, automatic forgetting or identity editing.
import { queryTerms } from '../soul/memory-recall.mjs';
export function fishScore(row,query,now) {
  const text=String(row.content).normalize('NFKC').toLowerCase();
  const terms=queryTerms(query),hits=terms.filter(term=>text.includes(term));
  const C=hits.length/(hits.length+1);
  const stable=/^(preference|profile|identity)\./.test(row.fact_key);
  const at=Date.parse(row.updated_at),days=Number.isFinite(at)?Math.max(0,now-at)/86400000:0;
  const I=row.pinned?1:.5,H=30*(1+2*I);
  const A=stable?1:Math.pow(2,-days/H),E=0;
  const P=C*(.35+.35*A+.15*I+.15*E);
  return {score:(row.pinned?1000:0)+P,relevance:C,activation:A,stable};
}
