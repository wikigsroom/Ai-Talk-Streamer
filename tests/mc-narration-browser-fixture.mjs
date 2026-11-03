import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { narrationFixture } from './game-narration-fixture.mjs';
import { sourceRoot } from './game-fixture.mjs';

const executablePath = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const playwright = join(sourceRoot, 'node_modules/playwright-core');
export const output = resolve(process.env.MC_NARRATION_EVIDENCE_ROOT || join(sourceRoot, 'outputs/mc-narration-ui'));
export const skip = !existsSync(executablePath) || !existsSync(playwright);
mkdirSync(output, { recursive: true });
export async function withPage(t, name, work) {
  const f = await narrationFixture(t, undefined, { ui: true });
  const report = { classification: 'LOCAL_BROWSER_AND_PROTOCOL_FIXTURES_ONLY', result: 'FAIL', browser_closed: false,
    page_errors: [], external_requests: [], real_minecraft: false, real_models: false, public_broadcast: false };
  let browser, context;
  try {
    const temp = join(sourceRoot, 'cache/mc-narration-browser'); mkdirSync(temp, { recursive: true });
    browser = await createRequire(import.meta.url)(playwright).chromium.launch({ executablePath, headless: true,
      env: { ...process.env, TEMP: temp, TMP: temp }, args: ['--disable-gpu', '--disable-background-networking'] });
    context = await browser.newContext({ viewport: { width: 1440, height: 1080 }, reducedMotion: 'reduce' });
    await context.route(/^https?:\/\//, async route => {
      if (route.request().url().startsWith(f.base + '/')) await route.continue();
      else { report.external_requests.push(route.request().url()); await route.abort(); }
    });
    const page = await context.newPage(); page.on('pageerror', error => report.page_errors.push(error.message));
    await work(f, page, report);
    assert.deepEqual(report.page_errors, []); assert.deepEqual(report.external_requests, []); report.result = 'PASS';
  } catch (error) {
    report.error = String(error.stack || error); throw error;
  } finally {
    try { await context?.close(); } finally {
      await browser?.close(); report.browser_closed = !browser?.isConnected();
      writeFileSync(join(output, name + '.json'), JSON.stringify(report, null, 2) + '\n');
    }
  }
}
