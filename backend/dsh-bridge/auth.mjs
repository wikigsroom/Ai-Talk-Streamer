// Open application access. This identity is ledger metadata, never a credential.
import { digest } from './channel.mjs';
import { id, utc } from '../memory/store.mjs';
import { requireValue } from './state.mjs';

export class Auth {
  constructor(_root, db, state) {
    this.db=db;this.state=state;
    this.identity=this.ensure('open-studio-identity-v1','operator','直接使用','operator-local');
  }
  ensure(value,role,label,viewerId) {
    const hash=digest(value),existing=this.db.get('SELECT * FROM principals WHERE token_hash=? AND revoked_at IS NULL',hash);
    if(existing)return existing;
    const principalId=id('principal');
    this.db.tx(()=>this.db.run('INSERT INTO principals VALUES (?,?,?,?,?,NULL,?)',principalId,hash,role,viewerId,label,utc(this.db.now())));
    return this.db.get('SELECT * FROM principals WHERE principal_id=?',principalId);
  }
  resolve() {
    return {principal_id:this.identity.principal_id,role:'operator',viewer_id:'operator-local',display_name:'直接使用',access_mode:'open',authentication_required:false};
  }
  require() { return this.resolve(); }
  anonymous() { return {principal:this.resolve()}; }
  login() { return this.anonymous(); }
  invite(label) {
    requireValue(typeof label==='string'&&label.trim().length>0&&label.length<=50,'VIEWER_LABEL_INVALID',400);
    return {viewer_id:id('viewer'),label:label.trim(),authentication_required:false};
  }
  playbackCredential() { return {consumer_id:'obs-'+id('consumer'),authentication_required:false}; }
}
