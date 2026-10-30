import { readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { digest } from './channel.mjs';

export function initialPersona(root, characterId) {
  if (!characterId) {
    const active = join(root, 'configs/active-character.json');
    characterId = process.env.AVATAR_CHARACTER_ID || (existsSync(active) ? JSON.parse(readFileSync(active, 'utf8')).character_id : 'female-a');
  }
  if (!/^[a-z][a-z0-9-]{0,63}$/.test(characterId)) throw new Error('CHARACTER_ID_INVALID');
  const character = JSON.parse(readFileSync(join(root, 'configs/characters', characterId + '.json'), 'utf8'));
  if (character.id !== characterId || !character.fictional || !character.name || !character.persona_prompt) throw new Error('CHARACTER_IDENTITY_MISMATCH');
  if (characterId === 'female-a' && (character.name !== '林知夏' || character.age !== 22)) throw new Error('CHARACTER_IDENTITY_MISMATCH');
  if (characterId !== 'female-a') {
    if (!Array.isArray(character.identity_fields) || !character.identity_fields.length || !Array.isArray(character.persona_sections)) throw new Error('CHARACTER_PERSONA_REQUIRED');
    const document = { schemaVersion: 1,
      identityCard: { fields: character.identity_fields, initializedAt: '2026-10-31T00:00:00.000Z', sealedAt: '2026-10-31T00:00:00.000Z' },
      mutableLayer: { sections: character.persona_sections, userDefined: [] },
    };
    return { document, version: characterId + '-v1-' + digest(document).slice(0, 12), character };
  }
  const document = { schemaVersion: 1,
    identityCard: { fields: [
      { key: '姓名', value: character.name, custom: false },
      { key: '性别', value: '女', custom: false },
      { key: '人格偏好', value: '自然、友好、独立判断的成年女大学生虚拟角色', custom: false },
      { key: '主语言', value: '简体中文', custom: false },
      { key: '角色设定', value: '虚构的22岁中国女大学生，档案女A。场景为知夏的日光宿舍，竖屏固定机位。', custom: true },
    ], initializedAt: '2026-10-24T00:00:00.000Z', sealedAt: '2026-10-24T00:00:00.000Z' },
    mutableLayer: { sections: [
      { title: '对用户称呼', items: ['自然称呼观众，不根据昵称推断长期身份。'] },
      { title: '说话风格', items: ['年轻自然的中文口语，简短、友好，有自己的判断。'] },
      { title: '交付格式', items: ['每次只给最终口播内容，通常一到三句。'] },
      { title: '行为边界', items: ['如实说明自己是虚拟角色；不把虚构学生身份说成现实经历。', '不泄露另一位观众的专属记忆，不改写已发布身份。'] },
    ], userDefined: [] },
  };
  return { document, version: characterId + '-v1-' + digest(document).slice(0, 12), character };
}
