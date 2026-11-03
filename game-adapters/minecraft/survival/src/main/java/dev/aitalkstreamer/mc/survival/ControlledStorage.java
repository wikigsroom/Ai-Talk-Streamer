package dev.aitalkstreamer.mc.survival;

import adris.altoclef.AltoClef;
import adris.altoclef.TaskCatalogue;
import adris.altoclef.chains.FoodChain;
import adris.altoclef.chains.UserTaskChain;
import adris.altoclef.tasksystem.*;
import adris.altoclef.util.ItemTarget;
import dev.aitalkstreamer.mc.core.InventoryExchange.Stack;
import net.minecraft.client.MinecraftClient;
import net.minecraft.item.*;
import net.minecraft.network.packet.s2c.play.InventoryS2CPacket;
import net.minecraft.screen.GenericContainerScreenHandler;
import net.minecraft.screen.slot.SlotActionType;
import net.minecraft.util.math.BlockPos;
import java.util.*;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Original Pickup/Store task resource path. No independent controller, public skill or cleanup clicks. */
public final class ControlledStorage {
    private static final Map<Task,Entry> entries=new IdentityHashMap<>();
    private static final StorageObservers<Item,BlockPos> observers=new StorageObservers<>();
    private static SurvivalAuthority.Session root;
    private static Entry opening,active;
    private static final class Entry {
        final SurvivalAuthority.Session owner;
        final Task task;
        final BlockPos target;
        final ItemTarget[] goals;
        final boolean deposit;
        final Object world,player,connection;
        final StorageLedger<Item> deposited=new StorageLedger<>();
        final List<ItemStack> types=new ArrayList<>();
        GenericContainerScreenHandler handler;
        StorageExchange exchange;
        Item moved;
        int amount,destination;
        long openingDeadline;
        boolean done,aborted,packetFailure;
        Entry(Task task,BlockPos target,ItemTarget[] goals,boolean deposit) {
            owner=SurvivalAuthority.session();this.task=task;this.target=target.toImmutable();this.deposit=deposit;
            this.goals=Arrays.stream(goals).map(g->new ItemTarget(g.getMatches().clone(),g.getTargetCount())).toArray(ItemTarget[]::new);
            var c=MinecraftClient.getInstance();world=c.world;player=c.player;connection=c.getNetworkHandler();
        }
        Stack token(ItemStack value) {
            if(value.isEmpty())return Stack.EMPTY;
            for(int i=0;i<types.size();i++)if(ItemStack.areItemsAndComponentsEqual(value,types.get(i)))return new Stack(i+1,value.getCount());
            require(types.size()<256,"GAME_STORAGE_COMPONENT_LIMIT");types.add(value.copyWithCount(1));return new Stack(types.size(),value.getCount());
        }
        StorageExchange.State state(List<ItemStack> values,ItemStack cursor){return new StorageExchange.State(values.stream().map(this::token).toList(),token(cursor));}
        StorageExchange.State state(){return state(handler.slots.stream().map(s->s.getStack().copy()).toList(),handler.getCursorStack());}
        int need(ItemTarget goal,List<ItemStack> playerItems) {
            if(deposit)return deposited.need(Arrays.asList(goal.getMatches()),goal.getTargetCount());
            int have=playerItems.stream().filter(s->goal.matches(s.getItem())).mapToInt(ItemStack::getCount).sum();
            return Math.max(0,goal.getTargetCount()-have);
        }
    }
    private static long now(){return System.nanoTime()/1_000_000;}
    private static MinecraftClient client(Entry own) {
        SurvivalAuthority.requireScope();var c=MinecraftClient.getInstance();
        require(c.isOnThread() && own.owner==SurvivalAuthority.session() && own.owner.current() && !own.aborted
                && c.world==own.world && c.player==own.player && c.getNetworkHandler()==own.connection
                && c.player!=null && c.player.isAlive() && c.interactionManager!=null && c.isWindowFocused() && !c.isPaused()
                && !c.player.isSpectator() && !c.player.getAbilities().creativeMode,"GAME_STORAGE_CONTEXT_CHANGED");return c;
    }
    private static Entry entry(Task task,BlockPos target,ItemTarget[] goals,boolean deposit) {
        SurvivalAuthority.requireScope();require(task!=null && target!=null && goals!=null && goals.length>0 && goals.length<=64
                && Arrays.stream(goals).allMatch(g->g!=null && g.getMatches()!=null && g.getMatches().length>0 && g.getMatches().length<=256
                && Arrays.stream(g.getMatches()).allMatch(Objects::nonNull) && g.getTargetCount()>=0 && g.getTargetCount()<=4096),"GAME_STORAGE_TARGET_INVALID");
        require(Arrays.stream(goals).flatMap(g->Arrays.stream(g.getMatches())).distinct().count()<=256,"GAME_STORAGE_TARGET_INVALID");
        ensureRoot();var found=entries.get(task);
        if(found==null){require(entries.size()<64,"GAME_STORAGE_TARGET_INVALID");found=new Entry(task,target,goals,deposit);entries.put(task,found);}
        require(found.target.equals(target) && found.deposit==deposit && Arrays.equals(found.goals,goals),"GAME_STORAGE_TARGET_INVALID");
        client(found);return found;
    }
    private static void ensureRoot(){
        var owner=SurvivalAuthority.session();
        if(root==null){root=owner;SurvivalAuthority.owned(()->{for(var e:entries.values())if(e.exchange!=null)e.exchange.close();entries.clear();observers.clear();opening=active=null;root=null;});}
        require(root==owner,"GAME_STORAGE_CONTEXT_CHANGED");
    }
    public static void watch(Task task,java.util.function.Predicate<BlockPos> filter,java.util.function.BiConsumer<Item,Integer> receive){ensureRoot();observers.watch(task,filter,receive);}
    public static void unwatch(Task task){SurvivalAuthority.requireOwnerScope();observers.unwatch(task);}
    /** Runs before the existing navigation/open task. Acquisition remains in the original task tree. */
    public static Task prepare(Task task,BlockPos target,ItemTarget[] goals,boolean deposit,boolean acquire) {
        var own=entry(task,target,goals,deposit);var c=client(own);
        require(active==null || active==own,"GAME_STORAGE_GUI_BUSY");if(own.done)return null;
        if(deposit && acquire && active==null) {
            for(var goal:own.goals) {
                int need=own.need(goal,List.of());var candidates=new HashSet<Integer>();int have=0;
                for(int i=0;i<36;i++){var stack=c.player.getInventory().getStack(i);if(goal.matches(stack.getItem())){candidates.add(i);have+=stack.getCount();}}
                int free=ResourceMaterials.usable(candidates).values().stream().mapToInt(Integer::intValue).sum();
                if(need>free) {
                    if(c.currentScreen!=null){require(SurvivalGui.backtrackReady(),"GAME_STORAGE_GUI_BUSY");SurvivalGui.finishOwned();own.handler=null;}
                    require(c.player.currentScreenHandler==c.player.playerScreenHandler && c.player.currentScreenHandler.getCursorStack().isEmpty(),"GAME_STORAGE_GUI_BUSY");
                    opening=null;return TaskCatalogue.getItemTask(new ItemTarget(goal,Math.addExact(have,need-free)));
                }
            }
        }
        opening=own;return null;
    }
    static boolean expects(BlockPos target){return opening!=null && opening.owner.current() && !opening.done && !opening.aborted && opening.target.equals(target);}
    public static boolean busy(){return active!=null && active.owner.current();}
    public static boolean blocksInventory(){return busy() || opening!=null && opening.owner.current() && SurvivalGui.storageOpening();}
    public static boolean defers(TaskChain chain){return blocksInventory() && (chain instanceof UserTaskChain || chain instanceof FoodChain);}
    public static boolean retains(Task parent){var own=active!=null?active:opening;return blocksInventory() && parent!=null && parent.thisOrChildSatisfies(t->t==own.task);}
    public static boolean finished(Task task){var own=entries.get(task);return own!=null && own.owner.current() && own.done && !own.aborted;}
    public static void stop(Task task) {
        SurvivalAuthority.requireOwnerScope();var own=entries.get(task);if(own==null)return;
        if(opening==own)opening=null;
        if(active==own){own.aborted=true;own.exchange.close();active=null;}
    }
    public static Task opened(Task task) {
        var own=entries.get(task);require(own!=null && opening==own,"GAME_STORAGE_CONTEXT_CHANGED");var c=client(own);
        var handler=SurvivalGui.ownedHandler();require(handler instanceof GenericContainerScreenHandler,"GAME_STORAGE_UNSUPPORTED");
        int split=handler.slots.size()-36;require(split==27 || split==54,"GAME_STORAGE_UNSUPPORTED");
        if(own.handler!=handler){require(active==null,"GAME_STORAGE_CONTEXT_CHANGED");own.handler=(GenericContainerScreenHandler)handler;own.openingDeadline=now()+1500;}
        var snapshot=SurvivalGui.storageSnapshot(own.target);
        if(snapshot==null){require(now()<own.openingDeadline,"GAME_STORAGE_SERVER_TIMEOUT");return null;}
        require(snapshot.contents().size()==handler.slots.size() && snapshot.cursor().isEmpty()
                && own.state(snapshot.contents(),snapshot.cursor()).equals(own.state()),"GAME_STORAGE_SERVER_DIVERGED");
        var inventory=handler.getSlot(0).inventory;require(inventory!=c.player.getInventory(),"GAME_STORAGE_STATE_INVALID");
        var indices=new HashSet<Integer>();
        for(int i=0;i<handler.slots.size();i++){
            var slot=handler.getSlot(i);
            require(i<split?slot.inventory==inventory && slot.getIndex()==i
                    :slot.inventory==c.player.getInventory() && slot.getIndex()>=0 && slot.getIndex()<36 && indices.add(slot.getIndex()),"GAME_STORAGE_STATE_INVALID");
        }
        List<ItemStack> playerItems=snapshot.contents().subList(split,handler.slots.size());
        for(var goal:own.goals) {
            int need=own.need(goal,playerItems);if(need==0)continue;
            boolean found=false,reserved=false;
            for(int source=own.deposit?split:0;source<(own.deposit?handler.slots.size():split);source++) {
                var from=handler.getSlot(source);var value=from.getStack();if(value.isEmpty() || !goal.matches(value.getItem()))continue;
                found=true;int available=value.getCount();
                if(own.deposit){available=ResourceMaterials.usable(Set.of(from.getIndex())).getOrDefault(from.getIndex(),0);if(available==0){reserved=true;continue;}}
                for(int dest=own.deposit?0:split;dest<(own.deposit?split:handler.slots.size());dest++) {
                    var to=handler.getSlot(dest);var there=to.getStack();
                    if(!there.isEmpty() && !ItemStack.areItemsAndComponentsEqual(there,value))continue;
                    int maximum=Math.min(value.getMaxCount(),to.getMaxItemCount(value));
                    int amount=Math.min(Math.min(need,available),maximum-there.getCount());if(amount<=0)continue;
                    require(from.canTakeItems(c.player) && to.canInsert(value) && (amount==value.getCount() || from.canInsert(value)),"GAME_STORAGE_MOVE_INVALID");
                    if(own.deposit)require(ResourceMaterials.removable(from.getIndex(),amount),"GAME_RESOURCE_MATERIAL_RESERVED");
                    require(!ConfirmedCraftTask.busy() && !ControlledCookingTask.busy() && !ControlledEatingTask.busy()
                            && !ControlledEquipment.busy() && !ControlledShield.busy(),"GAME_STORAGE_GUI_BUSY");
                    own.moved=value.getItem();own.amount=amount;own.destination=dest;
                    own.exchange=new StorageExchange(StorageExchange.plan(own.state(),source,dest,amount,maximum),ControlledStorage::now,own.owner::current);
                    active=own;advance(own);return null;
                }
            }
            require(!reserved,"GAME_RESOURCE_MATERIAL_RESERVED");require(found,"GAME_STORAGE_MATERIALS_MISSING");throw new dev.aitalkstreamer.mc.core.Json.Rejected("GAME_STORAGE_DESTINATION_FULL");
        }
        SurvivalGui.finishOwned();own.handler=null;own.done=true;opening=null;return null;
    }
    private static void advance(Entry own) {
        var c=client(own);require(!own.packetFailure && own.handler==SurvivalGui.ownedHandler(),"GAME_STORAGE_SERVER_DIVERGED");
        if(own.exchange.advance(own.state(),own.handler.getRevision(),step->{
            if(own.deposit && step.slot()==own.destination)require(ResourceMaterials.externalUsable(own.handler.getCursorStack())
                    >=(step.button()==1?1:own.handler.getCursorStack().getCount()),"GAME_RESOURCE_MATERIAL_RESERVED");
            SurvivalGui.slot(c.interactionManager,own.handler.syncId,step.slot(),step.button(),SlotActionType.PICKUP,c.player);
        })) {
            if(own.deposit){own.deposited.credit(own.moved,own.amount);observers.confirmed(own.target,own.moved,own.amount);}
            own.exchange.close();own.exchange=null;active=null;AltoClef.getInstance().getItemStorage().registerSlotAction();
        }
    }
    public static void checkpoint(){
        SurvivalAuthority.requireScope();
        if(busy())advance(active);
        else if(opening!=null && SurvivalGui.storageOpening() && SurvivalGui.storageReady())opened(opening.task);
    }
    static void guardGuiWrite(){if(blocksInventory())require(active!=null && active.exchange.sending(),"GAME_STORAGE_GUI_BUSY");}
    static int clickRevision(int revision){return busy() && active.exchange.sending()?active.exchange.revision(revision):revision;}
    static void inventory(InventoryS2CPacket packet) {
        var own=active;var c=MinecraftClient.getInstance();
        if(!busy() || !c.isOnThread() || c.world!=own.world || c.player!=own.player || c.getNetworkHandler()!=own.connection
                || c.player.currentScreenHandler!=own.handler || packet.getSyncId()!=own.handler.syncId)return;
        try{own.exchange.confirm(own.state(packet.getContents(),packet.getCursorStack()),packet.getRevision());}
        catch(RuntimeException error){own.packetFailure=true;}
    }
}
