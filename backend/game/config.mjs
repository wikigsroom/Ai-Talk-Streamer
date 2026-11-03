import { readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { ensure } from './errors.mjs';
import { NARRATION_DEFAULTS } from './narration-scheduler.mjs';
import { INTENT_DEFAULTS } from './audience-intents.mjs';

export const DEFAULT_CONFIG = Object.freeze({ schema_version: 1, enabled: false,
  planner: { enabled: false, engine: 'mindcraft_native', autostart: false, min_interval_ms: 3000, max_call_ms: 30000, candidate_limit: 16 },
  control: { state_stale_ms: 2000, heartbeat_ms: 1000, lease_ttl_ms: 3000,
    accept_within_ms: 1500, max_task_duration_ms: 120000, enabled_skills: [] },
  programme: { layout_id: 'mc-landscape-v1', avatar_variant: 'circle', comment_mode: 'feed', scene: 'play' },
  narration: { ...NARRATION_DEFAULTS },
  audience_intents: { ...INTENT_DEFAULTS },
  vision: { enabled: false, max_concurrency: 1, min_interval_ms: 1000, timeout_ms: 8000 } });

export function validateRelations(config) {
  ensure(config.control.lease_ttl_ms >= 3 * config.control.heartbeat_ms, 'GAME_CONFIG_LEASE_TOO_SHORT', 400);
  ensure(config.control.accept_within_ms <= config.control.state_stale_ms, 'GAME_CONFIG_ACCEPT_WINDOW', 400);
  return config;
}
export function applyPatch(config, patch) {
  const next = structuredClone(config);
  next.planner = { engine: 'mindcraft_native', autostart: false, ...next.planner };
  next.narration = { ...NARRATION_DEFAULTS, ...next.narration };
  next.audience_intents = { ...INTENT_DEFAULTS, ...next.audience_intents };
  for (const [key, value] of Object.entries(patch)) {
    if (value && typeof value === 'object' && !Array.isArray(value)) next[key] = { ...next[key], ...value };
    else next[key] = value;
  }
  return validateRelations(next);
}
export function initialConfig(root, validate) {
  const file = join(root, 'configs/mc-game.json');
  const config = existsSync(file) ? JSON.parse(readFileSync(file, 'utf8')) : structuredClone(DEFAULT_CONFIG);
  validate('GameConfig', config); return applyPatch(config, {});
}
