import { createHash, timingSafeEqual } from 'node:crypto';
import { check } from './config.mjs';
export function douyinSignature(headers, body, secret) {
  const names = ['x-msg-type', 'x-nonce-str', 'x-roomid', 'x-timestamp'];
  const prefix = names.map(name => name + '=' + headers[name]).join('&');
  return createHash('md5').update(prefix).update(body).update(secret).digest('base64');
}
export function verifyDouyin(headers, rawBody, secret, now = Date.now()) {
  check(secret, 'DOUYIN_CALLBACK_NOT_CONFIGURED', 503);
  check(['x-msg-type', 'x-nonce-str', 'x-roomid', 'x-timestamp', 'x-signature'].every(name => typeof headers[name] === 'string' && headers[name].length <= 200), 'DOUYIN_CALLBACK_HEADERS_INVALID', 400);
  const expected = Buffer.from(douyinSignature(headers, rawBody, secret)), actual = Buffer.from(headers['x-signature']);
  check(actual.length === expected.length && timingSafeEqual(actual, expected), 'DOUYIN_SIGNATURE_INVALID', 400);
  check(Number.isFinite(Number(headers['x-timestamp'])) && Math.abs(now - Number(headers['x-timestamp'])) < 300000, 'DOUYIN_CALLBACK_EXPIRED', 400);
  let data; try { data = JSON.parse(rawBody.toString('utf8')); } catch { check(false, 'DOUYIN_CALLBACK_JSON_INVALID'); }
  const rows = Array.isArray(data) ? data : Array.isArray(data.data) ? data.data : [data];
  check(rows.length <= 1000, 'DOUYIN_CALLBACK_BATCH_LIMIT');
  return rows.map(row => ({ ...row, type: headers['x-msg-type'], room_id: headers['x-roomid'] }));
}
