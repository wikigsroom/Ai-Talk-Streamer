package dev.aitalkstreamer.mc.survival;

import adris.altoclef.AltoClef;
import adris.altoclef.TaskCatalogue;
import adris.altoclef.tasksystem.Task;
import adris.altoclef.util.RecipeTarget;
import net.minecraft.client.MinecraftClient;
import net.minecraft.item.Item;
import net.minecraft.registry.Registries;
import net.minecraft.util.Identifier;
import java.util.*;
import static dev.aitalkstreamer.mc.core.Json.*;

/** One material acquisition child at a time, using a shared capacity budget for every pending recipe. */
public final class ControlledRecipeResourcesTask extends Task {
    private record Intent(Item output,int total,int batch,List<Set<String>> ingredients) { }
    private final SurvivalAuthority.Session owner;
    private final List<Intent> intents;
    private final boolean ignoreUncatalogued;
    private final Set<String> explicitMaterials;
    private final int explicitCount;
    private Task child;
    private ResourceAcquisitionPlan.Source selected;
    private List<ResourceMaterialsPlan.Stock> beforeChild;
    private boolean finished,settling;

    public ControlledRecipeResourcesTask(boolean ignoreUncatalogued,RecipeTarget[] targets) {
        owner=SurvivalAuthority.session();this.ignoreUncatalogued=ignoreUncatalogued;explicitMaterials=null;explicitCount=0;
        require(targets!=null && targets.length>0 && targets.length<=64,"GAME_RESOURCE_CRAFT_TARGET_INVALID");
        var values=new ArrayList<Intent>();
        for(var target:targets) {
            require(target!=null && target.getOutputItem()!=null && target.getRecipe()!=null,"GAME_RESOURCE_CRAFT_TARGET_INVALID");
            var recipe=target.getRecipe();var ingredients=new ArrayList<Set<String>>();
            for(int i=0;i<recipe.getSlotCount();i++) {
                var slot=recipe.getSlot(i);var options=new TreeSet<String>();
                if(slot!=null) for(var item:slot.getMatches()) if(item!=null) options.add(Registries.ITEM.getId(item).toString());
                ingredients.add(Set.copyOf(options));
            }
            values.add(new Intent(target.getOutputItem(),target.getTargetCount(),recipe.outputCount(),List.copyOf(ingredients)));
        }
        intents=List.copyOf(values);
    }
    public ControlledRecipeResourcesTask(Item[] materials,int count) {
        owner=SurvivalAuthority.session();ignoreUncatalogued=false;intents=List.of();
        require(materials!=null && materials.length>0 && materials.length<=256 && Arrays.stream(materials).allMatch(Objects::nonNull)
                && count>0 && count<=4096,"GAME_MATERIAL_REQUIREMENT_INVALID");
        explicitMaterials=Arrays.stream(materials).map(item->Registries.ITEM.getId(item).toString()).collect(java.util.stream.Collectors.toUnmodifiableSet());explicitCount=count;
    }
    private void context() {SurvivalAuthority.requireScope();require(owner==SurvivalAuthority.session(),"GAME_RESOURCE_MATERIAL_CONTEXT_CHANGED");ResourceMaterials.desired();}
    private ResourceMaterialsPlan.Plan plan(List<ResourceMaterialsPlan.Stock> stock) {
        if(explicitMaterials!=null) return ResourceMaterialsPlan.materials(explicitMaterials,explicitCount,stock,ResourceMaterials.desired());
        var goals=new ArrayList<ResourceMaterialsPlan.Goal>();var inventory=MinecraftClient.getInstance().player.getInventory();
        for(var intent:intents) {
            int baseline=0;for(int i=0;i<inventory.size();i++) if(inventory.getStack(i).isOf(intent.output())) baseline=Math.addExact(baseline,inventory.getStack(i).getCount());
            goals.add(new ResourceMaterialsPlan.Goal(Registries.ITEM.getId(intent.output()).toString(),baseline,intent.total(),intent.batch(),intent.ingredients()));
        }
        return ResourceMaterialsPlan.prepare(goals,stock,ResourceMaterials.desired());
    }
    private void settled() {child=null;selected=null;beforeChild=null;finished=false;settling=true;}
    @Override protected void onStart() {context();finished=false;}
    @Override protected Task onTick() {
        context();
        if(settling) {if(!SurvivalAsync.quiescent())return null;settling=false;}
        var stock=ResourceMaterials.stock();
        if(child!=null) {
            ResourceMaterials.begin(this,selected,beforeChild,stock);
            if(!child.isFinished()) return child;
            // Inventory quantity alone can finish the wrapper before its nested craft/cooking transaction closes.
            if(!ResourceBranchRecovery.ready(child))return child;
            ResourceBranchRecovery.stop(child,child);
            ResourceMaterials.finish(this,ResourceMaterials.stock());settled();return null;
        }
        var plan=plan(stock);if(plan.complete()) {finished=true;return null;}
        var mod=AltoClef.getInstance();boolean cycle=false,failed=false;
        for(var request:plan.requests()) {
            var matches=request.items().stream().sorted().map(id->Registries.ITEM.get(Identifier.of(id))).toArray(Item[]::new);
            var sources=new ArrayList<ResourceAcquisitionPlan.Source>();var accepted=new HashSet<>(Arrays.asList(matches));
            TaskCatalogue.resourceNames().stream().sorted().filter(name->TaskCatalogue.taskExists(name)
                    && new HashSet<>(Arrays.asList(TaskCatalogue.getItemMatches(name))).equals(accepted))
                    .forEach(name->sources.add(new ResourceAcquisitionPlan.Source(ResourceAcquisitionPlan.Kind.CATALOGUE,name,request.items())));
            for(var item:matches) if(TaskCatalogue.taskExists(item)) sources.add(new ResourceAcquisitionPlan.Source(
                    ResourceAcquisitionPlan.Kind.ITEM,Registries.ITEM.getId(item).toString(),request.items()));
            while(true) {
                var choice=ResourceMaterials.choose(this,sources,stock);cycle|=choice.blockedByCycle();failed|=choice.blockedByFailure();
                var source=choice.source();if(source==null) break;
                ResourceMaterials.select();ResourceMaterials.begin(this,source,stock,stock);
                // Count upstream-visible stock; never recursively construct an uncatalogued union ItemTarget.
                try {
                    if(source.kind()==ResourceAcquisitionPlan.Kind.CATALOGUE) child=TaskCatalogue.getItemTask(source.name(),Math.addExact(mod.getItemStorage().getItemCount(matches),request.missing()));
                    else {var item=Registries.ITEM.get(Identifier.of(source.name()));child=TaskCatalogue.getItemTask(item,Math.addExact(mod.getItemStorage().getItemCount(item),request.missing()));}
                } catch(Rejected failure) {
                    if(!ResourceBranchRecovery.recoverable(failure.code))throw failure;
                    try {
                        if(!ResourceBranchRecovery.ready(this))throw failure;
                        ResourceBranchRecovery.stop(null,this);ResourceMaterials.failed(this,ResourceMaterials.stock(),failure.code);settled();
                    }
                    catch(RuntimeException|Error cleanup) {if(cleanup!=failure)cleanup.addSuppressed(failure);throw cleanup;}
                    return null;
                }
                if(child!=null) {selected=source;beforeChild=stock;return child;}
                // A factory returning no task is a completed no-progress branch, with the same retirement boundary.
                ResourceBranchRecovery.stop(null,this);ResourceMaterials.finish(this,ResourceMaterials.stock());settled();return null;
            }
        }
        if(cycle) throw new dev.aitalkstreamer.mc.core.Json.Rejected("GAME_RESOURCE_MATERIAL_CYCLE");
        if(failed) throw new dev.aitalkstreamer.mc.core.Json.Rejected("GAME_RESOURCE_MATERIAL_NO_PROGRESS");
        throw new dev.aitalkstreamer.mc.core.Json.Rejected(ignoreUncatalogued?"GAME_RESOURCE_MATERIAL_UNAVAILABLE":"GAME_RESOURCE_MATERIAL_UNCATALOGUED");
    }
    @Override protected boolean onChildFailure(Task failed,Rejected failure) {
        if(failed!=child || selected==null || beforeChild==null || !ResourceBranchRecovery.recoverable(failure.code))return false;
        context();if(!ResourceBranchRecovery.ready(failed))return false;
        ResourceBranchRecovery.stop(failed,failed);ResourceMaterials.failed(this,ResourceMaterials.stock(),failure.code);
        settled();return true;
    }
    @Override protected void onStop(Task interruptTask) {ResourceMaterials.releaseAcquisition(owner,this);}
    @Override public boolean isFinished() {if(finished) {context();finished=plan(ResourceMaterials.stock()).complete();}return finished;}
    @Override protected boolean isEqual(Task other) {return other==this;}
    @Override protected String toDebugString() {return "Capacity-budgeted recipe materials";}
}
