package dev.aitalkstreamer.mc.survival;

import adris.altoclef.tasksystem.Task;
import adris.altoclef.util.RecipeTarget;
import net.minecraft.client.MinecraftClient;
import net.minecraft.registry.Registries;
import java.util.*;
import static dev.aitalkstreamer.mc.core.Json.*;

/** State-only material reservations belong to one original root, including suspended ancestors. */
public final class ResourceMaterials {
    private static State state;
    private static final class State {
        final SurvivalAuthority.Session owner;
        final Object world,player,connection;
        final MaterialReservations reservations=new MaterialReservations();
        final ResourceAcquisitionPlan acquisitions=new ResourceAcquisitionPlan();
        State() {
            owner=SurvivalAuthority.session();var client=MinecraftClient.getInstance();
            world=client.world;player=client.player;connection=client.getNetworkHandler();
        }
    }
    private static State current() {
        SurvivalAuthority.requireScope();var client=MinecraftClient.getInstance();
        require(client.isOnThread() && client.world!=null && client.player!=null && client.getNetworkHandler()!=null
                && client.player.isAlive() && client.isWindowFocused() && !client.isPaused(),"GAME_RESOURCE_MATERIAL_CONTEXT_CHANGED");
        if(state==null) {
            var created=new State();SurvivalAuthority.owned(()->{created.reservations.clear();created.acquisitions.clear();if(state==created)state=null;});state=created;
        }
        require(state.owner==SurvivalAuthority.session() && state.world==client.world && state.player==client.player
                && state.connection==client.getNetworkHandler(),"GAME_RESOURCE_MATERIAL_CONTEXT_CHANGED");return state;
    }
    static void enter(Task task,RecipeTarget[] targets) {
        var desired=new TreeMap<String,Integer>();require(targets!=null && targets.length>0 && targets.length<=64,"GAME_RESOURCE_CRAFT_TARGET_INVALID");
        for(var target:targets) {
            require(target!=null && target.getOutputItem()!=null && target.getTargetCount()>=0,"GAME_RESOURCE_CRAFT_TARGET_INVALID");
            desired.merge(Registries.ITEM.getId(target.getOutputItem()).toString(),target.getTargetCount(),Math::max);
        }
        current().reservations.enter(task,desired);
    }
    static void leave(SurvivalAuthority.Session original,Task task) {
        SurvivalAuthority.requireOwnerScope();if(state!=null && state.owner==original)state.reservations.leave(task);
    }
    static List<ResourceMaterialsPlan.Stock> stock() {
        current();var inventory=MinecraftClient.getInstance().player.getInventory();var values=new ArrayList<ResourceMaterialsPlan.Stock>();
        for(int i=0;i<36;i++) {var stack=inventory.getStack(i);values.add(new ResourceMaterialsPlan.Stock(i,Registries.ITEM.getId(stack.getItem()).toString(),stack.getCount()));}
        return values;
    }
    static MaterialTargets desired() {return current().reservations.desired();}
    static List<MaterialAllocation.Limit> limits() {return desired().limits(stock());}
    static void enter(Task task,Map<String,Integer> targets) {current().reservations.enter(task,targets);}
    static void enter(Task task,MaterialTargets targets) {current().reservations.enter(task,targets);}
    static Map<Integer,Integer> available() {return ResourceMaterialsPlan.available(stock(),desired());}
    static Map<String,Integer> singleUnits(Map<String,Set<Integer>> candidates) {return ResourceMaterialsPlan.singleUnits(stock(),desired(),candidates);}
    static int conversionFuel(int rawSlot,int rawCount,Set<Integer> fuels) {return ResourceMaterialsPlan.conversionFuel(stock(),desired(),rawSlot,rawCount,fuels);}
    static boolean removable(int slot,int count) {return ResourceMaterialsPlan.removable(stock(),desired(),slot,count);}
    static int externalUsable(net.minecraft.item.ItemStack stack) {return ResourceMaterialsPlan.externalUsable(stock(),desired(),Registries.ITEM.getId(stack.getItem()).toString(),stack.getCount());}
    static boolean consumable(int slot) {return !singleUnits(Map.of("item",Set.of(slot))).isEmpty();}
    static Map<Integer,Integer> usable(Set<Integer> candidates) {return ResourceMaterialsPlan.usable(stock(),desired(),candidates);}

    static void select() {current().reservations.select();}
    private static boolean ancestor(Object candidate,Task descendant) {return ((Task)candidate).thisOrChildSatisfies(task->task==descendant);}
    static ResourceAcquisitionPlan.Choice choose(Task task,List<ResourceAcquisitionPlan.Source> sources,List<ResourceMaterialsPlan.Stock> stock) {
        return current().acquisitions.choose(task,sources,stock,candidate->ancestor(candidate,task));
    }
    static void begin(Task task,ResourceAcquisitionPlan.Source source,List<ResourceMaterialsPlan.Stock> baseline,List<ResourceMaterialsPlan.Stock> stock) {
        current().acquisitions.begin(task,source,baseline,stock,candidate->ancestor(candidate,task));
    }
    static boolean finish(Task task,List<ResourceMaterialsPlan.Stock> stock) {return current().acquisitions.finish(task,stock);}
    static void failed(Task task,List<ResourceMaterialsPlan.Stock> stock,String reason) {current().acquisitions.failed(task,stock,reason);}
    static void releaseAcquisition(SurvivalAuthority.Session original,Task task) {
        SurvivalAuthority.requireOwnerScope();if(state!=null && state.owner==original)state.acquisitions.release(task);
    }
}
