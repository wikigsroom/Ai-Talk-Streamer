import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { StreamBridge } from '../backend/dsh-bridge/server.mjs';
import { gameFixture } from './game-fixture.mjs';

test('the existing host lazily owns one game service and delegates its open HTTP routes without starting DSH', async () => {
  const fixture = await gameFixture({ enabled: false }); await fixture.manager.close();
  const host = { ...fixture.bridge, root: fixture.folder };
  Object.setPrototypeOf(host, StreamBridge.prototype);
  let restored = 0;
  host.room = { ...host.room, replayRetention() { restored++; assert(host.game); assert.equal(host.game.timer, undefined); return 0; } };
  delete host.game;
  host.loadGame = () => StreamBridge.prototype.loadGame.call(host);
  const server = createServer((req, res) => { void StreamBridge.prototype.handle.call(host, req, res); });
  try {
    const [one, two] = await Promise.all([host.loadGame(), host.loadGame()]);
    assert.equal(one, two); assert.equal(host.host, undefined);
    assert.equal(restored, 1, 'concurrent lazy loads replay withdrawals once before starting the service');
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const base = 'http://127.0.0.1:' + server.address().port + '/api/dsh/game';
    const preflight = await fetch(base + '/frames/frame-preflight', { method: 'OPTIONS', headers: {
      Origin: 'http://127.0.0.1:8020', 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'x-mc-operation-id,x-mc-captured-at' } });
    assert.equal(preflight.status, 204); assert.equal(preflight.headers.get('access-control-allow-origin'), '*');
    assert.match(preflight.headers.get('access-control-allow-headers'), /X-MC-Operation-Id/);
    assert.match(preflight.headers.get('access-control-allow-headers'), /X-MC-Captured-At/);
    const config = await (await fetch(base + '/config')).json();
    assert.equal(config.settings.enabled, false);
    const response = await fetch(base + '/config', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expected_revision: config.revision, patch: { enabled: true } }) });
    assert.equal(response.status, 200);
    const state = await (await fetch(base + '/state')).json();
    assert.equal(state.connected, false); assert.equal(state.automation_ready, false);
    assert.equal(host.host, undefined); assert.equal(host.game.planner.running, null);
  } finally {
    await host.game?.close(); server.closeAllConnections();
    if (server.listening) await new Promise(resolve => server.close(resolve));
    await fixture.close();
  }
});
