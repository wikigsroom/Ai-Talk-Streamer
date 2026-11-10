import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';

// One public, versioned model contract. Credentials remain in the private file.
export function loadIsaacModel(root) {
  const value=JSON.parse(readFileSync(resolve(root,'configs/issac/core-model.json'),'utf8'));
  const integers=['context_window_tokens','max_output_tokens','context_reserve_tokens','max_serialized_message_bytes'];
  if(value.schema_version!==1||value.provider!=='deepseek-official'||value.model!=='deepseek-flash'
      ||value.protocol!=='responses'||value.base_url!=='https://api.deepseek.com'
      ||value.channel_source!=='issac_user_pinned_official_api'||value.reasoning_effort!=='low'
      ||value.private_configuration!=='private/issac/channel.env'
      ||integers.some(key=>!Number.isSafeInteger(value[key])||value[key]<=0)
      ||value.context_window_tokens>2000000||value.max_output_tokens>value.context_window_tokens
      ||value.context_reserve_tokens<4096||value.max_serialized_message_bytes>128*1024*1024
      ||value.max_serialized_message_bytes<value.context_window_tokens*4)
    throw Error('ISAAC_MODEL_PROFILE_INVALID');
  const inputBudget=value.context_window_tokens-value.max_output_tokens-value.context_reserve_tokens;
  if(inputBudget<14000)throw Error('ISAAC_MODEL_CONTEXT_RESERVE_INVALID');
  return Object.freeze({...value,max_input_estimated_tokens:inputBudget});
}
