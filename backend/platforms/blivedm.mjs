import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import { check } from './config.mjs';
export class BliveDmAdapter {
  constructor(root, config, { onEvent, onState }) { this.root = root; this.config = config; this.onEvent = onEvent; this.onState = onState; this.stopped = true; }
  async start() {
    const python = join(this.root, 'runtime/platforms/Scripts/python.exe'); check(existsSync(python), 'BLIVEDM_NOT_INSTALLED', 503);
    check(/^\d+$/.test(this.config.room_id), 'BILIBILI_ROOM_ID_REQUIRED'); this.stopped = false;
    this.child = spawn(python, ['-X', 'utf8', '-u', '-B', join(this.root, 'scripts/platform_blivedm.py')], { cwd: this.root, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
    this.child.stdin.on('error', () => {}); this.child.stdin.write(JSON.stringify({ room_id: this.config.room_id, cookie: this.config.cookie }) + '\n');
    this.lines = createInterface({ input: this.child.stdout });
    this.lines.on('line', line => { try { const value = JSON.parse(line); if (value.kind === 'event') this.onEvent(value.event, { roomId: value.room_id }); else if (value.kind === 'state') this.onState(value.state, value.error || null); } catch { this.onState('DEGRADED', 'BLIVEDM_MESSAGE_INVALID'); } });
    this.child.stderr.on('data', () => { if (!this.stopped) this.onState('RECONNECTING', 'BLIVEDM_CONNECTION_RETRY'); });
    this.child.on('error', () => this.onState('ERROR', 'BLIVEDM_START_FAILED'));
    this.child.on('exit', () => { if (!this.stopped) this.onState('ERROR', 'BLIVEDM_STOPPED'); });
    this.onState('CONNECTING');
  }
  async stop() {
    this.stopped = true;
    if (this.child && this.child.exitCode === null) await new Promise(resolve => {
      const timer = setTimeout(() => { this.child.kill(); resolve(); }, 4000); this.child.once('exit', () => { clearTimeout(timer); resolve(); }); this.child.stdin.end('{"stop":true}\n');
    });
    this.lines?.close(); this.onState('STOPPED');
  }
}
