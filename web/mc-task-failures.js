(function (root, factory) {
  const catalogue = factory();
  if (typeof module === 'object' && module.exports) module.exports = catalogue;
  else root.McTaskFailures = catalogue;
})(globalThis, function () {
  'use strict';
  // Shared read-only wording for the operator page and model facts. No retry authority.
  const reasons = Object.create(null);
  function group(codes, category, label, detail, action) {
    for (const code of codes.split(' ')) reasons[code] = Object.freeze({ code, category, label, detail, action });
  }
  group('GAME_ITEM_PLANT_TARGET_REQUIRED', 'target', '尚未指定补种位置',
    '补种需要明确选择耕地上方的空格，任务不会自行猜测位置。', '从当前可补种位置中选择后，重新核对目标。');
  group('GAME_ITEM_PLANT_SITE_UNAVAILABLE GAME_ITEM_PLANT_SITE_CHANGED', 'target', '补种位置当前不可用',
    '目标不再是可见、够得到的空耕地，或检查后位置已变化。', '核对目标位置、土壤、遮挡和距离，按新观测重新规划。');
  group('GAME_ITEM_PLANT_UNSUPPORTED GAME_ITEM_PLANTING_UNSUPPORTED', 'unsupported', '当前作物或适配器不支持补种',
    '仅已接入的适配器支持小麦、胡萝卜、土豆和甜菜的单次补种。', '核对所选作物、种子和当前游戏适配器。');
  group('GAME_STORAGE_SERVER_TIMEOUT', 'confirmation', '箱子取放确认超时',
    '服务器没有在期限内确认本次取放，任务已停止。', '核对箱内、背包和光标物品，再根据实际状态重新规划。');
  group('GAME_STORAGE_SERVER_DIVERGED GAME_STORAGE_CLICK_FAILED GAME_STORAGE_RESYNC_HOOK_MISSING GAME_STORAGE_UNEXPECTED_CLICK', 'confirmation', '箱子取放尚未确认',
    '实际库存或受控操作与计划不一致，尚未确认的搬运不计为完成。', '核对已有搬运与光标物品，保留原任务证据后再处理。');
  group('GAME_STORAGE_MATERIALS_MISSING', 'materials', '箱子取放缺少所需物品',
    '当前箱子或背包没有本次取放所需的物品。', '检查目标容器、任务数量与可用来源后重新规划。');
  group('GAME_STORAGE_DESTINATION_FULL', 'inventory', '箱子或背包没有足够空间',
    '本次搬运找不到可接收物品的兼容空位。', '整理对应容器或背包；取放过程不会自动丢弃物品腾位。');
  group('GAME_STORAGE_CONTEXT_CHANGED GAME_STORAGE_GUI_BUSY', 'context', '箱子取放条件已变化',
    '原任务的控制、世界、玩家或容器界面已变化，或另有库存操作尚未结束。', '核对任务和实际库存，等待操作结束后重新规划。');
  group('GAME_STORAGE_TARGET_INVALID GAME_STORAGE_STATE_INVALID GAME_STORAGE_MOVE_INVALID GAME_STORAGE_UNSUPPORTED GAME_STORAGE_COMPONENT_LIMIT', 'unsupported', '当前箱子取放不受支持',
    '本次目标、容器类型、物品组件或槽位未满足受控取放条件。', '核对普通箱子、陷阱箱、木桶及目标数量；其他容器仍需独立接入。');
  group('GAME_RESOURCE_MATERIAL_RESERVED', 'materials', '物品正由当前任务保留',
    '本次放置或丢弃会消耗当前任务仍需保留的物品，操作已停止。', '核对任务目标与实际库存，补齐可用材料后重新规划；不要将已有部分效果视作撤销。');
  group('GAME_CRAFT_MATERIALS_MISSING GAME_RESOURCE_CRAFT_MATERIALS_UNAVAILABLE GAME_RESOURCE_MATERIAL_UNAVAILABLE',
    'materials', '合成材料尚未备齐', '本次合成所需的材料仍有缺口，或当前采集方式无法补齐。', '核对当前库存与材料来源后重新规划。');
  group('GAME_RESOURCE_MATERIAL_UNCATALOGUED', 'materials', '材料尚无可用获取方式',
    '执行器没有找到适用于这项材料的获取方式。', '核对材料种类、可用资源与配方后调整目标。');
  group('GAME_RESOURCE_MATERIAL_NO_PROGRESS', 'materials', '材料收集没有进展',
    '子任务结束后，所需材料数量没有增加，当前库存下可用来源已尝试。', '检查资源是否可达、背包是否已满，并核对游戏现况。');
  group('GAME_RESOURCE_MATERIAL_CYCLE', 'materials', '材料依赖出现循环',
    '同一祖先任务链在库存数量未变化时再次请求了相同材料来源。', '核对配方依赖与可用材料来源，调整目标后重新规划。');
  group('GAME_MATERIAL_HOLD_UNAVAILABLE GAME_MATERIAL_RESERVATION_CHANGED', 'reservation', '预留材料已变化',
    '已登记的成品或材料预留无法继续满足，当前分配已停止。', '核对库存与其他任务需求，再重新规划材料分配。');
  group('GAME_RESOURCE_CRAFT_SEARCH_LIMIT GAME_RESOURCE_MATERIAL_SELECTION_LIMIT GAME_MATERIAL_ALLOCATION_LIMIT GAME_MATERIAL_REQUIREMENT_LIMIT GAME_MATERIAL_RESERVATION_LIMIT GAME_CRAFT_COMPONENT_BUDGET',
    'budget', '材料或合成计算达到上限', '这次任务已达到预设的材料分配、子任务选择或物品组件处理上限。', '核对配方依赖与目标数量，调整任务后重新规划。');
  group('GAME_RESOURCE_MATERIAL_TARGET_AMBIGUOUS GAME_CRAFT_RECIPE_AMBIGUOUS', 'recipe', '配方或目标存在冲突',
    '当前目标对应多项无法唯一确定的配方或材料需求。', '确认要使用的配方与产物后再继续。');
  group('GAME_CRAFT_RECIPE_UNAVAILABLE', 'recipe', '当前没有可用配方',
    '当前收到的配方中没有适用于本次目标的可执行配方。', '检查配方、工作台条件和目标物品。');
  group('GAME_CRAFT_WORKSTATION_UNAVAILABLE', 'recipe', '附近没有可用工作台',
    '本次合成需要普通工作台，当前加载范围内没有可见且够得到的工作台。', '放置或靠近普通工作台后，结合实际库存重新规划。');
  group('GAME_CRAFT_RECIPE_CHANGED GAME_CRAFT_RECIPE_NO_LONGER_MATCHES GAME_CRAFT_DYNAMIC_OUTPUT_CHANGED GAME_CRAFT_RESULT_CHANGED',
    'recipe', '合成配方或产物已变化', '执行期间的配方、匹配条件或产物与原计划不一致。', '核对当前配方与已产生物品，按新观测重新规划。');
  group('GAME_CRAFT_MATERIAL_CHANGED GAME_CRAFT_COMPONENT_CHANGED GAME_CRAFT_ALLOCATION_EXHAUSTED GAME_CRAFT_SOURCE_EMPTY',
    'inventory', '合成用料已变化', '原计划使用的物品数量、组件或所在材料槽已不能满足本次操作。', '检查材料与当前合成界面，按最新库存重新规划。');
  group('GAME_CRAFT_DESTINATION_FULL GAME_CRAFT_OUTPUT_SPACE_UNAVAILABLE', 'inventory', '背包没有足够空间',
    '没有足够空间安放本次产物、材料或容器余物。', '在游戏中整理背包并核对光标物品后再继续。');
  group('GAME_RESOURCE_CRAFT_CURSOR_BUSY GAME_RESOURCE_CRAFT_GRID_BUSY GAME_CRAFT_GRID_NOT_EMPTY GAME_CRAFT_GUI_BUSY',
    'interface', '合成界面仍有物品或正在使用', '当前光标、合成格或界面不满足本次任务的开始条件。', '核对光标、合成格和物品归属，清理后重新规划。');
  group('GAME_CRAFT_SERVER_TIMEOUT', 'confirmation', '合成确认超时',
    '等待服务器确认受控点击时超过时限，任务已停止。', '核对实际库存、光标和合成格；已有产物按任务证据处理。');
  group('GAME_CRAFT_SERVER_DIVERGED GAME_CRAFT_SERVER_PACKET_INVALID GAME_CRAFT_RESULT_NOT_CONFIRMED GAME_CRAFT_CLEANUP_NOT_CONFIRMED',
    'confirmation', '合成结果尚未确认', '服务器状态与预期不一致，或产物与收尾状态没有得到完整确认。', '先核对游戏实际变化与已有回执，再决定如何继续。');
  group('GAME_CRAFT_CONTEXT_CHANGED GAME_RESOURCE_CRAFT_CONTEXT_CHANGED GAME_RESOURCE_MATERIAL_CONTEXT_CHANGED GAME_CRAFT_HANDLER_CHANGED GAME_CRAFT_REVOKED',
    'context', '合成执行条件已变化', '原任务绑定的控制、世界、玩家或界面条件已不再成立。', '等待控制与游戏状态稳定，重新核对后再规划。');
  group('GAME_CRAFT_CLICK_FAILED GAME_CRAFT_STATE_CHANGED GAME_CRAFT_UNEXPECTED_CLICK GAME_CRAFT_RESYNC_HOOK_MISSING',
    'confirmation', '本次合成操作未能继续', '受控点击或状态同步未满足执行条件，任务已停止。', '检查实际库存、光标与任务证据后再处理。');
  group('GAME_RESOURCE_CRAFT_RECIPE_SET_INVALID GAME_CRAFT_ALLOCATION_INVALID GAME_CRAFT_GRID_INVALID GAME_CRAFT_HANDLER_INVALID GAME_CRAFT_INGREDIENT_INVALID GAME_CRAFT_INVENTORY_INVALID GAME_CRAFT_OUTPUT_COUNT_INVALID GAME_CRAFT_REMAINDER_INVALID GAME_CRAFT_STACK_INVALID GAME_CRAFT_STEP_INVALID GAME_MATERIAL_REQUIREMENT_INVALID GAME_MATERIAL_RESERVATION_INVALID GAME_MATERIAL_STOCK_INVALID GAME_RESOURCE_CRAFT_TARGET_INVALID',
    'unsupported', '当前合成或材料目标不受支持', '目标、配方、物品或界面数据未通过本次执行检查。', '核对目标与游戏现况，查看任务编号后调整配置或配方。');
  group('GAME_RESOURCE_SMELTING_RECIPE_UNSUPPORTED', 'recipe', '熔炼配方暂不受支持',
    '实际配方的产量、烹饪时间或材料条件超出本次受控转换范围。', '核对服务器配方、输入组件和炉具类型后调整目标。');
  group('GAME_RESOURCE_SMELTING_FUEL_UNAVAILABLE', 'materials', '熔炼燃料尚未备齐',
    '没有可供本次转换使用的足量普通燃料，或获取后仍未满足要求。', '核对燃料种类、已有预留和每份燃料的燃烧时长。');
  group('GAME_COOKING_WORKSTATION_UNAVAILABLE', 'workstation', '附近没有可用的对应炉具',
    '当前已加载且能够触及的位置没有本配方所需的熔炉、高炉或烟熏炉。', '先准备对应炉具并确认能够正常打开，再根据最新游戏观测提交新任务。'),
  group('GAME_COOKING_SERVER_TIMEOUT', 'confirmation', '炉内转换确认超时',
    '本次转换未在固定期限内收到完整库存或预期产物确认。', '核对炉内原料、燃料、产物和光标，再根据实际状态重新规划。');
  group('GAME_COOKING_SERVER_DIVERGED GAME_COOKING_SERVER_PACKET_INVALID GAME_COOKING_STATE_CHANGED GAME_COOKING_OPENING_CHANGED', 'confirmation', '炉内库存状态不一致',
    '服务器库存、光标或炉内状态与已捕获的转换计划不一致。', '核对已有产物和剩余物，保留原任务证据后重新规划。');
  group('GAME_COOKING_CONTEXT_CHANGED GAME_COOKING_REVOKED GAME_COOKING_HANDLER_CHANGED GAME_COOKING_HANDLER_INVALID GAME_COOKING_OWNER_CONFLICT', 'context', '炉具执行条件已变化',
    '原任务、世界、玩家、连接或已绑定炉具界面不再满足执行条件。', '核对控制状态、炉具和任务归属，按最新游戏现况处理。');
  group('GAME_COOKING_MATERIAL_CHANGED GAME_COOKING_INITIAL_STATE_INVALID GAME_COOKING_CLEANUP_REQUIRED', 'inventory', '炉内用料或回收条件不满足',
    '当前原料、燃料、炉内物品或光标不满足开始和收尾条件。', '检查预留材料与炉内余物，确认库存后再重新规划。');
  group('GAME_COOKING_GUI_BUSY GAME_COOKING_UNEXPECTED_CLICK GAME_COOKING_RESYNC_HOOK_MISSING GAME_COOKING_MOVE_INVALID GAME_COOKING_SLOT_INVALID', 'interface', '炉具操作条件不满足',
    '受控炉具操作与当前确认阶段或槽位规则不一致，任务已停止。', '核对炉具界面和任务记录，避免在未确认状态下继续操作。');
  group('GAME_COOKING_COMPONENT_BUDGET', 'budget', '炉内物品组件达到上限',
    '本次炉内事务捕获的物品组件种类超过预设处理上限。', '核对实际物品组件与任务规模后调整目标。');
  group('GAME_EXECUTOR_FAILED GAME_EXECUTOR_START_FAILED', 'executor', '游戏任务执行异常',
    '本次执行发生未分类异常，无法据此判定游戏效果。', '核对游戏现况、任务证据和故障记录。');
  group('TASK_TIMEOUT', 'timeout', '游戏任务超时', '任务未在规定时间内完成。', '核对实际进度与已有产物后重新规划。');
  group('GAME_EFFECT_NOT_VERIFIED', 'confirmation', '任务效果尚未验证',
    '执行器已结束，但后续观测尚不能证明目标完全实现。', '根据证据与游戏现况处理，不能将任务记为完成。');
  function describe(code) { return typeof code === 'string' ? reasons[code] || null : null; }
  function facts(task) {
    const failure = task && ['failed', 'cancelled'].includes(task.state) && describe(task.reason);
    return failure ? { ...task, execution_failure: { ...failure } } : task;
  }
  return Object.freeze({ describe, facts });
});
