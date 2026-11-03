package dev.aitalkstreamer.mc.survival;

import adris.altoclef.AltoClef;
import adris.altoclef.tasksystem.Task;
import adris.altoclef.util.SmeltTarget;
import net.minecraft.block.entity.AbstractFurnaceBlockEntity;
import net.minecraft.client.MinecraftClient;
import net.minecraft.item.*;
import net.minecraft.recipe.*;
import net.minecraft.recipe.input.SingleStackRecipeInput;
import net.minecraft.registry.Registries;
import net.minecraft.registry.tag.ItemTags;
import java.util.*;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Resource smelting retains acquisition and the original root; each bounded batch is server-confirmed. */
public final class ControlledSmeltingTask extends Task {
    private final SurvivalAuthority.Session owner;
    private final Object world,player,connection;
    private final CookingWorkstation workstation;
    private final List<SmeltingPlan.Goal> goals;
    private final MaterialTargets desired;
    private ControlledCookingTask current;
    private Task collector,opening;
    private boolean collect=true,started,finished,collectingFuel;

    public ControlledSmeltingTask(String kind,SmeltTarget[] targets) {
        SurvivalAuthority.requireScope();owner=SurvivalAuthority.session();var c=MinecraftClient.getInstance();world=c.world;player=c.player;connection=c.getNetworkHandler();
        require(kind!=null && Set.of("furnace","blast_furnace","smoker").contains(kind),"GAME_RESOURCE_CRAFT_TARGET_INVALID");
        workstation=CookingWorkstation.valueOf(kind.toUpperCase(Locale.ROOT));
        require(targets!=null && targets.length>0 && targets.length<=64,"GAME_RESOURCE_CRAFT_TARGET_INVALID");
        var values=new ArrayList<SmeltingPlan.Goal>();
        for(var target:targets) {
            require(target!=null && target.getItem()!=null && target.getMaterial()!=null,"GAME_RESOURCE_CRAFT_TARGET_INVALID");
            var raw=new HashSet<>(ids(target.getMaterial().getMatches()));
            if(target.getOptionalMaterials()!=null) raw.addAll(ids(target.getOptionalMaterials()));
            values.add(new SmeltingPlan.Goal(ids(target.getItem().getMatches()),raw,target.getItem().getTargetCount()));
        }
        goals=List.copyOf(values);desired=SmeltingPlan.desired(goals);
    }
    private static Set<String> ids(Item[] items) {
        require(items!=null && items.length<=256 && Arrays.stream(items).allMatch(Objects::nonNull),"GAME_RESOURCE_CRAFT_TARGET_INVALID");
        var result=new HashSet<String>();for(var item:items) result.add(Registries.ITEM.getId(item).toString());return Set.copyOf(result);
    }
    public void ignoreMaterials() {require(!started,"GAME_RESOURCE_MATERIAL_CONTEXT_CHANGED");collect=false;}
    private void context() {
        SurvivalAuthority.requireScope();var c=MinecraftClient.getInstance();
        require(owner==SurvivalAuthority.session() && c.isOnThread() && c.world==world && c.player==player && c.getNetworkHandler()==connection
                && c.player!=null && c.player.isAlive() && c.isWindowFocused() && !c.isPaused(),"GAME_RESOURCE_MATERIAL_CONTEXT_CHANGED");
    }
    @Override protected void onStart() {context();ResourceMaterials.enter(this,desired);started=true;finished=false;}
    private static boolean ordinary(ItemStack value) {return !value.isEmpty() && ItemStack.areItemsAndComponentsEqual(value,new ItemStack(value.getItem()));}
    private boolean dedicatedFuel(ItemStack stack,int cookTicks,Map<Item,Integer> times) {
        boolean kind=stack.isOf(Items.COAL)||stack.isOf(Items.CHARCOAL)||stack.isOf(Items.COAL_BLOCK)||stack.isOf(Items.DRIED_KELP_BLOCK)
                ||stack.isIn(ItemTags.LOGS)||stack.isIn(ItemTags.PLANKS);
        int burn=times.getOrDefault(stack.getItem(),0);if(workstation!=CookingWorkstation.FURNACE) burn/=2;
        return kind && SmeltingPlan.fuel(burn,cookTicks,stack.getItem().hasRecipeRemainder(),ordinary(stack),AltoClef.getInstance().getBehaviour().isProtected(stack.getItem()));
    }
    private RecipeEntry<? extends AbstractCookingRecipe> recipe(ItemStack input,SmeltingPlan.Goal goal) {
        var c=MinecraftClient.getInstance();var match=workstation.first(input).orElse(null);if(match==null) return null;
        var output=match.value().craft(new SingleStackRecipeInput(input),c.world.getRegistryManager());
        if(output.isEmpty() || !goal.outputs().contains(Registries.ITEM.getId(output.getItem()).toString())) return null;
        SmeltingPlan.cookMillis(match.value().getCookingTime(),workstation.maximumTicks());
        require(output.getCount()<=output.getMaxCount(),"GAME_RESOURCE_SMELTING_RECIPE_UNSUPPORTED");return match;
    }
    private Item[] materials(SmeltingPlan.Goal goal) {
        var result=new TreeMap<String,Item>();var recipes=workstation.recipes();
        require(recipes.size()<=4096,"GAME_RESOURCE_CRAFT_SEARCH_LIMIT");int scanned=0;
        for(var entry:recipes.stream().sorted(Comparator.comparing(e->e.id().toString())).toList()) {
            for(var ingredient:entry.value().getIngredients()) for(var stack:ingredient.getMatchingStacks()) {
                require(++scanned<=65536,"GAME_RESOURCE_CRAFT_SEARCH_LIMIT");var id=Registries.ITEM.getId(stack.getItem()).toString();
                if(goal.materials().contains(id) && !AltoClef.getInstance().getBehaviour().isProtected(stack.getItem()) && recipe(stack,goal)!=null) result.put(id,stack.getItem());
            }
        }
        require(!result.isEmpty(),"GAME_RESOURCE_MATERIAL_UNAVAILABLE");return result.values().toArray(Item[]::new);
    }
    private int materialUnits(Item[] materials,SmeltingPlan.Goal goal,int missing) {
        int units=workstation==CookingWorkstation.SMOKER?1:SmeltingPlan.MAX_INPUTS;
        for(var item:materials) {
            var input=new ItemStack(item);var output=recipe(input,goal).value().craft(new SingleStackRecipeInput(input),MinecraftClient.getInstance().world.getRegistryManager());
            units=Math.min(units,(missing+output.getCount()-1)/output.getCount());
        }
        return units;
    }
    static void closeEmptyWorkstation() {
        var c=MinecraftClient.getInstance();if(c.currentScreen==null) return;
        var handler=SurvivalGui.ownedHandler();require(handler.getCursorStack().isEmpty(),"GAME_RESOURCE_CRAFT_CURSOR_BUSY");
        require(Arrays.stream(CookingWorkstation.values()).anyMatch(k->k.handler(handler)) && handler.slots.subList(0,3).stream().allMatch(s->s.getStack().isEmpty()),"GAME_COOKING_INITIAL_STATE_INVALID");
        SurvivalGui.close(c.player);
    }
    @Override protected Task onTick() {
        context();
        if(current!=null) {if(!current.isFinished()) return current;current=null;collector=null;opening=null;}
        if(ControlledStorage.blocksInventory() || ControlledEquipment.busy() || ControlledEatingTask.busy() || ControlledShield.busy() || ControlledCookingTask.busy()) return null;
        if(opening!=null && workstation.handler(MinecraftClient.getInstance().player.currentScreenHandler)) {
            if(SurvivalGui.furnaceSnapshot()==null)return null;
            collector=null;opening=null;
        }
        var stock=ResourceMaterials.stock();var goal=goals.stream().filter(g->SmeltingPlan.missing(g,stock)>0).findFirst().orElse(null);
        if(goal==null) {closeEmptyWorkstation();finished=true;return null;}
        if(collector!=null && !collector.isFinished()) return collector;
        boolean collected=collector!=null;
        var c=MinecraftClient.getInstance();var inventory=c.player.getInventory();
        RecipeEntry<? extends AbstractCookingRecipe> selected=null;int raw=-1;
        for(int i=0;i<36;i++) {
            var stack=inventory.getStack(i);
            if(!stack.isEmpty() && goal.materials().contains(Registries.ITEM.getId(stack.getItem()).toString())
                    && !AltoClef.getInstance().getBehaviour().isProtected(stack.getItem()) && ResourceMaterials.consumable(i)) {
                var match=recipe(stack,goal);if(match!=null) {selected=match;raw=i;break;}
            }
        }
        if(selected==null) {
            require(collect && (!collected || collectingFuel),"GAME_RESOURCE_MATERIAL_UNAVAILABLE");closeEmptyWorkstation();opening=null;collectingFuel=false;
            var options=materials(goal);collector=new ControlledRecipeResourcesTask(options,materialUnits(options,goal,SmeltingPlan.missing(goal,stock)));return collector;
        }
        var times=AbstractFurnaceBlockEntity.createFuelTimeMap();var fuelSlots=new TreeMap<Integer,Set<Integer>>();
        var output=selected.value().craft(new SingleStackRecipeInput(inventory.getStack(raw).copyWithCount(1)),c.world.getRegistryManager());
        int rawCount=ResourceMaterials.usable(Set.of(raw)).getOrDefault(raw,0);
        for(int i=0;i<36;i++) if(dedicatedFuel(inventory.getStack(i),selected.value().getCookingTime(),times)) {
            int burn=times.getOrDefault(inventory.getStack(i).getItem(),0);if(workstation!=CookingWorkstation.FURNACE)burn/=2;
            int limit=SmeltingPlan.batchLimit(rawCount,SmeltingPlan.missing(goal,stock),output.getCount(),output.getMaxCount(),burn,
                    selected.value().getCookingTime(),workstation.maximumTicks(),workstation==CookingWorkstation.SMOKER?1:SmeltingPlan.MAX_INPUTS);
            for(int n=1;n<=limit;n++)fuelSlots.computeIfAbsent(n,key->new HashSet<>()).add(i);
        }
        int fuel=-1,inputs=0;
        for(var entry:fuelSlots.descendingMap().entrySet()) {
            int candidate=ResourceMaterials.conversionFuel(raw,entry.getKey(),entry.getValue());
            if(candidate>=0) {fuel=candidate;inputs=entry.getKey();break;}
        }
        if(fuel<0) {
            require(!collected || !collectingFuel,"GAME_RESOURCE_SMELTING_FUEL_UNAVAILABLE");collectingFuel=true;
            var needed=selected;Item[] fuels=times.keySet().stream().filter(item->dedicatedFuel(new ItemStack(item),needed.value().getCookingTime(),times))
                    .sorted(Comparator.comparing(item->Registries.ITEM.getId(item).toString())).toArray(Item[]::new);
            require(fuels.length>0,"GAME_RESOURCE_SMELTING_FUEL_UNAVAILABLE");closeEmptyWorkstation();opening=null;
            collector=new ControlledRecipeResourcesTask(fuels,SmeltingPlan.fuelUnits(dedicatedFuel(inventory.getStack(raw),selected.value().getCookingTime(),times)));return collector;
        }
        if(!workstation.handler(c.player.currentScreenHandler)) {
            require(c.currentScreen==null,"GAME_COOKING_HANDLER_INVALID");if(opening==null) opening=new ControlledCookingTask.OpenWorkstation(workstation);return opening;
        }
        // Workstation preparation may have consumed the selected raw or fuel. Selection above always runs again after opening.
        if(SurvivalGui.furnaceSnapshot()==null) return null;
        ResourceMaterials.select();current=ControlledCookingTask.resource(workstation,selected,raw,fuel,inputs);return current;
    }
    @Override protected void onStop(Task interrupted) {ResourceMaterials.leave(owner,this);}
    @Override public boolean isFinished() {return finished;}
    @Override public boolean isEqual(Task other) {return other==this;}
    @Override public String toDebugString() {return "Confirmed resource "+workstation.id();}
}
