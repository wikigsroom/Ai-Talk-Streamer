package dev.aitalkstreamer.mc.neoforge;

import dev.aitalkstreamer.mc.core.*;
import net.minecraft.client.Minecraft;
import net.minecraft.network.protocol.game.ClientboundContainerSetContentPacket;
import net.minecraft.world.inventory.InventoryMenu;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.block.state.BlockState;
import java.util.*;
import java.util.function.BooleanSupplier;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Uses the gather task's original scope; a storage swap needs its own full server acknowledgement. */
final class NativeToolBelt {
    private final Minecraft client;
    private final NativeInputOwner.Scope scope;
    private final ControlArbiter control;
    private final ControlArbiter.Permit permit;
    private final BooleanSupplier current;
    private final InventoryMenu menu;
    private final List<ItemStack> types=new ArrayList<>();
    private InventoryExchange exchange;
    private InventoryExchange.State expected;
    private int source=-1,hotbar=-1,clicks,packets,confirmed,revision=-1;
    private boolean closed;
    private String packetFailure;
    NativeToolBelt(Minecraft client,NativeInputOwner.Scope scope,ControlArbiter control,ControlArbiter.Permit permit,BooleanSupplier current){
        this.client=client;this.scope=scope;this.control=control;this.permit=permit;this.current=current;menu=client.player.inventoryMenu;
    }
    private boolean live(){return !closed && client.isSameThread() && current.getAsBoolean() && control.allowed()
            && control.epoch()==permit.epoch() && client.player!=null && client.player.containerMenu==menu && client.player.inventoryMenu==menu
            && client.screen==null && client.player.isAlive() && client.isWindowActive() && !client.isPaused();}
    private void context(){
        require(live() && control.permit().equals(permit),"GAME_ITEM_CONTEXT_CHANGED");scope.current();
        require(packetFailure==null,"GAME_ITEM_PACKET_INVALID");
        require(menu.getClass()==InventoryMenu.class && menu.slots.size()==46 && menu.getCarried().isEmpty(),"GAME_ITEM_HANDLER_INVALID");
        for(int i=0;i<5;i++)require(menu.getSlot(i).getItem().isEmpty(),"GAME_ITEM_GRID_NOT_EMPTY");
    }
    private InventoryExchange.Stack token(ItemStack stack){
        if(stack.isEmpty())return InventoryExchange.Stack.EMPTY;
        int type=0;while(type<types.size() && !ItemStack.isSameItemSameComponents(stack,types.get(type)))type++;
        if(type==types.size()){require(types.size()<256,"GAME_ITEM_COMPONENT_LIMIT");types.add(stack.copyWithCount(1));}
        return new InventoryExchange.Stack(type+1,stack.getCount());
    }
    private InventoryExchange.State state(List<ItemStack> slots,ItemStack cursor){return new InventoryExchange.State(slots.stream().map(this::token).toList(),token(cursor));}
    private InventoryExchange.State state(){return state(menu.slots.stream().map(s->s.getItem().copy()).toList(),menu.getCarried().copy());}
    private int slot(int index){
        return java.util.stream.IntStream.range(5,46).filter(i->menu.getSlot(i).container==client.player.getInventory()
                && menu.getSlot(i).getContainerSlot()==index).findFirst().orElseThrow(()->new Rejected("GAME_ITEM_HANDLER_INVALID"));
    }
    void tick(){
        context();if(exchange==null)return;exchange.check();
        if(exchange.confirmed()){
            require(state().equals(expected),"GAME_ITEM_STATE_CHANGED");revision=exchange.confirmedRevision();confirmed++;
            exchange.close();exchange=null;expected=null;
        }
    }
    boolean pending(){return exchange!=null;}
    int prepare(BlockState block){
        context();if(exchange!=null)return -1;
        var stock=new ArrayList<NativeToolPlan.Candidate>();
        for(int i=0;i<=36;i++){
            ItemStack stack=client.player.getInventory().getItem(i==36?40:i);
            stock.add(new NativeToolPlan.Candidate(!block.requiresCorrectToolForDrops() || stack.isCorrectToolForDrops(block),stack.getDestroySpeed(block),
                    stack.isDamageableItem()?stack.getMaxDamage()-stack.getDamageValue():-1));
        }
        int selected=client.player.getInventory().selected,best=NativeToolPlan.choose(stock,selected);
        if(best<0)throw new LocalTaskFailure(LocalTaskFailure.Reason.GATHER_TOOL_UNAVAILABLE);
        if(best<9)return best;
        require(clicks<36,"GAME_GATHER_TOOL_STATE_INVALID");scope.stopMining(control,permit);
        source=best==36?40:best;hotbar=selected;var before=state();expected=before.swap(slot(source),slot(hotbar));
        exchange=new InventoryExchange(()->System.nanoTime()/1_000_000,this::live);
        exchange.send(before,expected,state(),menu.getStateId(),()->scope.swapInventory(menu,slot(source),hotbar,control,permit));clicks++;
        return -1;
    }
    int clickRevision(int original){return exchange!=null && exchange.sending()?exchange.revision(original):original;}
    void inventory(ClientboundContainerSetContentPacket packet){
        if(!live() || exchange==null || packet.getContainerId()!=menu.containerId)return;
        try{packets++;exchange.confirm(state(packet.getItems(),packet.getCarriedItem()),packet.getStateId());}
        catch(RuntimeException invalid){packetFailure="GAME_ITEM_PACKET_INVALID";}
    }
    void close(){closed=true;if(exchange!=null)exchange.close();exchange=null;expected=null;}
    com.google.gson.JsonObject proof(){return obj("pending",exchange!=null,"source_slot",source,"hotbar_slot",hotbar,
            "clicks",clicks,"server_full_packets",packets,"confirmed_swaps",confirmed,"server_revision",revision,"closed",closed);}
}
