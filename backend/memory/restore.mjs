import { DatabaseSync } from 'node:sqlite';
import { copyFileSync, readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { join, resolve, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { StateStore, id, utc } from './store.mjs';
import { MemoryAdministration } from './administration.mjs';
import { MemoryService } from './service.mjs';
import { StreamState, requireValue } from '../dsh-bridge/state.mjs';
import { loadPolicy, inside } from '../dsh-bridge/policy.mjs';
import { canonical, digest } from '../dsh-bridge/channel.mjs';

export function currentPolicy(root) {
  const pointer=join(root,'configs/dsh-active-policy.json');
  return existsSync(pointer)?JSON.parse(readFileSync(pointer,'utf8')).policy_file:undefined;
}
function watermark(file) {
  if(!existsSync(file))return {event_seq:0,interaction_seq:0,interaction_hash:null};
  const db=new DatabaseSync(file,{readOnly:true});
  try {
    const row=db.prepare("SELECT event_seq,payload_sha256 FROM stream_events WHERE event_type IN ('input.accepted','playback.completed') ORDER BY event_seq DESC LIMIT 1").get();
    return {event_seq:db.prepare('SELECT COALESCE(MAX(event_seq),0) n FROM stream_events').get().n,interaction_seq:row?.event_seq||0,interaction_hash:row?.payload_sha256||null};
  } finally {db.close();}
}
export function prepareRestore(root,backupRelative,{policyFile=currentPolicy(root)}={}) {
  root=resolve(root);const policy=loadPolicy(root,policyFile),backup=inside(root,backupRelative);
  const manifest=JSON.parse(readFileSync(join(backup,'manifest.json'),'utf8'));
  requireValue(manifest.schema_version===2&&manifest.policy_version===policy.policy_version&&manifest.dsh==='0.2.0-rc.2'&&manifest.humanity==='0.1.17'&&manifest.connector==='stream-humanity-v1','RESTORE_VERSION_MISMATCH');
  requireValue(digest(readFileSync(join(backup,'state.sqlite3')))===manifest.database.sha256,'RESTORE_DATABASE_HASH');
  const persona=JSON.parse(readFileSync(join(backup,'persona.json'),'utf8'));
  requireValue(digest(persona)===manifest.persona_sha256,'RESTORE_PERSONA_HASH');
  const ledgerContext={root,ledgerFile:join(root,'state/deletion-ledger.jsonl'),ledgerHead:join(root,'state/deletion-head.json')};
  const ledger=MemoryAdministration.prototype.readLedger.call(ledgerContext);
  const head=existsSync(ledgerContext.ledgerHead)?JSON.parse(readFileSync(ledgerContext.ledgerHead,'utf8')):null;
  requireValue(!head||ledger.some(row=>row.sha256===head.sha256&&row.generation===head.generation),'RESTORE_LATEST_LEDGER_MISSING');
  requireValue(!manifest.deletion_head||ledger.some(row=>row.sha256===manifest.deletion_head),'RESTORE_LEDGER_ANCESTRY');
  const productionFile=inside(root,join(policy.deployment.state_relative_path,'stream.sqlite3'));
  const productionWatermark=watermark(productionFile),backupWatermark=watermark(join(backup,'state.sqlite3'));
  const directory=inside(root,join('state/restores',id('restore')));mkdirSync(directory,{recursive:true});
  const target=join(directory,'stream.sqlite3');copyFileSync(join(backup,'state.sqlite3'),target);
  const native=new DatabaseSync(target);try{native.exec('UPDATE bridge_owner SET lease_until=0');}finally{native.close();}
  const restoredPolicy=structuredClone(policy);restoredPolicy.deployment.state_relative_path=relative(root,directory).replaceAll('\\','/');
  restoredPolicy.deployment.dsh_home_relative_path=restoredPolicy.deployment.state_relative_path+'/dsh-home';
  let db;
  try {
    db=new StateStore(target);const state=new StreamState(db,restoredPolicy,persona.publication.persona_version);
    const memory=new MemoryService(db,state,restoredPolicy,{}),admin={db,state,memory};
    let replayed=0;
    for(const row of ledger.filter(row=>row.generation>state.room().deletion_generation)) {
      db.tx(()=>MemoryAdministration.prototype.redactInTransaction.call(admin,{operationId:row.operation_id,subject:row.subject_key,selectedMemoryId:row.memory_id,replay:row}));replayed++;
    }
    requireValue(state.room().deletion_generation===(ledger.at(-1)?.generation||0),'RESTORE_DELETION_GENERATION');
    const integrity=db.integrity();requireValue(integrity.integrity==='ok'&&integrity.foreign_keys.length===0,'RESTORE_INTEGRITY');
    // Fresh Humanity home plus unapplied outbox deterministically rebuilds the mirror.
    db.tx(()=>db.run("UPDATE mirror_outbox SET state='PENDING',next_attempt_at=? WHERE state='APPLIED'",utc()));
    const receipt={schema_version:1,restore_id:directory.split(/[\\/]/).at(-1),prepared_at:utc(),source_backup:relative(root,backup),
      database:target,policy_file:relative(root,join(directory,'policy.json')).replaceAll('\\','/'),production_file:productionFile,
      production_watermark:productionWatermark,backup_watermark:backupWatermark,deletion_head:ledger.at(-1)?.sha256||null,
      deletion_generation:state.room().deletion_generation,replayed_deletions:replayed,integrity,activated:false};
    writeFileSync(join(directory,'policy.json'),canonical(restoredPolicy));writeFileSync(join(directory,'restore-receipt.json'),canonical(receipt));
    return receipt;
  } finally {db?.close();}
}
export async function activateRestore(root,receiptRelative) {
  root=resolve(root);const file=inside(root,receiptRelative),receipt=JSON.parse(readFileSync(file,'utf8'));
  let alive=false;try{await fetch('http://127.0.0.1:3092/health',{signal:AbortSignal.timeout(1500)});alive=true;}catch{}
  requireValue(!alive,'RESTORE_STOP_BRIDGE_FIRST');
  const latest=MemoryAdministration.prototype.readLedger.call({ledgerFile:join(root,'state/deletion-ledger.jsonl')}).at(-1)?.sha256||null;
  requireValue(latest===receipt.deletion_head,'RESTORE_NEW_DELETIONS_REPREPARE');
  const now=watermark(inside(root,receipt.production_file));
  requireValue(canonical(now)===canonical(receipt.production_watermark),'RESTORE_PRODUCTION_CHANGED');
  requireValue(now.interaction_seq<=receipt.backup_watermark.interaction_seq&&now.interaction_hash===receipt.backup_watermark.interaction_hash,'RESTORE_WOULD_LOSE_NEW_INTERACTIONS');
  const check=new StateStore(inside(root,receipt.database));try{requireValue(check.integrity().integrity==='ok','RESTORE_INTEGRITY');}finally{check.close();}
  loadPolicy(root,receipt.policy_file);mkdirSync(join(root,'configs'),{recursive:true});
  const pointer=join(root,'configs/dsh-active-policy.json');if(existsSync(pointer))copyFileSync(pointer,pointer+'.before-'+Date.now());
  writeFileSync(pointer,canonical({policy_file:receipt.policy_file,restore_id:receipt.restore_id,activated_at:utc()}));
  receipt.activated=true;writeFileSync(file,canonical(receipt));return receipt;
}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  const [action,root,path]=process.argv.slice(2);
  const result=action==='prepare'?prepareRestore(root,path):action==='activate'?await activateRestore(root,path):null;
  requireValue(result,'RESTORE_ACTION');console.log(canonical(result));
}
