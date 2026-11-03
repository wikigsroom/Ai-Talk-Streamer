package dev.aitalkstreamer.mc.neoforge;

import com.google.gson.JsonObject;
import dev.aitalkstreamer.mc.core.*;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.client.Minecraft;
import net.minecraft.core.component.DataComponents;
import net.minecraft.world.food.FoodProperties;
import net.minecraft.world.entity.EquipmentSlot;
import net.minecraft.world.item.*;
import net.minecraft.world.item.context.BlockPlaceContext;
import net.minecraft.network.protocol.game.ClientboundContainerSetContentPacket;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.inventory.InventoryMenu;
import net.minecraft.world.inventory.ClickType;
import net.minecraft.world.InteractionHand;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.HitResult;
import net.minecraft.world.phys.shapes.CollisionContext;
import net.minecraft.core.BlockPos;
import java.util.*;
import java.util.function.LongSupplier;
import java.util.function.Supplier;
import java.util.stream.IntStream;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Exactly one requested use; slot writes and the bounded action share the original permit. */
final class NativeItemUse implements ExecutorTaskSession.Runtime {
    private enum Phase { PREPARE, PREPARE_ACK, ARM, USE, FINISH_ACK, DONE }
    private record Plan(ItemStack stack, int source, int hotbar, int equipment, FoodProperties food,
                        BlockHitResult hit, BlockPos placed, Block block, String destination) { }
    private final Minecraft client;
    private final NativeInputOwner inputs;
    private final Supplier<JsonObject> observation;
    private final LongSupplier clock = () -> System.nanoTime() / 1_000_000;
    private final List<ItemStack> types = new ArrayList<>();
    private JsonObject task;
    private ControlArbiter control;
    private ControlArbiter.Permit permit;
    private NativeInputOwner.Scope scope;
    private Object world, player, connection;
    private InventoryMenu handler;
    private Plan plan;
    private InventoryExchange exchange;
    private InventoryExchange.State prepared;
    private Phase phase;
    private Runnable finished;
    private long deadline, armDeadline;
    private int baseline, initialFood, serverFood = -1, revision = -1;
    private boolean startedUsing, effectIssued, inventoryConfirmed, effectConfirmed, clean, closed;
    private String packetFailure;
    private ItemUseReceipt stopped;

    NativeItemUse(Minecraft client, NativeInputOwner inputs, Supplier<JsonObject> observation) {
        this.client = client; this.inputs = inputs; this.observation = observation;
    }
    private static int count(Minecraft client, String item) {
        int total = 0;
        for (int i = 0; i < client.player.getInventory().getContainerSize(); i++) {
            var stack = client.player.getInventory().getItem(i);
            if (!stack.isEmpty() && BuiltInRegistries.ITEM.getKey(stack.getItem()).toString().equals(item)) total += stack.getCount();
        }
        return total;
    }
    private void ready() {
        require(client.isSameThread(), "GAME_WRONG_THREAD");
        require(client.player != null && client.level != null && client.getConnection() != null && client.gameMode != null,
                "GAME_WORLD_UNAVAILABLE");
        require(client.player.isAlive() && client.isWindowActive() && !client.isPaused() && client.screen == null,
                "GAME_GUI_BLOCKED");
        require(!client.player.getAbilities().instabuild && !client.player.isSpectator(), "GAME_ITEM_SURVIVAL_REQUIRED");
        require(client.player.containerMenu == client.player.inventoryMenu
                && client.player.inventoryMenu.getClass() == InventoryMenu.class
                && client.player.inventoryMenu.getCarried().isEmpty(), "GAME_ITEM_HANDLER_INVALID");
        for (int i = 0; i < 5; i++) require(client.player.inventoryMenu.getSlot(i).getItem().isEmpty(), "GAME_ITEM_GRID_NOT_EMPTY");
    }
    private int slot(int index) {
        return IntStream.range(5, 46).filter(i -> handler.getSlot(i).container == client.player.getInventory()
                && handler.getSlot(i).getContainerSlot() == index).findFirst().orElseThrow(() -> new Rejected("GAME_ITEM_HANDLER_INVALID"));
    }
    private boolean placeable(BlockPlaceContext placement, Block block) {
        BlockPos at = placement.getClickedPos();
        if (!client.level.hasChunkAt(at) || !placement.canPlace()
                || client.level.getBlockState(at).getBlock() == block) return false;
        BlockState state = block.getStateForPlacement(placement);
        // canPlace() on the context only checks replacement. Use the ordinary
        // BlockItem checks too: a replaceable cell can still intersect a player.
        return state != null && (state.isCollisionShapeFullBlock(client.level, at) || NativePlanting.crop(block))
                && state.canSurvive(client.level, at)
                && client.level.isUnobstructed(state, at, CollisionContext.of(client.player));
    }
    private Plan capture(JsonObject goal) {
        ready(); require(!client.player.isUsingItem(), "GAME_ITEM_ALREADY_USING");
        require(str(goal, "skill").equals("use_item"), "GAME_CAPABILITY_UNAVAILABLE");
        ResourceLocation id = ResourceLocation.tryParse(str(goal, "item_id"));
        require(id != null && BuiltInRegistries.ITEM.containsKey(id), "GAME_ITEM_UNSUPPORTED");
        Item item = BuiltInRegistries.ITEM.get(id); String purpose = str(goal, "purpose"); int equipment = -1;
        if (purpose.equals("equip")) {
            EquipmentSlot target = item instanceof ArmorItem armor ? armor.getEquipmentSlot()
                    : item == Items.ELYTRA ? EquipmentSlot.CHEST : EquipmentSlot.OFFHAND;
            require(target != null && target != EquipmentSlot.BODY, "GAME_ITEM_EQUIPMENT_UNSUPPORTED");
            equipment = target == EquipmentSlot.OFFHAND ? 40 : 36 + target.getIndex();
            var worn = client.player.getInventory().getItem(equipment);
            if (worn.is(item)) return new Plan(worn.copy(), -1, client.player.getInventory().selected, equipment,
                    null, null, null, null, target.getName());
        }
        int source = -1;
        for (int i = 0; i < 36; i++) if (client.player.getInventory().getItem(i).is(item)) { source = i; break; }
        require(source >= 0, "GAME_ITEM_NOT_IN_INVENTORY");
        ItemStack stack = client.player.getInventory().getItem(source).copy();
        int hotbar = source < 9 ? source : client.player.getInventory().selected;
        if (purpose.equals("eat")) {
            require(id.getNamespace().equals("minecraft"), "GAME_ITEM_FOOD_UNSUPPORTED");
            var food = stack.get(DataComponents.FOOD);
            require(food != null && food.nutrition() > 0 && food.eatDurationTicks() > 0 && food.eatDurationTicks() <= 100, "GAME_ITEM_FOOD_UNSUPPORTED");
            require(client.player.canEat(food.canAlwaysEat()), "GAME_FOOD_NOT_NEEDED");
            return new Plan(stack, source, hotbar, -1, food, null, null, null, "mainhand:consume_once");
        }
        if (purpose.equals("equip")) {
            EquipmentSlot target = item instanceof ArmorItem armor ? armor.getEquipmentSlot()
                    : item == Items.ELYTRA ? EquipmentSlot.CHEST : EquipmentSlot.OFFHAND;
            require(equipment == 40 || stack.getCount() == 1, "GAME_ITEM_EQUIPMENT_COUNT");
            return new Plan(stack, source, hotbar, equipment, null, null, null, null, target.getName());
        }
        require(purpose.equals("activate") && id.getNamespace().equals("minecraft"), "GAME_ITEM_ACTIVATION_UNSUPPORTED");
        String crop = NativePlanting.crop(id.toString());
        require(crop != null ? item instanceof ItemNameBlockItem : item.getClass() == BlockItem.class,
                "GAME_ITEM_ACTIVATION_UNSUPPORTED");
        require(crop == null || goal.has("target"), "GAME_ITEM_PLANT_TARGET_REQUIRED");
        require(!goal.has("target") || crop != null || NativeConstruction.supported(id.toString()), "GAME_ITEM_PLACEMENT_UNSUPPORTED");
        require(!client.options.toggleCrouch().get(), "GAME_ITEM_TOGGLE_CROUCH_UNSUPPORTED");
        BlockHitResult hit;
        if (goal.has("target")) {
            var target = goal.getAsJsonObject("target");
            require(str(target, "dimension").equals(client.level.dimension().location().toString()), "GAME_DIMENSION_CHANGED");
            var at = new BlockPos(Math.toIntExact(num(target, "x")), Math.toIntExact(num(target, "y")), Math.toIntExact(num(target, "z")));
            hit = crop != null ? NativePlanting.site(client, at) : NativeConstruction.terrain(id.toString())
                    ? NativeConstruction.terrainSite(client,at) : NativeConstruction.site(client, at);
            require(hit != null, crop != null ? "GAME_ITEM_PLANT_SITE_UNAVAILABLE" : "GAME_ITEM_PLACEMENT_SITE_UNAVAILABLE");
            require(crop == null || item instanceof BlockItem planted && BuiltInRegistries.BLOCK.getKey(planted.getBlock()).toString().equals(crop),
                    "GAME_ITEM_PLANT_UNSUPPORTED");
        } else {
            require(client.hitResult instanceof BlockHitResult && client.hitResult.getType() == HitResult.Type.BLOCK,
                    "GAME_ITEM_BLOCK_TARGET_REQUIRED");
            hit = (BlockHitResult) client.hitResult;
        }
        require(client.player.distanceToSqr(hit.getLocation()) <= Math.pow(client.player.blockInteractionRange(), 2), "GAME_ITEM_BLOCK_OUT_OF_REACH");
        var placement = new BlockPlaceContext(client.player, InteractionHand.MAIN_HAND, stack, hit);
        BlockPos placed = placement.getClickedPos().immutable(); Block block = ((BlockItem) item).getBlock();
        if (goal.has("target")) {
            var target=goal.getAsJsonObject("target");
            require(placed.getX()==num(target,"x") && placed.getY()==num(target,"y") && placed.getZ()==num(target,"z"),
                    "GAME_ITEM_BLOCK_TARGET_CHANGED");
        }
        require(placeable(placement, block), "GAME_ITEM_PLACEMENT_UNSUPPORTED");
        return new Plan(stack, source, hotbar, -1, null, hit, placed, block,
                client.level.dimension().location() + ":" + placed.getX() + "," + placed.getY() + "," + placed.getZ());
    }
    JsonObject check(JsonObject goal) {
        String reason = null;
        try { capture(goal); } catch (Rejected denied) { reason = denied.code; }
        return obj("allowed", reason == null, "reason", reason, "source", "runtime_client",
                "unknown_fields", List.of("server_side_use_restrictions", "late_packet_causality", "non_static_mod_activation"));
    }
    @Override public void start(JsonObject accepted, ControlArbiter control, ControlArbiter.Permit permit,
                                InventoryTarget target, BaseTarget base, Runnable finished) {
        require(task == null || closed, "GAME_TASK_BUSY"); Plan captured = capture(accepted.getAsJsonObject("goal"));
        this.task = accepted.deepCopy(); this.control = control; this.permit = permit; this.finished = finished; plan = captured;
        world = client.level; player = client.player; connection = client.getConnection(); handler = client.player.inventoryMenu;
        scope = inputs.scope(); types.clear(); exchange = null; prepared = null; stopped = null;
        baseline = count(client, str(accepted.getAsJsonObject("goal"), "item_id")); initialFood = client.player.getFoodData().getFoodLevel();
        require(observation.get() != null && InventoryTarget.count(observation.get(), str(accepted.getAsJsonObject("goal"), "item_id")) == baseline,
                "GAME_ITEM_INVENTORY_CHANGED");
        serverFood = -1; revision = -1; startedUsing = effectIssued = inventoryConfirmed = effectConfirmed = clean = closed = false;
        packetFailure = null; phase = Phase.PREPARE; deadline = clock.getAsLong() + 10000;
    }
    private boolean current() {
        return !closed && task != null && client.isSameThread() && control.allowed() && control.epoch() == permit.epoch()
                && client.level == world && client.player == player && client.getConnection() == connection
                && client.player != null && client.player.containerMenu == handler;
    }
    private void context() {
        ready(); require(current() && control.permit().equals(permit), "GAME_ITEM_CONTEXT_CHANGED"); scope.current();
        require(clock.getAsLong() < deadline, "GAME_ITEM_USE_TIMEOUT");
        require(packetFailure == null, packetFailure == null ? "GAME_ITEM_PACKET_INVALID" : packetFailure);
    }
    private InventoryExchange.Stack token(ItemStack stack) {
        if (stack.isEmpty()) return InventoryExchange.Stack.EMPTY;
        int index = 0;
        while (index < types.size() && !ItemStack.isSameItemSameComponents(types.get(index), stack)) index++;
        if (index == types.size()) { require(types.size() < 256, "GAME_ITEM_COMPONENT_LIMIT"); types.add(stack.copyWithCount(1)); }
        return new InventoryExchange.Stack(index + 1, stack.getCount());
    }
    private InventoryExchange.State state(List<ItemStack> slots, ItemStack cursor) {
        return new InventoryExchange.State(slots.stream().map(this::token).toList(), token(cursor));
    }
    private InventoryExchange.State state() { return state(handler.slots.stream().map(s -> s.getItem().copy()).toList(), handler.getCarried()); }
    private void sync(InventoryExchange.State before, InventoryExchange.State after, int clickSlot, ClickType action, int button) {
        if (exchange != null) exchange.close();
        exchange = new InventoryExchange(clock, this::current);
        exchange.send(before, after, state(), handler.getStateId(), () -> control.actuate(permit, () -> {
            context(); client.gameMode.handleInventoryMouseClick(handler.containerId, clickSlot, button, action, client.player);
        }));
    }
    private void barrier(InventoryExchange.State expected) {
        require(handler.getSlot(0).getItem().isEmpty() && handler.getCarried().isEmpty(), "GAME_ITEM_GRID_NOT_EMPTY");
        sync(state(), expected, 0, ClickType.PICKUP, 0);
    }
    @Override public void tick() {
        context(); if (exchange != null) exchange.check();
        if (phase == Phase.PREPARE) {
            if (plan.source >= 9) {
                var before = state(); int source = slot(plan.source), hotbar = slot(plan.hotbar);
                require(ItemStack.matches(handler.getSlot(source).getItem(), plan.stack), "GAME_ITEM_SOURCE_CHANGED");
                sync(before, before.swap(source, hotbar), source, ClickType.SWAP, plan.hotbar); phase = Phase.PREPARE_ACK; return;
            }
            phase = Phase.ARM;
        }
        if (phase == Phase.PREPARE_ACK) {
            if (!exchange.confirmed()) return; revision = exchange.confirmedRevision(); phase = Phase.ARM;
        }
        if (phase == Phase.ARM) {
            prepared = state();
            if (plan.source < 0) {
                effectIssued = true; barrier(prepared); phase = Phase.FINISH_ACK; return;
            }
            require(ItemStack.matches(client.player.getInventory().getItem(plan.hotbar), plan.stack), "GAME_ITEM_SOURCE_CHANGED");
            scope.select(plan.hotbar, control, permit);
            if (plan.block != null) {
                if (task.getAsJsonObject("goal").has("target")) {
                    var delta = plan.hit.getLocation().subtract(client.player.getEyePosition());
                    scope.look((float) Math.toDegrees(Math.atan2(-delta.x, delta.z)),
                            (float) -Math.toDegrees(Math.atan2(delta.y, Math.hypot(delta.x, delta.z))), control, permit);
                }
                scope.key(client.options.keyShift, true, control, permit); armDeadline = clock.getAsLong() + 600; phase = Phase.USE; return;
            }
            phase = Phase.USE;
        }
        if (phase == Phase.USE) {
            require(client.player.getInventory().selected == plan.hotbar, "GAME_ITEM_SELECTED_SLOT_CHANGED");
            if (plan.food != null) {
                if (!effectIssued) { effectIssued = true; scope.use(plan.hotbar, control, permit); return; }
                if (client.player.isUsingItem()) {
                    startedUsing = true;
                    require(ItemStack.isSameItemSameComponents(client.player.getUseItem(), plan.stack), "GAME_ITEM_SOURCE_CHANGED"); return;
                }
                if (!startedUsing) return;
                scope.key(client.options.keyUse, false, control, permit);
                require(baseline - count(client, str(task.getAsJsonObject("goal"), "item_id")) == 1, "GAME_ITEM_CONSUMPTION_NOT_OBSERVED");
                barrier(state()); phase = Phase.FINISH_ACK; return;
            }
            if (plan.equipment >= 0) {
                int destination = slot(plan.equipment), source = slot(plan.hotbar);
                require(handler.getSlot(destination).mayPlace(plan.stack) && handler.getSlot(destination).mayPickup(client.player),
                        "GAME_ITEM_EQUIPMENT_BLOCKED");
                effectIssued = true; sync(prepared, prepared.swap(source, destination), destination, ClickType.SWAP, plan.hotbar);
                phase = Phase.FINISH_ACK; return;
            }
            require(clock.getAsLong() < armDeadline, "GAME_ITEM_SNEAK_NOT_CONFIRMED");
            if (!client.player.isShiftKeyDown()) return;
            require(state().equals(prepared), "GAME_ITEM_STATE_CHANGED");
            if (NativePlanting.crop(plan.block)) {
                if (NativePlanting.site(client,plan.placed)==null)
                    throw new LocalTaskFailure(LocalTaskFailure.Reason.ITEM_PLANT_SITE_CHANGED);
            } else if (task.getAsJsonObject("goal").has("target") && (plan.block==net.minecraft.world.level.block.Blocks.DIRT
                    ? NativeConstruction.terrainSite(client,plan.placed) : NativeConstruction.site(client,plan.placed))==null)
                throw new LocalTaskFailure(LocalTaskFailure.Reason.ITEM_PLACEMENT_SITE_CHANGED);
            var placement = new BlockPlaceContext(client.player, InteractionHand.MAIN_HAND, plan.stack, plan.hit);
            if (!placement.getClickedPos().equals(plan.placed) || !placeable(placement,plan.block))
                throw new LocalTaskFailure(LocalTaskFailure.Reason.ITEM_BLOCK_TARGET_CHANGED);
            effectIssued = true;
            control.actuate(permit, () -> { context(); client.gameMode.useItemOn(client.player, InteractionHand.MAIN_HAND, plan.hit); });
            scope.key(client.options.keyShift, false, control, permit);
            var afterStack = plan.stack.copy(); afterStack.shrink(1);
            barrier(prepared.slot(slot(plan.hotbar), token(afterStack))); phase = Phase.FINISH_ACK; return;
        }
        if (phase == Phase.FINISH_ACK) {
            if (!exchange.confirmed()) return; revision = exchange.confirmedRevision(); inventoryConfirmed = true;
            if (plan.equipment >= 0) effectConfirmed = client.player.getInventory().getItem(plan.equipment).is(plan.stack.getItem());
            else if (plan.food != null) effectConfirmed = initialFood == 20 && plan.food.canAlwaysEat()
                    || serverFood >= Math.min(20, initialFood + plan.food.nutrition());
            if (!effectConfirmed) return;
            scope.release(); clean = true; phase = Phase.DONE; finished.run();
        }
    }
    int clickRevision(int original) { return exchange != null && exchange.sending() ? exchange.revision(original) : original; }
    void inventory(ClientboundContainerSetContentPacket packet) {
        if (!current() || exchange == null || packet.getContainerId() != handler.containerId) return;
        try { exchange.confirm(state(packet.getItems(), packet.getCarriedItem()), packet.getStateId()); }
        catch (RuntimeException error) { packetFailure = "GAME_ITEM_PACKET_INVALID"; }
    }
    void health(int food) { if (current() && effectIssued && plan.food != null) serverFood = food; }
    void block(BlockPos pos, BlockState state) {
        if (current() && effectIssued && plan.block != null && plan.placed.equals(pos))
            effectConfirmed = NativePlanting.confirmed(plan.block, state);
    }
    @Override public ItemUseReceipt itemUseReceipt() {
        if (stopped != null) return stopped;
        if (task == null) return null;
        boolean confirmed = inventoryConfirmed || phase == Phase.FINISH_ACK && exchange != null && exchange.confirmedRevision() >= 0;
        int last = exchange != null && exchange.confirmedRevision() >= 0 ? exchange.confirmedRevision() : revision;
        var goal = task.getAsJsonObject("goal");
        return new ItemUseReceipt(str(task, "task_id"), str(task, "world_session_id"), num(task, "control_epoch"),
                str(goal, "item_id"), str(goal, "purpose"), baseline,
                confirmed && !str(goal, "purpose").equals("equip") ? 1 : 0, plan.destination, last, confirmed, effectConfirmed, clean);
    }
    @Override public void cancel() {
        if (task == null || closed) return;
        var receipt = itemUseReceipt(); if (exchange != null) exchange.close();
        scope.release(); stopped = receipt; closed = true;
    }
}
