package dev.aitalkstreamer.mc.survival;

import adris.altoclef.AltoClef;
import adris.altoclef.tasksystem.Task;
import adris.altoclef.util.helpers.ItemHelper;
import dev.aitalkstreamer.mc.core.InventoryExchange;
import dev.aitalkstreamer.mc.core.LocalTaskFailure;
import net.minecraft.client.MinecraftClient;
import net.minecraft.component.DataComponentTypes;
import net.minecraft.item.*;
import net.minecraft.network.packet.s2c.play.InventoryS2CPacket;
import net.minecraft.screen.PlayerScreenHandler;
import net.minecraft.screen.slot.SlotActionType;
import net.minecraft.util.Hand;
import java.util.*;
import java.util.stream.IntStream;
import static dev.aitalkstreamer.mc.core.Json.*;
import static dev.aitalkstreamer.mc.core.LocalTaskFailure.Reason.*;

/** An original-root child: one exact food stack, one use, full server resolution and restoration. */
public final class ControlledEatingTask extends Task {
    private enum Phase { PREPARE, PREPARE_ACK, USE, RESOLVE, RESTORE, RESTORE_ACK, DONE }
    private static ControlledEatingTask active;
    private static SurvivalAuthority.Session episodeOwner;
    private static EatingBudget episode;
    private final SurvivalAuthority.Session owner;
    private final Object world, player, connection;
    private final PlayerScreenHandler handler;
    private final ItemStack food;
    private final int source, hotbar, originalSelected, sourceSlot, handSlot;
    private final List<ItemStack> types = new ArrayList<>();
    private final InventoryExchange.State initial, prepared, consumed;
    private final EatingBudget budget;
    private InventoryExchange exchange;
    private Phase phase = Phase.PREPARE;
    private boolean held, interrupted, issuing;
    private String packetFailure;

    private ControlledEatingTask(int source) {
        owner = SurvivalAuthority.session(); var client = MinecraftClient.getInstance();
        world = client.world; player = client.player; connection = client.getNetworkHandler(); handler = client.player.playerScreenHandler;
        this.source = source; originalSelected = client.player.getInventory().selectedSlot; hotbar = source < 9 ? source : originalSelected;
        food = client.player.getInventory().getStack(source).copy(); sourceSlot = slot(source); handSlot = slot(hotbar);
        initial = state(); prepared = source < 9 ? initial : initial.swap(sourceSlot, handSlot);
        var remainder = food.get(DataComponentTypes.FOOD).usingConvertsTo().map(ItemStack::copy).orElse(ItemStack.EMPTY);
        // HoneyBottleItem additionally returns a bottle in its native finishUsing override.
        if (food.getItem().getClass() == HoneyBottleItem.class) remainder = new ItemStack(Items.GLASS_BOTTLE);
        require(remainder.isEmpty() || !remainder.contains(DataComponentTypes.FOOD), "GAME_EATING_REMAINDER_UNSUPPORTED");
        consumed = FoodInventory.consumed(prepared, handSlot, token(remainder), remainder.isEmpty() ? 64 : Math.min(64, remainder.getMaxCount()),
                IntStream.range(0,36).mapToObj(this::slot).toList(), slot(40));
        if (episodeOwner != owner || episode == null || episode.full()) {
            var original = owner; episodeOwner = owner; episode = new EatingBudget(now());
            SurvivalAuthority.owned(() -> { if (episodeOwner == original) { episodeOwner = null; episode = null; } });
        }
        budget = episode; budget.begin(now(), client.player.getHungerManager().getFoodLevel(), food.get(DataComponentTypes.FOOD).nutrition());
        active = this;
        SurvivalAuthority.owned(() -> { if (active == this) active = null; if (exchange != null) exchange.close(); });
    }
    public static boolean busy() { return active != null && active.owner.current() && active.phase != Phase.DONE; }
    public static boolean blocksRepeatedUse() { return busy() && !active.interrupted; }
    public static Task currentTask() { SurvivalAuthority.requireScope(); require(busy() && active.owner == SurvivalAuthority.session(), "GAME_EATING_NO_TASK"); return active; }
    public static Task select(Item requested) {
        SurvivalAuthority.requireScope(); if (busy()) return currentTask();
        var client = MinecraftClient.getInstance();
        if (client.currentScreen != null || client.player.isUsingItem() || client.player.getHungerManager().getFoodLevel() >= 20
                || ControlledCookingTask.blocksInventory() || ControlledEquipment.busy() || ControlledStorage.blocksInventory()) return null;
        ready(client);
        for (int i = 0; i < 36; i++) {
            var value = client.player.getInventory().getStack(i);
            if (value.isOf(requested) && canEat(value) && ItemHelper.canThrowAwayStack(AltoClef.getInstance(), value) && ResourceMaterials.consumable(i))
                return new ControlledEatingTask(i);
        }
        return null;
    }
    public static boolean canEat(ItemStack value) {
        if (!ControlledSupplyTask.allowedFood(value)) return false;
        Class<?> type = value.getItem().getClass();
        // These exact vanilla classes use the inspected food/remainder paths. Mod overrides
        // must acquire their own verified effect model rather than inheriting Item's model.
        return type == Item.class || type == AliasedBlockItem.class || type == HoneyBottleItem.class
                && value.get(DataComponentTypes.FOOD).usingConvertsTo().isEmpty();
    }
    private static void ready(MinecraftClient client) {
        require(client.isOnThread() && client.world != null && client.player != null && client.getNetworkHandler() != null
                && client.interactionManager != null && client.player.isAlive() && client.isWindowFocused() && !client.isPaused()
                && client.currentScreen == null && client.player.currentScreenHandler == client.player.playerScreenHandler
                && client.player.playerScreenHandler.getClass() == PlayerScreenHandler.class
                && client.player.playerScreenHandler.getCursorStack().isEmpty() && !client.player.isSpectator()
                && !client.player.getAbilities().creativeMode, "GAME_EATING_CONTEXT_CHANGED");
        for (int i = 0; i < 5; i++) require(client.player.playerScreenHandler.getSlot(i).getStack().isEmpty(), "GAME_EATING_GRID_NOT_EMPTY");
    }
    private void context() {
        SurvivalAuthority.requireScope(); var client = MinecraftClient.getInstance(); ready(client);
        if (owner != SurvivalAuthority.session() || client.world != world || client.player != player
                || client.getNetworkHandler() != connection || client.player.currentScreenHandler != handler)
            throw new LocalTaskFailure(EATING_CONTEXT_CHANGED);
        if (packetFailure != null) throw new LocalTaskFailure(EATING_SERVER_DIVERGED);
        budget.check(now());
        if (exchange != null) exchange.check();
    }
    public static void checkpoint() {
        SurvivalAuthority.requireScope(); if (!busy()) return;
        active.budget.check(now()); if (active.packetFailure != null) throw new LocalTaskFailure(EATING_SERVER_DIVERGED);
        if (active.exchange != null) active.exchange.check();
        // Emergency chains can keep FoodChain below the scheduler's winner indefinitely.
        // Resolve the existing interrupted child here; never issue a fresh bite or reset its clock.
        if (active.interrupted && !MinecraftClient.getInstance().player.isUsingItem()) active.onTick();
    }
    static void guardGuiWrite() {
        if (busy()) require(active.exchange != null && active.exchange.sending(), "GAME_EATING_GUI_BUSY");
    }
    static void guardItemUse() { if (busy() && !active.interrupted) require(active.issuing, "GAME_EATING_USE_BUSY"); }
    static void guardFoodStop() {
        SurvivalAuthority.requireScope(); var client = MinecraftClient.getInstance();
        require(busy() && active.owner == SurvivalAuthority.session() && active.held && !active.issuing
                && client.world == active.world && client.player == active.player && client.getNetworkHandler() == active.connection
                && (!client.player.isUsingItem() || ItemStack.areItemsAndComponentsEqual(client.player.getActiveItem(), active.food)),
                "GAME_EATING_STOP_NOT_OWNED");
    }
    static int clickRevision(int original) {
        return busy() && active.exchange != null && active.exchange.sending() ? active.exchange.revision(original) : original;
    }
    static void inventory(InventoryS2CPacket packet) {
        var own = packetOwner(); if (own == null || own.exchange == null || packet.getSyncId() != own.handler.syncId) return;
        try { own.exchange.confirm(own.state(packet.getContents(), packet.getCursorStack()), packet.getRevision()); }
        catch (RuntimeException error) { own.packetFailure = "GAME_EATING_SERVER_PACKET_INVALID"; }
    }
    static void health(int food) {
        var own = packetOwner(); if (own == null) return;
        try { own.budget.health(now(), food); }
        catch (RuntimeException error) { own.packetFailure = "GAME_EATING_SERVER_PACKET_INVALID"; }
    }
    private static ControlledEatingTask packetOwner() {
        var client = MinecraftClient.getInstance(); var own = active;
        return busy() && client.isOnThread() && client.world == own.world && client.player == own.player
                && client.getNetworkHandler() == own.connection && client.player.currentScreenHandler == own.handler ? own : null;
    }
    /** A live emergency may stop our current food use. Revoked cleanup never sends a stop packet. */
    public static void interrupt() {
        if (!SurvivalAuthority.inScope()) { SurvivalAuthority.requireOwnerScope(); return; }
        if (!busy()) return;
        require(active.owner == SurvivalAuthority.session(), "GAME_EATING_OWNER_CONFLICT");
        active.interrupted = true; active.releaseUse();
    }
    private void releaseUse() {
        if (!held) return;
        var client = MinecraftClient.getInstance();
        // Another emergency item use must not be stopped on behalf of our old bite.
        if (client.player.isUsingItem() && !ItemStack.areItemsAndComponentsEqual(client.player.getActiveItem(), food)) return;
        SurvivalInputs.key(client.options.useKey, false);
        // Always place RELEASE_USE_ITEM before the read barrier, including when the client
        // animation already ended. Otherwise the server could finish this bite after a zero
        // inventory snapshot. This path requires our original pending food request.
        SurvivalActions.stopFoodUse(client.interactionManager, client.player);
        held = false;
    }
    @Override protected void onStart() { context(); }
    @Override protected Task onTick() {
        context(); var client = MinecraftClient.getInstance();
        if (phase == Phase.PREPARE) {
            require(state().equals(initial), "GAME_EATING_SOURCE_CHANGED");
            sync(List.of(prepared), source < 9 ? 0 : sourceSlot, source < 9 ? SlotActionType.PICKUP : SlotActionType.SWAP,
                    source < 9 ? 0 : hotbar); phase = Phase.PREPARE_ACK; return null;
        }
        if (phase == Phase.PREPARE_ACK) {
            if (!exchange.confirmed()) return null;
            require(state().equals(prepared), "GAME_EATING_EQUIPMENT_CHANGED");
            if (interrupted) { budget.inventory(now(), false); phase = Phase.RESTORE; return null; }
            require(canEat(client.player.getInventory().getStack(hotbar))
                    && ItemHelper.canThrowAwayStack(AltoClef.getInstance(), client.player.getInventory().getStack(hotbar))
                    && ResourceMaterials.consumable(hotbar), "GAME_EATING_MATERIAL_RESERVED");
            SurvivalInputs.select(client.player.getInventory(), hotbar);
            budget.issue(now()); held = true; phase = Phase.USE;
            SurvivalInputs.key(client.options.useKey, true); issuing = true;
            try { if (!SurvivalActions.interactItem(client.interactionManager, client.player, Hand.MAIN_HAND).isAccepted()) interrupted = true; }
            finally { issuing = false; }
            return null;
        }
        if (phase == Phase.USE) {
            if (!interrupted && client.player.isUsingItem()) {
                require(client.player.getInventory().selectedSlot == hotbar
                        && ItemStack.areItemsAndComponentsEqual(client.player.getActiveItem(), food), "GAME_EATING_ACTIVE_ITEM_CHANGED"); return null;
            }
            releaseUse();
            if (held) return null; // An emergency item is still active; do not stop it or resolve the old bite yet.
            // Force a server read even when the local animation was cancelled or completed
            // before the next tick. Exactly zero or one consumption is resolvable.
            sync(List.of(prepared, consumed), 0, SlotActionType.PICKUP, 0); phase = Phase.RESOLVE; return null;
        }
        if (phase == Phase.RESOLVE) {
            if (!exchange.confirmed()) return null;
            budget.inventory(now(), exchange.confirmedState().equals(consumed));
            if (!budget.resolved(now())) return null;
            phase = Phase.RESTORE;
        }
        if (phase == Phase.RESTORE) {
            var current = state();
            require(current.equals(exchange.confirmedState()) && (current.equals(prepared) || current.equals(consumed)), "GAME_EATING_STATE_CHANGED");
            if (source >= 9) {
                sync(List.of(current.swap(sourceSlot, handSlot)), sourceSlot, SlotActionType.SWAP, hotbar); phase = Phase.RESTORE_ACK; return null;
            }
            finish(); return null;
        }
        if (phase == Phase.RESTORE_ACK) {
            if (!exchange.confirmed()) return null;
            require(state().equals(exchange.confirmedState()), "GAME_EATING_RESTORE_CHANGED"); finish();
        }
        return null;
    }
    private void finish() {
        var client = MinecraftClient.getInstance(); releaseUse();
        SurvivalInputs.select(client.player.getInventory(), originalSelected);
        budget.restored(now()); phase = Phase.DONE; active = null; if (exchange != null) exchange.close();
    }
    private int slot(int inventory) { return IntStream.range(5,46).filter(i -> handler.getSlot(i).inventory == MinecraftClient.getInstance().player.getInventory()
            && handler.getSlot(i).getIndex() == inventory).findFirst().orElseThrow(); }
    private InventoryExchange.Stack token(ItemStack value) {
        if (value.isEmpty()) return InventoryExchange.Stack.EMPTY;
        for (int i = 0; i < types.size(); i++) if (ItemStack.areItemsAndComponentsEqual(value, types.get(i))) return new InventoryExchange.Stack(i + 1,value.getCount());
        require(types.size() < 128, "GAME_EATING_COMPONENT_LIMIT"); types.add(value.copyWithCount(1)); return new InventoryExchange.Stack(types.size(),value.getCount());
    }
    private InventoryExchange.State state(List<ItemStack> values, ItemStack cursor) { return new InventoryExchange.State(values.stream().map(this::token).toList(),token(cursor)); }
    private InventoryExchange.State state() { return state(handler.slots.stream().map(s -> s.getStack().copy()).toList(),handler.getCursorStack()); }
    private void sync(List<InventoryExchange.State> expected, int slot, SlotActionType action, int button) {
        if (exchange != null) exchange.close(); exchange = new InventoryExchange(() -> now(), owner::current);
        var actual = state();
        exchange.sendAlternatives(actual, expected, actual, handler.getRevision(), () -> SurvivalGui.slot(MinecraftClient.getInstance().interactionManager,
                handler.syncId, slot, button, action, MinecraftClient.getInstance().player));
    }
    @Override protected void onStop(Task interrupting) { interrupt(); }
    @Override public boolean isFinished() { return phase == Phase.DONE; }
    @Override protected boolean isEqual(Task other) { return other == this; }
    @Override protected String toDebugString() { return "Server-confirmed food use and hotbar restoration"; }
    private static long now() { return System.nanoTime() / 1_000_000; }
}
