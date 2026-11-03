package dev.aitalkstreamer.mc.survival;

import adris.altoclef.AltoClef;
import adris.altoclef.tasksystem.Task;
import net.minecraft.block.entity.AbstractFurnaceBlockEntity;
import net.minecraft.client.MinecraftClient;
import net.minecraft.item.*;
import net.minecraft.recipe.*;
import net.minecraft.recipe.input.SingleStackRecipeInput;
import java.util.*;
import static dev.aitalkstreamer.mc.core.Json.*;

/** One supply conversion: gather and prepare first, then bind exact slots to the original server baseline. */
public final class ControlledFoodCookingTask extends Task {
    private static ControlledFoodCookingTask active;
    private final SurvivalAuthority.Session owner;
    private final Object world,player,connection;
    private final RecipeEntry<SmokingRecipe> recipe;
    private final ItemStack raw,cooked;
    private final int target;
    private Task collector,opening;
    private ControlledCookingTask conversion;
    private boolean collectingFuel,finished;

    ControlledFoodCookingTask(RecipeEntry<SmokingRecipe> recipe,ItemStack raw,int target) {
        SurvivalAuthority.requireScope();require(!busy(),"GAME_COOKING_OWNER_CONFLICT");
        owner=SurvivalAuthority.session();var c=MinecraftClient.getInstance();world=c.world;player=c.player;connection=c.getNetworkHandler();
        this.recipe=recipe;this.raw=raw.copyWithCount(1);this.target=SupplyPolicy.validateTarget(target);
        cooked=recipe.value().craft(new SingleStackRecipeInput(this.raw),c.world.getRegistryManager());
        active=this;SurvivalAuthority.owned(()->{if(active==this)active=null;});
    }
    public static boolean busy() {return active!=null && active.owner.current() && !active.finished;}
    static Task currentTask() {SurvivalAuthority.requireScope();require(busy() && active.owner==SurvivalAuthority.session(),"GAME_COOKING_OWNER_CONFLICT");return active;}
    static boolean retains(Task parent) {var own=active;return busy() && parent!=null && parent!=own && parent.thisOrChildSatisfies(task->task==own);}
    /** A material child may retire without stopping the preparation which is waiting above it. */
    static boolean within(Task subtree) {var own=active;return busy() && subtree!=null && subtree.thisOrChildSatisfies(task->task==own);}
    static void checkpoint() {if(busy())active.context();}
    private void context() {
        SurvivalAuthority.requireScope();var c=MinecraftClient.getInstance();
        require(owner==SurvivalAuthority.session() && c.isOnThread() && c.world==world && c.player==player && c.getNetworkHandler()==connection
                && c.player!=null && c.player.isAlive() && c.isWindowFocused() && !c.isPaused()
                && ControlledCookingTask.recipe(raw).map(entry->entry.value()==recipe.value()).orElse(false)
                && ItemStack.areEqual(recipe.value().craft(new SingleStackRecipeInput(raw),c.world.getRegistryManager()),cooked),"GAME_COOKING_CONTEXT_CHANGED");
    }
    private boolean fuel(ItemStack value) {
        if(!(value.isOf(Items.COAL)||value.isOf(Items.CHARCOAL)))return false;
        return SmeltingPlan.fuel(AbstractFurnaceBlockEntity.createFuelTimeMap().getOrDefault(value.getItem(),0)/2,
                recipe.value().getCookingTime(),value.getItem().hasRecipeRemainder(),
                ItemStack.areItemsAndComponentsEqual(value,new ItemStack(value.getItem())),
                AltoClef.getInstance().getBehaviour().isProtected(value.getItem()));
    }
    @Override protected void onStart() {context();}
    @Override protected Task onTick() {
        context();
        if(conversion!=null) {
            if(!conversion.isFinished())return conversion;
            finished=true;active=null;return null;
        }
        if(ControlledCookingTask.busy() || ControlledEquipment.busy() || ControlledEatingTask.busy() || ControlledShield.busy())return null;
        var c=MinecraftClient.getInstance();
        // A prepared smoker may have consumed the old collector's stock. Do not resume that collector inside its GUI.
        if(opening!=null && CookingWorkstation.SMOKER.handler(c.player.currentScreenHandler)) {
            if(SurvivalGui.furnaceSnapshot()==null)return null;
            collector=null;opening=null;
        }
        if(collector!=null && !collector.isFinished())return collector;
        boolean collected=collector!=null;
        if(ControlledSupplyTask.inventoryNutrition()>=target) {
            ControlledSmeltingTask.closeEmptyWorkstation();finished=true;active=null;return null;
        }
        var inventory=c.player.getInventory();int rawSlot=-1;
        for(int i=0;i<36;i++) if(ItemStack.areItemsAndComponentsEqual(inventory.getStack(i),raw)
                && !AltoClef.getInstance().getBehaviour().isProtected(raw.getItem()) && ResourceMaterials.consumable(i)) {rawSlot=i;break;}
        if(rawSlot<0) {
            require((!collected || collectingFuel) && ItemStack.areItemsAndComponentsEqual(raw,new ItemStack(raw.getItem())),"GAME_COOKING_MATERIAL_CHANGED");
            ControlledSmeltingTask.closeEmptyWorkstation();opening=null;collectingFuel=false;
            collector=new ControlledRecipeResourcesTask(new Item[]{raw.getItem()},1);return collector;
        }
        var fuels=new HashSet<Integer>();for(int i=0;i<36;i++)if(fuel(inventory.getStack(i)))fuels.add(i);
        var assigned=ResourceMaterials.singleUnits(Map.of("raw",Set.of(rawSlot),"fuel",fuels));
        if(assigned.isEmpty()) {
            require(!collected || !collectingFuel,"GAME_RESOURCE_SMELTING_FUEL_UNAVAILABLE");
            var options=Arrays.stream(new Item[]{Items.COAL,Items.CHARCOAL}).filter(item->fuel(new ItemStack(item))).toArray(Item[]::new);
            require(options.length>0,"GAME_RESOURCE_SMELTING_FUEL_UNAVAILABLE");
            ControlledSmeltingTask.closeEmptyWorkstation();opening=null;collectingFuel=true;
            collector=new ControlledRecipeResourcesTask(options,SmeltingPlan.fuelUnits(fuel(raw)));return collector;
        }
        if(!CookingWorkstation.SMOKER.handler(c.player.currentScreenHandler)) {
            require(c.currentScreen==null,"GAME_COOKING_HANDLER_INVALID");
            if(opening==null)opening=new ControlledCookingTask.OpenWorkstation(CookingWorkstation.SMOKER);return opening;
        }
        if(SurvivalGui.furnaceSnapshot()==null)return null;
        ResourceMaterials.select();conversion=ControlledCookingTask.supply(recipe,assigned.get("raw"),assigned.get("fuel"));return conversion;
    }
    @Override protected void onStop(Task interrupted) { /* Suspension retains this preparation; root cleanup owns disposal. */ }
    @Override public boolean isFinished() {return finished;}
    @Override public boolean isEqual(Task other) {return other==this;}
    @Override public String toDebugString() {return "Prepare one confirmed food conversion";}
}
