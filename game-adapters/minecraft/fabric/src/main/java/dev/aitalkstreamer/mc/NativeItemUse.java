package dev.aitalkstreamer.mc;

import com.google.gson.JsonObject;
import dev.aitalkstreamer.mc.core.*;
import net.minecraft.block.Block;
import net.minecraft.block.BlockState;
import net.minecraft.client.MinecraftClient;
import net.minecraft.component.DataComponentTypes;
import net.minecraft.component.type.FoodComponent;
import net.minecraft.entity.EquipmentSlot;
import net.minecraft.item.*;
import net.minecraft.network.packet.s2c.play.InventoryS2CPacket;
import net.minecraft.registry.Registries;
import net.minecraft.screen.PlayerScreenHandler;
import net.minecraft.screen.slot.SlotActionType;
import net.minecraft.util.Hand;
import net.minecraft.util.Identifier;
import net.minecraft.util.hit.BlockHitResult;
import net.minecraft.util.hit.HitResult;
import net.minecraft.util.math.BlockPos;
import java.util.*;
import java.util.function.LongSupplier;
import java.util.function.Supplier;
import java.util.stream.IntStream;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Exactly one requested use; slot writes and the bounded action share the original permit. */
final class NativeItemUse implements ExecutorTaskSession.Runtime {
    private enum Phase { PREPARE, PREPARE_ACK, ARM, USE, FINISH_ACK, DONE }
    private record Plan(ItemStack stack, int source, int hotbar, int equipment, FoodComponent food,
                        BlockHitResult hit, BlockPos placed, Block block, String destination) { }
    private final MinecraftClient client;
    private final InputOwner inputs;
    private final Supplier<JsonObject> observation;
    private final LongSupplier clock = () -> System.nanoTime() / 1_000_000;
    private final List<ItemStack> types = new ArrayList<>();
    private JsonObject task;
    private ControlArbiter control;
    private ControlArbiter.Permit permit;
    private InputOwner.Scope scope;
    private Object world, player, connection;
    private PlayerScreenHandler handler;
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

    NativeItemUse(MinecraftClient client, InputOwner inputs, Supplier<JsonObject> observation) {
        this.client = client; this.inputs = inputs; this.observation = observation;
    }
    private static int count(MinecraftClient client, String item) {
        int total = 0;
        for (int i = 0; i < client.player.getInventory().size(); i++) {
            var stack = client.player.getInventory().getStack(i);
            if (!stack.isEmpty() && Registries.ITEM.getId(stack.getItem()).toString().equals(item)) total += stack.getCount();
        }
        return total;
    }
    private void ready() {
        require(client.isOnThread(), "GAME_WRONG_THREAD");
        require(client.player != null && client.world != null && client.getNetworkHandler() != null && client.interactionManager != null,
                "GAME_WORLD_UNAVAILABLE");
        require(client.player.isAlive() && client.isWindowFocused() && !client.isPaused() && client.currentScreen == null,
                "GAME_GUI_BLOCKED");
        require(!client.player.getAbilities().creativeMode && !client.player.isSpectator(), "GAME_ITEM_SURVIVAL_REQUIRED");
        require(client.player.currentScreenHandler == client.player.playerScreenHandler
                && client.player.playerScreenHandler.getClass() == PlayerScreenHandler.class
                && client.player.playerScreenHandler.getCursorStack().isEmpty(), "GAME_ITEM_HANDLER_INVALID");
        for (int i = 0; i < 5; i++) require(client.player.playerScreenHandler.getSlot(i).getStack().isEmpty(), "GAME_ITEM_GRID_NOT_EMPTY");
    }
    private int slot(int index) {
        return IntStream.range(5, 46).filter(i -> handler.getSlot(i).inventory == client.player.getInventory()
                && handler.getSlot(i).getIndex() == index).findFirst().orElseThrow(() -> new Rejected("GAME_ITEM_HANDLER_INVALID"));
    }
    private Plan capture(JsonObject goal) {
        ready(); require(!client.player.isUsingItem(), "GAME_ITEM_ALREADY_USING");
        require(str(goal, "skill").equals("use_item"), "GAME_CAPABILITY_UNAVAILABLE");
        require(!goal.has("target"), "GAME_ITEM_PLANTING_UNSUPPORTED");
        Identifier id = Identifier.tryParse(str(goal, "item_id"));
        require(id != null && id.getNamespace().equals("minecraft") && Registries.ITEM.containsId(id), "GAME_ITEM_UNSUPPORTED");
        Item item = Registries.ITEM.get(id); String purpose = str(goal, "purpose"); int equipment = -1;
        if (purpose.equals("equip")) {
            EquipmentSlot target = item instanceof ArmorItem armor ? armor.getSlotType()
                    : item == Items.ELYTRA ? EquipmentSlot.CHEST : item == Items.SHIELD ? EquipmentSlot.OFFHAND : null;
            require(target != null && target != EquipmentSlot.BODY, "GAME_ITEM_EQUIPMENT_UNSUPPORTED");
            equipment = target == EquipmentSlot.OFFHAND ? 40 : 36 + target.getEntitySlotId();
            var worn = client.player.getInventory().getStack(equipment);
            if (worn.isOf(item)) return new Plan(worn.copy(), -1, client.player.getInventory().selectedSlot, equipment,
                    null, null, null, null, target.getName());
        }
        int source = -1;
        for (int i = 0; i < 36; i++) if (client.player.getInventory().getStack(i).isOf(item)) { source = i; break; }
        require(source >= 0, "GAME_ITEM_NOT_IN_INVENTORY");
        ItemStack stack = client.player.getInventory().getStack(source).copy();
        int hotbar = source < 9 ? source : client.player.getInventory().selectedSlot;
        if (purpose.equals("eat")) {
            var food = stack.get(DataComponentTypes.FOOD);
            require(food != null && food.nutrition() > 0 && food.getEatTicks() > 0 && food.getEatTicks() <= 100, "GAME_ITEM_FOOD_UNSUPPORTED");
            require(client.player.canConsume(food.canAlwaysEat()), "GAME_FOOD_NOT_NEEDED");
            return new Plan(stack, source, hotbar, -1, food, null, null, null, "mainhand:consume_once");
        }
        if (purpose.equals("equip")) {
            EquipmentSlot target = item instanceof ArmorItem armor ? armor.getSlotType()
                    : item == Items.SHIELD ? EquipmentSlot.OFFHAND : EquipmentSlot.CHEST;
            require(stack.getCount() == 1, "GAME_ITEM_EQUIPMENT_COUNT");
            return new Plan(stack, source, hotbar, equipment, null, null, null, null, target.getName());
        }
        require(purpose.equals("activate") && item.getClass() == BlockItem.class, "GAME_ITEM_ACTIVATION_UNSUPPORTED");
        require(client.crosshairTarget instanceof BlockHitResult && client.crosshairTarget.getType() == HitResult.Type.BLOCK,
                "GAME_ITEM_BLOCK_TARGET_REQUIRED");
        var hit = (BlockHitResult) client.crosshairTarget;
        require(client.player.squaredDistanceTo(hit.getPos()) <= Math.pow(client.player.getBlockInteractionRange(), 2), "GAME_ITEM_BLOCK_OUT_OF_REACH");
        var placement = new ItemPlacementContext(client.player, Hand.MAIN_HAND, stack, hit);
        BlockPos placed = placement.getBlockPos().toImmutable(); Block block = ((BlockItem) item).getBlock();
        require(client.world.isChunkLoaded(placed) && placement.canPlace() && block.getDefaultState().isFullCube(client.world, placed)
                && client.world.getBlockState(placed).getBlock() != block, "GAME_ITEM_PLACEMENT_UNSUPPORTED");
        return new Plan(stack, source, hotbar, -1, null, hit, placed, block,
                client.world.getRegistryKey().getValue() + ":" + placed.getX() + "," + placed.getY() + "," + placed.getZ());
    }
    JsonObject check(JsonObject goal) {
        String reason = null;
        try { capture(goal); } catch (Rejected denied) { reason = denied.code; }
        return obj("allowed", reason == null, "reason", reason, "source", "runtime_client",
                "unknown_fields", List.of("server_side_use_restrictions", "late_packet_causality"));
    }
    @Override public void start(JsonObject accepted, ControlArbiter control, ControlArbiter.Permit permit,
                                InventoryTarget target, BaseTarget base, Runnable finished) {
        require(task == null || closed, "GAME_TASK_BUSY"); Plan captured = capture(accepted.getAsJsonObject("goal"));
        this.task = accepted.deepCopy(); this.control = control; this.permit = permit; this.finished = finished; plan = captured;
        world = client.world; player = client.player; connection = client.getNetworkHandler(); handler = client.player.playerScreenHandler;
        scope = inputs.scope(); types.clear(); exchange = null; prepared = null; stopped = null;
        baseline = count(client, str(accepted.getAsJsonObject("goal"), "item_id")); initialFood = client.player.getHungerManager().getFoodLevel();
        require(observation.get() != null && InventoryTarget.count(observation.get(), str(accepted.getAsJsonObject("goal"), "item_id")) == baseline,
                "GAME_ITEM_INVENTORY_CHANGED");
        serverFood = -1; revision = -1; startedUsing = effectIssued = inventoryConfirmed = effectConfirmed = clean = closed = false;
        packetFailure = null; phase = Phase.PREPARE; deadline = clock.getAsLong() + 10000;
    }
    private boolean current() {
        return !closed && task != null && client.isOnThread() && control.allowed() && control.epoch() == permit.epoch()
                && client.world == world && client.player == player && client.getNetworkHandler() == connection
                && client.player != null && client.player.currentScreenHandler == handler;
    }
    private void context() {
        ready(); require(current() && control.permit().equals(permit), "GAME_ITEM_CONTEXT_CHANGED"); scope.current();
        require(clock.getAsLong() < deadline, "GAME_ITEM_USE_TIMEOUT");
        require(packetFailure == null, packetFailure == null ? "GAME_ITEM_PACKET_INVALID" : packetFailure);
    }
    private InventoryExchange.Stack token(ItemStack stack) {
        if (stack.isEmpty()) return InventoryExchange.Stack.EMPTY;
        int index = 0;
        while (index < types.size() && !ItemStack.areItemsAndComponentsEqual(types.get(index), stack)) index++;
        if (index == types.size()) { require(types.size() < 256, "GAME_ITEM_COMPONENT_LIMIT"); types.add(stack.copyWithCount(1)); }
        return new InventoryExchange.Stack(index + 1, stack.getCount());
    }
    private InventoryExchange.State state(List<ItemStack> slots, ItemStack cursor) {
        return new InventoryExchange.State(slots.stream().map(this::token).toList(), token(cursor));
    }
    private InventoryExchange.State state() { return state(handler.slots.stream().map(s -> s.getStack().copy()).toList(), handler.getCursorStack()); }
    private void sync(InventoryExchange.State before, InventoryExchange.State after, int clickSlot, SlotActionType action, int button) {
        if (exchange != null) exchange.close();
        exchange = new InventoryExchange(clock, this::current);
        exchange.send(before, after, state(), handler.getRevision(), () -> control.actuate(permit, () -> {
            context(); client.interactionManager.clickSlot(handler.syncId, clickSlot, button, action, client.player);
        }));
    }
    private void barrier(InventoryExchange.State expected) {
        require(handler.getSlot(0).getStack().isEmpty() && handler.getCursorStack().isEmpty(), "GAME_ITEM_GRID_NOT_EMPTY");
        sync(state(), expected, 0, SlotActionType.PICKUP, 0);
    }
    @Override public void tick() {
        context(); if (exchange != null) exchange.check();
        if (phase == Phase.PREPARE) {
            if (plan.source >= 9) {
                var before = state(); int source = slot(plan.source), hotbar = slot(plan.hotbar);
                require(ItemStack.areEqual(handler.getSlot(source).getStack(), plan.stack), "GAME_ITEM_SOURCE_CHANGED");
                sync(before, before.swap(source, hotbar), source, SlotActionType.SWAP, plan.hotbar); phase = Phase.PREPARE_ACK; return;
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
            require(ItemStack.areEqual(client.player.getInventory().getStack(plan.hotbar), plan.stack), "GAME_ITEM_SOURCE_CHANGED");
            inputs.select(plan.hotbar, control, permit);
            if (plan.block != null) {
                inputs.key(client.options.sneakKey, true, control, permit); armDeadline = clock.getAsLong() + 600; phase = Phase.USE; return;
            }
            phase = Phase.USE;
        }
        if (phase == Phase.USE) {
            require(client.player.getInventory().selectedSlot == plan.hotbar, "GAME_ITEM_SELECTED_SLOT_CHANGED");
            if (plan.food != null) {
                if (!effectIssued) { effectIssued = true; inputs.use(plan.hotbar, control, permit); return; }
                if (client.player.isUsingItem()) {
                    startedUsing = true;
                    require(ItemStack.areItemsAndComponentsEqual(client.player.getActiveItem(), plan.stack), "GAME_ITEM_SOURCE_CHANGED"); return;
                }
                if (!startedUsing) return;
                inputs.key(client.options.useKey, false, control, permit);
                require(baseline - count(client, str(task.getAsJsonObject("goal"), "item_id")) == 1, "GAME_ITEM_CONSUMPTION_NOT_OBSERVED");
                barrier(state()); phase = Phase.FINISH_ACK; return;
            }
            if (plan.equipment >= 0) {
                int destination = slot(plan.equipment), source = slot(plan.hotbar);
                require(handler.getSlot(destination).canInsert(plan.stack) && handler.getSlot(destination).canTakeItems(client.player),
                        "GAME_ITEM_EQUIPMENT_BLOCKED");
                effectIssued = true; sync(prepared, prepared.swap(source, destination), destination, SlotActionType.SWAP, plan.hotbar);
                phase = Phase.FINISH_ACK; return;
            }
            require(clock.getAsLong() < armDeadline, "GAME_ITEM_SNEAK_NOT_CONFIRMED");
            if (!client.player.isSneaking()) return;
            require(state().equals(prepared), "GAME_ITEM_STATE_CHANGED");
            var placement = new ItemPlacementContext(client.player, Hand.MAIN_HAND, plan.stack, plan.hit);
            require(placement.canPlace() && placement.getBlockPos().equals(plan.placed)
                    && client.world.getBlockState(plan.placed).getBlock() != plan.block, "GAME_ITEM_BLOCK_TARGET_CHANGED");
            effectIssued = true;
            control.actuate(permit, () -> { context(); client.interactionManager.interactBlock(client.player, Hand.MAIN_HAND, plan.hit); });
            inputs.key(client.options.sneakKey, false, control, permit);
            var afterStack = plan.stack.copy(); afterStack.decrement(1);
            barrier(prepared.slot(slot(plan.hotbar), token(afterStack))); phase = Phase.FINISH_ACK; return;
        }
        if (phase == Phase.FINISH_ACK) {
            if (!exchange.confirmed()) return; revision = exchange.confirmedRevision(); inventoryConfirmed = true;
            if (plan.equipment >= 0) effectConfirmed = client.player.getInventory().getStack(plan.equipment).isOf(plan.stack.getItem());
            else if (plan.food != null) effectConfirmed = initialFood == 20 && plan.food.canAlwaysEat()
                    || serverFood >= Math.min(20, initialFood + plan.food.nutrition());
            if (!effectConfirmed) return;
            scope.release(); clean = true; phase = Phase.DONE; finished.run();
        }
    }
    int clickRevision(int original) { return exchange != null && exchange.sending() ? exchange.revision(original) : original; }
    void inventory(InventoryS2CPacket packet) {
        if (!current() || exchange == null || packet.getSyncId() != handler.syncId) return;
        try { exchange.confirm(state(packet.getContents(), packet.getCursorStack()), packet.getRevision()); }
        catch (RuntimeException error) { packetFailure = "GAME_ITEM_PACKET_INVALID"; }
    }
    void health(int food) { if (current() && effectIssued && plan.food != null) serverFood = food; }
    void block(BlockPos pos, BlockState state) {
        if (current() && effectIssued && plan.block != null && plan.placed.equals(pos)) effectConfirmed = state.getBlock() == plan.block;
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
