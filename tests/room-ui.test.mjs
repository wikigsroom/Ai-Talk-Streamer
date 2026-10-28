import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { existsSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { fixture, root } from './room-fixture.mjs';
const playwright = join(root, 'node_modules/playwright-core');
const executablePath = ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(existsSync);
const output = join(root, 'outputs/room-admin/ui'); mkdirSync(output, { recursive: true });
async function browser() { return createRequire(import.meta.url)(playwright).chromium.launch({ executablePath, headless: true, args: ['--autoplay-policy=no-user-gesture-required', '--disable-gpu'] }); }

test('admin operates real room APIs, private agent, music and safe inbox at desktop and mobile widths', { skip: !executablePath || !existsSync(playwright) }, async () => {
  const f = await fixture(), b = await browser();
  try {
    const context = await b.newContext({ viewport: { width: 1536, height: 1100 } }), page = await context.newPage(), errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.goto(f.base + '/admin'); await page.waitForFunction(() => window.adminRoom?.state && window.adminRoom.connected);
    await page.locator('#identityForm input[name=topic]').fill('窗边的周末闲聊'); await page.locator('#identityForm button[type=submit]').click(); await page.waitForFunction(() => window.adminRoom.state.settings.identity.topic === '窗边的周末闲聊');
    await page.screenshot({ path: join(output, 'fixture-admin-desktop.png'), fullPage: true });
    await page.getByRole('button', { name: '音乐与声音', exact: false }).click(); await page.locator('.track').first().getByRole('button', { name: '播放', exact: true }).click(); await page.waitForFunction(() => window.adminRoom.state.music.playing);
    await page.locator('#repeatMode').selectOption('all'); await page.waitForFunction(() => window.adminRoom.state.music.repeat === 'all');
    await page.locator('[data-page=visual]').click(); await page.locator('[data-theme=paper]').click(); await page.waitForFunction(() => window.adminRoom.state.settings.overlay.theme === 'paper');
    await page.locator('[data-test=gift]').click(); await page.locator('[data-page=messages]').click(); await page.locator('#noteText').fill('欢迎来到知夏的日光宿舍'); await page.locator('#noteForm button').click(); await page.waitForFunction(() => window.adminRoom.state.board.featured?.text === '欢迎来到知夏的日光宿舍');
    f.manager.acceptPlatformEvent({ event_key: 'xss-1', type: 'comment', nickname: '<img src=x onerror="window.BAD=1">', text: '<script>window.BAD=1</script>', platform: 'custom', room_id: 'fixture' });
    await page.locator('#messageSearch').fill('window.BAD'); await page.waitForFunction(() => document.querySelector('#inbox').textContent.includes('<script>window.BAD=1</script>')); assert.equal(await page.evaluate(() => window.BAD), undefined); assert.equal(await page.locator('#inbox img,#inbox script').count(), 0);
    await page.locator('[data-page=agent]').click(); await page.locator('#agentText').fill('帮我想一个自然的开场'); await page.locator('#askAgent').click(); await page.waitForFunction(() => document.querySelector('#agentHistory').textContent.includes('可以从今天的一件小事聊起'));
    assert.equal(f.accepted.length, 0); await page.locator('[data-action=agent-speak]').click(); assert.match(await page.locator('#speechText').inputValue(), /今天的一件小事/); assert.equal(f.accepted.length, 0);
    await page.locator('#startSession').click(); await page.waitForFunction(() => window.adminRoom.state.broadcast?.state === 'LIVE'); await page.locator('#speechForm button[type=submit]').click(); await page.waitForFunction(() => document.querySelector('#speechText').value === ''); assert.equal(f.accepted.length, 1);
    await page.setViewportSize({ width: 390, height: 844 }); for (const name of ['overview', 'music', 'visual', 'messages', 'agent', 'logs']) { await page.locator('[data-page=' + name + ']').click(); await page.waitForTimeout(50); assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true, name + ' mobile overflow'); }
    await page.locator('[data-page=overview]').click(); await page.screenshot({ path: join(output, 'fixture-admin-mobile.png'), fullPage: true }); assert.deepEqual(errors, []); await context.close();
  } finally { await b.close(); await f.close(); }
});
test('portrait overlay keeps face safe, reacts to board/moderation, and reconnect does not replay old gifts', { skip: !executablePath || !existsSync(playwright) }, async () => {
  const f = await fixture(), b = await browser();
  try {
    await f.post('test-event', { type: 'gift' }); const context = await b.newContext({ viewport: { width: 720, height: 1280 } }), page = await context.newPage(), errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.goto(f.base + '/overlay'); await page.waitForFunction(() => document.querySelector('.room-brand strong').textContent.length > 0); assert.equal(await page.locator('.room-gift').isHidden(), true);
    await page.evaluate(() => { document.body.style.background = 'url(/character/reference.png) center / contain no-repeat'; });
    await f.post('test-event', { type: 'comment', text: '知夏，今天的阳光真好。' }); await f.post('messages', { action: 'create', text: '今天也一起，把平凡的小事过得有趣。', feature: true, test: true }); await f.post('test-event', { type: 'gift' });
    await page.waitForFunction(() => !document.querySelector('.room-board').hidden && !document.querySelector('.room-gift').hidden);
    const boxes = await page.locator('.room-brand,.room-chat,.room-board,.room-gift').evaluateAll(els => els.map(e => { const r = e.getBoundingClientRect(); return { top: r.top, bottom: r.bottom }; })); for (const box of boxes) assert.ok(box.bottom <= 245 || box.top >= 645, 'overlay overlaps face safety band');
    await page.screenshot({ path: join(output, 'fixture-overlay-daylight.png') });
    await f.post('config', { expected_revision: f.manager.store.revision, patch: { moderation: { blocked_names: ['本地测试'] } } }); await page.waitForFunction(() => document.querySelector('.room-chat').childElementCount === 0 && document.querySelector('.room-gift').hidden);
    assert.deepEqual(errors, []); await context.close();
  } finally { await b.close(); await f.close(); }
});
test('Web Audio mixer ducks only during scheduled valid speech, clears on cancel, and preview stays silent', { skip: !executablePath || !existsSync(playwright) }, async () => {
  const f = await fixture(), b = await browser();
  try {
    const context = await b.newContext(), page = await context.newPage(); await page.goto(f.base + '/overlay'); await page.addScriptTag({ url: f.base + '/room-audio.js' });
    await page.evaluate(async () => {
      const room = window.testRoom = new RoomClient(); await room.start(); const audio = window.testAudio = new AudioContext(); await audio.resume(); const mixer = window.testMixer = new RoomAudioMixer(audio, audio.destination, room);
      await room.post('music', { action: 'play' });
      const source = audio.createBufferSource(); source.buffer = audio.createBuffer(1, 24000, 24000); source.connect(mixer.speech); const at = audio.currentTime + .6; source.start(at); window.testSource = source; mixer.schedule(source, { request_id: 'fixture-speech', ranges: [{ packet_offset: 0, sample_count: 24000 }] }, at, 24000);
    });
    await page.waitForTimeout(220); assert.equal(await page.evaluate(() => testMixer.ducked), false);
    await page.waitForFunction(() => testMixer.ducked); const duckGain = await page.evaluate(() => testMixer.targetGain); assert.ok(duckGain < .1 && duckGain > 0);
    await page.evaluate(() => { testSource._dshCancelled = true; testSource.stop(); testMixer.clear(); }); await page.waitForFunction(() => !testMixer.ducked && testMixer.targetGain === .22);
    const result = await page.evaluate(async () => { const preview = new RoomAudioMixer(testAudio, testAudio.destination, testRoom, { audible: false }); await new Promise(r => setTimeout(r, 250)); const r = { paused: preview.audio.paused, master: preview.master.gain.value }; preview.close(); testMixer.close(); testRoom.close(); await testAudio.close(); return r; });
    assert.equal(result.paused, true); assert.ok(result.master < .001); await context.close();
  } finally { await b.close(); await f.close(); }
});
