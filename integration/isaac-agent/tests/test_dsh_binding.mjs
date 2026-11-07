import test from 'node:test';
import assert from 'node:assert/strict';
import { DecisionBinding } from '../dsh-host/isaac-plugin/decision_binding.mjs';
const decision=()=>({pending:true,connected:true,id:'complete-opaque-decision-32chars',context_id:'complete-context-20c',
  remaining_ms:20000,offers:[{id:'complete-offer-one',label:'coin'},{id:'complete-offer-two',label:'route'}]});
test('short choice preserves exact identities and stable idempotency',()=>{
  const b=new DecisionBinding(()=>1000);const view=b.bind(decision());
  assert.equal(view.context_id,undefined);assert.equal(view.offers[0].id,undefined);
  assert.equal(view.offers[1].offer_ref,'A2');
  const args={offer_ref:'a2',reason:'choose route',budget:{coins:0,keys:0,bombs:0,health_half_hearts:0}};
  const plan=b.plan(args);
  assert.equal(plan.decision_id,decision().id);assert.equal(plan.context_id,decision().context_id);
  assert.equal(plan.offer_id,'complete-offer-two');assert.deepEqual(b.plan(args),plan);
});
test('caller changes cannot retarget a previously bound decision',()=>{
  const b=new DecisionBinding(()=>1000);const d=decision();const view=b.bind(d);
  d.id='changed';view.offers[0].id='changed';
  const plan=b.plan({offer_ref:'A1',reason:'coin',decision_id:'injected',context_id:'injected'});
  assert.equal(plan.decision_id,decision().id);assert.equal(plan.offer_id,'complete-offer-one');
});
test('unknown reference and expired observation are rejected before HTTP',()=>{
  let now=1000;const b=new DecisionBinding(()=>now);b.bind(decision());
  assert.throws(()=>b.plan({offer_ref:'A9',reason:'unknown'}),/Unknown/);
  now=21000;assert.throws(()=>b.plan({offer_ref:'A1',reason:'late'}),/expired/);
});
test('new turn or absent decision cannot reuse prior authorization',()=>{
  const b=new DecisionBinding(()=>1000);b.bind(decision());b.reset();
  assert.throws(()=>b.plan({offer_ref:'A1',reason:'old turn'}),/expired/);
  b.bind(decision());b.bind({pending:false,connected:true});
  assert.throws(()=>b.plan({offer_ref:'A1',reason:'old view'}),/expired/);
});
