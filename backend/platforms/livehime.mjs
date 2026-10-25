import { existsSync, mkdirSync, readFileSync } from 'node:fs';
import { join, resolve, sep } from 'node:path';
import { spawn } from 'node:child_process';
import { playwrightFor } from './browser.mjs';
import { check, PlatformError } from './config.mjs';

export const LIVEHIME_WINDOW_TITLE = '女A · 林知夏 · 直播姬画面';
export const LIVEHIME_SOURCE_URL = 'http://127.0.0.1:8010/output.html?output=platform&renderer=livehime';
export const LIVEHIME_OUTPUT_URL = 'http://127.0.0.1:8010/output.html?renderer=preview';

// Owns one local Chromium application window. Livehime owns its account,
// capture settings and actual public broadcast; no OBS client is called here.
export class LivehimeOutput {
  constructor(root, { playwright, spawnChild = spawn } = {}) {
    this.root = resolve(root); this.playwright = playwright; this.spawnChild = spawnChild;
    this.context = null; this.page = null; this.clientRequested = false;
  }
  receipt() {
    const file = join(this.root, 'outputs/platforms/setup/bilibili-livehime.json');
    if (!existsSync(file)) return null;
    try {
      const value = JSON.parse(readFileSync(file, 'utf8').replace(/^\uFEFF/, ''));
      const application = resolve(this.root, value.application || '');
      check(application.startsWith(this.root + sep) && existsSync(application)
        && value.prepared === true && value.application_signature?.status === 'Valid', 'LIVEHIME_RECEIPT_INVALID', 503);
      return { ...value, application };
    } catch { throw new PlatformError('LIVEHIME_RECEIPT_INVALID', 503); }
  }
  async status() {
    const receipt = this.receipt();
    let player = null;
    if (this.page && !this.page.isClosed()) {
      try {
        player = await this.page.evaluate(() => ({
          title: document.title, width: innerWidth, height: innerHeight,
          video_width: document.querySelector('video')?.videoWidth || 0,
          video_height: document.querySelector('video')?.videoHeight || 0,
          frames: document.querySelector('video')?.getVideoPlaybackQuality?.().totalVideoFrames || 0,
          audio_state: window.avatarAudioContext?.state || 'unknown',
          consumer_id: window.avatarTransport?.dsh?.consumerId || null,
        }));
      } catch {}
    }
    return { renderer: 'livehime', obs_required: false, client_installed: !!receipt,
      client_version: receipt?.version || null, client_launch_requested: this.clientRequested,
      window_open: !!this.page && !this.page.isClosed(), window_title: LIVEHIME_WINDOW_TITLE,
      player, source_url: LIVEHIME_SOURCE_URL, source_width: 720, source_height: 1280,
      capture_method: 'livehime_browser_source', account_login_verified: false, audience_delivery_verified: false };
  }
  async launchClient(force = false) {
    const receipt = this.receipt(); check(receipt, 'LIVEHIME_NOT_INSTALLED', 503);
    if (!this.clientRequested || force) {
      const appdata = join(this.root, 'state/platforms/livehime/roaming'), local = join(this.root, 'state/platforms/livehime/local'), temp = join(this.root, 'cache/platforms/livehime-temp');
      for (const folder of [appdata, local, temp]) mkdirSync(folder, { recursive: true });
      await new Promise((resolveLaunch, reject) => {
        const child = this.spawnChild(receipt.application, [], {
          cwd: join(receipt.application, '..'), detached: true, windowsHide: true, stdio: 'ignore',
          env: { ...process.env, APPDATA: appdata, LOCALAPPDATA: local, TEMP: temp, TMP: temp },
        });
        child.once('error', () => reject(new PlatformError('LIVEHIME_LAUNCH_FAILED', 503)));
        child.once('spawn', () => { child.unref(); this.clientRequested = true; resolveLaunch(); });
      });
    }
    return { launch_requested: true, account_login_verified: false, public_broadcast_started: false };
  }
  async prepare() {
    if (this.preparing) return this.preparing;
    this.preparing = this.prepareWindow().finally(() => { this.preparing = null; });
    return this.preparing;
  }
  async prepareWindow() {
    // A missing client cannot be reported as a ready Livehime workflow.
    await this.launchClient();
    if (this.page && !this.page.isClosed()) return { prepared: true, status: await this.status() };
    const { chromium } = this.playwright || playwrightFor(this.root);
    const executablePath = [
      'C:/Program Files/Google/Chrome/Application/chrome.exe',
      'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
      'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
    ].find(existsSync);
    check(executablePath || this.playwright, 'OUTPUT_BROWSER_NOT_INSTALLED', 503);
    try {
      const context = this.context = await chromium.launchPersistentContext(join(this.root, 'cache/platforms/livehime-output'), {
        executablePath, headless: false, chromiumSandbox: true, viewport: { width: 720, height: 1280 }, deviceScaleFactor: 1,
        ignoreDefaultArgs: ['--enable-automation'],
        args: ['--app=' + LIVEHIME_OUTPUT_URL, '--window-size=720,1310', '--window-position=20,30',
          '--autoplay-policy=no-user-gesture-required', '--disable-extensions', '--no-first-run',
          '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
          '--disable-backgrounding-occluded-windows', '--disable-features=CalculateNativeWinOcclusion'],
      });
      let pages = context.pages();
      this.page = pages.find(page => page.url().startsWith(LIVEHIME_OUTPUT_URL)) || pages[0] || await context.newPage();
      if (!this.page.url().startsWith(LIVEHIME_OUTPUT_URL)) await this.page.goto(LIVEHIME_OUTPUT_URL, { waitUntil: 'domcontentloaded', timeout: 15000 });
      for (const other of context.pages()) if (other !== this.page) await other.close();
      this.page.on('close', () => { void context.close().catch(() => {}); if (this.context === context) this.context = null; });
      context.on('close', () => { if (this.context === context) { this.context = null; this.page = null; } });
      await this.page.waitForFunction(() => {
        const video = document.querySelector('video');
        return video?.videoWidth === 720 && video.videoHeight === 1280
          && window.avatarAudioContext?.state === 'running'
          && (video.getVideoPlaybackQuality?.().totalVideoFrames || 0) > 0;
      }, null, { timeout: 30000 });
      return { prepared: true, public_broadcast_started: false, status: await this.status() };
    } catch (error) {
      await this.close();
      throw error instanceof PlatformError ? error : new PlatformError('LIVEHIME_WINDOW_NOT_READY', 503);
    }
  }
  async close() {
    const context = this.context; this.context = null; this.page = null;
    await context?.close();
    // The official client may have user activity; closing our output never
    // terminates Livehime or claims its external broadcast has ended.
  }
}
