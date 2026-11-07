// Keep opaque identities out of model-generated text. The selected reference
// binds to the exact decision observed earlier, never a newly fetched context.
export class DecisionBinding {
  constructor(clock=Date.now) { this.clock=clock; this.reset(); }
  reset() { this.current=null; }
  bind(decision) {
    this.reset();
    const view=structuredClone(decision);
    if(!decision.pending||!decision.connected)return view;
    if(!decision.id||!decision.context_id||!Array.isArray(decision.offers))throw new Error('Incomplete local decision');
    const refs=new Map();
    view.offers=view.offers.map((offer,index)=>{
      const ref='A'+(index+1);refs.set(ref,offer.id);
      const result={...offer,offer_ref:ref};delete result.id;return result;
    });
    this.current={id:decision.id,context:decision.context_id,refs,inventory:decision.context?.inventory_revision??null,
      deadline:this.clock()+Math.max(0,Number(decision.remaining_ms)||0)};
    delete view.context_id;
    return view;
  }
  wiki(query) {
    const current=this.current;
    if(!current||this.clock()>=current.deadline)throw Error('Observed decision expired; query again');
    return {query,context:{decision_id:current.id,context_id:current.context,inventory_revision:current.inventory}};
  }
  isCurrent(decision) {
    return !!(this.current&&decision.pending&&decision.connected&&decision.id===this.current.id&&
      decision.context_id===this.current.context&&(decision.context?.inventory_revision??null)===this.current.inventory);
  }
  plan(args) {
    const current=this.current;
    if(!current||this.clock()>=current.deadline)throw new Error('Observed decision expired; query again');
    const ref=String(args.offer_ref??'').trim().toUpperCase();
    if(!current.refs.has(ref))throw new Error('Unknown offer_ref for observed decision');
    if(typeof args.reason!=='string'||!args.reason.trim())throw new Error('Decision reason required');
    return {plan_id:current.id+'-dsh',decision_id:current.id,context_id:current.context,
      offer_id:current.refs.get(ref),budget:args.budget,reason:args.reason,
      ...(args.execution_seconds===undefined?{}:{execution_seconds:args.execution_seconds})};
  }
}
