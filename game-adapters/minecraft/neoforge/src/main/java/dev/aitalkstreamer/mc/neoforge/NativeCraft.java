package dev.aitalkstreamer.mc.neoforge;

import com.google.gson.JsonObject;
import dev.aitalkstreamer.mc.core.*;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.client.gui.screens.inventory.CraftingScreen;
import net.minecraft.core.*;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.network.protocol.game.*;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.world.inventory.*;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.crafting.*;
import net.minecraft.world.level.ClipContext;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.phys.*;
import java.util.*;
import java.util.function.Supplier;
import java.util.stream.IntStream;
import static dev.aitalkstreamer.mc.core.Json.*;

/** This player's vanilla crafting menus, one leased click and authoritative full-state reply at a time. */
final class NativeCraft implements ExecutorTaskSession.Runtime {
    private record Spec(RecipeHolder<CraftingRecipe> entry, NativeCraftPlan.Plan plan, List<ItemStack> stock, BlockHitResult table) { }
    private final Minecraft client;
    private final NativeInputOwner inputs;
    private final Supplier<JsonObject> observation;
    private final List<ItemStack> types = new ArrayList<>();
    private final Deque<CraftExchange.Step> steps = new ArrayDeque<>();
    private final java.util.function.LongSupplier clock = () -> System.nanoTime() / 1_000_000;
    private JsonObject task;
    private ControlArbiter control;
    private ControlArbiter.Permit permit;
    private NativeContext owner;
    private NativeInputOwner.Scope scope;
    private AbstractContainerMenu menu;
    private Screen ownedScreen;
    private Spec spec;
    private int[] remaining;
    private List<Integer> inventory, grid;
    private CraftExchange.Confirmation confirmation;
    private Runnable finished;
    private CraftReceipt stopped;
    private int phase, batches, revision = -1, clicks, packets;
    private long deadline, openingDeadline;
    private boolean opening, closed, done, counted, clean;
    private String packetFailure;
    NativeCraft(Minecraft client, NativeInputOwner inputs, Supplier<JsonObject> observation) {
        this.client=client;this.inputs=inputs;this.observation=observation;
    }
    private void ready() {
        require(client.isSameThread(),"GAME_WRONG_THREAD");
        require(client.level!=null && client.player!=null && client.getConnection()!=null && client.gameMode!=null,"GAME_WORLD_UNAVAILABLE");
        require(client.player.isAlive() && client.isWindowActive() && !client.isPaused() && client.screen==null,"GAME_GUI_BLOCKED");
        require(!client.player.getAbilities().instabuild && !client.player.isSpectator() && !client.player.isUsingItem(),"GAME_CRAFT_CONTEXT_CHANGED");
        var handler=client.player.containerMenu;
        require(handler==client.player.inventoryMenu && handler.getClass()==InventoryMenu.class && handler.getCarried().isEmpty(),"GAME_CRAFT_HANDLER_INVALID");
        for(int i=0;i<5;i++) require(handler.getSlot(i).getItem().isEmpty(),"GAME_CRAFT_GRID_NOT_EMPTY");
    }
    private BlockHitResult table() {
        var eye=client.player.getEyePosition(); double reach=client.player.blockInteractionRange();
        BlockHitResult best=null;double nearest=reach*reach;
        var from=client.player.blockPosition();
        for(BlockPos pos:BlockPos.betweenClosed(from.offset(-5,-4,-5),from.offset(5,4,5))) {
            if(!client.level.hasChunkAt(pos) || !client.level.getBlockState(pos).is(Blocks.CRAFTING_TABLE)) continue;
            for(Direction face:Direction.values()) {
                var aim=Vec3.atCenterOf(pos).add(Vec3.atLowerCornerOf(face.getNormal()).scale(.499));
                double distance=eye.distanceToSqr(aim);if(distance>nearest)continue;
                var hit=client.level.clip(new ClipContext(eye,aim,ClipContext.Block.COLLIDER,ClipContext.Fluid.NONE,client.player));
                if(hit.getType()==HitResult.Type.BLOCK && hit.getBlockPos().equals(pos)) {best=hit;nearest=distance;}
            }
        }
        return best;
    }
    @SuppressWarnings("unchecked")
    private Spec capture(JsonObject goal) {
        ready();require(str(goal,"skill").equals("craft"),"GAME_CAPABILITY_UNAVAILABLE");
        String item=str(goal,"item_id");var id=ResourceLocation.tryParse(item);
        require(id!=null && BuiltInRegistries.ITEM.containsKey(id),"GAME_CRAFT_RECIPE_UNAVAILABLE");
        List<ItemStack> stock=IntStream.range(0,36).mapToObj(i->client.player.getInventory().getItem(i).copy()).toList();
        List<Integer> counts=stock.stream().map(ItemStack::getCount).toList();
        int baseline=InventoryTarget.count(observation.get(),item), requested=Math.toIntExact(num(goal,"count"));
        var candidates=new ArrayList<NativeCraftPlan.Plan>();var entries=new HashMap<String,RecipeHolder<CraftingRecipe>>();
        int scanned=0, known=0;
        for(var raw:client.getConnection().getRecipeManager().getRecipes()) {
            require(++scanned<=65536,"GAME_CRAFT_RECIPE_UNAVAILABLE");
            var value=raw.value();if(value.getClass()!=ShapedRecipe.class && value.getClass()!=ShapelessRecipe.class) continue;
            var entry=(RecipeHolder<CraftingRecipe>)(RecipeHolder<?>)raw;var recipe=entry.value();
            ItemStack output;
            try {output=recipe.getResultItem(client.level.registryAccess());}catch(RuntimeException unavailable){continue;}
            if(output.isEmpty() || !BuiltInRegistries.ITEM.getKey(output.getItem()).toString().equals(item))continue;
            known++;
            boolean shaped=recipe instanceof ShapedRecipe;
            var ingredients=recipe.getIngredients().stream().map(ingredient->new NativeCraftPlan.Ingredient(ingredient.isEmpty(),
                    ingredient.isEmpty()?Set.of():IntStream.range(0,36).filter(s->!stock.get(s).isEmpty() && ingredient.test(stock.get(s)))
                            .boxed().collect(java.util.stream.Collectors.toSet()))).toList();
            var candidate=new NativeCraftPlan.Recipe(entry.id().toString(),shaped,shaped?((ShapedRecipe)recipe).getWidth():0,
                    shaped?((ShapedRecipe)recipe).getHeight():0,output.getCount(),ingredients);
            var allocated=NativeCraftPlan.allocate(candidate,counts,item,baseline,requested);
            if(allocated!=null){candidates.add(allocated);entries.put(candidate.id(),entry);}
        }
        require(known>0,"GAME_CRAFT_RECIPE_UNAVAILABLE");var plan=NativeCraftPlan.unique(candidates);
        var table=plan.recipe().gridSize()==3?table():null;
        require(plan.recipe().gridSize()==2 || table!=null,"GAME_CRAFT_WORKSTATION_UNAVAILABLE");
        return new Spec(entries.get(plan.recipe().id()),plan,stock,table);
    }
    JsonObject check(JsonObject goal) {
        String reason=null;try{capture(goal);}catch(Rejected denied){reason=denied.code;}
        return obj("allowed",reason==null,"reason",reason,"source","runtime_client",
                "unknown_fields",List.of("server_crafting_restrictions","unsupported_dynamic_or_machine_recipes","unloaded_workstations"));
    }
    @Override public void start(JsonObject accepted,ControlArbiter control,ControlArbiter.Permit permit,
                                InventoryTarget target,BaseTarget base,Runnable finished) {
        require(task==null || closed,"GAME_TASK_BUSY");var captured=capture(accepted.getAsJsonObject("goal"));
        this.task=accepted.deepCopy();this.control=control;this.permit=permit;this.finished=finished;spec=captured;
        owner=new NativeContext(client.level,client.player,client.getConnection(),client.gameMode);scope=inputs.scope();
        remaining=spec.plan.allocations().stream().mapToInt(NativeCraftPlan.Allocation::count).toArray();
        confirmation=null;menu=null;ownedScreen=null;types.clear();steps.clear();stopped=null;packetFailure=null;
        phase=batches=clicks=packets=0;revision=-1;opening=closed=done=counted=clean=false;deadline=clock.getAsLong()+90000;
    }
    private boolean lease() {
        return task!=null && !closed && client.isSameThread() && control.allowed() && control.epoch()==permit.epoch()
                && client.level==owner.world() && client.player==owner.player() && client.getConnection()==owner.connection()
                && client.gameMode==owner.interactions();
    }
    private boolean current() {return lease() && menu!=null && client.player.containerMenu==menu && client.screen==ownedScreen;}
    private void context() {
        require(lease() && control.permit().equals(permit),"GAME_CRAFT_CONTEXT_CHANGED");
        owner.require(client.level,client.player,client.getConnection(),client.gameMode);
        require(client.player.isAlive() && client.isWindowActive() && !client.isPaused() && clock.getAsLong()<deadline,"GAME_CRAFT_CONTEXT_CHANGED");
        require(client.getConnection().getRecipeManager().byKey(spec.entry.id()).map(e->e.value()==spec.entry.value()).orElse(false),"GAME_CRAFT_RECIPE_CHANGED");
        require(packetFailure==null,packetFailure==null?"GAME_CRAFT_SERVER_PACKET_INVALID":packetFailure);
        if(menu!=null) {require(current(),"GAME_CRAFT_HANDLER_CHANGED");scope.currentMenu(menu,ownedScreen);}
        else {scope.current();require(client.player.containerMenu==client.player.inventoryMenu,"GAME_CRAFT_HANDLER_CHANGED");}
    }
    private void bind(AbstractContainerMenu handler,Screen screen) {
        require(handler.getClass()==(spec.plan.recipe().gridSize()==2?InventoryMenu.class:CraftingMenu.class),"GAME_CRAFT_HANDLER_INVALID");
        menu=handler;ownedScreen=screen;
        inventory=IntStream.range(0,36).mapToObj(index->IntStream.range(1,menu.slots.size())
                .filter(i->menu.getSlot(i).container==client.player.getInventory() && menu.getSlot(i).getContainerSlot()==index)
                .findFirst().orElseThrow(()->new Rejected("GAME_CRAFT_HANDLER_INVALID"))).toList();
        int size=spec.plan.recipe().gridSize();grid=IntStream.rangeClosed(1,size*size).boxed().toList();
        var state=state();require(state.cursor().empty() && grid.stream().allMatch(i->state.slots().get(i).empty()),"GAME_CRAFT_GRID_NOT_EMPTY");
        confirmation=new CraftExchange.Confirmation(clock,this::current);
    }
    void opened(ClientboundOpenScreenPacket packet) {
        if(!lease() || !opening || menu!=null)return;
        try {
            require(clock.getAsLong()<openingDeadline && packet.getType()==MenuType.CRAFTING
                    && client.player.containerMenu.containerId==packet.getContainerId()
                    && client.screen instanceof CraftingScreen screen && screen.getMenu()==client.player.containerMenu,
                    "GAME_CRAFT_HANDLER_CHANGED");
            require(client.level.getBlockState(spec.table.getBlockPos()).is(Blocks.CRAFTING_TABLE),"GAME_CRAFT_WORKSTATION_UNAVAILABLE");
            bind(client.player.containerMenu,client.screen);opening=false;
        }catch(RuntimeException failed){packetFailure="GAME_CRAFT_HANDLER_CHANGED";}
    }
    boolean allowsGui(JsonObject accepted) {
        return current() && !done && ownedScreen!=null && str(accepted,"task_id").equals(str(task,"task_id"))
                && num(accepted,"control_epoch")==permit.epoch();
    }
    @Override public boolean allowsGui() {return task!=null && allowsGui(task);}
    private CraftExchange.Stack token(ItemStack value) {
        if(value.isEmpty())return CraftExchange.Stack.EMPTY;
        for(int i=0;i<types.size();i++)if(ItemStack.isSameItemSameComponents(value,types.get(i)))
            return new CraftExchange.Stack(i+1,value.getCount(),value.getMaxStackSize());
        require(types.size()<512,"GAME_CRAFT_COMPONENT_BUDGET");types.add(value.copyWithCount(1));
        return new CraftExchange.Stack(types.size(),value.getCount(),value.getMaxStackSize());
    }
    private ItemStack stack(CraftExchange.Stack value) {return value.empty()?ItemStack.EMPTY:types.get(value.type()-1).copyWithCount(value.count());}
    private CraftExchange.State state(List<ItemStack> slots,ItemStack cursor) {return new CraftExchange.State(slots.stream().map(this::token).toList(),token(cursor));}
    private CraftExchange.State state() {return state(menu.slots.stream().map(s->s.getItem().copy()).toList(),menu.getCarried().copy());}
    private void materials() {
        int[] needed=NativeCraftPlan.remaining(spec.plan,remaining);
        for(int slot=0;slot<36;slot++)if(needed[slot]>0) {
            var actual=client.player.getInventory().getItem(slot);
            require(actual.getCount()>=needed[slot] && ItemStack.isSameItemSameComponents(actual,spec.stock.get(slot)),"GAME_CRAFT_MATERIAL_CHANGED");
        }
    }
    private void fill() {
        materials();var current=state();require(current.cursor().empty() && grid.stream().allMatch(i->current.slots().get(i).empty()),"GAME_CRAFT_GRID_NOT_EMPTY");
        var next=current;
        for(int ingredient=0;ingredient<spec.plan.recipe().ingredients().size();ingredient++) {
            if(spec.plan.recipe().ingredients().get(ingredient).empty())continue;
            int source=-1;
            for(int j=0;j<remaining.length;j++)if(remaining[j]>0 && spec.plan.allocations().get(j).ingredient()==ingredient) {
                source=spec.plan.allocations().get(j).slot();remaining[j]--;break;
            }
            require(source>=0,"GAME_CRAFT_ALLOCATION_EXHAUSTED");var material=stack(next.slots().get(inventory.get(source)));
            require(spec.entry.value().getIngredients().get(ingredient).test(material)
                    && ItemStack.isSameItemSameComponents(material,spec.stock.get(source)),"GAME_CRAFT_COMPONENT_CHANGED");
            var move=CraftExchange.moveOne(next,inventory.get(source),1+spec.plan.positions().get(ingredient));steps.addAll(move);next=move.getLast().after();
        }
    }
    private void output() {
        var before=state();int size=spec.plan.recipe().gridSize();
        var positioned=CraftingInput.ofPositioned(size,size,grid.stream().map(i->menu.getSlot(i).getItem().copy()).toList());
        var input=positioned.input();var recipe=spec.entry.value();
        require(recipe.matches(input,client.level),"GAME_CRAFT_RECIPE_NO_LONGER_MATCHES");
        var result=recipe.assemble(input,client.level.registryAccess());
        require(!result.isEmpty() && BuiltInRegistries.ITEM.getKey(result.getItem()).toString().equals(spec.plan.target().itemId())
                && result.getCount()==spec.plan.target().outputPerBatch(),"GAME_CRAFT_DYNAMIC_OUTPUT_CHANGED");
        var compact=recipe.getRemainingItems(input);
        require(compact.size()==input.width()*input.height(),"GAME_CRAFT_REMAINDER_INVALID");
        var rest=new ArrayList<>(Collections.nCopies(grid.size(),CraftExchange.Stack.EMPTY));
        for(int y=0;y<input.height();y++)for(int x=0;x<input.width();x++)
            rest.set((y+positioned.top())*size+x+positioned.left(),token(compact.get(y*input.width()+x)));
        var take=CraftExchange.output(before,token(result),grid,rest);var cleanup=new ArrayList<CraftExchange.Step>();
        var next=take.after();var deposit=CraftExchange.storeCursor(next,inventory);cleanup.addAll(deposit);if(!deposit.isEmpty())next=deposit.getLast().after();
        for(int slot:grid)if(!next.slots().get(slot).empty()) {
            var pick=CraftExchange.pickup(next,slot,0);cleanup.add(pick);next=pick.after();
            var store=CraftExchange.storeCursor(next,inventory);cleanup.addAll(store);if(!store.isEmpty())next=store.getLast().after();
        }
        steps.add(take);steps.addAll(cleanup);
    }
    @Override public void tick() {
        if(done)return;context();
        if(menu==null) {
            if(spec.plan.recipe().gridSize()==2)bind(client.player.inventoryMenu,null);
            else {
                if(opening){require(clock.getAsLong()<openingDeadline,"GAME_CRAFT_SERVER_TIMEOUT");return;}
                var fresh=table();require(fresh!=null && fresh.getBlockPos().equals(spec.table.getBlockPos()),"GAME_CRAFT_WORKSTATION_UNAVAILABLE");
                opening=true;openingDeadline=clock.getAsLong()+1500;scope.interact(fresh,control,permit);return;
            }
        }
        confirmation.check();if(confirmation.pending())return;
        if(!steps.isEmpty()) {
            var step=steps.remove();require(step.before().matches(state()),"GAME_CRAFT_STATE_CHANGED");
            require(menu.getSlot(step.slot()).mayPickup(client.player),"GAME_CRAFT_STATE_CHANGED");
            if(!menu.getCarried().isEmpty() && step.slot()!=0)require(menu.getSlot(step.slot()).mayPlace(menu.getCarried()),"GAME_CRAFT_STATE_CHANGED");
            confirmation.send(step,state(),menu.getStateId(),()->scope.click(menu,ownedScreen,step.slot(),step.button(),control,permit));clicks++;return;
        }
        if(phase==0) {fill();phase=1;return;}
        if(phase==1) {output();phase=2;return;}
        require(confirmation.crafts()==batches+1,"GAME_CRAFT_RESULT_NOT_CONFIRMED");batches++;counted=true;revision=confirmation.lastRevision();
        var finalState=state();require(finalState.cursor().empty() && grid.stream().allMatch(i->finalState.slots().get(i).empty())
                && finalState.slots().getFirst().empty(),"GAME_CRAFT_CLEANUP_NOT_CONFIRMED");
        if(batches<spec.plan.target().batches()){phase=0;counted=false;return;}
        if(ownedScreen!=null)scope.closeMenu(menu,ownedScreen,control,permit);
        scope.release();clean=true;done=true;finished.run();
    }
    int clickRevision(int original) {return confirmation!=null && confirmation.sending()?confirmation.revision(original):original;}
    void inventory(ClientboundContainerSetContentPacket packet) {
        if(!current() || confirmation==null || packet.getContainerId()!=menu.containerId)return;
        try {confirmation.confirm(state(packet.getItems(),packet.getCarriedItem()),packet.getStateId());packets++;}
        catch(RuntimeException failed){packetFailure="GAME_CRAFT_SERVER_PACKET_INVALID";}
    }
    @Override public CraftReceipt craftReceipt() {
        if(stopped!=null)return stopped;if(task==null)return null;
        int confirmed=confirmation==null?0:confirmation.crafts();
        int last=confirmation!=null && confirmation.lastRevision()>=0?confirmation.lastRevision():revision;
        var target=spec.plan.target();return new CraftReceipt(str(task,"task_id"),str(task,"world_session_id"),permit.epoch(),
                spec.plan.recipe().id(),target.itemId(),target.baseline(),target.requestedIncrement(),target.outputPerBatch(),
                target.batches(),confirmed,last,clean && done);
    }
    @Override public void cancel() {
        if(task==null || closed)return;var receipt=craftReceipt();if(confirmation!=null)confirmation.cancel();steps.clear();
        scope.release();stopped=receipt;closed=true;opening=false;
        // No clicks or screen changes after revocation; preserve actual cursor/grid for the human.
    }
    JsonObject proof() {
        if(task==null)return obj("active",false);
        var receipt=craftReceipt();return obj("active",!closed && !done,"task_id",str(task,"task_id"),"recipe_id",spec.plan.recipe().id(),
                "grid_size",spec.plan.recipe().gridSize(),"phase",phase,"clicks",clicks,"server_full_packets",packets,
                "confirmed_batches",receipt.confirmedBatches(),"planned_batches",receipt.batches(),"produced",receipt.produced(),
                "server_revision",receipt.lastServerRevision(),"clean_end",receipt.cleanEnd(),"owned_menu_current",current(),
                "cursor_empty",menu==null || menu.getCarried().isEmpty(),"cancelled_without_gui_writes",closed && !done);
    }
}
