package dev.aitalkstreamer.mc.survival;

import adris.altoclef.AltoClef;
import adris.altoclef.TaskCatalogue;
import adris.altoclef.tasks.container.DoStuffInContainerTask;
import adris.altoclef.tasksystem.Task;
import adris.altoclef.util.ItemTarget;
import dev.aitalkstreamer.mc.core.LocalTaskFailure;
import net.minecraft.block.Blocks;
import net.minecraft.client.MinecraftClient;
import net.minecraft.component.DataComponentTypes;
import net.minecraft.item.*;
import net.minecraft.network.packet.s2c.play.InventoryS2CPacket;
import net.minecraft.network.packet.s2c.play.ScreenHandlerSlotUpdateS2CPacket;
import net.minecraft.recipe.*;
import net.minecraft.recipe.input.SingleStackRecipeInput;
import net.minecraft.screen.AbstractFurnaceScreenHandler;
import net.minecraft.screen.slot.SlotActionType;
import java.util.*;
import java.util.stream.IntStream;
import static dev.aitalkstreamer.mc.core.Json.*;
import static dev.aitalkstreamer.mc.core.LocalTaskFailure.Reason.*;

/** Internal supply child. No new public skill, controller, retry loop or independent success. */
public final class ControlledCookingTask extends Task {
    private static ControlledCookingTask active;
    private final SurvivalAuthority.Session owner;
    private final Object world, player, connection;
    private final RecipeEntry<? extends AbstractCookingRecipe> recipe;
    private final CookingWorkstation workstation;
    private final boolean supply;
    private final ItemStack raw, cooked, fuel;
    private final int rawInventory, fuelInventory, inputs;
    private final List<ItemStack> types = new ArrayList<>();
    private final Task opening;
    private AbstractFurnaceScreenHandler handler;
    private List<ItemStack> openingContents;
    private ItemStack openingCursor;
    private List<Integer> main;
    private CookingExchange exchange;
    private int openingRevision, phase, movePhase, rawInserted;
    private boolean finished;
    private String packetFailure;

    private ControlledCookingTask(RecipeEntry<SmokingRecipe> recipe, int rawSlot, int fuelSlot) {
        this(CookingWorkstation.SMOKER,recipe,rawSlot,fuelSlot,true,1);
    }
    private ControlledCookingTask(CookingWorkstation workstation,RecipeEntry<? extends AbstractCookingRecipe> recipe,int rawSlot,int fuelSlot,boolean supply,int inputs) {
        owner = SurvivalAuthority.session(); var client = MinecraftClient.getInstance();
        require(inputs>0 && inputs<=SmeltingPlan.MAX_INPUTS && (workstation!=CookingWorkstation.SMOKER || inputs==1)
                && ResourceMaterials.conversionFuel(rawSlot,inputs,Set.of(fuelSlot))==fuelSlot,"GAME_COOKING_MATERIAL_CHANGED");
        world = client.world; player = client.player; connection = client.getNetworkHandler();
        this.recipe = recipe; this.workstation=workstation;this.supply=supply;this.inputs=inputs;opening=new OpenWorkstation(workstation);
        rawInventory = rawSlot; fuelInventory = fuelSlot;
        raw = client.player.getInventory().getStack(rawSlot).copyWithCount(1);
        fuel = client.player.getInventory().getStack(fuelSlot).copyWithCount(1);
        cooked = recipe.value().craft(new SingleStackRecipeInput(raw), client.world.getRegistryManager());
        require(!cooked.isEmpty() && (long)cooked.getCount()*inputs<=cooked.getMaxCount(),"GAME_RESOURCE_SMELTING_RECIPE_UNSUPPORTED");
        if(workstation.handler(client.player.currentScreenHandler)) {
            var snapshot=SurvivalGui.furnaceSnapshot();require(snapshot!=null,"GAME_COOKING_OPENING_CHANGED");
            handler=(AbstractFurnaceScreenHandler)snapshot.handler();openingContents=snapshot.contents();openingCursor=snapshot.cursor();openingRevision=snapshot.revision();
        }
        active = this;
        SurvivalAuthority.owned(() -> { if (active == this) active = null; if (exchange != null) exchange.cancel(); });
    }
    public static boolean busy() { return active != null && active.owner.current() && !active.finished; }
    static ControlledCookingTask resource(CookingWorkstation workstation,RecipeEntry<? extends AbstractCookingRecipe> recipe,int rawSlot,int fuelSlot) {
        return resource(workstation,recipe,rawSlot,fuelSlot,1);
    }
    static ControlledCookingTask resource(CookingWorkstation workstation,RecipeEntry<? extends AbstractCookingRecipe> recipe,int rawSlot,int fuelSlot,int inputs) {
        SurvivalAuthority.requireScope();require(!busy(),"GAME_COOKING_OWNER_CONFLICT");
        return new ControlledCookingTask(workstation,recipe,rawSlot,fuelSlot,false,inputs);
    }
    public static boolean blocksInventory() {return busy() && active.handler!=null;}
    public static boolean supplyBusy() {return ControlledFoodCookingTask.busy() || busy() && active.supply;}
    public static boolean retains(Task parent) {var own=active;return ControlledFoodCookingTask.retains(parent) || busy() && parent!=null && parent!=own && parent.thisOrChildSatisfies(t->t==own);}
    static void guardGuiWrite() {
        var own = active;
        if (busy() && own.exchange != null) require(own.exchange.sending(), "GAME_COOKING_GUI_BUSY");
    }
    static int clickRevision(int original) {
        var own = active;
        return busy() && own.exchange != null && own.exchange.sending() ? own.exchange.revision(original) : original;
    }
    static Optional<RecipeEntry<SmokingRecipe>> recipe(ItemStack input) {
        var client = MinecraftClient.getInstance();
        var match = client.getNetworkHandler().getRecipeManager().getFirstMatch(RecipeType.SMOKING, new SingleStackRecipeInput(input), client.world);
        return match.filter(entry -> {
            var output = entry.value().craft(new SingleStackRecipeInput(input), client.world.getRegistryManager());
            int rawNutrition = ControlledSupplyTask.allowedFood(input) ? input.get(DataComponentTypes.FOOD).nutrition() : 0;
            return entry.value().getCookingTime() > 0 && entry.value().getCookingTime() <= 120 && output.getCount() == 1
                    && ControlledSupplyTask.allowedFood(output) && output.get(DataComponentTypes.FOOD).nutrition() > rawNutrition;
        });
    }
    /** Actual safe stock plus finite, runtime-recipe cooking gains. Wheat/hay are counted once. */
    public static double foodPotential(AltoClef mod) {
        SurvivalAuthority.requireScope(); int potential = ControlledSupplyTask.inventoryNutrition();
        var inventory=mod.getPlayer().getInventory();int wheat=0;var candidates=new HashSet<Integer>();
        for(int i=0;i<36;i++) {
            var value=inventory.getStack(i);if(value.isEmpty() || mod.getBehaviour().isProtected(value.getItem())) continue;
            boolean ordinary=ItemStack.areItemsAndComponentsEqual(value,new ItemStack(value.getItem()));
            if(ordinary && (value.isOf(Items.WHEAT)||value.isOf(Items.HAY_BLOCK)) || recipe(value).isPresent()) candidates.add(i);
        }
        for(var available:ResourceMaterials.usable(candidates).entrySet()) {
            var value=inventory.getStack(available.getKey());int count=available.getValue();
            boolean ordinary=ItemStack.areItemsAndComponentsEqual(value,new ItemStack(value.getItem()));
            if(ordinary && value.isOf(Items.WHEAT)) {wheat=Math.addExact(wheat,count);continue;}
            if(ordinary && value.isOf(Items.HAY_BLOCK)) {wheat=Math.addExact(wheat,Math.multiplyExact(count,9));continue;}
            var entry=recipe(value);
            if(entry.isPresent()) {
                var output=entry.get().value().craft(new SingleStackRecipeInput(value),mod.getWorld().getRegistryManager());
                int existing=ControlledSupplyTask.allowedFood(value)?value.get(DataComponentTypes.FOOD).nutrition():0;
                potential=Math.addExact(potential,Math.multiplyExact(count,output.get(DataComponentTypes.FOOD).nutrition()-existing));
            }
        }
        return Math.addExact(potential, Math.multiplyExact(wheat / 3, 5));
    }
    /** Preparation retains the original episode; exact slots are captured only after the smoker is ready. */
    public static Task select(double units) {
        SurvivalAuthority.requireScope(); int target=SupplyPolicy.validateTarget(units);
        if(ControlledFoodCookingTask.busy()) return ControlledFoodCookingTask.currentTask();
        if(busy()) {require(active.owner==SurvivalAuthority.session(),"GAME_COOKING_OWNER_CONFLICT");return active.supply?active:null;}
        if(ControlledSupplyTask.inventoryNutrition()>=target) return null;
        var mod=AltoClef.getInstance();var inventory=mod.getPlayer().getInventory();
        for(int raw=0;raw<36;raw++) {
            var input=inventory.getStack(raw);
            if(input.isEmpty() || mod.getBehaviour().isProtected(input.getItem())) continue;
            var entry=recipe(input);if(entry.isPresent() && ResourceMaterials.consumable(raw)) return new ControlledFoodCookingTask(entry.get(),input,target);
        }
        return null;
    }
    static ControlledCookingTask supply(RecipeEntry<SmokingRecipe> recipe,int raw,int fuel) {
        SurvivalAuthority.requireScope();require(!busy(),"GAME_COOKING_OWNER_CONFLICT");return new ControlledCookingTask(recipe,raw,fuel);
    }
    @Override protected void onStart() { context(); }
    private void context() {
        SurvivalAuthority.requireScope(); var client = MinecraftClient.getInstance();
        if (owner != SurvivalAuthority.session() || !owner.current() || client.world != world || client.player != player
                || client.getNetworkHandler() != connection || !client.player.isAlive() || !client.isWindowFocused() || client.isPaused()
                || workstation.first(raw).map(entry -> entry.value() != recipe.value()).orElse(true)
                || !ItemStack.areEqual(recipe.value().craft(new SingleStackRecipeInput(raw), client.world.getRegistryManager()), cooked))
            throw new LocalTaskFailure(COOKING_CONTEXT_CHANGED);
        if (packetFailure != null) throw new LocalTaskFailure(COOKING_SERVER_DIVERGED);
    }
    public static void checkpoint() {
        SurvivalAuthority.requireScope(); ControlledFoodCookingTask.checkpoint(); if (!busy()) return;
        active.context(); if (active.exchange != null) active.exchange.check();
    }
    static void synchronizedInventory(InventoryS2CPacket packet) {
        var own = packetOwner(); if (own == null || packet.getSyncId() != MinecraftClient.getInstance().player.currentScreenHandler.syncId) return;
        try {
            if (own.exchange == null) {
                own.handler = (AbstractFurnaceScreenHandler) MinecraftClient.getInstance().player.currentScreenHandler;
                own.openingContents = packet.getContents().stream().map(ItemStack::copy).toList();
                own.openingCursor = packet.getCursorStack().copy(); own.openingRevision = packet.getRevision();
            } else own.exchange.inventory(own.state(packet.getContents(), packet.getCursorStack()), packet.getRevision());
        } catch (RuntimeException error) { own.packetFailure = "GAME_COOKING_SERVER_PACKET_INVALID"; }
    }
    static void synchronizedSlot(ScreenHandlerSlotUpdateS2CPacket packet) {
        var own = packetOwner(); if (own == null || own.exchange == null || packet.getSyncId() != own.handler.syncId) return;
        try { own.exchange.slot(packet.getSlot(), own.token(packet.getStack()), packet.getRevision()); }
        catch (RuntimeException error) { own.packetFailure = "GAME_COOKING_SERVER_PACKET_INVALID"; }
    }
    private static ControlledCookingTask packetOwner() {
        var own = active; var client = MinecraftClient.getInstance();
        if (!busy() || !client.isOnThread() || client.world != own.world || client.player != own.player
                || client.getNetworkHandler() != own.connection || !own.workstation.handler(client.player.currentScreenHandler)
                || own.handler != null && own.handler != client.player.currentScreenHandler) return null;
        return own;
    }
    @Override protected Task onTick() {
        context(); var client = MinecraftClient.getInstance(); if (finished) return null;
        if (exchange == null) {
            if (client.currentScreen == null) return opening;
            require(workstation.handler(SurvivalGui.ownedHandler()), "GAME_COOKING_HANDLER_INVALID");
            if (openingContents == null) return null;
            require(handler == SurvivalGui.ownedHandler(), "GAME_COOKING_HANDLER_CHANGED");
            main = IntStream.range(0, 36).mapToObj(index -> IntStream.range(3, 39)
                    .filter(i -> handler.getSlot(i).inventory == client.player.getInventory() && handler.getSlot(i).getIndex() == index)
                    .findFirst().orElseThrow(() -> new IllegalStateException("GAME_COOKING_HANDLER_INVALID"))).toList();
            require(ItemStack.areItemsAndComponentsEqual(client.player.getInventory().getStack(rawInventory), raw)
                    && ItemStack.areItemsAndComponentsEqual(client.player.getInventory().getStack(fuelInventory), fuel)
                    && ResourceMaterials.conversionFuel(rawInventory,inputs,Set.of(fuelInventory))==fuelInventory, "GAME_COOKING_MATERIAL_CHANGED");
            var initial = state(openingContents, openingCursor); require(initial.equals(state()), "GAME_COOKING_OPENING_CHANGED");
            exchange = new CookingExchange(initial, token(raw), token(cooked), token(fuel), openingRevision,
                    () -> System.nanoTime() / 1_000_000, owner::current, supply?CookingExchange.COOK_MS:SmeltingPlan.batchMillis(recipe.value().getCookingTime(),inputs,workstation.maximumTicks()),inputs);
            var capacity = initial.slot(main.get(rawInventory), initial.slots().get(main.get(rawInventory)).count(initial.slots().get(main.get(rawInventory)).count() - inputs));
            CraftClicks.storeCursor(new CraftClicks.State(capacity.slots(), token(cooked.copyWithCount(cooked.getCount()*inputs))), main);
        }
        exchange.check(); require(handler == SurvivalGui.ownedHandler(), "GAME_COOKING_HANDLER_CHANGED");
        if (exchange.pending()) return null;
        var current = state(); require(current.equals(exchange.server()), "GAME_COOKING_STATE_CHANGED");
        if (phase == 1 && exchange.cooked()) {
            if (!current.cursor().empty()) send(CookingExchange.pickup(current, main.get(fuelInventory), 0));
            else { phase = 2; movePhase = 0; }
            return null;
        }
        if (phase < 2) {
            int source = main.get(phase == 0 ? rawInventory : fuelInventory), destination = phase;
            if (movePhase == 0) { send(CookingExchange.pickup(current, source, 0)); movePhase = 1; }
            else if (movePhase == 1) {
                send(CookingExchange.pickup(current, destination, 1));
                if(phase!=0 || ++rawInserted==inputs)movePhase=2;
            }
            else if (!current.cursor().empty()) { send(CookingExchange.pickup(current, source, 0)); }
            else { phase++; movePhase = 0; }
            return null;
        }
        if (phase == 2) {
            if (!exchange.cooked()) return null;
            send(CookingExchange.pickup(current, 2, 0)); phase = 3; return null;
        }
        if (!current.cursor().empty()) {
            send(CraftClicks.storeCursor(current, main).getFirst()); return null;
        }
        if (!current.slots().get(1).empty()) { send(CookingExchange.pickup(current, 1, 0)); return null; }
        require(current.slots().subList(0, 3).stream().allMatch(CraftClicks.Stack::empty), "GAME_COOKING_CLEANUP_REQUIRED");
        // All returned stacks and empty cursor were acknowledged before relinquishing the GUI.
        active = null; SurvivalGui.close(client.player); finished = true; exchange.cancel(); return null;
    }
    private void send(CraftClicks.Step step) {
        var client = MinecraftClient.getInstance();
        exchange.send(step, state(), handler.getRevision(), () -> SurvivalGui.slot(client.interactionManager, handler.syncId,
                step.slot(), step.button(), SlotActionType.PICKUP, client.player));
    }
    private CraftClicks.Stack token(ItemStack value) {
        if (value.isEmpty()) return CraftClicks.Stack.EMPTY;
        for (int i = 0; i < types.size(); i++) if (ItemStack.areItemsAndComponentsEqual(value, types.get(i)))
            return new CraftClicks.Stack(i + 1, value.getCount(), value.getMaxCount());
        require(types.size() < 128, "GAME_COOKING_COMPONENT_BUDGET"); types.add(value.copyWithCount(1));
        return new CraftClicks.Stack(types.size(), value.getCount(), value.getMaxCount());
    }
    private CraftClicks.State state(List<ItemStack> values, ItemStack cursor) { return new CraftClicks.State(values.stream().map(this::token).toList(), token(cursor)); }
    private CraftClicks.State state() { return state(handler.slots.stream().map(slot -> slot.getStack().copy()).toList(), handler.getCursorStack().copy()); }
    @Override protected void onStop(Task interrupted) { /* Revocation must leave the operator's GUI and inventory untouched. */ }
    @Override public boolean isFinished() { return finished; }
    @Override protected boolean isEqual(Task other) { return other == this; }
    @Override protected String toDebugString() { return "Server-confirmed "+workstation.id()+" conversion"; }
    static final class OpenWorkstation extends DoStuffInContainerTask {
        private final CookingWorkstation workstation;
        OpenWorkstation(CookingWorkstation workstation) { super(workstation.block(), new ItemTarget(workstation.id()));this.workstation=workstation; }
        @Override protected boolean isContainerOpen(AltoClef mod) { return workstation.handler(mod.getPlayer().currentScreenHandler); }
        @Override protected Task containerSubTask(AltoClef mod) { return null; }
        @Override protected boolean isSubTaskEqual(DoStuffInContainerTask other) { return other == this; }
        @Override protected double getCostToMakeNew(AltoClef mod) { return 100; }
    }
}
