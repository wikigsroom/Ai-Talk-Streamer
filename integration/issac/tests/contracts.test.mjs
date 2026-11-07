import test from 'node:test';
import assert from 'node:assert/strict';
import {DecisionBinding} from '../../isaac-agent/dsh-host/isaac-plugin/decision_binding.mjs';

const offered=(revision='1',context='room-A-visit-1')=>({pending:true,connected:true,id:'complete-decision-identity',
 context_id:context,remaining_ms:10000,context:{inventory_revision:revision},offers:[{id:'pay-one-key',op:'pickup'}]});

test('wiki evidence and offer cannot survive inventory, visit or ABA changes',()=>{
 const binding=new DecisionBinding(()=>1000);binding.bind(offered());
 assert.equal(binding.isCurrent(offered()),true);
 assert.equal(binding.isCurrent(offered('2')),false);
 assert.equal(binding.isCurrent(offered('1','room-A-visit-3')),false);
 assert.equal(binding.wiki({operation:'item',query:'D6'}).context.inventory_revision,'1');
});

test('slow cancelled turn cannot select a newly offered action',()=>{
 let now=1000;const binding=new DecisionBinding(()=>now);binding.bind(offered());
 now=11000;assert.throws(()=>binding.plan({offer_ref:'A1',reason:'late'}),/expired/);
 binding.reset();assert.throws(()=>binding.wiki({operation:'item',query:'D6'}),/expired/);
});
