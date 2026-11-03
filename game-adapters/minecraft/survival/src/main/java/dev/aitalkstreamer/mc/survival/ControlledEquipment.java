package dev.aitalkstreamer.mc.survival;

import adris.altoclef.chains.FoodChain;
import adris.altoclef.chains.UserTaskChain;
import adris.altoclef.tasksystem.TaskChain;
import dev.aitalkstreamer.mc.core.InventoryExchange;
import dev.aitalkstreamer.mc.core.LocalTaskFailure;
import net.minecraft.client.MinecraftClient;
import net.minecraft.item.*;
import net.minecraft.network.packet.s2c.play.InventoryS2CPacket;
import net.minecraft.screen.PlayerScreenHandler;
import net.minecraft.screen.slot.SlotActionType;
import java.util.*;
import java.util.function.Predicate;
import java.util.stream.IntStream;
import static dev.aitalkstreamer.mc.core.Json.require;
import static dev.aitalkstreamer.mc.core.LocalTaskFailure.Reason.*;

/** Shared original-root hand/tool/offhand/armor transfers, never a new public skill. */
public final class ControlledEquipment {
    private static ControlledEquipment active;
    private final SurvivalAuthority.Session owner;
    private final Object world,player,connection;
    private final PlayerScreenHandler handler;
    private final List<ItemStack> types=new ArrayList<>();
    private final EquipmentExchange exchange;
    private final int select;
    private String packetFailure;
    private ControlledEquipment(int source,int target,int select) {
        owner=SurvivalAuthority.session();var client=MinecraftClient.getInstance();
        world=client.world;player=client.player;connection=client.getNetworkHandler();handler=client.player.playerScreenHandler;this.select=select;
        var before=state();List<EquipmentPlan.Step> plan;
        if(source<0)plan=List.of();
        else {
            var from=handler.getSlot(source);var to=handler.getSlot(target);var value=from.getStack();var old=to.getStack();
            require(from.canTakeItems(client.player)&&to.canTakeItems(client.player)
                    &&to.canInsert(value)&&from.canInsert(old)
                    &&value.getCount()<=Math.min(64,to.getMaxItemCount(value))&&old.getCount()<=Math.min(64,from.getMaxItemCount(old)),"GAME_EQUIPMENT_SLOT_REJECTED");
            plan=target<9?EquipmentPlan.armor(before,source,target):target==45?EquipmentPlan.offhand(before,source):EquipmentPlan.main(before,source,target);
        }
        exchange=new EquipmentExchange(before,plan,ControlledEquipment::now,owner::current);
        SurvivalActions.cancelBreaking(client.interactionManager);
        active=this;SurvivalAuthority.owned(()->{exchange.close();if(active==this)active=null;});
        advance();
    }
    public static boolean busy(){return active!=null&&active.owner.current();}
    public static boolean defers(TaskChain chain){return busy()&&(chain instanceof UserTaskChain||chain instanceof FoodChain);}
    private static boolean available(){
        SurvivalAuthority.requireScope();var c=MinecraftClient.getInstance();
        return !busy()&&!ControlledStorage.blocksInventory()&&!ControlledEatingTask.busy()&&!ControlledCookingTask.blocksInventory()&&c.player!=null&&c.currentScreen==null
                &&c.player.currentScreenHandler==c.player.playerScreenHandler&&!c.player.isUsingItem()
                &&c.player.playerScreenHandler.getCursorStack().isEmpty();
    }
    private static MinecraftClient ready(){
        SurvivalAuthority.requireScope();var c=MinecraftClient.getInstance();
        require(c.isOnThread()&&c.world!=null&&c.player!=null&&c.interactionManager!=null&&c.getNetworkHandler()!=null
                &&c.player.isAlive()&&c.isWindowFocused()&&!c.isPaused()&&c.currentScreen==null
                &&c.player.currentScreenHandler==c.player.playerScreenHandler&&c.player.playerScreenHandler.getClass()==PlayerScreenHandler.class
                &&!c.player.isSpectator()&&!c.player.getAbilities().creativeMode,"GAME_EQUIPMENT_CONTEXT_CHANGED");
        for(int i=0;i<5;i++)require(c.player.playerScreenHandler.getSlot(i).getStack().isEmpty(),"GAME_EQUIPMENT_GRID_NOT_EMPTY");return c;
    }
    public static boolean main(Item... matches){
        if(!available())return false;var c=ready();validate(matches);
        if(matches(c.player.getMainHandStack(),matches))return true;
        for(int i=0;i<36;i++)if(matches(c.player.getInventory().getStack(i),matches))return mainSlot(i);
        return false;
    }
    public static boolean mainSlot(int inventory){
        if(!available())return false;var c=ready();require(inventory>=0&&inventory<36,"GAME_EQUIPMENT_SLOT_INVALID");
        if(c.player.getInventory().selectedSlot==inventory)return true;
        if(inventory<9)new ControlledEquipment(-1,-1,inventory);
        else new ControlledEquipment(slot(c,inventory),slot(c,c.player.getInventory().selectedSlot),c.player.getInventory().selectedSlot);
        return false;
    }
    public static boolean mainSlot(adris.altoclef.util.slots.Slot source){
        if(!available())return false;var c=ready();
        require(source instanceof adris.altoclef.util.slots.PlayerSlot,"GAME_EQUIPMENT_SOURCE_NOT_PLAYER_SLOT");
        int inventory=source.getInventorySlot();require(inventory>=0&&inventory<36
                &&source.getWindowSlot()==slot(c,inventory),"GAME_EQUIPMENT_SOURCE_NOT_PLAYER_SLOT");
        return mainSlot(inventory);
    }
    public static boolean offhand(Item requested){
        if(!available())return false;var c=ready();validate(new Item[]{requested});
        if(c.player.getOffHandStack().isOf(requested))return true;
        for(int i=0;i<36;i++)if(c.player.getInventory().getStack(i).isOf(requested)){
            new ControlledEquipment(slot(c,i),45,-1);return false;
        }
        return false;
    }
    public static boolean armor(Item... matches){
        if(!available())return false;var c=ready();validate(matches);
        for(Item item:matches){int target=armorSlot(item);if(target>=0&&c.player.playerScreenHandler.getSlot(target).getStack().isOf(item))return true;}
        for(Item item:matches){
            int target=armorSlot(item);if(target<0)continue;
            for(int i=0;i<36;i++)if(c.player.getInventory().getStack(i).isOf(item)){
                new ControlledEquipment(slot(c,i),target,-1);return false;
            }
        }
        return false;
    }
    public static boolean deequip(Predicate<ItemStack> bad){
        if(!available())return false;var c=ready();Objects.requireNonNull(bad);
        if(!bad.test(c.player.getMainHandStack().copy()))return true;
        for(int i=0;i<36;i++)if(!bad.test(c.player.getInventory().getStack(i).copy()))return mainSlot(i);
        return false;
    }
    public static void refresh(){if(available()){ready();new ControlledEquipment(-1,-1,-1);}}
    private static void validate(Item[] matches){require(matches!=null&&matches.length>0&&matches.length<=128&&Arrays.stream(matches).allMatch(Objects::nonNull),"GAME_EQUIPMENT_TARGET_INVALID");}
    private static boolean matches(ItemStack stack,Item[] items){return Arrays.stream(items).anyMatch(stack::isOf);}
    private static int armorSlot(Item item){
        if(item instanceof ShieldItem)return 45;if(!(item instanceof ArmorItem armor))return -1;
        return switch(armor.getSlotType()){case HEAD->5;case CHEST->6;case LEGS->7;case FEET->8;default->-1;};
    }
    private static int slot(MinecraftClient c,int inventory){return IntStream.range(5,46).filter(i->c.player.playerScreenHandler.getSlot(i).inventory==c.player.getInventory()
            &&c.player.playerScreenHandler.getSlot(i).getIndex()==inventory).findFirst().orElseThrow();}
    private InventoryExchange.Stack token(ItemStack value){
        if(value.isEmpty())return InventoryExchange.Stack.EMPTY;
        for(int i=0;i<types.size();i++)if(ItemStack.areItemsAndComponentsEqual(value,types.get(i)))return new InventoryExchange.Stack(i+1,value.getCount());
        require(types.size()<128,"GAME_EQUIPMENT_COMPONENT_LIMIT");types.add(value.copyWithCount(1));return new InventoryExchange.Stack(types.size(),value.getCount());
    }
    private InventoryExchange.State state(List<ItemStack> values,ItemStack cursor){return new InventoryExchange.State(values.stream().map(this::token).toList(),token(cursor));}
    private InventoryExchange.State state(){return state(handler.slots.stream().map(s->s.getStack().copy()).toList(),handler.getCursorStack());}
    private void advance(){
        var c=ready();if(owner!=SurvivalAuthority.session()||c.world!=world||c.player!=player||c.getNetworkHandler()!=connection||c.player.currentScreenHandler!=handler)throw new LocalTaskFailure(EQUIPMENT_CONTEXT_CHANGED);
        if(packetFailure!=null)throw new LocalTaskFailure(EQUIPMENT_SERVER_DIVERGED);
        if(exchange.advance(state(),handler.getRevision(),step->SurvivalGui.slot(c.interactionManager,handler.syncId,step.slot(),step.button(),
                step.action()==EquipmentPlan.Action.SWAP?SlotActionType.SWAP:SlotActionType.PICKUP,c.player))){
            if(select>=0)SurvivalInputs.select(c.player.getInventory(),select);exchange.close();adris.altoclef.AltoClef.getInstance().getItemStorage().registerSlotAction();active=null;
        }
    }
    public static void checkpoint(){SurvivalAuthority.requireScope();if(busy())active.advance();}
    static void guardGuiWrite(){if(busy())require(active.exchange!=null&&active.exchange.sending(),"GAME_EQUIPMENT_GUI_BUSY");}
    static int clickRevision(int original){return busy()&&active.exchange.sending()?active.exchange.revision(original):original;}
    static void inventory(InventoryS2CPacket packet){
        var c=MinecraftClient.getInstance();var own=active;
        if(!busy()||!c.isOnThread()||c.world!=own.world||c.player!=own.player||c.getNetworkHandler()!=own.connection
                ||c.player.currentScreenHandler!=own.handler||packet.getSyncId()!=own.handler.syncId)return;
        try{own.exchange.confirm(own.state(packet.getContents(),packet.getCursorStack()),packet.getRevision());}
        catch(RuntimeException error){own.packetFailure="GAME_EQUIPMENT_PACKET_INVALID";}
    }
    private static long now(){return System.nanoTime()/1_000_000;}
}
