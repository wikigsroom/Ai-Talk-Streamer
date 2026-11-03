package dev.aitalkstreamer.mc.survival;

import adris.altoclef.AltoClef;
import adris.altoclef.tasksystem.Task;
import java.util.Set;

/** Retire one acquisition branch under the same root; uncertain effects and revocation never qualify. */
final class ResourceBranchRecovery {
    private static final Set<String> RECOVERABLE=Set.of(
            "GAME_CRAFT_MATERIALS_MISSING","GAME_CRAFT_RECIPE_UNAVAILABLE","GAME_CRAFT_RECIPE_AMBIGUOUS",
            "GAME_RESOURCE_CRAFT_MATERIALS_UNAVAILABLE","GAME_RESOURCE_MATERIAL_CYCLE","GAME_RESOURCE_MATERIAL_NO_PROGRESS",
            "GAME_RESOURCE_MATERIAL_UNAVAILABLE","GAME_RESOURCE_MATERIAL_UNCATALOGUED",
            "GAME_RESOURCE_SMELTING_FUEL_UNAVAILABLE","GAME_RESOURCE_SMELTING_RECIPE_UNSUPPORTED");
    private ResourceBranchRecovery() { }
    static boolean recoverable(String reason) {return reason!=null && RECOVERABLE.contains(reason);}
    static boolean ready(Task subtree) {
        SurvivalAuthority.requireScope();ResourceMaterials.desired();
        dev.aitalkstreamer.mc.core.Json.require(subtree!=null,"GAME_RESOURCE_MATERIAL_CONTEXT_CHANGED");
        return !ConfirmedCraftTask.busy() && !ControlledCookingTask.busy() && !ControlledFoodCookingTask.within(subtree)
                && !ControlledEatingTask.busy() && !ControlledEquipment.busy() && !ControlledStorage.blocksInventory() && !ControlledShield.busy()
                && SurvivalGui.backtrackReady();
    }
    static void stop(Task branch,Task boundary) {
        SurvivalAuthority.requireScope();
        if(!ready(boundary))throw new dev.aitalkstreamer.mc.core.Json.Rejected("GAME_RESOURCE_MATERIAL_CONTEXT_CHANGED");
        // onStop itself can cancel paths and synchronously deliver path callbacks.
        SurvivalAsync.invalidate();
        if(branch!=null)branch.stop();
        // Retire any calculation submitted by the old subtree's cleanup as well.
        SurvivalAsync.invalidate();
        var mod=AltoClef.getInstance();mod.getClientBaritone().getPathingBehavior().forceCancel();
        SurvivalCallbacks.clearRootEvents((SurvivalCallbacks.RootResettable)(Object)mod.getClientBaritone().getPathingBehavior());
        mod.getClientBaritone().getInputOverrideHandler().clearAllKeys();mod.getInputControls().clearControlledQueue();
        SurvivalActions.finishOwned();SurvivalGui.finishOwned();
        if(!ready(boundary))throw new dev.aitalkstreamer.mc.core.Json.Rejected("GAME_RESOURCE_MATERIAL_CONTEXT_CHANGED");
    }
}
