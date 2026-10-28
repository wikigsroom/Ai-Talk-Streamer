import { createReadStream, createWriteStream, existsSync, statSync, readdirSync } from 'node:fs';
import { mkdir, rename, unlink } from 'node:fs/promises';
import { join, extname } from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { Transform } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { check, RoomError } from './defaults.mjs';
const exec = promisify(execFile);
export const MAX_UPLOAD = 128 * 1024 * 1024;
const mimes = { '.wav': 'audio/wav', '.mp3': 'audio/mpeg', '.ogg': 'audio/ogg', '.flac': 'audio/flac', '.m4a': 'audio/mp4' };
function bundledProbe(root) {
  const queue = [[join(root, 'tools/ffmpeg'), 0]];
  while (queue.length) { const [folder, depth] = queue.shift(); if (!existsSync(folder)) continue; for (const entry of readdirSync(folder, { withFileTypes: true })) { const p = join(folder, entry.name); if (entry.isFile() && entry.name.toLowerCase() === 'ffprobe.exe') return p; if (entry.isDirectory() && depth < 3) queue.push([p, depth + 1]); } }
  return 'ffprobe';
}
export async function probeAudio(root, path) {
  const probe = bundledProbe(root);
  let data;
  try { const { stdout } = await exec(probe, ['-v', 'error', '-show_entries', 'format=duration:stream=codec_type', '-of', 'json', path], { timeout: 15000, maxBuffer: 128 * 1024, windowsHide: true }); data = JSON.parse(stdout); }
  catch { throw new RoomError('AUDIO_PROBE_FAILED_INSTALL_NATIVE_FFPROBE', 422); }
  const duration = Number(data.format?.duration);
  check(data.streams?.some(s => s.codec_type === 'audio') && !data.streams.some(s => s.codec_type === 'video') && Number.isFinite(duration) && duration >= 1 && duration <= 7200, 'AUDIO_DURATION_OR_FORMAT_INVALID', 422);
  return duration;
}
export async function uploadAudio(root, req, name, probe = probeAudio) {
  check(typeof name === 'string' && name.length > 0 && name.length <= 120 && !/[\\/\u0000-\u001f]/.test(name), 'AUDIO_NAME_INVALID');
  const extension = extname(name).toLowerCase(); check(Object.hasOwn(mimes, extension), 'AUDIO_EXTENSION_INVALID');
  const size = Number(req.headers['content-length'] || 0); check(Number.isFinite(size) && size >= 0 && size <= MAX_UPLOAD, 'AUDIO_UPLOAD_TOO_LARGE', 413);
  const id = randomUUID(), folder = join(root, 'assets/custom/room-bgm'), partial = join(folder, id + '.uploading'), target = join(folder, id + extension);
  await mkdir(folder, { recursive: true }); let bytes = 0; const hash = createHash('sha256');
  try {
    await pipeline(req, new Transform({ transform(chunk, _encoding, done) { bytes += chunk.length; if (bytes > MAX_UPLOAD) return done(new RoomError('AUDIO_UPLOAD_TOO_LARGE', 413)); hash.update(chunk); done(null, chunk); } }), createWriteStream(partial, { flags: 'wx' }));
    check(bytes > 44, 'AUDIO_EMPTY'); const duration = await probe(root, partial); await rename(partial, target);
    return { id, name, path: target, mime: mimes[extension], duration, bytes, sha256: hash.digest('hex'), builtin: 0 };
  } catch (e) { await unlink(partial).catch(() => {}); await unlink(target).catch(() => {}); throw e; }
}
export function sendAudio(req, res, track) {
  check(track && existsSync(track.path), 'AUDIO_NOT_FOUND', 404);
  const size = statSync(track.path).size; let start = 0, end = size - 1, status = 200;
  if (req.headers.range) {
    const match = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range);
    if (!match || (!match[1] && !match[2])) { res.writeHead(416, { 'Content-Range': `bytes */${size}` }); res.end(); return; }
    if (!match[1]) start = Math.max(0, size - Number(match[2])); else start = Number(match[1]);
    if (match[2] && match[1]) end = Math.min(size - 1, Number(match[2]));
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start > end || start >= size) { res.writeHead(416, { 'Content-Range': `bytes */${size}` }); res.end(); return; }
    status = 206;
  }
  res.writeHead(status, { 'Content-Type': track.mime, 'Content-Length': end - start + 1, 'Accept-Ranges': 'bytes', 'Cache-Control': 'private, max-age=3600', ...(status === 206 ? { 'Content-Range': `bytes ${start}-${end}/${size}` } : {}) });
  if (req.method === 'HEAD') return res.end();
  const stream = createReadStream(track.path, { start, end }); stream.on('error', () => res.destroy()); res.on('close', () => stream.destroy()); stream.pipe(res);
}
