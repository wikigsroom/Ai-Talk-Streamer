"""Check the non-installable controlled survival engineering artifact, never start a game."""
from __future__ import annotations
from collections import Counter
from pathlib import Path
import csv
import hashlib
import json
import xml.etree.ElementTree as ET
import zipfile
import mc_prepare_survival as prepare

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / 'game-adapters/minecraft/survival'
OUTPUT = ROOT / 'outputs/mc-validation/survival-build-receipt.json'
SHA = lambda data: hashlib.sha256(data).hexdigest()


def verify_transform(mode: str, preparation: dict) -> dict:
    report_path = PROJECT / f'build/reports/control/{mode}-gates.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    policy_path = PROJECT / 'gate-policy.json'
    mapping = ROOT / '.setup/mc-gradle/caches/fabric-loom/1.21.1/net.fabricmc.yarn.1_21_1.1.21.1+build.3-v2/mappings-base.tiny'
    if (report['classification'] != 'ENGINEERING_BYTECODE_TRANSFORM_NOT_RUNTIME_ACCEPTANCE'
            or report['automatic_input_authorized'] is not False
            or report['namespace'] != ('intermediary' if mode == 'baritone' else 'named')
            or report['policy_sha256'] != SHA(policy_path.read_bytes())
            or report['mapping_sha256'] != SHA(mapping.read_bytes())
            or report.get('callback_compiler_revision') != 2
            or not report['classes'] or not report['sites']):
        raise ValueError('MC_SURVIVAL_GATE_RECEIPT_INVALID')
    paths = [row['path'] for row in report['classes']]
    if len(paths) != len(set(paths)):
        raise ValueError('MC_SURVIVAL_GATE_CLASS_DUPLICATE')
    hotbar_owner, hotbar_field = ('net/minecraft/class_1661', 'field_7545') if mode == 'baritone' else ('net/minecraft/entity/player/PlayerInventory', 'selectedSlot')
    hotbar = [row for row in report['sites'] if (row['kind'], row['owner'], row['member'], row['descriptor'])
              == ('FIELD', hotbar_owner, hotbar_field, 'I')]
    if len(hotbar) != (7 if mode == 'baritone' else 1) or any(row['route'] != 'select' for row in hotbar):
        raise ValueError('MC_SURVIVAL_HOTBAR_OWNERSHIP_ROUTE_MISSING')
    actions = Counter(row['route'] for row in report['sites'] if row['route'].startswith('action_'))
    expected_actions = ({'action_yaw':5, 'action_pitch':7, 'action_attackEntity':1, 'action_swing':3,
                         'action_interactItem':2, 'action_interactEntity':3, 'action_stopUsing':1}
                        if mode == 'main' else
                        {'action_yaw':6, 'action_pitch':5, 'action_sprint':1, 'action_swing':3,
                         'action_attackBlock':1, 'action_cancelBreaking':1, 'action_interactItem':1, 'action_breakProgress':1})
    if actions != expected_actions:
        raise ValueError('MC_SURVIVAL_TYPED_INTERACTION_ROUTES_MISSING')
    options = Counter(row['route'] for row in report['sites'] if row['route'].startswith('option_'))
    if options != ({'option_value': 2, 'option_pauseOnLostFocus': 1} if mode == 'main' else {'option_value': 2}):
        raise ValueError('MC_SURVIVAL_OWNED_OPTION_ROUTES_MISSING')
    sneaking = [row for row in report['sites'] if row['route'] == 'sneaking']
    if len(sneaking) != (2 if mode == 'main' else 0):
        raise ValueError('MC_SURVIVAL_OWNED_SNEAK_ROUTES_MISSING')
    if mode == 'baritone':
        original = ROOT / '.setup/mc-survival/baritone-unoptimized-fabric-1.21.1.jar'
        controlled = PROJECT / 'build/controlled/maven/dev/aitalkstreamer/pinned/baritone-controlled/1.21.1-ats.2/baritone-controlled-1.21.1-ats.2.jar'
        callbacks = report.get('callback_sites', [])
        if (len(callbacks) != 23 or Counter(row['origin'] for row in callbacks) != {
                'baritone/event/GameEventHandler': 17, 'baritone/utils/PlayerMovementInput': 3,
                'baritone/behavior/PathingBehavior': 3} or len({(r['origin'], r['method']) for r in callbacks}) != 23):
            raise ValueError('MC_SURVIVAL_CALLBACK_TRANSFORMS_MISSING')
        expected = next(row['sha256'] for row in preparation['embedded_artifacts']
                        if row['entry'].endswith('/baritone-unoptimized-fabric-1.21.1.jar'))
        if (report['input_sha256'] != expected or SHA(original.read_bytes()) != expected
                or SHA(controlled.read_bytes()) != report['output_sha256']
                or report['output_sha256'] == expected):
            raise ValueError('MC_SURVIVAL_CONTROLLED_BARITONE_PROVENANCE')
        with zipfile.ZipFile(original) as before, zipfile.ZipFile(controlled) as after:
            for name, markers in {
                'baritone/event/GameEventHandler': [b'SurvivalCallbacks', b'register'],
                'baritone/utils/PlayerMovementInput': [b'$ats$callback$binding', b'$ats$callback$zero', b'SurvivalCallbacks'],
                'baritone/behavior/PathingBehavior': [b'$ats$callback$pathCommit', b'SurvivalAsync', b'atsClearRootEvents', b'SurvivalOptions']
            }.items():
                if any(marker not in after.read(name + '.class') for marker in markers):
                    raise ValueError('MC_SURVIVAL_CALLBACK_CLASS_MISSING')
            expected_paths = {name for name in before.namelist() if name.endswith('.class')}
            if set(paths) != expected_paths or set(after.namelist()) != {n for n in before.namelist() if not n.endswith('/')}:
                raise ValueError('MC_SURVIVAL_GATE_CLASS_SET')
            for row in report['classes']:
                if SHA(before.read(row['path'])) != row['before'] or SHA(after.read(row['path'])) != row['after']:
                    raise ValueError('MC_SURVIVAL_GATE_CLASS_HASH')
            for name in before.namelist():
                if not name.endswith(('.class', '/')) and before.read(name) != after.read(name):
                    raise ValueError('MC_SURVIVAL_BARITONE_RESOURCE_CHANGED')
    else:
        if report.get('callback_sites') != []:
            raise ValueError('MC_SURVIVAL_UNEXPECTED_SOURCE_CALLBACK_PATCH')
        original = PROJECT / 'build/classes/java/main'
        controlled = PROJECT / 'build/controlled/main'
        expected_paths = {path.relative_to(original).as_posix() for path in original.rglob('*') if path.is_file()}
        if set(paths) != expected_paths:
            raise ValueError('MC_SURVIVAL_GATE_CLASS_SET')
        with zipfile.ZipFile(PROJECT / 'build/controlled/devlibs/altoclef-controlled-1.21.1-0.19+ats.1-controlled-dev.jar') as development:
            for row in report['classes']:
                if (SHA((original / row['path']).read_bytes()) != row['before']
                        or SHA((controlled / row['path']).read_bytes()) != row['after']
                        or SHA(development.read(row['path'])) != row['after']):
                    raise ValueError('MC_SURVIVAL_GATE_CLASS_HASH')
        controls = (controlled / 'adris/altoclef/control/InputControls.class').read_bytes()
        if (b'SurvivalInputs' not in controls or b'onKeyPressed' in controls or b'getDefaultKey' in controls
                or b'clearControlledQueue' not in controls or b'requireOwnerScope' not in controls):
            raise ValueError('MC_SURVIVAL_RAW_KEY_QUEUE_REMAINING')
        subscription = (controlled / 'adris/altoclef/eventbus/Subscription.class').read_bytes()
        if b'subscriber' not in subscription or b'dev/aitalkstreamer/mc/survival/SurvivalAuthority' not in subscription:
            raise ValueError('MC_SURVIVAL_UNSCOPED_TASK_SUBSCRIPTIONS')
        for name in ['adris/altoclef/multiversion/OptionsVer', 'adris/altoclef/BotBehaviour$State']:
            if b'dev/aitalkstreamer/mc/survival/SurvivalOptions' not in (controlled / (name + '.class')).read_bytes():
                raise ValueError('MC_SURVIVAL_UNOWNED_UPSTREAM_OPTIONS')
    return {'report': report_path.relative_to(ROOT).as_posix(), 'sha256': SHA(report_path.read_bytes()),
            'namespace': report['namespace'], 'policy_sha256': report['policy_sha256'],
            'mapping_sha256': report['mapping_sha256'], 'classes': len(report['classes']),
            'transformed_classes': len({row['origin'] for row in report['sites']}),
            'sites': len(report['sites']), 'routes': dict(Counter(row['route'] for row in report['sites'])),
            'owned_hotbar_sites': len(hotbar),
            'typed_interaction_sites': sum(actions.values()), 'typed_interaction_routes': dict(actions),
            'owned_option_sites': sum(options.values()), 'owned_option_routes': dict(options),
            'owned_sneak_sites': len(sneaking),
            'output_sha256': report.get('output_sha256'),
            'input_sha256': report.get('input_sha256'),
            'coverage': 'EXPLICIT_SELECTED_SITES_NOT_COMPLETE_RUNTIME_COVERAGE'}


def verify_build() -> dict:
    preparation = prepare.verify()
    gates = {mode: verify_transform(mode, preparation) for mode in ['main', 'baritone']}
    bridge_jar = ROOT / 'game-adapters/minecraft/fabric/build/libs/ai-talk-streamer-mc-bridge-0.1.0.jar'
    with zipfile.ZipFile(bridge_jar) as bridge:
        mixins = json.loads(bridge.read('mc-bridge.mixins.json'))
        if mixins['client'].count('MinecraftInputInvoker') != 1 or mixins['client'].count('KeyBindingAccessor') != 1:
            raise ValueError('MC_SURVIVAL_NATIVE_INPUT_MIXIN_MISSING')
        refmap = json.loads(bridge.read(mixins['refmap']))
        mappings = refmap['data']['named:intermediary']
        prefix = 'dev/aitalkstreamer/mc/mixin/'
        if (mappings[prefix + 'MinecraftInputInvoker'] != {'doAttack': 'method_1536()Z', 'doItemUse': 'method_1583()V'}
                or mappings[prefix + 'KeyBindingAccessor']['boundKey'] != 'field_1655:Lnet/minecraft/class_3675$class_306;'):
            raise ValueError('MC_SURVIVAL_NATIVE_INPUT_REFMAP')
        held = mappings[prefix + 'HeldInputMixin']
        expected_held = {'doAttack':'method_1536()Z', 'doItemUse':'method_1583()V', 'handleBlockBreaking':'method_1590(Z)V'}
        if (set(held) != set(expected_held) or any(not held[k].endswith(v) for k,v in expected_held.items())
                or mixins['client'].count('HeldInputMixin') != 1):
            raise ValueError('MC_SURVIVAL_HELD_INPUT_REFMAP')
        craft_click = mappings[prefix + 'CraftClickMixin']
        packet_constructor = 'Lnet/minecraft/network/packet/c2s/play/ClickSlotC2SPacket;<init>(IIIILnet/minecraft/screen/slot/SlotActionType;Lnet/minecraft/item/ItemStack;Lit/unimi/dsi/fastutil/ints/Int2ObjectMap;)V'
        if (craft_click['clickSlot'] != 'Lnet/minecraft/class_636;method_2906(IIILnet/minecraft/class_1713;Lnet/minecraft/class_1657;)V'
                or craft_click[packet_constructor] != 'Lnet/minecraft/class_2813;<init>(IIIILnet/minecraft/class_1713;Lnet/minecraft/class_1799;Lit/unimi/dsi/fastutil/ints/Int2ObjectMap;)V'
                or mappings[prefix + 'InventorySyncMixin']['onInventory'] != 'Lnet/minecraft/class_634;method_11153(Lnet/minecraft/class_2649;)V'
                or not {'CraftClickMixin', 'InventorySyncMixin'}.issubset(set(mixins['client']))):
            raise ValueError('MC_SURVIVAL_NATIVE_CRAFT_REFMAP')
        if (mappings[prefix + 'ItemUseSyncMixin'] != {
                    'onHealthUpdate': 'Lnet/minecraft/class_634;method_11122(Lnet/minecraft/class_2749;)V',
                    'onBlockUpdate': 'Lnet/minecraft/class_634;method_11136(Lnet/minecraft/class_2626;)V',
                    'onChunkDeltaUpdate': 'Lnet/minecraft/class_634;method_11100(Lnet/minecraft/class_2637;)V'}
                or mappings[prefix + 'ItemUseRepeatMixin'] != {'doItemUse': 'Lnet/minecraft/class_310;method_1583()V'}
                or not {'ItemUseSyncMixin', 'ItemUseRepeatMixin'}.issubset(set(mixins['client']))):
            raise ValueError('MC_SURVIVAL_NATIVE_ITEM_REFMAP')
        for name in ['InputOwner', 'InputOwner$Scope', 'core/NativeContext', 'core/InputLeaseFence', 'core/OwnedValue', 'core/HotbarSelection', 'core/InputLedger', 'core/InventoryTarget', 'core/BaseTarget', 'core/TaskGuiLease', 'core/CraftReceipt', 'mixin/MinecraftInputInvoker', 'mixin/CraftClickMixin', 'mixin/InventorySyncMixin']:
            if not bridge.read('dev/aitalkstreamer/mc/' + name + '.class').startswith(bytes.fromhex('cafebabe')):
                raise ValueError('MC_SURVIVAL_NATIVE_INPUT_CLASS')
        for name in ['core/HeldActionRouter', 'core/HeldActionRouter$Action', 'mixin/HeldInputMixin', 'NativeItemUse', 'core/InventoryExchange', 'core/ItemUseReceipt', 'mixin/ItemUseSyncMixin', 'mixin/ItemUseRepeatMixin']:
            if not bridge.read('dev/aitalkstreamer/mc/' + name + '.class').startswith(bytes.fromhex('cafebabe')):
                raise ValueError('MC_SURVIVAL_NATIVE_ITEM_CLASS')
        if not bridge.read('dev/aitalkstreamer/mc/core/OwnedFlag.class').startswith(bytes.fromhex('cafebabe')):
            raise ValueError('MC_SURVIVAL_NATIVE_SNEAK_OWNER_MISSING')
        input_owner = bridge.read('dev/aitalkstreamer/mc/InputOwner.class')
        if any(marker not in input_owner for marker in (b'OwnedFlag', b'sneaking', b'GAME_PLAYER_INPUT_CONTEXT')):
            raise ValueError('MC_SURVIVAL_NATIVE_SNEAK_BINDING_MISSING')
    jar = PROJECT / 'build/libs/altoclef-controlled-1.21.1-0.19+ats.1.jar'
    required = ['SurvivalAuthority', 'SurvivalAuthority$Session', 'ArbiterBoundary', 'ControlledTaskFactory',
                'ControlledAltoClefDriver', 'ControlledTaskRunner', 'SurvivalInputs', 'SurvivalLaunchGuard',
                'SurvivalCallbacks', 'SurvivalCallbacks$Binding', 'SurvivalCallbacks$RootResettable', 'SurvivalAsync', 'SurvivalAsync$State',
                'SurvivalGameExecutor', 'CraftPlan', 'CraftPlan$Plan', 'SurvivalGui', 'SurvivalGui$Binding',
                'CraftSpec', 'CraftClicks', 'CraftClicks$Confirmation', 'ConfirmedCraftTask',
                'SurvivalActions', 'SurvivalActions$Binding', 'InteractionLedger', 'InteractionLedger$Kind',
                'SupplyPolicy', 'SupplyPolicy$Facts', 'SupplyPolicy$Limits', 'SupplyPolicy$Decision', 'ControlledSupplyTask', 'ControlledCookingTask', 'ControlledFoodCookingTask', 'ControlledCookingTask$OpenWorkstation', 'CookingWorkstation', 'ControlledSmeltingTask', 'SmeltingPlan', 'SmeltingPlan$Goal', 'SurvivalGui$FurnaceSnapshot', 'CookingExchange', 'ControlledEatingTask', 'EatingBudget', 'FoodInventory', 'ControlledEquipment', 'EquipmentPlan', 'EquipmentExchange', 'ControlledShield', 'ShieldCycle', 'ShieldCycle$Source', 'ShieldCycle$Action', 'ResourceRecipePlan', 'ResourceRecipePlan$Box', 'ControlledResourceCraftTask', 'ControlledResourceCraftTask$OpenTable', 'MaterialAllocation', 'MaterialAllocation$Need', 'MaterialAllocation$Assigned', 'MaterialAllocation$Result', 'MaterialAllocation$Edge', 'MaterialAllocation$Limit', 'MaterialAllocation$Budget', 'MaterialTargets', 'ResourceMaterialsPlan', 'ResourceMaterialsPlan$Stock', 'ResourceMaterialsPlan$Goal', 'ResourceMaterialsPlan$Request', 'ResourceMaterialsPlan$Plan', 'MaterialReservations', 'ResourceMaterials', 'ControlledMaterialUse', 'ResourceMaterials$State', 'ResourceAcquisitionPlan', 'ResourceAcquisitionPlan$Kind', 'ResourceAcquisitionPlan$Source', 'ResourceAcquisitionPlan$Choice', 'ResourceAcquisitionPlan$Claim', 'ResourceAcquisitionPlan$Failed', 'ResourceAcquisitionPlan$Failure', 'ResourceBranchRecovery', 'SurvivalAsync$Work', 'SurvivalAsync$Result', 'ControlledRecipeResourcesTask', 'ControlledRecipeResourcesTask$Intent']
    required += ['ControlledStorage', 'ControlledStorage$Entry', 'StorageExchange', 'StorageExchange$State', 'StorageExchange$Step', 'StorageLedger', 'StorageObservers', 'StorageObservers$Watch', 'SurvivalGui$StorageSite', 'SurvivalGui$ContainerSnapshot', 'SurvivalOptions', 'SurvivalOptions$Binding', 'SettingLease']
    with zipfile.ZipFile(jar) as archive:
        names = archive.namelist()
        if len(set(names)) != len(names) or any(n.endswith('Test.class') or '/audit/' in n for n in names):
            raise ValueError('MC_SURVIVAL_PACKAGE_TEST_OR_DUPLICATE_CLASS')
        for name in required:
            data = archive.read('dev/aitalkstreamer/mc/survival/' + name + '.class')
            if data[:4] != bytes.fromhex('cafebabe') or int.from_bytes(data[6:8]) != 65:
                raise ValueError('MC_SURVIVAL_PACKAGE_JAVA_21')
        if 'dev/aitalkstreamer/mc/core/ControlArbiter.class' in names:
            raise ValueError('MC_SURVIVAL_DUPLICATE_NATIVE_ARBITER')
        mod = json.loads(archive.read('fabric.mod.json'))
        if mod['id'] != 'altoclef' or mod['version'] != '1.21.1-0.19+ats.1':
            raise ValueError('MC_SURVIVAL_PORT_PROVIDER_METADATA_INVALID')
        if mod['entrypoints']['preLaunch'] != ['dev.aitalkstreamer.mc.survival.SurvivalLaunchGuard']:
            raise ValueError('MC_SURVIVAL_LAUNCH_GUARD_MISSING')
        if mod['entrypoints'].get('ai_talk_streamer_executor') != ['dev.aitalkstreamer.mc.survival.SurvivalGameExecutor']:
            raise ValueError('MC_SURVIVAL_PORT_BINDING_MISSING')
        if b'dev/aitalkstreamer/mc/ClientExecutor' not in archive.read('dev/aitalkstreamer/mc/survival/SurvivalGameExecutor.class'):
            raise ValueError('MC_SURVIVAL_PORT_INTERFACE_MISSING')
        gui = archive.read('dev/aitalkstreamer/mc/survival/SurvivalGui.class')
        if any(marker not in gui for marker in (b'TaskGuiLease', b'SurvivalAuthority', b'beforeUse', b'finishOwned', b'GAME_GUI_SYNC_CHANGED', b'GAME_CRAFT_RECIPE_CHANGED')):
            raise ValueError('MC_SURVIVAL_GUI_BINDING_MISSING')
        actions = archive.read('dev/aitalkstreamer/mc/survival/SurvivalActions.class')
        options = archive.read('dev/aitalkstreamer/mc/survival/SurvivalOptions.class')
        if any(marker not in options for marker in (b'SurvivalAuthority', b'SettingLease', b'GAME_OPTION_CONTEXT_CHANGED',
                b'GAME_OPTION_NO_TASK', b'checkpoint', b'GAME_OPTION_VALUE_INVALID')):
            raise ValueError('MC_SURVIVAL_OWNED_CLIENT_OPTIONS_MISSING')
        driver = archive.read('dev/aitalkstreamer/mc/survival/ControlledAltoClefDriver$1.class')
        if b'SurvivalOptions' not in driver or b'checkpoint' not in driver:
            raise ValueError('MC_SURVIVAL_CLIENT_OPTIONS_CHECKPOINT_MISSING')
        if any(marker not in actions for marker in (b'SurvivalAuthority', b'InteractionLedger', b'GAME_ACTION_ENTITY_CHANGED',
                b'GAME_ACTION_BLOCK_OUT_OF_REACH', b'finishOwned', b'requireOwnerScope')):
            raise ValueError('MC_SURVIVAL_TYPED_INTERACTION_BINDING_MISSING')
        defense = archive.read('dev/aitalkstreamer/mc/survival/ControlledDefenseTask.class')
        if any(marker not in defense for marker in (b'DefensePolicy', b'KillEntityTask', b'RunAwayFromHostilesTask', b'SurvivalAuthority', b'LocalTaskFailure')):
            raise ValueError('MC_SURVIVAL_CONTROLLED_DEFENSE_MISSING')
        for control_class in ['DefensePolicy', 'DefensePolicy$Facts', 'DefensePolicy$Limits', 'DefensePolicy$Decision', 'AttackPacer']:
            if not archive.read('dev/aitalkstreamer/mc/survival/' + control_class + '.class'):
                raise ValueError('MC_SURVIVAL_DEFENSE_CONTROL_MISSING')
        if any(marker not in actions for marker in (b'AttackPacer', b'ControlledDefenseTask', b'entityInReach', b'readyToAttack')):
            raise ValueError('MC_SURVIVAL_DEFENSE_ACTION_BINDING_MISSING')
        supply = archive.read('dev/aitalkstreamer/mc/survival/ControlledSupplyTask.class')
        if any(marker not in supply for marker in (b'SupplyPolicy', b'CollectFoodTask', b'SurvivalAuthority',
                b'LocalTaskFailure', b'allowedFood', b'inventoryNutrition')):
            raise ValueError('MC_SURVIVAL_CONTROLLED_SUPPLY_MISSING')
        food_chain = archive.read('adris/altoclef/chains/FoodChain.class')
        collection = archive.read('adris/altoclef/tasks/resources/CollectFoodTask.class')
        if any(marker not in food_chain for marker in (b'ControlledSupplyTask', b'allowedFood', b'validateSettings')):
            raise ValueError('MC_SURVIVAL_SUPPLY_CHAIN_BINDING_MISSING')
        if any(marker not in collection for marker in (b'breadTarget', b'wheatTarget', b'inventoryNutrition')):
            raise ValueError('MC_SURVIVAL_FINITE_FOOD_RESOURCE_BINDING_MISSING')
        cooking = archive.read('dev/aitalkstreamer/mc/survival/ControlledCookingTask.class')
        if any(marker not in cooking for marker in (b'CookingExchange', b'SurvivalGui', b'SurvivalAuthority',
                b'foodPotential', b'isProtected', b'synchronizedSlot', b'ControlledFoodCookingTask', b'GAME_COOKING_CLEANUP_REQUIRED')):
            raise ValueError('MC_SURVIVAL_CONFIRMED_COOKING_MISSING')
        if b'ControlledCookingTask' not in food_chain or b'ControlledCookingTask' not in collection:
            raise ValueError('MC_SURVIVAL_COOKING_RESOURCE_BINDING_MISSING')
        food_preparation = archive.read('dev/aitalkstreamer/mc/survival/ControlledFoodCookingTask.class')
        if any(marker not in food_preparation for marker in (b'ResourceMaterials', b'singleUnits', b'ControlledRecipeResourcesTask', b'furnaceSnapshot', b'ControlledCookingTask', b'supply')):
            raise ValueError('MC_SURVIVAL_FOOD_PREPARATION_MISSING')
        if b'consumableFoods' not in food_chain or b'ControlledFoodCookingTask' not in collection:
            raise ValueError('MC_SURVIVAL_SHARED_FOOD_CONSUMPTION_MISSING')
        smelting = archive.read('dev/aitalkstreamer/mc/survival/ControlledSmeltingTask.class')
        # Release jars use the pinned intermediary name for AbstractFurnaceBlockEntity.createFuelTimeMap.
        if any(marker not in smelting for marker in (b'ResourceMaterials', b'conversionFuel', b'batchLimit', b'ControlledRecipeResourcesTask', b'ControlledCookingTask', b'CookingWorkstation', b'furnaceSnapshot', b'method_11196', b'fuelUnits')):
            raise ValueError('MC_SURVIVAL_CONFIRMED_RESOURCE_SMELTING_MISSING')
        for wrapper in ['SmeltInFurnaceTask', 'SmeltInBlastFurnaceTask', 'SmeltInSmokerTask']:
            if b'ControlledSmeltingTask' not in archive.read('adris/altoclef/tasks/container/' + wrapper + '.class'):
                raise ValueError('MC_SURVIVAL_SMELTING_WRAPPER_MISSING')
        eating = archive.read('dev/aitalkstreamer/mc/survival/ControlledEatingTask.class')
        if any(marker not in eating for marker in (b'EatingBudget', b'FoodInventory', b'InventoryExchange', b'SurvivalGui',
                b'SurvivalAuthority', b'blocksRepeatedUse', b'GAME_EATING_STATE_CHANGED', b'sendAlternatives')):
            raise ValueError('MC_SURVIVAL_CONFIRMED_EATING_MISSING')
        if b'ControlledEatingTask' not in food_chain or b'ControlledEatingTask' not in collection:
            raise ValueError('MC_SURVIVAL_EATING_RESOURCE_BINDING_MISSING')
        resource = archive.read('dev/aitalkstreamer/mc/survival/ControlledResourceCraftTask.class')
        if any(marker not in resource for marker in (b'CraftSpec', b'ConfirmedCraftTask', b'CollectRecipeCataloguedResourcesTask', b'SurvivalAuthority', b'collectorFactory', b'closeEmptyOwnedScreen')):
            raise ValueError('MC_SURVIVAL_RESOURCE_CRAFT_MISSING')
        for name in ['adris/altoclef/tasks/CraftInInventoryTask.class', 'adris/altoclef/tasks/container/CraftInTableTask.class']:
            if b'ControlledResourceCraftTask' not in archive.read(name):
                raise ValueError('MC_SURVIVAL_RESOURCE_CRAFT_WRAPPER_MISSING')
        for name in ['adris/altoclef/tasksystem/Task.class', 'adris/altoclef/chains/SingleTaskChain.class']:
            if b'ConfirmedCraftTask' not in archive.read(name) or b'retains' not in archive.read(name):
                raise ValueError('MC_SURVIVAL_RESOURCE_CRAFT_CONTINUITY_MISSING')
        if b'ControlledRecipeResourcesTask' not in archive.read('adris/altoclef/tasks/resources/CollectRecipeCataloguedResourcesTask.class'):
            raise ValueError('MC_SURVIVAL_MATERIAL_COLLECTOR_MISSING')
        for name in ['CraftPlan', 'ResourceMaterialsPlan']:
            if b'MaterialAllocation' not in archive.read('dev/aitalkstreamer/mc/survival/' + name + '.class'):
                raise ValueError('MC_SURVIVAL_SHARED_MATERIAL_ALLOCATION_MISSING')
        if b'ResourceMaterials' not in resource or b'ResourceMaterials' not in archive.read('dev/aitalkstreamer/mc/survival/CraftSpec.class'):
            raise ValueError('MC_SURVIVAL_ANCESTOR_OUTPUT_HOLDS_MISSING')
        material_use = archive.read('dev/aitalkstreamer/mc/survival/ControlledMaterialUse.class')
        if any(marker not in material_use for marker in (b'removable', b'externalUsable', b'beforeDrop', b'beforeBlockHands', b'disposable', b'throwawayCount')):
            raise ValueError('MC_SURVIVAL_SHARED_BUILDING_AND_DISPOSAL_MISSING')
        grouped_targets = archive.read('dev/aitalkstreamer/mc/survival/MaterialTargets.class')
        allocation = archive.read('dev/aitalkstreamer/mc/survival/MaterialAllocation.class')
        if any(marker not in grouped_targets for marker in (b'limits', b'externalUsable', b'merge')) or b'constrained' not in allocation:
            raise ValueError('MC_SURVIVAL_GROUPED_OUTPUT_RETENTION_MISSING')
        acquisition = archive.read('dev/aitalkstreamer/mc/survival/ControlledRecipeResourcesTask.class')
        materials = archive.read('dev/aitalkstreamer/mc/survival/ResourceMaterials.class')
        if b'ResourceAcquisitionPlan' not in materials or any(marker not in acquisition for marker in (b'ResourceAcquisitionPlan', b'GAME_RESOURCE_MATERIAL_CYCLE', b'choose', b'begin', b'finish', b'releaseAcquisition')):
            raise ValueError('MC_SURVIVAL_BOUNDED_ACQUISITION_POLICY_MISSING')
        recovery = archive.read('dev/aitalkstreamer/mc/survival/ResourceBranchRecovery.class')
        if any(marker not in recovery for marker in (b'invalidate', b'finishOwned', b'backtrackReady', b'forceCancel')) or b'onChildFailure' not in acquisition:
            raise ValueError('MC_SURVIVAL_RESOURCE_SUBTREE_RECOVERY_MISSING')
        if b'onChildFailure' not in archive.read('adris/altoclef/tasksystem/Task.class') or b'generation' not in archive.read('dev/aitalkstreamer/mc/survival/SurvivalAsync.class'):
            raise ValueError('MC_SURVIVAL_RESOURCE_FAILURE_BOUNDARY_OR_ASYNC_GENERATION_MISSING')
        if b'settled' not in acquisition or b'within' not in archive.read('dev/aitalkstreamer/mc/survival/ControlledFoodCookingTask.class'):
            raise ValueError('MC_SURVIVAL_RESOURCE_COMPLETION_SETTLEMENT_MISSING')
        equipment = archive.read('dev/aitalkstreamer/mc/survival/ControlledEquipment.class')
        if any(marker not in equipment for marker in (b'EquipmentPlan', b'EquipmentExchange', b'SurvivalGui', b'SurvivalAuthority',
                b'defers', b'checkpoint', b'GAME_EQUIPMENT_SLOT_REJECTED')):
            raise ValueError('MC_SURVIVAL_CONFIRMED_EQUIPMENT_MISSING')
        shield = archive.read('dev/aitalkstreamer/mc/survival/ControlledShield.class')
        if any(marker not in shield for marker in (b'ShieldCycle', b'SurvivalAuthority', b'SurvivalActions',
                b'field_5810', b'method_6058', b'ControlledEatingTask', b'guardShieldStop', b'beginTick', b'endTick')):
            raise ValueError('MC_SURVIVAL_OWNED_SHIELD_MISSING')
        for entry in ['adris/altoclef/chains/MobDefenseChain.class', 'adris/altoclef/control/KillAura.class']:
            if b'ControlledShield' not in archive.read(entry):
                raise ValueError('MC_SURVIVAL_SHIELD_DEMAND_BINDING_MISSING')
        if b'ControlledEquipment' not in archive.read('adris/altoclef/control/SlotHandler.class') or b'ControlledEquipment' not in archive.read('adris/altoclef/tasks/misc/EquipArmorTask.class'):
            raise ValueError('MC_SURVIVAL_SHARED_EQUIPMENT_BINDING_MISSING')
        if mod['depends']['ai_talk_streamer_bridge'] != '0.1.0' or mod['environment'] != 'client':
            raise ValueError('MC_SURVIVAL_BRIDGE_DEPENDENCY_MISSING')
        for name in ['LICENSE-AltoClef', 'LICENSE-Ai-Talk-Streamer', 'altoclef.mixins.json']:
            if not archive.read(name):
                raise ValueError('MC_SURVIVAL_REQUIRED_RESOURCE')
        if SHA(archive.read('META-INF/mc-control/gate-policy.json')) != gates['main']['policy_sha256']:
            raise ValueError('MC_SURVIVAL_GATE_POLICY_RESOURCE')
        main_report = json.loads((ROOT / gates['main']['report']).read_text(encoding='utf-8'))
        for origin in {row['origin'] for row in main_report['sites']}:
            if b'$ats$effect$' not in archive.read(origin + '.class'):
                raise ValueError('MC_SURVIVAL_FINAL_PACKAGE_MISSING_GATES')
        embedded = prepare.embedded_jars(jar.read_bytes(), jar.name)
        pinned = json.loads((ROOT / 'configs/mc-survival-build.lock.json').read_text(encoding='utf-8'))
        if (sum(item['sha256'] == gates['baritone']['output_sha256'] for item in embedded) != 1
                or any(item['sha256'] == pinned['nested'][0]['sha256'] for item in embedded)):
            raise ValueError('MC_SURVIVAL_CONTROLLED_BARITONE_MISSING_OR_DUPLICATED')
        nether = [item for item in preparation['embedded_artifacts'] if item['entry'].endswith('/nether-pathfinder-1.4.1.jar')]
        if len(nether) != 1 or sum(item['sha256'] == nether[0]['sha256'] for item in embedded) != 1:
            raise ValueError('MC_SURVIVAL_NETHER_PATHFINDER_CHANGED')
        # This build targets Java21 directly and does not run the upstream bytecode downgrader.
        if any(b'xyz/wagyourtail/jvmdg' in archive.read(n) for n in names if n.endswith('.class')):
            raise ValueError('MC_SURVIVAL_UNDECLARED_DOWNGRADER_RUNTIME')
    tests = []
    reports = sorted((PROJECT / 'build/test-results/test').glob('*.xml'))
    for report in reports:
        for case in ET.parse(report).iter('testcase'):
            if any(case.find(tag) is not None for tag in ['failure', 'error', 'skipped']):
                raise ValueError('MC_SURVIVAL_TEST_NOT_PASSED')
            tests.append(case.get('classname') + ':' + case.get('name'))
    if len(tests) != 872 or len(set(tests)) != 872:
        raise ValueError('MC_SURVIVAL_TEST_REPORT_MISSING')
    option_tests = Counter(name.split(':', 1)[0].rsplit('.', 1)[-1] for name in tests
                           if name.split(':', 1)[0].rsplit('.', 1)[-1] in {'SettingLeaseTest', 'OptionGateTest'})
    if option_tests != {'SettingLeaseTest': 8, 'OptionGateTest': 15}:
        raise ValueError('MC_SURVIVAL_OPTION_TEST_REPORT_MISSING')
    if sum(name.startswith('dev.aitalkstreamer.mc.survival.SneakGateTest:') for name in tests) != 19:
        raise ValueError('MC_SURVIVAL_SNEAK_TEST_REPORT_MISSING')
    if sum(name.startswith('dev.aitalkstreamer.mc.survival.MovementPolicyGateTest:') for name in tests) != 33:
        raise ValueError('MC_SURVIVAL_MOVEMENT_POLICY_TEST_REPORT_MISSING')
    inventory = PROJECT / 'build/reports/control/write-sites.tsv'
    with inventory.open(encoding='utf-8', newline='') as stream:
        sites = list(csv.DictReader(stream, delimiter='\t'))
    if not sites or set(row['artifact'] for row in sites) != {'controlled-altoclef', 'pinned-baritone'} or any(row['status'] != 'UNREVIEWED' for row in sites):
        raise ValueError('MC_SURVIVAL_INVENTORY_INVALID')
    result = {
        'classification': 'NON_INSTALLABLE_ENGINEERING_BUILD_AND_CPU_CHECKS_ONLY',
        'result': 'PASS', 'branch': 'mc', 'minecraft': '1.21.1', 'source_commit': preparation['source_commit'],
        'source_files_verified': preparation['source_files'], 'patches_applied': len(preparation['patches']),
        'lock_sha256': preparation['lock_sha256'], 'patches_sha256': preparation['patches_sha256'],
        'gradle_lock_sha256': SHA((PROJECT / 'gradle.lockfile').read_bytes()),
        'jar': jar.relative_to(ROOT).as_posix(), 'jar_sha256': SHA(jar.read_bytes()),
        'bridge_api_jar_sha256': SHA((ROOT / 'game-adapters/minecraft/fabric/build/devlibs/ai-talk-streamer-mc-bridge-0.1.0-dev.jar').read_bytes()),
        'java_class_major': 65, 'required_control_classes': required,
        'tests': {'passed': len(tests), 'failed': 0, 'skipped': 0, 'names': tests},
        'explicit_effect_gates': gates,
        'native_input_artifact': {'jar_sha256': SHA(bridge_jar.read_bytes()),
                                  'mixin_refmap_verified': True,
                                  'real_mixin_application_tested': False},
        'native_hotbar_ownership': {'source_sites': gates['main']['owned_hotbar_sites'],
                                   'baritone_sites': gates['baritone']['owned_hotbar_sites'],
                                   'scope': 'ORIGINAL_TASK_PERMIT_INPUT_GENERATION_AND_PLAYER_INVENTORY',
                                   'restoration_packet_failure_remains_retryable': True,
                                   'real_client_server_accepted': False,
                                   'server_packet_is_not_an_acknowledgement': True},
        'native_client_options': {'source_sites': gates['main']['owned_option_sites'],
                                  'baritone_sites': gates['baritone']['owned_option_sites'],
                                  'settings': ['autoJump', 'gamma', 'pauseOnLostFocus'],
                                  'original_task_permit_required': True,
                                  'actual_original_and_post_set_values_observed': True,
                                  'intervening_changes_preserved': True,
                                  'cleanup_failure_retains_original_root': True,
                                  'game_options_replacement_is_not_modified': True,
                                  'real_client_accepted': False,
                                  'coverage': 'ONLY_THREE_TYPED_SETTINGS_NOT_ALL_CLIENT_STATE'},
        'native_temporary_sneaking': {'source_sites': gates['main']['owned_sneak_sites'],
                                     'sole_native_input_owner': True, 'original_scope_and_permit_required': True,
                                     'keyboard_restoration_polls_current_mapping': True,
                                     'non_keyboard_input_restores_owned_original': True,
                                     'physical_read_failure_retains_input_generation': True,
                                     'real_client_and_physical_takeover_accepted': False,
                                     'coverage': 'TWO_UPSTREAM_TEMPORARY_SNEAK_WRITES_NOT_ALL_INPUTS'},
        'embedded_artifacts': embedded, 'duplicate_native_arbiter_absent': True,
        'static_inventory': {'path': inventory.relative_to(ROOT).as_posix(), 'sha256': SHA(inventory.read_bytes()),
                             'sites': len(sites), 'by_artifact': dict(Counter(row['artifact'] for row in sites)),
                             'by_instruction_kind': dict(Counter(row['kind'] for row in sites)),
                             'review_status': 'UNREVIEWED_NOT_A_MUTATION_COVERAGE_ASSERTION'},
        'launch_guard': 'UNCONDITIONAL_PRELAUNCH_REJECTION',
        'expected_gui_binding': {'supported_types': ['inventory', 'crafting_table', 'smoker', 'furnace', 'blast_furnace', 'storage'],
                                 'opening_deadline_ms': 1500, 'idle_ms': 3000, 'absolute_max_ms': 15000,
                                 'same_player_real_client_accepted': False, 'other_containers_bound': False,
                                 'manual_takeover_closes_gui': False},
        'automatic_input_authorized': False, 'runtime_started': False, 'real_game_acceptance': 'not_run',
        'bounded_storage': {'ordinary_types':['chest','trapped_chest','barrel'], 'container_slots':[27,54],
                            'original_root_and_expected_position_required':True,'double_chest_both_entities_bound':True,
                            'server_full_inventory_baseline':True,'full_inventory_ack_per_pickup':True,
                            'click_ack_timeout_ms':1500,'transfer_deadline_ms':12000,'gui_absolute_max_ms':15000,
                            'one_pending_click':True,'exact_amount_and_components':True,'original_material_reservations_checked':True,
                            'confirmed_task_local_deposit_ledger':True,'nearby_and_stash_confirmed_observers':True,
                            'preexisting_container_contents_not_counted':True,'automatic_drop_or_retry':False,
                            'revocation_rollback_clicks':False,'other_container_types_supported':False,
                            'real_client_server_accepted':False,'full_resource_graph_complete':False},
        'bounded_cooking': {'items_per_session':1, 'fuel_items_per_session_max':1,
                            'fuel_types':['minecraft:coal','minecraft:charcoal'],
                            'click_ack_timeout_ms':1500, 'cook_deadline_ms':8000,
                            'smoker_idle_ms':10000, 'gui_absolute_deadline_ms':15000,
                            'owned_smoker_only':True,'exact_runtime_recipe_and_components':True,
                            'full_inventory_ack_per_click':True,'authoritative_slot_updates':True,
                            'same_original_supply_root':True,'supply_completion_waits_for_gui_cleanup':True,
                            'food_preparation_before_slot_capture':True,'preparation_retained_across_interruptions':True,
                            'fuel_acquisition_uses_original_material_collector':True,'prepared_smoker_recaptures_materials':True,
                            'complete_resource_chain':False,'real_client_accepted':False},
        'bounded_resource_smelting': {'workstations':['furnace','blast_furnace','smoker'], 'raw_items_per_conversion_max':4,
                           'raw_items_by_workstation_max':{'furnace':4,'blast_furnace':4,'smoker':1}, 'fuel_items_per_conversion_max':1,
                           'output_count_from_actual_recipe':True, 'all_declared_absolute_goals_processed':True,
                           'root_selection_limit':256, 'raw_and_fuel_share_unreserved_capacity':True,
                           'remainder_fuel_supported':False, 'fuel_types':['coal','charcoal','coal_block','dried_kelp_block','logs','planks'],
                           'runtime_recipe_and_fuel_map':True, 'recapture_stock_after_workstation_preparation':True,
                           'opening_baseline_from_full_server_packet':True, 'furnace_max_ticks':1200, 'smoker_max_ticks':120,
                           'furnace_idle_ms':65000, 'furnace_absolute_ms':75000,
                           'cook_deadline_formula':'recipe_ticks*50*inputs+3000+(inputs-1)*1500', 'maximum_cook_ms':63000,
                           'counted_raw_and_fuel_joint_allocation':True,'single_fuel_covers_entire_batch':True,
                           'partial_batches_do_not_complete':True,'incoherent_partial_updates_block_clicks':True,
                           'preparation_waits_for_full_initial_packet_before_stock_decisions':True,
                           'all_intermediates_globally_reserved_across_every_consumer':False,
                           'complete_resource_chain':False,'real_client_server_accepted':False},
        'bounded_supply': {'target_units_max':256, 'target_is_total_safe_inventory_nutrition':True,
                           'original_root_required':True, 'same_episode_across_interruptions':True,
                           'checkpoint_before_all_upstream_chains':True,
                           'total_ms':120000, 'no_progress_ms':45000, 'anchor_radius':96,
                           'native_default_minimum_units':12, 'native_default_target_units':40,
                           'explicit_zero_collection_settings_preserved':True,
                           'protected_task_stock_is_not_zero_consumption_score':True,
                           'actual_stack_food_components':True, 'selected_hand_rechecked':True,
                           'bread_and_wheat_conversion_targets_finite':True,
                           'automatic_eating_server_confirmation_bound':True,
                           'automatic_eating_real_client_accepted':False,
                           'whole_supply_and_resource_chains_completed':False, 'real_client_server_accepted':False},
        'bounded_resource_crafting': {'original_root_required':True, 'internal_target_is_absolute_total':True,
                           'actual_current_server_recipe_required':True, 'native_and_catalogue_ingredient_intersection':True,
                           'max_recipe_candidates':64, 'search_steps':20000, 'max_requested_increment':4096,
                           'public_ambiguity_rules_unchanged':True, 'multiple_executable_recipes_are_ambiguous':True,
                           'inventory_and_table_material_acquisition_retained':True, 'virtual_material_collector_preserved':True,
                           'recapture_after_table_creation':True, 'parent_waits_for_full_server_confirmation':True,
                           'every_batch_requires_empty_cursor_grid_and_owned_close':True,
                           'unknown_cursor_discarded':False, 'revoked_cleanup_has_inventory_effects':False,
                           'full_material_reservation_system':False, 'complete_resource_chain':False,
                           'real_client_server_accepted':False},
        'bounded_materials': {'typed_acquisition_failure_bubbles_to_nearest_collector':True, 'failed_subtree_stopped_before_alternative':True, 'replacement_waits_for_actual_async_job_quiescence':True,
                            'normal_source_completion_retires_before_replan':True, 'completed_wrapper_waits_for_nested_transaction_cleanup':True,
                            'no_task_factory_retires_before_no_progress_record':True, 'food_preparation_ancestor_does_not_block_material_child_retirement':True,
                            'cleanup_calculations_invalidated_before_and_after_subtree_stop':True,
                           'stale_branch_calculations_invalidated_without_root_renewal':True, 'uncertain_server_and_transaction_failures_not_recovered':True,
                           'source_factory_and_nested_failures_share_bounded_history':True,'grouped_alternative_outputs_not_flattened':True, 'overlapping_absolute_targets_share_stock':True,
                           'bounded_joint_consumer_allocation':True, 'collection_crafting_fuel_food_building_disposal_use_grouped_targets':True,
                           'original_root_required':True, 'one_capacity_allocator_for_collection_and_crafting':True,
                           'component_aware_consumers_and_retained_outputs_jointly_allocated':True,
                              'building_selection_and_counts_share_retained_capacity':True,
                              'garbage_ranking_requires_whole_stack_removal_capacity':True,
                              'gui_disposal_rechecks_actual_slot_and_cursor':True,
                              'held_block_use_rechecks_material_capacity':True,
                           'single_unit_consumers_per_request_max':64,'selected_eating_capacity_rechecked_after_equipment_ack':True,
                           'food_choice_uses_consumable_main_inventory_stacks':True,
                           'protected_owned_food_still_counts_for_supply_admission':True,
                           'pending_recipe_groups_sum_material_demands':True,
                           'active_ancestor_output_targets_retained':True,
                           'legacy_retained_output_flow_precedes_material_flow':True, 'absolute_output_limits_apply_to_every_joint_allocation':True,
                           'component_restricted_craft_inputs_preserved':True,
                           'acquisition_count_includes_upstream_visible_stock':True,
                           'recursive_uncatalogued_union_factory_avoided':True,
                           'recheck_finished_collector_after_table_consumption':True,
                           'slot_rearrangement_is_not_quantity_progress':True,
                           'max_active_frames':64, 'max_retained_output_kinds':4096, 'max_requirements':640, 'allocation_step_limit':2000000,
                           'root_material_selections_max':256, 'selection_budget_survives_interruptions':True,
                           'revoked_cleanup_has_inventory_effects':False,
                           'all_inputs_globally_reserved_across_every_consumer':False,
                           'complete_resource_chain':False, 'real_client_server_accepted':False},
        'bounded_shield': {'original_root_required':True, 'native_hand':'OFF_HAND',
                           'fresh_per_tick_demand_required':True, 'threat_and_melee_claims_independent':True,
                           'wait_ms':8000, 'hold_ms':10000, 'total_encounter_ms':60000, 'max_starts':64,
                           'quiet_reset_ms':2000, 'mainhand_or_cursor_moved_for_shield':False,
                           'interrupted_food_resolves_without_food_priority':True,
                           'melee_release_before_attack':True, 'projectile_demand_blocks_attack':True,
                           'owned_stop_includes_ended_local_animation':True,
                           'revoked_cleanup_sends_stop_or_inventory_packet':False,
                           'local_use_animation_is_not_server_block_ack':True,
                           'real_client_server_accepted':False, 'complete_pve_system':False},
        'bounded_equipment': {'original_root_required':True, 'total_ms':8000, 'click_ack_ms':1500,
                              'full_authoritative_baseline_required':True, 'one_pending_click':True,
                              'main_tool_offhand_armor_and_deequip_bound':True, 'armor_preserves_old_piece':True,
                              'native_slot_insert_take_and_capacity_checks':True, 'no_drop_or_quick_move':True,
                              'dependent_user_and_food_chains_deferred':True, 'other_survival_chains_remain_eligible':True,
                              'predicted_equipment_gameplay_blocked':True, 'owner_revocation_has_no_inventory_rollback':True,
                              'server_selected_slot_acknowledged':False, 'complete_equipment_and_survival_system':False,
                              'real_client_server_accepted':False},
        'bounded_eating': {'original_root_required':True, 'episode_total_ms':120000, 'bite_total_ms':10000,
                           'episode_attempts_max':20, 'one_use_per_bite':True, 'full_server_inventory_required':True,
                           'positive_consumption_requires_server_food_gain':True, 'exact_zero_or_one_resolution':True,
                           'native_remainder_inventory_order_modeled':True, 'remainder_space_preflight':True,
                           'same_deadlines_across_interruptions':True, 'confirmed_inventory_swap_restoration_required':True,
                           'original_selected_slot_restored_via_owner':True, 'selected_slot_server_acknowledged':False,
                           'owned_native_stop_before_zero_effect_read':True,
                           'cancelled_cleanup_has_no_inventory_or_stop_packet':True,
                           'unknown_mod_finish_using_overrides_supported':False,
                           'complete_food_and_equipment_system':False, 'real_client_server_accepted':False},
        'bounded_defense': {'target':'original_entity_identity', 'original_root_required':True,
                            'same_encounter_retained_across_interruptions':True,
                            'checkpoint_before_all_upstream_chains':True, 'resource_interactions_resume_after_safe_finish':True,
                            'vanilla_reach_sight_and_cooldown':True, 'attempts_per_player_tick':1,
                            'total_ms':30000, 'no_progress_ms':6000, 'escape_ms':10000,
                            'pursuit_radius':16, 'escape_radius':16, 'absolute_anchor_radius':48,
                            'completion_is_kill_proof':False, 'whole_pve_and_supply_completed':False,
                            'real_client_server_accepted':False},
        'native_item_uses': {'purposes': ['eat', 'equip', 'activate'], 'one_effect_request': True,
                            'server_inventory_and_effect_checks': True, 'later_observation_required': True,
                            'real_client_server_accepted': False, 'real_mixin_application_tested': False,
                            'remaining': ['physical input and selected-slot restoration',
                                          'real food/equipment/block effects and server restrictions',
                                          'late packet correlation across task reuse',
                                          'hand-held equipment and non-full-cube/special/mod items']},
        'native_held_interactions': {'wrapped_vanilla_methods':['doAttack','handleBlockBreaking','doItemUse'],
                                     'original_root_permit_required':True,'physical_input_is_not_automatic':True,
                                     'item_transaction_repeats_suppressed':True,'use_gui_preflight_once':True,
                                     'real_mixin_application_tested':False,'real_client_server_accepted':False,
                                     'complete_mutation_coverage':False},
        'native_direct_interactions': {'source_sites':gates['main']['typed_interaction_sites'],
                                      'baritone_sites':gates['baritone']['typed_interaction_sites'],
                                      'input_scope_actual_world_player_connection_manager_bound':True,
                                      'game_provided_reach_checks':True,
                                      'natural_completion_stops_claimed_actions':True,
                                      'revoked_cleanup_cancels_physical_operator_action':False,
                                      'real_client_server_accepted':False,
                                      'complete_mutation_coverage':False,
                                      'remaining':['real vanilla held-input Mixin application and indirect interactions',
                                                   'packet/reflection/options and other container paths',
                                                   'real cancelled mining/use restoration and physical takeover',
                                                   'ordinary PvE and full resource-chain effect verification']},
        'craft_transactions': {'transport': 'vanilla_full_inventory_resync_after_controlled_click',
                               'one_pending_click': True, 'timeout_ms': 1500, 'automatic_retry': False,
                               'exact_component_and_material_checks': True, 'real_client_server_accepted': False,
                               'recipe_scope': 'unambiguous_received_shaped_or_shapeless',
                               'full_sync_contains_task_nonce': False,
                               'remaining': ['special and variable-output recipes', 'ambiguous recipe selection',
                                             'worktable preparation material changes',
                                             'late packet correlation across reused handler/sync identities',
                                             'real vanilla/modded server and Mixin acceptance']},
        'distribution_gates': ['all native input/view/GUI/Baritone writes bound to the sole arbiter',
                               'physical ownership restoration and expected GUI',
                               'binary/source correspondence and LGPL/native dependency notices',
                               'same-player real-client acceptance']
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    receipt = verify_build()
    print(json.dumps({'result': receipt['result'], 'classification': receipt['classification'],
                      'passed': receipt['tests']['passed'], 'static_sites_unreviewed': receipt['static_inventory']['sites'],
                      'launch_guard': receipt['launch_guard'], 'receipt': OUTPUT.relative_to(ROOT).as_posix()}, ensure_ascii=False))
