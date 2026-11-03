package dev.aitalkstreamer.mc.survival;

import adris.altoclef.AltoClef;
import adris.altoclef.tasks.container.DoStuffInContainerTask;
import adris.altoclef.tasks.resources.CollectRecipeCataloguedResourcesTask;
import adris.altoclef.tasksystem.ITaskUsesCraftingGrid;
import adris.altoclef.tasksystem.Task;
import adris.altoclef.util.ItemTarget;
import adris.altoclef.util.RecipeTarget;
import net.minecraft.block.Blocks;
import net.minecraft.client.MinecraftClient;
import net.minecraft.screen.CraftingScreenHandler;
import java.util.*;
import java.util.function.Supplier;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Resource-tree crafting keeps acquisition but executes each actual recipe through confirmed native inventory steps. */
public final class ControlledResourceCraftTask extends Task implements ITaskUsesCraftingGrid {
    private final SurvivalAuthority.Session owner;
    private final Object world, player, connection;
    private final RecipeTarget[] targets;
    private final boolean collect, ignoreUncatalogued;
    private ConfirmedCraftTask current;
    private Task opening;
    private final Supplier<Task> collectorFactory;
    private Task collector;
    private boolean finished, collected;

    public ControlledResourceCraftTask(RecipeTarget[] targets) { this(targets,true,false); }
    public ControlledResourceCraftTask(RecipeTarget[] targets,boolean collect,boolean ignoreUncatalogued) {
        this(targets,collect,ignoreUncatalogued,null);
    }
    public ControlledResourceCraftTask(RecipeTarget[] targets,boolean collect,boolean ignoreUncatalogued,Supplier<Task> collectorFactory) {
        owner=SurvivalAuthority.session();var client=MinecraftClient.getInstance();
        world=client.world;player=client.player;connection=client.getNetworkHandler();
        require(targets!=null && targets.length>0 && targets.length<=64 && Arrays.stream(targets).allMatch(Objects::nonNull),
                "GAME_RESOURCE_CRAFT_TARGET_INVALID");
        this.targets=targets.clone();this.collect=collect;this.ignoreUncatalogued=ignoreUncatalogued;
        this.collectorFactory=collectorFactory;
    }
    private void context() {
        SurvivalAuthority.requireScope();var client=MinecraftClient.getInstance();
        require(owner==SurvivalAuthority.session() && client.isOnThread() && client.world==world && client.player==player
                && client.getNetworkHandler()==connection && client.player.isAlive() && client.isWindowFocused() && !client.isPaused(),
                "GAME_RESOURCE_CRAFT_CONTEXT_CHANGED");
    }
    private static int count(RecipeTarget target) {
        var inventory=MinecraftClient.getInstance().player.getInventory();int result=0;
        for(int i=0;i<inventory.size();i++) if(inventory.getStack(i).isOf(target.getOutputItem())) result=Math.addExact(result,inventory.getStack(i).getCount());
        return result;
    }
    private static void closeEmptyOwnedScreen() {
        var client=MinecraftClient.getInstance();if(client.currentScreen==null) return;
        var handler=SurvivalGui.ownedHandler();
        require(handler.getCursorStack().isEmpty(),"GAME_RESOURCE_CRAFT_CURSOR_BUSY");
        int grid=handler instanceof CraftingScreenHandler?9:4;
        for(int i=1;i<=grid;i++) require(handler.getSlot(i).getStack().isEmpty(),"GAME_RESOURCE_CRAFT_GRID_BUSY");
        SurvivalGui.close(client.player);
    }
    @Override protected void onStart() { context();ResourceMaterials.enter(this,targets);finished=false; }
    @Override protected Task onTick() {
        context();var client=MinecraftClient.getInstance();
        if(current!=null) {if(!current.isFinished()) return current;current=null;opening=null;collector=null;collected=false;}
        if(ControlledStorage.blocksInventory() || ControlledEquipment.busy() || ControlledEatingTask.busy() || ControlledCookingTask.blocksInventory() || ControlledShield.busy()) return null;
        RecipeTarget next=Arrays.stream(targets).filter(target->count(target)<target.getTargetCount()).findFirst().orElse(null);
        if(next==null) {closeEmptyOwnedScreen();finished=true;return null;}
        require(client.player.currentScreenHandler.getCursorStack().isEmpty(),"GAME_RESOURCE_CRAFT_CURSOR_BUSY");
        CraftSpec spec;
        try {spec=CraftSpec.captureResource(next);}
        catch(Rejected failure) {
            if(!failure.code.equals("GAME_CRAFT_MATERIALS_MISSING") || !collect) throw failure;
            closeEmptyOwnedScreen();
            if(collector==null) collector=collectorFactory==null?new CollectRecipeCataloguedResourcesTask(ignoreUncatalogued,targets):collectorFactory.get();
            require(collector!=null,"GAME_RESOURCE_CRAFT_MATERIALS_UNAVAILABLE");
            require(!collected || !collector.isFinished(),"GAME_RESOURCE_CRAFT_MATERIALS_UNAVAILABLE");
            collected=true;return collector;
        }
        if(spec==null) return null;
        if(spec.plan.gridSize()==3 && !(client.player.currentScreenHandler instanceof CraftingScreenHandler)) {
            closeEmptyOwnedScreen();if(opening==null) opening=new OpenTable();return opening;
        }
        if(spec.plan.gridSize()==2 && client.player.currentScreenHandler instanceof CraftingScreenHandler) {closeEmptyOwnedScreen();return null;}
        // Recaptured after creating/opening the table: its own materials cannot remain in an old allocation.
        current=new ConfirmedCraftTask(spec);return current;
    }
    @Override protected void onStop(Task interrupted) { ResourceMaterials.leave(owner,this); /* State only, including after revocation. */ }
    @Override public boolean isFinished() { return finished; }
    @Override public boolean isEqual(Task other) {return other instanceof ControlledResourceCraftTask task && task.owner==owner
            && task.collect==collect && task.ignoreUncatalogued==ignoreUncatalogued && Arrays.equals(task.targets,targets);}
    @Override public String toDebugString() {return "Confirmed resource recipes "+Arrays.toString(targets);}
    private static final class OpenTable extends DoStuffInContainerTask {
        OpenTable() {super(Blocks.CRAFTING_TABLE,new ItemTarget("crafting_table"));}
        @Override protected boolean isContainerOpen(AltoClef mod) {return MinecraftClient.getInstance().player.currentScreenHandler instanceof CraftingScreenHandler;}
        @Override protected Task containerSubTask(AltoClef mod) {return null;}
        @Override protected boolean isSubTaskEqual(DoStuffInContainerTask other) {return other==this;}
        @Override protected double getCostToMakeNew(AltoClef mod) {return 100;}
    }
}
