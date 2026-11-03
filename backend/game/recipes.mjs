import { validate } from './protocol.mjs';
import { ensure } from './errors.mjs';

/** Validate the current server's descriptive projection; it does not authorize a craft. */
export function recipeResult(result, pending) {
  validate('RecipeResult', result);
  ensure(result.item_id === pending.recipeParams.item_id && result.requested_count === pending.recipeParams.count
    && result.based_on_seq >= pending.admittedSeq, 'GAME_RECIPE_RESULT_CONTEXT');
  ensure(Buffer.byteLength(JSON.stringify(result)) <= 51200, 'GAME_RECIPE_RESULT_TOO_LARGE');
  const ids = result.recipes.map(recipe => recipe.recipe_id);
  ensure(new Set(ids).size === ids.length && ids.every((id, i) => i === 0 || ids[i - 1] < id), 'GAME_RECIPE_RESULT_INVALID');
  ensure(result.recipe_known === (result.candidate_count > 0) && result.ambiguous === (result.candidate_count > 1)
    && result.candidate_count >= ids.length && (!result.recipe_known || ids.length > 0), 'GAME_RECIPE_RESULT_INVALID');
  const projectionUnknowns = ['unprojectable_received_recipe_outputs', 'candidate_count', 'ambiguous'];
  const incomplete = projectionUnknowns.some(field => result.unknown_fields.includes(field));
  ensure(!incomplete || (result.recipe_known && projectionUnknowns.every(field => result.unknown_fields.includes(field))),
    'GAME_RECIPE_RESULT_INVALID');
  let truncated = incomplete || result.candidate_count > ids.length;
  for (const recipe of result.recipes) {
    ensure(recipe.batches === Math.ceil(result.requested_count / recipe.output_per_batch)
      && recipe.output_for_batches === recipe.batches * recipe.output_per_batch, 'GAME_RECIPE_RESULT_INVALID');
    ensure(recipe.layout === 'shaped' ? recipe.width > 0 && recipe.height > 0
      && recipe.slots.length === recipe.width * recipe.height : recipe.width === 0 && recipe.height === 0, 'GAME_RECIPE_RESULT_INVALID');
    ensure(recipe.ingredients_known === (recipe.slots.length > 0), 'GAME_RECIPE_RESULT_INVALID');
    for (const [index, slot] of recipe.slots.entries()) {
      ensure(slot.index === index && slot.empty === (slot.alternatives_total === 0)
        && slot.alternatives_total >= slot.alternatives.length
        && (slot.empty || slot.alternatives.length > 0)
        && slot.truncated === (slot.alternatives_total > slot.alternatives.length), 'GAME_RECIPE_RESULT_INVALID');
      truncated ||= slot.truncated;
    }
  }
  ensure(result.truncated === truncated, 'GAME_RECIPE_RESULT_INVALID');
  for (const field of ['ingredient_components', 'remaining_items', 'recipe_unlock_requirements',
    'server_side_crafting_restrictions', 'inventory_allocation', 'unreceived_server_recipes', 'dynamic_recipe_outputs']) {
    ensure(result.unknown_fields.includes(field), 'GAME_RECIPE_UNKNOWNS_MISSING');
  }
  return result;
}
