/* Capture the actual deployed app. No public broadcasting or model downloads. */
const { chromium } = require('playwright-core');
const { mkdirSync, writeFileSync } = require('node:fs');
const { join, resolve } = require('node:path');
const root = resolve(__dirname, '..'), output = join(root, 'docs/media/room'); mkdirSync(output, { recursive: true });
const base = process.env.STREAM_STUDIO_URL; if (!base) throw Error('Set STREAM_STUDIO_URL to the deployed studio origin');
let browser; const report = { source: 'actual_deployed_app', screenshots: [], errors: [], public_broadcast_started: false, ok: false };
(async () => {
  try {
    browser = await chromium.launch({ executablePath: process.env.STREAM_CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true, args: ['--autoplay-policy=no-user-gesture-required'] });
    const context = await browser.newContext({ viewport: { width: 1536, height: 1100 } }), page = await context.newPage(); page.on('pageerror', e => report.errors.push(e.message));
    await page.goto(base + '/admin'); await page.waitForFunction(() => window.adminRoom?.state && window.adminRoom.connected);
    await page.locator('#previewStart').click(); const preview = page.frameLocator('#preview');
    await preview.locator('#notice').waitFor({ state: 'hidden', timeout: 45000 }); await page.waitForTimeout(4500);
    // Clearly marked synthetic decoration examples; remove them after capture.
    await page.evaluate(async () => { const room = window.adminRoom; await room.post('messages', { action: 'create', nickname: '本地演示', text: '今天也一起，把平凡的小事过得有趣。', test: true, feature: true }); await room.post('test-event', { type: 'comment', text: '知夏，今天的阳光真好。' }); await room.post('test-event', { type: 'gift' }); });
    await page.waitForTimeout(700);
    for (const name of ['overview', 'music', 'visual', 'messages', 'agent', 'logs']) {
      await page.locator('[data-page=' + name + ']').click(); await page.waitForTimeout(450);
      await page.screenshot({ path: join(output, 'admin-' + name + '.png'), fullPage: true }); report.screenshots.push('admin-' + name + '.png');
    }
    await page.locator('#preview').screenshot({ path: join(output, 'program-preview.png') }); report.screenshots.push('program-preview.png');
    await page.locator('#previewStop').click(); await page.setViewportSize({ width: 390, height: 844 }); await page.locator('[data-page=overview]').click();
    await page.screenshot({ path: join(output, 'admin-mobile.png'), fullPage: true }); report.screenshots.push('admin-mobile.png');
    await page.evaluate(async () => { await window.adminRoom.post('messages', { action: 'unfeature' }); await window.adminRoom.post('messages', { action: 'clear_tests' }); });
    report.ok = report.errors.length === 0; await context.close();
  } finally { await browser?.close(); writeFileSync(join(root, 'outputs/room-admin/capture.json'), JSON.stringify(report, null, 2)); }
  if (!report.ok) throw Error('Deployed UI capture failed: ' + report.errors.join(',')); console.log(JSON.stringify(report));
})().catch(error => { console.error(error.message); process.exitCode = 1; });
