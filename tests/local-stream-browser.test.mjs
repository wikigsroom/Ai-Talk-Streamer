import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createServer } from 'node:http';
import { createRequire } from 'node:module';
import { existsSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

const root = resolve(process.cwd());
const modulePath = join(root, 'node_modules/playwright-core');
const executablePath = ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(existsSync);

test('native browser source outputs canvas/audio directly, recovers from decoder overload, and preserves preview playback', { skip: !existsSync(modulePath) }, async () => {
  assert.ok(executablePath, 'Native Chrome or Edge is required');
  let jpeg, sequence = 0;
  // One generated Baseline Annex-B keyframe: ffmpeg color=0x2ac083,
  // 720x1280, libx264 baseline level3.1, ultrafast/zerolatency, one frame.
  const h264 = readFileSync(join(root, 'tests/fixtures/stream-green-720x1280.h264'));
  const sockets = new Set(), closeCodes = [];
  const frame = (opcode, payload) => {
    const header = Buffer.alloc(payload.length < 126 ? 2 : 4);
    header[0] = 0x80 | opcode;
    if (payload.length < 126) header[1] = payload.length;
    else { header[1] = 126; header.writeUInt16BE(payload.length, 2); }
    return Buffer.concat([header, payload]);
  };
  const server = createServer((req, res) => {
    const path = new URL(req.url, 'http://localhost').pathname;
    const files = { '/output.html': 'integration/obs.html', '/browser-id.js': 'web/browser-id.js', '/dsh-playback.js': 'web/dsh-playback.js', '/local-stream.js': 'web/local-stream.js' };
    if (files[path]) { res.writeHead(200, { 'Content-Type': path.endsWith('.html') ? 'text/html' : 'application/javascript' }); res.end(readFileSync(join(root, files[path]))); }
    else if (path === '/fixture.jpg') { res.writeHead(200, { 'Content-Type': 'image/jpeg' }); res.end(jpeg); }
    else { req.resume(); res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ broadcast: null, claim: false })); }
  });
  server.on('upgrade', (req, socket) => {
    const avc = new URL(req.url, 'http://localhost').searchParams.get('codec') === 'h264';
    const accept = createHash('sha1').update(req.headers['sec-websocket-key'] + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
    socket.write('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ' + accept + '\r\n\r\n');
    sockets.add(socket);
    const timer = setInterval(() => {
      const samples = 640, picture = avc ? Buffer.concat([Buffer.from([65, 86, 67, 49, 1, 0, 0, 0]), h264]) : jpeg, packet = Buffer.alloc(12 + picture.length + samples * 2);
      packet.writeUInt32LE(sequence++, 0); packet.writeUInt32LE(picture.length, 4); packet.writeUInt32LE(16000, 8); picture.copy(packet, 12);
      for (let i = 0; i < samples; i++) packet.writeInt16LE(Math.round(Math.sin(2 * Math.PI * 440 * i / 16000) * 4000), 12 + picture.length + i * 2);
      if (!socket.destroyed) socket.write(frame(2, packet));
    }, 40);
    let pending = Buffer.alloc(0);
    socket.on('data', chunk => {
      pending = Buffer.concat([pending, chunk]);
      while (pending.length >= 2) {
        const masked = !!(pending[1] & 128), short = pending[1] & 127;
        if (short === 127) { socket.destroy(); return; }
        if (short === 126 && pending.length < 4) return;
        const length = short === 126 ? pending.readUInt16BE(2) : short, offset = (short === 126 ? 4 : 2) + (masked ? 4 : 0);
        if (pending.length < offset + length) return;
        const opcode = pending[0] & 15, payload = Buffer.from(pending.subarray(offset, offset + length));
        if (masked) for (let i = 0; i < payload.length; i++) payload[i] ^= pending[offset - 4 + i % 4];
        pending = pending.subarray(offset + length);
        if (opcode === 8) { closeCodes.push(payload.length >= 2 ? payload.readUInt16BE(0) : null); socket.end(frame(8, payload)); return; }
        if (opcode === 9) socket.write(frame(10, payload));
      }
    });
    socket.on('error', () => {});
    socket.on('close', () => { clearInterval(timer); sockets.delete(socket); });
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const { chromium } = createRequire(import.meta.url)(modulePath);
  const browser = await chromium.launch({ executablePath, headless: true, args: ['--autoplay-policy=no-user-gesture-required'] });
  try {
    const context = await browser.newContext({ viewport: { width: 720, height: 1280 } }), page = await context.newPage(), errors = [];
    page.on('pageerror', error => errors.push(error.message));
    jpeg = Buffer.from(await page.evaluate(() => { const c = document.createElement('canvas'); c.width = 720; c.height = 1280; const x = c.getContext('2d'); x.fillStyle = '#2ac083'; x.fillRect(0, 0, 720, 1280); return c.toDataURL('image/jpeg').split(',')[1]; }), 'base64');
    await context.addInitScript(() => {
      const NativeContext = window.AudioContext;
      window.AudioContext = class extends NativeContext {
        constructor() { super(); const probe = this.createAnalyser(); probe.connect(this.destination); Object.defineProperty(this, 'destination', { value: probe }); window.audioProbe = probe; }
      };
      if (new URLSearchParams(location.search).get('renderer') === 'livehime') {
        HTMLCanvasElement.prototype.captureStream = () => { throw Error('Native output must not recapture its canvas'); };
        HTMLMediaElement.prototype.play = () => { throw Error('Native output must not use a MediaStream video'); };
      }
    });
    const base = 'http://127.0.0.1:' + server.address().port;
    await page.goto(base + '/output.html?renderer=livehime&output=platform&codec=jpeg&buffer_ms=800');
    await page.waitForFunction(() => window.avatarTransport?.frames > 35 && window.avatarTransport.metrics().fps > 18);
    const native = await page.evaluate(() => {
      const t = window.avatarTransport, samples = new Float32Array(window.audioProbe.fftSize); window.audioProbe.getFloatTimeDomainData(samples);
      return { metrics: t.metrics(), rms: Math.sqrt(samples.reduce((sum, sample) => sum + sample * sample, 0) / samples.length), hiddenVideo: document.querySelector('video').hidden, visibleCanvas: t.canvas.isConnected, stream: !!t.stream };
    });
    assert.equal(native.metrics.output_mode, 'direct_canvas_audio'); assert.equal(native.metrics.fps_source, 'canvas_draw');
    assert.equal(native.metrics.width, 720); assert.equal(native.metrics.height, 1280);
    assert.ok(native.metrics.fps > 18 && native.metrics.fps < 32); assert.ok(native.rms > 0.02, 'PCM reaches the actual Web Audio output path');
    assert.equal(native.hiddenVideo, true); assert.equal(native.visibleCanvas, true); assert.equal(native.stream, false);
    await page.evaluate(() => {
      const t = window.oldTransport = window.avatarTransport;
      t.avcDecoder = { state: 'configured', decodeQueueSize: 9, close() { this.state = 'closed'; } };
      const packet = new ArrayBuffer(28), h = new DataView(packet); h.setUint32(4, 16, true); h.setUint32(12, 0x41564331, false);
      return t.enqueuePicture(packet, t.audioContext.currentTime + 1);
    });
    await page.waitForFunction(() => window.oldTransport.running === false);
    assert.ok(closeCodes.includes(4001), 'Decoder overload closes a real browser WebSocket with a permitted application code');
    assert.deepEqual(await page.evaluate(() => [window.oldTransport.sources.size, window.oldTransport.imageTimers.size, window.oldTransport.timers.size]), [0, 0, 0]);
    await page.waitForFunction(() => window.avatarTransport !== window.oldTransport && window.avatarTransport.frames > 20, null, { timeout: 15000 });
    assert.equal(await page.locator('canvas').count(), 1, 'Reconnection removes the old canvas');
    await page.goto(base + '/output.html?renderer=preview&codec=jpeg&buffer_ms=800');
    await page.waitForFunction(() => document.querySelector('video').videoWidth === 720 && window.avatarTransport.presentedFrames > 20);
    const preview = await page.evaluate(() => ({ metrics: window.avatarTransport.metrics(), muted: document.querySelector('video').muted }));
    assert.equal(preview.metrics.output_mode, 'media_stream'); assert.equal(preview.metrics.fps_source, 'video_presentation'); assert.equal(preview.muted, true);
    await page.goto(base + '/output.html?renderer=livehime&output=platform&buffer_ms=800');
    await page.waitForFunction(() => window.avatarTransport?.frames > 35 && window.avatarTransport.metrics().fps > 18);
    const avc = await page.evaluate(() => ({ metrics: window.avatarTransport.metrics(), preference: window.avatarTransport.avcConfig?.hardwareAcceleration, pixel: [...window.avatarTransport.context.getImageData(300, 500, 1, 1).data] }));
    assert.equal(avc.metrics.codec, 'h264_nvenc'); assert.equal(avc.preference, 'prefer-software');
    assert.equal(avc.metrics.decode_errors, 0); assert.equal(avc.metrics.audio_underruns, 0);
    assert.ok(avc.pixel[1] > avc.pixel[0] && avc.pixel[1] > avc.pixel[2], 'A real Annex-B frame is decoded and painted');
    await page.evaluate(() => { const t = window.throwingTransport = window.avatarTransport; t.avcDecoder.decode = () => { throw Error('Injected deferred decoder failure'); }; });
    await page.waitForFunction(() => window.throwingTransport?.running === false);
    assert.ok(await page.evaluate(() => window.throwingTransport.decodeErrors > 0), 'Deferred decoder failure is observed and handled');
    await page.waitForFunction(() => window.avatarTransport && window.avatarTransport !== window.throwingTransport && window.avatarTransport.frames > 15, null, { timeout: 15000 });
    assert.deepEqual(errors, []);
    await context.close(); assert.equal(browser.contexts().length, 0);
  } finally {
    await browser.close(); for (const socket of sockets) socket.destroy(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
  }
});
