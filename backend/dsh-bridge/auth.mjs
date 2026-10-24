import { randomBytes, timingSafeEqual } from 'node:crypto';
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { digest } from './channel.mjs';
import { id, utc } from '../memory/store.mjs';
import { requireValue } from './state.mjs';
const token = () => randomBytes(32).toString('base64url');
function secretFile(root, name) {
  const path = join(root, 'configs', name); mkdirSync(join(root, 'configs'), { recursive: true });
  if (!existsSync(path)) writeFileSync(path, token(), { flag: 'wx', mode: 0o600 });
  const value = readFileSync(path, 'utf8').trim();
  requireValue(/^[A-Za-z0-9_-]{32,100}$/.test(value), 'AUTH_SECRET_INVALID', 503);
  return value;
}
export class Auth {
  constructor(root, db, state) {
    this.db = db; this.state = state;
    this.operatorKey = secretFile(root, 'dsh-operator.token'); this.mediaKey = secretFile(root, 'dsh-media.token');
    this.ensure(this.operatorKey, 'operator', '本机管理员', 'operator-local');
    this.ensure(this.mediaKey, 'media', '本机媒体服务', null);
  }
  ensure(value, role, label, viewerId) {
    const hash = digest(value), existing = this.db.get('SELECT * FROM principals WHERE token_hash=? AND revoked_at IS NULL', hash);
    if (existing) return existing;
    const principalId = id('principal');
    this.db.tx(() => this.db.run('INSERT INTO principals VALUES (?,?,?,?,?,NULL,?)', principalId, hash, role, viewerId, label, utc(this.db.now())));
    return this.db.get('SELECT * FROM principals WHERE principal_id=?', principalId);
  }
  resolve(headers) {
    const bearer = headers.authorization?.match(/^Bearer ([A-Za-z0-9_-]{32,100})$/)?.[1];
    const cookie = headers.cookie?.split(';').map(item => item.trim()).find(item => item.startsWith('dsh_session='))?.slice(12);
    const value = bearer || cookie;
    const principal=value ? this.db.get('SELECT principal_id,role,viewer_id,display_name FROM principals WHERE token_hash=? AND revoked_at IS NULL', digest(value)) ?? null : null;
    if(principal?.viewer_id?.startsWith('playback:')) {
      const saved=this.db.get('SELECT value_json FROM runtime_meta WHERE key=?','playback_credential:'+principal.principal_id);
      const scope=saved&&JSON.parse(saved.value_json);
      if(!scope||scope.expires_at<=this.db.now())return null;
      return {...principal,role:'playback',consumer_id:scope.consumer_id};
    }
    return principal;
  }
  require(headers, role) { const principal = this.resolve(headers); requireValue(principal && (!role || principal.role === role), role ? role.toUpperCase() + '_REQUIRED' : 'AUTHENTICATION_REQUIRED', principal ? 403 : 401); return principal; }
  login(value) {
    requireValue(typeof value === 'string' && value.length < 101, 'LOGIN_INVALID', 401);
    const supplied = Buffer.from(digest(value)), expected = Buffer.from(digest(this.operatorKey));
    const invited = this.db.get("SELECT * FROM principals WHERE token_hash=? AND role='viewer' AND viewer_id NOT LIKE 'playback:%' AND revoked_at IS NULL", digest(value));
    requireValue(timingSafeEqual(supplied, expected) || invited, 'LOGIN_INVALID', 401);
    const session = token(), role = invited ? 'viewer' : 'operator', viewerId = invited?.viewer_id || 'operator-local';
    const principal = this.ensure(session, role, invited?.display_name || '管理员', viewerId);
    return { principal: { principal_id: principal.principal_id, role, viewer_id: viewerId, display_name: principal.display_name }, cookie: this.cookie(session) };
  }
  anonymous(headers) {
    const current = this.resolve(headers), broadcastId = this.state.current()?.broadcast_id || 'offair';
    if (current && (current.role === 'operator' || current.role === 'viewer' && (!current.viewer_id.startsWith('anon:') || current.viewer_id.startsWith('anon:' + broadcastId + ':')))) return { principal: current };
    const session = token(), viewerId = 'anon:' + broadcastId + ':' + id('v'), principal = this.ensure(session, 'viewer', '临时观众', viewerId);
    return { principal: { principal_id: principal.principal_id, role: 'viewer', viewer_id: viewerId, display_name: '临时观众' }, cookie: this.cookie(session) };
  }
  invite(label) {
    requireValue(typeof label === 'string' && label.trim().length > 0 && label.length <= 50, 'VIEWER_LABEL_INVALID', 400);
    const value = token(), principal = this.ensure(value, 'viewer', label.trim(), id('viewer'));
    return { viewer_id: principal.viewer_id, label: principal.display_name, invitation_token: value };
  }
  playbackCredential() {
    const value=token(),consumerId='obs-'+id('consumer'),principal=this.ensure(value,'viewer','本机 OBS 播放确认','playback:'+consumerId);
    this.db.tx(()=>this.db.run('INSERT INTO runtime_meta VALUES (?,?)','playback_credential:'+principal.principal_id,JSON.stringify({consumer_id:consumerId,expires_at:this.db.now()+21600000})));
    return {token:value,consumer_id:consumerId,expires_in_seconds:21600};
  }
  cookie(value) { return 'dsh_session=' + value + '; HttpOnly; SameSite=Strict; Path=/; Max-Age=2592000'; }
}
