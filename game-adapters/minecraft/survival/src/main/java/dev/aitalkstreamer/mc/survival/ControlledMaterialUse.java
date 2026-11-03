package dev.aitalkstreamer.mc.survival;

import adris.altoclef.AltoClef;
import adris.altoclef.util.slots.Slot;
import adris.altoclef.util.helpers.ItemHelper;
import net.minecraft.block.Block;
import net.minecraft.client.MinecraftClient;
import net.minecraft.item.*;
import net.minecraft.screen.ScreenHandler;
import net.minecraft.screen.slot.SlotActionType;
import net.minecraft.util.Hand;
import java.util.*;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Building and GUI disposal share the original root's retained material capacity. No inventory writes here. */
public final class ControlledMaterialUse {
    private ControlledMaterialUse() { }
    private static MinecraftClient client() {ResourceMaterials.desired();return MinecraftClient.getInstance();}
    private static boolean ordinaryBlock(ItemStack stack) {
        return stack.getItem() instanceof BlockItem && !stack.isEmpty()
                && !AltoClef.getInstance().getBehaviour().isProtected(stack.getItem())
                && ItemStack.areItemsAndComponentsEqual(stack,new ItemStack(stack.getItem()));
    }
    private static int mainSlot(Slot source) {
        var c=client();if(source==null || Slot.isCursor(source))return -1;
        int window=source.getWindowSlot();var handler=c.player.currentScreenHandler;
        if(window<0 || window>=handler.slots.size())return -1;
        var slot=handler.getSlot(window);int index=slot.getIndex();
        return slot.inventory==c.player.getInventory() && index>=0 && index<36 && source.getInventorySlot()==index?index:-1;
    }
    public static boolean disposable(Slot source) {
        int slot=mainSlot(source);if(slot<0)return false;
        var stack=client().player.getInventory().getStack(slot);
        return !stack.isEmpty() && ResourceMaterials.removable(slot,stack.getCount());
    }
    private static int count(Collection<Item> allowed,boolean stable,boolean throwaway) {
        var c=client();require(allowed!=null && allowed.size()<=4096 && allowed.stream().allMatch(Objects::nonNull),"GAME_MATERIAL_REQUIREMENT_INVALID");
        var items=new HashSet<>(allowed);var candidates=new HashSet<Integer>();
        for(int i=0;i<36;i++) {
            var stack=c.player.getInventory().getStack(i);
            if(items.contains(stack.getItem()) && ordinaryBlock(stack) && (!throwaway || ItemHelper.canThrowAwayStack(AltoClef.getInstance(),stack))
                    && (!stable || !stack.isOf(Items.SAND) && !stack.isOf(Items.GRAVEL)))candidates.add(i);
        }
        return ResourceMaterials.usable(candidates).values().stream().mapToInt(Integer::intValue).sum();
    }
    public static int throwawayCount(AltoClef mod,boolean stable) {return count(Arrays.asList(mod.getModSettings().getThrowawayItems(mod)),stable,true);}
    public static Optional<Slot> throwawaySlot(AltoClef mod,boolean hotbar) {
        var c=client();var items=new HashSet<>(Arrays.asList(mod.getModSettings().getThrowawayItems(mod)));
        require(items.size()<=4096,"GAME_MATERIAL_REQUIREMENT_INVALID");
        for(int i=0;i<(hotbar?9:36);i++) {
            var stack=c.player.getInventory().getStack(i);
            if(items.contains(stack.getItem()) && ordinaryBlock(stack) && ItemHelper.canThrowAwayStack(mod,stack) && ResourceMaterials.consumable(i))return Optional.of(Slot.getFromCurrentScreenInventory(i));
        }
        return Optional.empty();
    }
    public static int structureCount(Block[] blocks,boolean throwaways) {
        require(blocks!=null && blocks.length<=256 && Arrays.stream(blocks).allMatch(Objects::nonNull),"GAME_MATERIAL_REQUIREMENT_INVALID");
        var items=new HashSet<Item>();for(var block:blocks)items.add(block.asItem());
        if(throwaways)items.addAll(AltoClef.getInstance().getClientBaritoneSettings().acceptableThrowawayItems.value);
        return count(items,false,false);
    }
    static void beforeBlock(Hand hand) {
        var c=client();require(hand!=null,"GAME_ACTION_HAND_INVALID");var stack=c.player.getStackInHand(hand);
        if(!(stack.getItem() instanceof BlockItem))return;
        require(ordinaryBlock(stack),"GAME_RESOURCE_MATERIAL_UNAVAILABLE");
        require(hand==Hand.MAIN_HAND?ResourceMaterials.removable(c.player.getInventory().selectedSlot,1):ResourceMaterials.externalUsable(stack)>0,"GAME_RESOURCE_MATERIAL_RESERVED");
    }
    static void beforeBlockHands() {beforeBlock(Hand.MAIN_HAND);beforeBlock(Hand.OFF_HAND);}
    /** Recheck actual handler/cursor contents immediately before a GUI throw, including a prior pickup. */
    static void beforeDrop(ScreenHandler handler,int slot,int button,SlotActionType action) {
        if(action!=SlotActionType.THROW && !(action==SlotActionType.PICKUP && slot==-999))return;
        var c=client();ItemStack stack;int count;
        if(action==SlotActionType.PICKUP && slot==-999) {
            stack=handler.getCursorStack();if(stack.isEmpty())return;count=button==0?stack.getCount():1;
            require(ResourceMaterials.externalUsable(stack)>=count,"GAME_RESOURCE_MATERIAL_RESERVED");return;
        }
        if(action!=SlotActionType.THROW)return;
        var source=handler.getSlot(slot);stack=source.getStack();if(stack.isEmpty())return;count=button==0?1:stack.getCount();
        int index=source.getIndex();
        boolean allowed=source.inventory==c.player.getInventory() && index>=0 && index<36
                ?ResourceMaterials.removable(index,count):ResourceMaterials.externalUsable(stack)>=count;
        require(allowed,"GAME_RESOURCE_MATERIAL_RESERVED");
    }
}
