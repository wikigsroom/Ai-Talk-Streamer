package dev.aitalkstreamer.mc.survival;

import adris.altoclef.AltoClef;
import adris.altoclef.tasks.container.DoStuffInContainerTask;
import adris.altoclef.tasksystem.Task;
import adris.altoclef.util.ItemTarget;
import dev.aitalkstreamer.mc.core.CraftReceipt;
import net.minecraft.block.Blocks;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.gui.screen.ingame.InventoryScreen;
import net.minecraft.item.ItemStack;
import net.minecraft.network.packet.s2c.play.InventoryS2CPacket;
import net.minecraft.recipe.input.CraftingRecipeInput;
import net.minecraft.registry.Registries;
import net.minecraft.screen.*;
import net.minecraft.screen.slot.SlotActionType;
import java.util.*;
import java.util.stream.IntStream;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Public craft uses exact allocated stacks and authoritative full-state confirmations. */
public final class ConfirmedCraftTask extends Task implements adris.altoclef.tasksystem.ITaskUsesCraftingGrid {
    private static ConfirmedCraftTask transaction;
    private final CraftSpec spec;
    private final SurvivalAuthority.Session owner;
    private final Object world, player, connection;
    private final List<ItemStack> types = new ArrayList<>();
    private final Deque<CraftClicks.Step> steps = new ArrayDeque<>();
    private final int[] remaining;
    private ScreenHandler handler;
    private List<Integer> main, grid;
    private CraftClicks.Confirmation confirmation;
    private int phase, confirmed, revision = -1;
    private boolean finished, counted;
    private String packetFailure;
    private Task opening;

    ConfirmedCraftTask(CraftSpec spec) {
        this.spec = spec; owner = SurvivalAuthority.session(); var client = MinecraftClient.getInstance();
        world = client.world; player = client.player; connection = client.getNetworkHandler();
        remaining = spec.plan.allocation().stream().mapToInt(CraftPlan.Allocation::count).toArray();
        SurvivalAuthority.owned(() -> { if (transaction == this) transaction = null; if (confirmation != null) confirmation.cancel(); });
    }
    public static boolean busy() { return transaction!=null && transaction.owner.current() && !transaction.finished; }
    /** Keep the immediate path to this transaction; ancestors must not act on predicted output or cursor stacks. */
    public static boolean retains(Task parent) {
        var own=transaction;return busy() && parent!=null && parent!=own && parent.thisOrChildSatisfies(task->task==own);
    }
    public static void checkpoint() {
        SurvivalAuthority.requireScope();if(!busy()) return;transaction.context();transaction.confirmation.check();
    }
    static void guardGuiWrite() {
        var own = transaction;
        if (own != null && own.owner.current()) require(own.confirmation != null && own.confirmation.sending(), "GAME_CRAFT_GUI_BUSY");
    }
    static int clickRevision(int original) {
        var own = transaction;
        return own != null && own.owner.current() && own.confirmation != null && own.confirmation.sending()
                ? own.confirmation.revision(original) : original;
    }
    static void synchronizedInventory(InventoryS2CPacket packet) {
        var own = transaction; if (own == null || !own.owner.current()) return;
        var client = MinecraftClient.getInstance();
        if (!client.isOnThread() || client.world != own.world || client.player != own.player
                || client.getNetworkHandler() != own.connection || own.handler != client.player.currentScreenHandler
                || own.confirmation == null || packet.getSyncId() != own.handler.syncId) return;
        try { own.confirmation.confirm(own.state(packet.getContents(), packet.getCursorStack()), packet.getRevision()); }
        catch (RuntimeException error) { own.packetFailure = "GAME_CRAFT_SERVER_PACKET_INVALID"; }
    }
    CraftReceipt receipt(boolean clean) {
        var context = owner.context(); var target = spec.plan.target();
        // A confirmed output remains evidence even if cancellation arrives before the next task tick.
        int batches = confirmed + (confirmation != null && !counted ? confirmation.crafts() : 0);
        int last = confirmation != null && confirmation.lastRevision() >= 0 ? confirmation.lastRevision() : revision;
        return new CraftReceipt(context.task(), context.world(), context.epoch(), spec.plan.recipeId(), target.itemId(),
                target.baseline(), target.requestedIncrement(), target.outputPerBatch(), target.batches(), batches, last, clean && finished);
    }
    @Override protected void onStart() { SurvivalAuthority.requireScope(); }
    private void context() {
        SurvivalAuthority.requireScope(); var client = MinecraftClient.getInstance();
        require(owner == SurvivalAuthority.session() && client.world == world && client.player == player
                && client.getNetworkHandler() == connection && client.player.isAlive() && client.isWindowFocused() && !client.isPaused(), "GAME_CRAFT_CONTEXT_CHANGED");
        require(client.getNetworkHandler().getRecipeManager().get(spec.entry.id()).map(e -> e.value() == spec.entry.value()).orElse(false),
                "GAME_CRAFT_RECIPE_CHANGED");
        if (packetFailure != null) throw new IllegalStateException(packetFailure);
    }
    @Override protected Task onTick() {
        context(); var client = MinecraftClient.getInstance(); if (finished) return null;
        if (confirmation == null) {
            if (client.currentScreen == null) {
                if (spec.plan.gridSize() == 2) SurvivalGui.screen(client, new InventoryScreen(client.player));
                else { if (opening == null) opening = new OpenTable(); return opening; }
                return null;
            }
            handler = SurvivalGui.ownedHandler();
            require(spec.plan.gridSize() == 2 ? handler.getClass() == PlayerScreenHandler.class : handler.getClass() == CraftingScreenHandler.class,
                    "GAME_CRAFT_HANDLER_INVALID");
            require(transaction == null || transaction == this || !transaction.owner.current(), "GAME_CRAFT_GUI_BUSY");
            // Intervening food or table preparation may change unrelated stock. Every
            // remaining allocated input must still have its original components and count.
            var needed=CraftPlan.remainingBySlot(spec.plan,remaining);
            for (int source=0;source<36;source++) {
                int required=needed[source];
                if(required>0) {var material=client.player.getInventory().getStack(source);
                    require(material.getCount()>=required && ItemStack.areItemsAndComponentsEqual(material,spec.stock().get(source)),"GAME_CRAFT_MATERIAL_CHANGED");}
            }
            main = IntStream.range(0, 36).mapToObj(index -> IntStream.range(1, handler.slots.size())
                    .filter(i -> handler.getSlot(i).inventory == client.player.getInventory() && handler.getSlot(i).getIndex() == index)
                    .findFirst().orElseThrow(() -> new IllegalStateException("GAME_CRAFT_HANDLER_INVALID"))).toList();
            grid = IntStream.rangeClosed(1, spec.plan.gridSize() * spec.plan.gridSize()).boxed().toList();
            var initial = state(); require(initial.cursor().empty() && grid.stream().allMatch(i -> initial.slots().get(i).empty()), "GAME_CRAFT_GRID_NOT_EMPTY");
            confirmation = new CraftClicks.Confirmation(() -> System.nanoTime() / 1_000_000, owner::current);
            transaction = this; phase = 0; counted = false; buildFill(initial);
        }
        confirmation.check(); require(handler == SurvivalGui.ownedHandler(), "GAME_CRAFT_HANDLER_CHANGED");
        if (confirmation.pending()) return null;
        if (!steps.isEmpty()) {
            var step = steps.removeFirst(); var actual = state();
            confirmation.send(step, actual, handler.getRevision(), () -> SurvivalGui.slot(client.interactionManager, handler.syncId,
                    step.slot(), step.button(), SlotActionType.PICKUP, client.player)); return null;
        }
        if (phase == 0) { buildOutput(); phase = 1; return null; }
        if (phase == 1) {
            require(confirmation.crafts() == 1, "GAME_CRAFT_RESULT_NOT_CONFIRMED");
            confirmed++; counted = true; revision = confirmation.lastRevision(); phase = 2; return null;
        }
        var current = state(); require(current.cursor().empty() && grid.stream().allMatch(i -> current.slots().get(i).empty()), "GAME_CRAFT_CLEANUP_NOT_CONFIRMED");
        revision = confirmation.lastRevision();
        // Each batch ends with server-confirmed empty cursor/grid. Reopen under a new
        // GUI lease, never extend the absolute lifetime of an already open screen.
        transaction = null; SurvivalGui.close(client.player); confirmation.cancel(); confirmation = null; handler = null; opening = null;
        if (confirmed == spec.plan.target().batches()) finished = true;
        return null;
    }
    private void buildFill(CraftClicks.State initial) {
        var current = initial;
        for (int ingredient = 0; ingredient < spec.entry.value().getIngredients().size(); ingredient++) {
            if (spec.entry.value().getIngredients().get(ingredient).isEmpty()) continue;
            int source = -1;
            for (int i = 0; i < remaining.length; i++) {
                var allocation = spec.plan.allocation().get(i);
                if (allocation.ingredientIndex() == ingredient && remaining[i] > 0) { source = allocation.inventorySlot(); remaining[i]--; break; }
            }
            require(source >= 0, "GAME_CRAFT_ALLOCATION_EXHAUSTED");
            var material = stack(current.slots().get(main.get(source)));
            require(spec.entry.value().getIngredients().get(ingredient).test(material)
                    && ItemStack.areItemsAndComponentsEqual(material, spec.stock().get(source)), "GAME_CRAFT_COMPONENT_CHANGED");
            var move = CraftClicks.moveOne(current, main.get(source), 1 + spec.plan.gridSlots().get(ingredient));
            steps.addAll(move); current = move.getLast().after();
        }
    }
    private void buildOutput() {
        var client = MinecraftClient.getInstance(); var before = state();
        var input = CraftingRecipeInput.create(spec.plan.gridSize(), spec.plan.gridSize(), grid.stream().map(i -> handler.getSlot(i).getStack().copy()).toList());
        var recipe = spec.entry.value(); require(recipe.matches(input, client.world), "GAME_CRAFT_RECIPE_NO_LONGER_MATCHES");
        ItemStack output = recipe.craft(input, client.world.getRegistryManager());
        require(!output.isEmpty() && Registries.ITEM.getId(output.getItem()).toString().equals(spec.plan.target().itemId())
                && output.getCount() == spec.plan.target().outputPerBatch(), "GAME_CRAFT_DYNAMIC_OUTPUT_CHANGED");
        // CraftingRecipeInput trims the grid. Remainders must be mapped back using
        // the positioned input rather than shifting shaped/empty recipe slots.
        var positioned = CraftingRecipeInput.createPositioned(spec.plan.gridSize(), spec.plan.gridSize(), grid.stream().map(i -> handler.getSlot(i).getStack().copy()).toList());
        var compact = recipe.getRemainder(positioned.input());
        List<CraftClicks.Stack> rest = new ArrayList<>(Collections.nCopies(grid.size(), CraftClicks.Stack.EMPTY));
        for (int y = 0; y < positioned.input().getHeight(); y++) for (int x = 0; x < positioned.input().getWidth(); x++)
            rest.set((y + positioned.top()) * spec.plan.gridSize() + x + positioned.left(), token(compact.get(y * positioned.input().getWidth() + x)));
        var take = CraftClicks.output(before, token(output), grid, rest);
        // Plan all return/storage operations before taking output. Never discard to
        // the ground or swap components to create room.
        List<CraftClicks.Step> cleanup = new ArrayList<>(); var current = take.after();
        var deposit = CraftClicks.storeCursor(current, main); cleanup.addAll(deposit); if (!deposit.isEmpty()) current = deposit.getLast().after();
        for (int slot : grid) if (!current.slots().get(slot).empty()) {
            var pick = CraftClicks.pickup(current, slot, 0); cleanup.add(pick); current = pick.after();
            var store = CraftClicks.storeCursor(current, main); cleanup.addAll(store); if (!store.isEmpty()) current = store.getLast().after();
        }
        steps.add(take); steps.addAll(cleanup);
    }
    private CraftClicks.Stack token(ItemStack value) {
        if (value.isEmpty()) return CraftClicks.Stack.EMPTY;
        for (int i = 0; i < types.size(); i++) if (ItemStack.areItemsAndComponentsEqual(value, types.get(i)))
            return new CraftClicks.Stack(i + 1, value.getCount(), value.getMaxCount());
        require(types.size() < 512, "GAME_CRAFT_COMPONENT_BUDGET"); types.add(value.copyWithCount(1));
        return new CraftClicks.Stack(types.size(), value.getCount(), value.getMaxCount());
    }
    private ItemStack stack(CraftClicks.Stack value) { return value.empty() ? ItemStack.EMPTY : types.get(value.type() - 1).copyWithCount(value.count()); }
    private CraftClicks.State state(List<ItemStack> slots, ItemStack cursor) { return new CraftClicks.State(slots.stream().map(this::token).toList(), token(cursor)); }
    private CraftClicks.State state() { return state(handler.slots.stream().map(s -> s.getStack().copy()).toList(), handler.getCursorStack().copy()); }
    @Override protected void onStop(Task interrupted) { /* No game effects during revoked cleanup. */ }
    @Override public boolean isFinished() { return finished; }
    @Override protected boolean isEqual(Task other) { return other == this; }
    @Override protected String toDebugString() { return "Confirmed craft " + spec.plan.recipeId(); }
    private static final class OpenTable extends DoStuffInContainerTask {
        OpenTable() { super(Blocks.CRAFTING_TABLE, new ItemTarget("crafting_table")); }
        @Override protected boolean isContainerOpen(AltoClef mod) { return MinecraftClient.getInstance().player.currentScreenHandler instanceof CraftingScreenHandler; }
        @Override protected Task containerSubTask(AltoClef mod) { return null; }
        @Override protected boolean isSubTaskEqual(DoStuffInContainerTask other) { return other == this; }
        @Override protected double getCostToMakeNew(AltoClef mod) { return Double.POSITIVE_INFINITY; }
    }
}
