import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { existsSync, mkdirSync, mkdtempSync, rmSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { observeChat, CHAT_SELECTORS } from '../backend/platforms/browser.mjs';
import { normalizeEvent } from '../backend/platforms/events.mjs';
import { PlatformStore } from '../backend/platforms/store.mjs';
const root = resolve(process.cwd()), modulePath = process.env.PLATFORM_PLAYWRIGHT_MODULE || [join(root, 'node_modules/playwright-core'), join(root, 'tools/dsh-browser/node_modules/playwright-core')].find(existsSync) || join(root, 'node_modules/playwright-core');
const available = existsSync(modulePath);
for (const platform of ['bilibili', 'douyin']) test(platform + ': a native browser ignores existing comments and reads only new DOM messages', { skip: !available }, async () => {
  const { chromium } = createRequire(import.meta.url)(modulePath);
  const executablePath = ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(existsSync);
  assert.ok(executablePath, 'Native Chrome or Edge is required');
  const browser = await chromium.launch({ executablePath, headless: true, args: ['--disable-gpu'] });
  const folder = join(root, 'outputs/platforms/browser-tests'); mkdirSync(folder, { recursive: true }); const temp = mkdtempSync(join(folder, 'case-')), store = new PlatformStore(join(temp, 'events.sqlite3'));
  const selectors = CHAT_SELECTORS[platform], events = [];
  try {
    const context = await browser.newContext(); const page = await context.newPage();
    await page.exposeBinding('aiTalkPlatformMessage', (_source, data) => { events.push(data); store.insert(normalizeEvent(platform, data, { source: 'browser' })); });
    const cls = selector => selector.split('.').filter(Boolean).join(' ');
    await page.setContent(`<main id="chat"><div class="${cls(selectors.item)}" data-msg-id="old" data-uid="111"><span class="${cls(selectors.user)}">同名观众</span><span class="${cls(selectors.text)}">打开前已有的历史消息</span></div></main>`);
    await page.evaluate(observeChat, { selectors, roomId: 'fixture-room', sessionId: 'fixture-session' });
    await page.waitForTimeout(50); assert.equal(events.length, 0);
    await page.evaluate(({ selectors }) => {
      const node = document.querySelector(selectors.item).cloneNode(true); node.setAttribute('data-msg-id', 'new'); node.setAttribute('data-uid', '222'); node.querySelector(selectors.text).textContent = '新评论 <script>不会成为代码</script>'; document.querySelector('#chat').append(node);
    }, { selectors });
    await page.waitForFunction(() => window.__aiTalkChatObserver.observed === 1); assert.equal(events.length, 1); assert.equal(events[0].user_id, '222');
    await page.evaluate(({ selectors }) => { const node = document.querySelectorAll(selectors.item)[1]; node.replaceWith(node.cloneNode(true)); }, { selectors });
    await page.waitForTimeout(100); assert.equal(store.recent().length, 1, 'Re-rendered platform IDs remain de-duplicated');
    await page.evaluate(() => window.__aiTalkChatObserver.stop());
    await context.close(); assert.equal(browser.contexts().length, 0);
  } finally { store.close(); await browser.close(); rmSync(temp, { recursive: true, force: true }); }
});
