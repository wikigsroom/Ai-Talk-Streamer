package dev.aitalkstreamer.mc.neoforge;

import com.google.gson.JsonObject;
import dev.aitalkstreamer.mc.core.*;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.client.gui.screens.inventory.*;
import net.minecraft.core.*;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.network.protocol.game.*;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.tags.ItemTags;
import net.minecraft.world.inventory.*;
import net.minecraft.world.item.*;
import net.minecraft.world.item.crafting.*;
import net.minecraft.world.level.ClipContext;
import net.minecraft.world.level.block.*;
import net.minecraft.world.phys.*;
import java.util.*;
import java.util.function.Supplier;
import java.util.stream.IntStream;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Ordinary received cooking recipes, this player's actual furnace and the existing craft lease. */
final class NativeSmelt implements ExecutorTaskSession.Runtime {
    private enum Station {
        FURNACE(Blocks.FURNACE,MenuType.FURNACE,FurnaceMenu.class,FurnaceScreen.class),
        SMOKER(Blocks.SMOKER,MenuType.SMOKER,SmokerMenu.class,SmokerScreen.class),
        BLAST(Blocks.BLAST_FURNACE,MenuType.BLAST_FURNACE,BlastFurnaceMenu.class,BlastFurnaceScreen.class);
        final Block block;final MenuType<?> type;final Class<?> menu,screen;
        Station(Block block,MenuType<?> type,Class<?> menu,Class<?> screen){this.block=block;this.type=type;this.menu=menu;this.screen=screen;}
    }
    private record Spec(RecipeHolder<?> entry,AbstractCookingRecipe recipe,Station station,BlockHitResult hit,
                        ItemStack output,List<ItemStack> stock,NativeSmeltPlan.Plan plan) { }
    private final Minecraft client;
    private final NativeInputOwner inputs;
    private final Supplier<JsonObject> observation;
    private final java.util.function.LongSupplier clock=()->System.nanoTime()/1_000_000;
    private final List<ItemStack> types=new ArrayList<>();
    private final Deque<CraftExchange.Step> steps=new ArrayDeque<>();
    private JsonObject task;
    private ControlArbiter control;private ControlArbiter.Permit permit;
    private NativeContext owner;private NativeInputOwner.Scope scope;
    private Spec spec;private AbstractContainerMenu menu;private Screen ownedScreen;
    private List<Integer> inventory;
    private CookingExchange exchange;
    private CraftReceipt stopped;
    private Runnable finished;
    private int phase,batch,converted,clicks,packets,slotPackets,revision=-1;
    private long deadline,openingDeadline;
    private boolean opening,initial,closed,done,clean;
    private String packetFailure;
    NativeSmelt(Minecraft client,NativeInputOwner inputs,Supplier<JsonObject> observation){this.client=client;this.inputs=inputs;this.observation=observation;}
    private Station station(Object recipe){return recipe.getClass()==SmeltingRecipe.class?Station.FURNACE:
            recipe.getClass()==SmokingRecipe.class?Station.SMOKER:recipe.getClass()==BlastingRecipe.class?Station.BLAST:null;}
    private void ready(){
        require(client.isSameThread(),"GAME_WRONG_THREAD");
        require(client.level!=null && client.player!=null && client.getConnection()!=null && client.gameMode!=null,"GAME_WORLD_UNAVAILABLE");
        require(client.player.isAlive() && client.isWindowActive() && !client.isPaused() && client.screen==null,"GAME_COOKING_GUI_BUSY");
        require(!client.player.getAbilities().instabuild && !client.player.isSpectator() && !client.player.isUsingItem(),"GAME_COOKING_CONTEXT_CHANGED");
        var handler=client.player.containerMenu;
        require(handler==client.player.inventoryMenu && handler.getClass()==InventoryMenu.class && handler.getCarried().isEmpty(),"GAME_COOKING_CLEANUP_REQUIRED");
        for(int i=0;i<5;i++)require(handler.getSlot(i).getItem().isEmpty(),"GAME_COOKING_CLEANUP_REQUIRED");
    }
    private BlockHitResult find(Station station){
        var eye=client.player.getEyePosition();double nearest=Math.pow(client.player.blockInteractionRange(),2);BlockHitResult best=null;
        var from=client.player.blockPosition();
        for(BlockPos pos:BlockPos.betweenClosed(from.offset(-5,-4,-5),from.offset(5,4,5))) {
            if(!client.level.hasChunkAt(pos) || !client.level.getBlockState(pos).is(station.block))continue;
            for(Direction face:Direction.values()){
                var aim=Vec3.atCenterOf(pos).add(Vec3.atLowerCornerOf(face.getNormal()).scale(.499));double distance=eye.distanceToSqr(aim);
                if(distance>nearest)continue;
                var hit=client.level.clip(new ClipContext(eye,aim,ClipContext.Block.COLLIDER,ClipContext.Fluid.NONE,client.player));
                if(hit.getType()==HitResult.Type.BLOCK && hit.getBlockPos().equals(pos)){best=hit;nearest=distance;}
            }
        }return best;
    }
    private boolean receivedFirst(Spec candidate,ItemStack stack){return receivedFirst(candidate.entry,candidate.station,stack);}
    private boolean receivedFirst(RecipeHolder<?> entry,Station station,ItemStack stack){
        if(stack.isEmpty())return false;var input=new SingleRecipeInput(stack);
        var manager=client.getConnection().getRecipeManager();
        return switch(station){
            case FURNACE->manager.getRecipeFor(RecipeType.SMELTING,input,client.level).map(v->v.id().equals(entry.id())).orElse(false);
            case SMOKER->manager.getRecipeFor(RecipeType.SMOKING,input,client.level).map(v->v.id().equals(entry.id())).orElse(false);
            case BLAST->manager.getRecipeFor(RecipeType.BLASTING,input,client.level).map(v->v.id().equals(entry.id())).orElse(false);
        };
    }
    private int fuel(ItemStack stack,AbstractCookingRecipe recipe,String output){
        if(stack.isEmpty() || BuiltInRegistries.ITEM.getKey(stack.getItem()).toString().equals(output)
                || stack.hasCraftingRemainingItem() || !ItemStack.isSameItemSameComponents(stack,stack.getItem().getDefaultInstance()))return 0;
        if(!(stack.is(Items.COAL) || stack.is(Items.CHARCOAL) || stack.is(Items.COAL_BLOCK) || stack.is(Items.DRIED_KELP_BLOCK)
                || stack.is(ItemTags.LOGS) || stack.is(ItemTags.PLANKS)))return 0;
        return Math.max(0,stack.getBurnTime(recipe.getType()));
    }
    boolean hasRecipe(JsonObject goal){
        if(client.getConnection()==null || client.level==null)return false;
        String item=str(goal,"item_id");
        for(var entry:client.getConnection().getRecipeManager().getRecipes())if(station(entry.value())!=null){
            var result=entry.value().getResultItem(client.level.registryAccess());
            if(!result.isEmpty() && BuiltInRegistries.ITEM.getKey(result.getItem()).toString().equals(item))return true;
        }return false;
    }
    private Spec capture(JsonObject goal){
        ready();require(str(goal,"skill").equals("craft"),"GAME_CAPABILITY_UNAVAILABLE");
        String item=str(goal,"item_id");var id=ResourceLocation.tryParse(item);
        require(id!=null && BuiltInRegistries.ITEM.containsKey(id),"GAME_CRAFT_RECIPE_UNAVAILABLE");
        var stock=IntStream.range(0,36).mapToObj(i->client.player.getInventory().getItem(i).copy()).toList();
        int baseline=InventoryTarget.count(observation.get(),item),requested=Math.toIntExact(num(goal,"count"));
        var entries=new ArrayList<>(client.getConnection().getRecipeManager().getRecipes());
        require(entries.size()<=65536,"GAME_RESOURCE_SMELTING_RECIPE_UNSUPPORTED");
        entries.sort(Comparator.comparing(e->e.id().toString()));
        String failure="GAME_CRAFT_RECIPE_UNAVAILABLE";boolean known=false,available=false;
        for(var entry:entries){
            Station station=station(entry.value());if(station==null)continue;
            var recipe=(AbstractCookingRecipe)entry.value();var output=recipe.getResultItem(client.level.registryAccess());
            if(output.isEmpty() || !BuiltInRegistries.ITEM.getKey(output.getItem()).toString().equals(item))continue;
            known=true;var hit=find(station);if(hit==null)continue;available=true;
            try{
                var rows=stock.stream().map(stack->{
                    boolean raw=!stack.isEmpty() && !BuiltInRegistries.ITEM.getKey(stack.getItem()).toString().equals(item)
                            && recipe.matches(new SingleRecipeInput(stack),client.level) && receivedFirst(entry,station,stack)
                            && ItemStack.matches(recipe.assemble(new SingleRecipeInput(stack),client.level.registryAccess()),output);
                    return new NativeSmeltPlan.Stock(stack.getCount(),raw,fuel(stack,recipe,item));
                }).toList();
                var plan=NativeSmeltPlan.allocate(rows,recipe.getCookingTime(),output.getCount(),output.getMaxStackSize(),item,baseline,requested);
                return new Spec(entry,recipe,station,hit,output.copy(),stock,plan);
            }catch(Rejected denied){failure=denied.code;}
        }
        require(!known || available,"GAME_COOKING_WORKSTATION_UNAVAILABLE");throw new Rejected(failure);
    }
    JsonObject check(JsonObject goal){String reason=null;try{capture(goal);}catch(Rejected denied){reason=denied.code;}
        return obj("allowed",reason==null,"reason",reason,"source","runtime_client",
                "unknown_fields",List.of("unopened_furnace_contents","residual_furnace_heat","server_cooking_restrictions","unsupported_machine_recipes"));}
    @Override public void start(JsonObject accepted,ControlArbiter control,ControlArbiter.Permit permit,InventoryTarget target,BaseTarget base,Runnable finished){
        require(task==null || closed,"GAME_TASK_BUSY");var captured=capture(accepted.getAsJsonObject("goal"));
        task=accepted.deepCopy();this.control=control;this.permit=permit;this.finished=finished;spec=captured;
        owner=new NativeContext(client.level,client.player,client.getConnection(),client.gameMode);scope=inputs.scope();
        menu=null;ownedScreen=null;exchange=null;stopped=null;types.clear();steps.clear();packetFailure=null;
        phase=batch=converted=clicks=packets=slotPackets=0;revision=-1;opening=initial=closed=done=clean=false;
        deadline=clock.getAsLong()+spec.plan.budgetMillis()+10000;
    }
    private boolean lease(){return task!=null && !closed && client.isSameThread() && control.allowed() && control.epoch()==permit.epoch()
            && client.level==owner.world() && client.player==owner.player() && client.getConnection()==owner.connection() && client.gameMode==owner.interactions();}
    private boolean current(){return lease() && menu!=null && client.player.containerMenu==menu && client.screen==ownedScreen;}
    private void context(){
        require(lease() && control.permit().equals(permit),"GAME_COOKING_CONTEXT_CHANGED");
        owner.require(client.level,client.player,client.getConnection(),client.gameMode);
        require(client.player.isAlive() && client.isWindowActive() && !client.isPaused() && clock.getAsLong()<deadline,"GAME_COOKING_CONTEXT_CHANGED");
        require(client.getConnection().getRecipeManager().byKey(spec.entry.id()).map(e->e.value()==spec.entry.value()).orElse(false),"GAME_CRAFT_RECIPE_CHANGED");
        require(packetFailure==null,packetFailure==null?"GAME_COOKING_SERVER_PACKET_INVALID":packetFailure);
        if(menu==null){scope.current();require(client.player.containerMenu==client.player.inventoryMenu,"GAME_COOKING_HANDLER_CHANGED");}
        else {require(current(),"GAME_COOKING_HANDLER_CHANGED");scope.currentMenu(menu,ownedScreen);}
    }
    void opened(ClientboundOpenScreenPacket packet){
        if(!lease() || !opening || menu!=null)return;
        try{
            require(clock.getAsLong()<openingDeadline && packet.getType()==spec.station.type
                    && client.player.containerMenu.containerId==packet.getContainerId()
                    && client.player.containerMenu.getClass()==spec.station.menu && client.screen!=null && client.screen.getClass()==spec.station.screen
                    && client.screen instanceof AbstractContainerScreen<?> screen && screen.getMenu()==client.player.containerMenu,
                    "GAME_COOKING_HANDLER_INVALID");
            require(client.level.getBlockState(spec.hit.getBlockPos()).is(spec.station.block),"GAME_COOKING_WORKSTATION_UNAVAILABLE");
            menu=client.player.containerMenu;ownedScreen=client.screen;
            require(menu.slots.size()==39,"GAME_COOKING_HANDLER_INVALID");
            inventory=IntStream.range(0,36).mapToObj(index->IntStream.range(3,39).filter(i->menu.getSlot(i).container==client.player.getInventory()
                    && menu.getSlot(i).getContainerSlot()==index).findFirst().orElseThrow(()->new Rejected("GAME_COOKING_HANDLER_INVALID"))).toList();
            opening=false;
        }catch(RuntimeException failed){packetFailure="GAME_COOKING_HANDLER_INVALID";}
    }
    boolean allowsGui(JsonObject accepted){return current() && !done && str(accepted,"task_id").equals(str(task,"task_id")) && num(accepted,"control_epoch")==permit.epoch();}
    @Override public boolean allowsGui(){return task!=null && allowsGui(task);}
    private CraftExchange.Stack token(ItemStack stack){
        if(stack.isEmpty())return CraftExchange.Stack.EMPTY;
        for(int i=0;i<types.size();i++)if(ItemStack.isSameItemSameComponents(stack,types.get(i)))return new CraftExchange.Stack(i+1,stack.getCount(),stack.getMaxStackSize());
        require(types.size()<512,"GAME_COOKING_COMPONENT_BUDGET");types.add(stack.copyWithCount(1));return new CraftExchange.Stack(types.size(),stack.getCount(),stack.getMaxStackSize());
    }
    private CraftExchange.State state(List<ItemStack> slots,ItemStack cursor){return new CraftExchange.State(slots.stream().map(this::token).toList(),token(cursor));}
    private CraftExchange.State state(){return state(menu.slots.stream().map(s->s.getItem().copy()).toList(),menu.getCarried().copy());}
    private NativeSmeltPlan.Batch batch(){return spec.plan.batches().get(batch);}
    private void beginBatch(){
        int[] needed=spec.plan.requiredFrom(batch);
        for(int slot=0;slot<36;slot++)if(needed[slot]>0){var actual=client.player.getInventory().getItem(slot);
            require(actual.getCount()>=needed[slot] && ItemStack.isSameItemSameComponents(actual,spec.stock.get(slot)),"GAME_COOKING_MATERIAL_CHANGED");}
        var raw=client.player.getInventory().getItem(batch().rawSlot());
        require(receivedFirst(spec,raw) && spec.recipe.matches(new SingleRecipeInput(raw),client.level)
                && ItemStack.matches(spec.recipe.assemble(new SingleRecipeInput(raw),client.level.registryAccess()),spec.output),"GAME_CRAFT_RECIPE_CHANGED");
        var actual=state();require(actual.cursor().empty() && actual.slots().subList(0,3).stream().allMatch(CraftExchange.Stack::empty),"GAME_COOKING_CLEANUP_REQUIRED");
        var source=actual.slots().get(inventory.get(batch().rawSlot()));
        // Reserve capacity before touching the furnace. Returned fuel remains present in this pessimistic projection.
        var projected=actual.slot(inventory.get(batch().rawSlot()),source.count(source.count()-batch().inputs()));
        CraftExchange.storeCursor(new CraftExchange.State(projected.slots(),token(spec.output.copyWithCount(spec.output.getCount()*batch().inputs()))),inventory);
        exchange=new CookingExchange(actual,token(raw.copyWithCount(1)),token(spec.output),token(spec.stock.get(batch().fuelSlot()).copyWithCount(1)),
                revision,clock,this::current,batch().budgetMillis(),batch().inputs());phase=1;
        steps.add(CookingExchange.pickup(actual,inventory.get(batch().rawSlot()),0));
    }
    private void queueCursorReturn(int source){var state=exchange.server();if(!state.cursor().empty())steps.add(CookingExchange.pickup(state,inventory.get(source),0));}
    @Override public void tick(){
        if(done)return;context();
        if(menu==null){
            if(opening){require(clock.getAsLong()<openingDeadline,"GAME_COOKING_SERVER_TIMEOUT");return;}
            var hit=find(spec.station);require(hit!=null && hit.getBlockPos().equals(spec.hit.getBlockPos()),"GAME_COOKING_WORKSTATION_UNAVAILABLE");
            opening=true;openingDeadline=clock.getAsLong()+2000;scope.interact(hit,control,permit);return;
        }
        require(initial || clock.getAsLong()<openingDeadline,"GAME_COOKING_SERVER_TIMEOUT");if(!initial)return;
        if(exchange==null){beginBatch();return;}
        exchange.check();if(exchange.pending())return;
        if(!steps.isEmpty()){
            var step=steps.remove();require(step.before().equals(state()) && exchange.server().equals(state()),"GAME_COOKING_STATE_CHANGED");
            require(menu.getSlot(step.slot()).mayPickup(client.player),"GAME_COOKING_STATE_CHANGED");
            if(!menu.getCarried().isEmpty())require(menu.getSlot(step.slot()).mayPlace(menu.getCarried()),"GAME_COOKING_STATE_CHANGED");
            exchange.send(step,state(),menu.getStateId(),()->scope.click(menu,ownedScreen,step.slot(),step.button(),control,permit));clicks++;return;
        }
        var actual=exchange.server();
        if(phase==1){
            int inserted=actual.slots().get(0).count()+exchange.confirmedConversions();
            if(inserted<batch().inputs()){steps.add(CookingExchange.pickup(actual,0,1));return;}
            phase=2;queueCursorReturn(batch().rawSlot());return;
        }
        if(phase==2){
            if(exchange.cooked()){phase=5;return;}
            steps.add(CookingExchange.pickup(actual,inventory.get(batch().fuelSlot()),0));phase=3;return;
        }
        if(phase==3){if(!exchange.cooked())steps.add(CookingExchange.pickup(actual,1,1));phase=4;return;}
        if(phase==4){queueCursorReturn(batch().fuelSlot());phase=5;return;}
        if(phase==5){if(!exchange.cooked())return;steps.add(CookingExchange.pickup(actual,2,0));phase=6;return;}
        if(phase==6){steps.addAll(CraftExchange.storeCursor(actual,inventory));phase=7;return;}
        if(phase==7){if(!actual.slots().get(1).empty()){steps.add(CookingExchange.pickup(actual,1,0));phase=8;return;}phase=9;return;}
        if(phase==8){steps.addAll(CraftExchange.storeCursor(actual,inventory));phase=9;return;}
        require(actual.equals(state()) && actual.cursor().empty() && actual.slots().subList(0,3).stream().allMatch(CraftExchange.Stack::empty),"GAME_COOKING_CLEANUP_REQUIRED");
        require(exchange.confirmedConversions()==batch().inputs(),"GAME_COOKING_SERVER_DIVERGED");
        converted+=exchange.confirmedConversions();revision=exchange.lastRevision();exchange.cancel();exchange=null;batch++;
        if(batch<spec.plan.batches().size()){phase=0;return;}
        scope.closeMenu(menu,ownedScreen,control,permit);scope.release();clean=true;done=true;finished.run();
    }
    int clickRevision(int original){return exchange!=null && exchange.sending()?exchange.revision(original):original;}
    void inventory(ClientboundContainerSetContentPacket packet){
        if(!current() || packet.getContainerId()!=menu.containerId)return;
        try{
            var received=state(packet.getItems(),packet.getCarriedItem());packets++;
            if(!initial){require(received.equals(state()) && received.slots().size()==39,"GAME_COOKING_SERVER_PACKET_INVALID");
                require(received.cursor().empty() && received.slots().subList(0,3).stream().allMatch(CraftExchange.Stack::empty),"GAME_COOKING_CLEANUP_REQUIRED");
                revision=packet.getStateId();initial=true;
            }else if(exchange!=null)exchange.inventory(received,packet.getStateId());
        }catch(Rejected failed){packetFailure=failed.code;}catch(RuntimeException failed){packetFailure="GAME_COOKING_SERVER_PACKET_INVALID";}
    }
    void slot(ClientboundContainerSetSlotPacket packet){
        if(!current() || exchange==null || packet.getContainerId()!=menu.containerId)return;
        try{exchange.slot(packet.getSlot(),token(packet.getItem()),packet.getStateId());slotPackets++;}
        catch(RuntimeException failed){packetFailure="GAME_COOKING_SERVER_PACKET_INVALID";}
    }
    @Override public CraftReceipt craftReceipt(){
        if(stopped!=null)return stopped;if(task==null)return null;
        var target=spec.plan.target();return new CraftReceipt(str(task,"task_id"),str(task,"world_session_id"),permit.epoch(),spec.entry.id().toString(),
                target.itemId(),target.baseline(),target.requestedIncrement(),target.outputPerBatch(),target.batches(),
                converted+(exchange==null?0:exchange.confirmedConversions()),exchange==null?revision:exchange.lastRevision(),clean && done);
    }
    @Override public void cancel(){if(task==null || closed)return;stopped=craftReceipt();if(exchange!=null)exchange.cancel();steps.clear();scope.release();closed=true;opening=false;}
    JsonObject proof(){if(task==null)return obj("active",false);var receipt=craftReceipt();
        return obj("active",!closed && !done,"task_id",str(task,"task_id"),"recipe_id",spec.entry.id().toString(),"workstation",spec.station.name(),
                "phase",phase,"batch_index",batch,"planned_fuel_batches",spec.plan.batches().size(),"clicks",clicks,"server_full_packets",packets,
                "server_slot_packets",slotPackets,"confirmed_inputs",receipt.confirmedBatches(),"planned_inputs",receipt.batches(),"produced",receipt.produced(),
                "server_revision",receipt.lastServerRevision(),"clean_end",receipt.cleanEnd(),"owned_menu_current",current(),
                "cursor_empty",menu==null || menu.getCarried().isEmpty(),"cancelled_without_gui_writes",closed && !done);
    }
}
