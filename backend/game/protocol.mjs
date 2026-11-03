import { readFileSync } from 'node:fs';
import Ajv2020 from 'ajv/dist/2020.js';
import addFormats from 'ajv-formats';
import { GameError, ensure } from './errors.mjs';

const schema = JSON.parse(readFileSync(new URL('../../docs/technical/mc-live-v1/contracts/game.schema.json', import.meta.url), 'utf8'));
const ajv = new Ajv2020({ strict: false, allErrors: false, coerceTypes: false, removeAdditional: false });
addFormats(ajv); ajv.addSchema(schema);
const validators = new Map();
export function validate(name, value) {
  ensure(Object.hasOwn(schema.$defs, name), 'GAME_CONTRACT_TYPE_UNKNOWN', 500);
  if (!validators.has(name)) validators.set(name, ajv.compile({ $ref: schema.$id + '#/$defs/' + name }));
  const validator = validators.get(name);
  if (!validator(value)) {
    const issue = validator.errors?.[0];
    throw new GameError(issue?.keyword === 'additionalProperties' ? 'GAME_UNKNOWN_FIELD' : 'GAME_REQUEST_INVALID', 400,
      { contract: name, path: issue?.instancePath || '', rule: issue?.keyword || 'invalid' });
  }
  return value;
}
export const FROM_GAME = new Set(['hello', 'snapshot', 'delta', 'game_event', 'heartbeat', 'control_result', 'task_update', 'query_result', 'protocol_error', 'ack']);
export function parseEnvelope(data, binary = false) {
  ensure(!binary, 'GAME_BINARY_FRAME_REJECTED', 400);
  ensure(Buffer.byteLength(data) <= 131072, 'GAME_BODY_TOO_LARGE', 413);
  let value; try { value = JSON.parse(String(data)); } catch { throw new GameError('GAME_JSON_INVALID', 400); }
  validate('BridgeEnvelope', value);
  ensure(FROM_GAME.has(value.type), 'GAME_MESSAGE_DIRECTION', 400);
  return value;
}
export async function readBody(req) {
  const chunks = []; let length = 0;
  for await (const chunk of req) { length += chunk.length; ensure(length <= 131072, 'GAME_BODY_TOO_LARGE', 413); chunks.push(chunk); }
  try {
    const value = chunks.length ? JSON.parse(Buffer.concat(chunks).toString('utf8')) : {};
    ensure(value && typeof value === 'object' && !Array.isArray(value), 'GAME_REQUEST_INVALID', 400);
    return value;
  } catch (error) { if (error instanceof GameError) throw error; throw new GameError('GAME_JSON_INVALID', 400); }
}
