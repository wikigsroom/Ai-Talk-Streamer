package dev.aitalkstreamer.mc.survival;

import org.junit.jupiter.api.Test;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

class ResourceMaterialsBindingTest {
    final HeldNativeProtocolTest code=new HeldNativeProtocolTest();
    List<String> all(String name)throws Exception {return code.calls(name).values().stream().flatMap(List::stream).toList();}
    boolean has(List<String> calls,String prefix) {return calls.stream().anyMatch(s->s.startsWith(prefix));}
    @Test void actualDefaultCollectorDelegatesToTheCapacityBudgetedChild()throws Exception {
        var tick=code.calls("adris/altoclef/tasks/resources/CollectRecipeCataloguedResourcesTask").get("onTick()Ladris/altoclef/tasksystem/Task;");
        assertTrue(has(tick,"dev/aitalkstreamer/mc/survival/ControlledRecipeResourcesTask:<init>"));
        assertFalse(has(tick,"adris/altoclef/TaskCatalogue:getItemTask"));assertFalse(has(tick,"adris/altoclef/util/helpers/StorageHelper:"));
    }
    @Test void actualCollectorCompletionUsesTheSameChildInsteadOfTheOldGreedyMaterialCheck()throws Exception {
        var done=code.calls("adris/altoclef/tasks/resources/CollectRecipeCataloguedResourcesTask").get("isFinished()Z");
        assertTrue(has(done,"dev/aitalkstreamer/mc/survival/ControlledRecipeResourcesTask:isFinished"));assertFalse(has(done,"adris/altoclef/util/helpers/StorageHelper:hasRecipeMaterialsOrTarget"));
    }
    @Test void materialChildRefreshesItsFinishedStateAgainstCurrentStock()throws Exception {
        var done=code.calls("dev/aitalkstreamer/mc/survival/ControlledRecipeResourcesTask").get("isFinished()Z");
        assertTrue(has(done,"dev/aitalkstreamer/mc/survival/ResourceMaterials:stock"));assertTrue(has(done,"dev/aitalkstreamer/mc/survival/ControlledRecipeResourcesTask:plan"));
    }
    @Test void realResourceFramesRegisterAndReleaseTheirOriginalRootState()throws Exception {
        var methods=code.calls("dev/aitalkstreamer/mc/survival/ControlledResourceCraftTask");
        assertTrue(has(methods.get("onStart()V"),"dev/aitalkstreamer/mc/survival/ResourceMaterials:enter"));
        assertTrue(has(methods.get("onStop(Ladris/altoclef/tasksystem/Task;)V"),"dev/aitalkstreamer/mc/survival/ResourceMaterials:leave"));
    }
    @Test void resourceRootStateCapturesItsOwnerAndRegistersStateOnlyCleanup()throws Exception {
        var calls=all("dev/aitalkstreamer/mc/survival/ResourceMaterials");
        assertTrue(has(calls,"dev/aitalkstreamer/mc/survival/SurvivalAuthority:owned"));assertTrue(has(calls,"dev/aitalkstreamer/mc/survival/SurvivalAuthority:requireOwnerScope"));
        assertTrue(has(all("dev/aitalkstreamer/mc/survival/ResourceMaterials$State"),"dev/aitalkstreamer/mc/survival/SurvivalAuthority:session"));
        for(String forbidden:List.of("dev/aitalkstreamer/mc/survival/SurvivalGui:","dev/aitalkstreamer/mc/survival/SurvivalInputs:","dev/aitalkstreamer/mc/survival/SurvivalActions:","dev/aitalkstreamer/mc/survival/SurvivalAuthority:open"))assertFalse(has(calls,forbidden));
    }
    @Test void actualResourceRecipeSelectionIncludesActiveAncestorOutputHolds()throws Exception {
        var capture=code.calls("dev/aitalkstreamer/mc/survival/CraftSpec").get("captureResource(Ladris/altoclef/util/RecipeTarget;)Ldev/aitalkstreamer/mc/survival/CraftSpec;");
        assertTrue(has(capture,"dev/aitalkstreamer/mc/survival/ResourceMaterials:limits"));
        assertTrue(has(all("dev/aitalkstreamer/mc/survival/ResourceRecipePlan"),"dev/aitalkstreamer/mc/survival/CraftPlan:prepare(Ljava/util/List;Ljava/util/List;Ljava/lang/String;IILjava/util/List;Ljava/util/List;)"));
    }
    @Test void bothAcquisitionAndActualCraftingUseTheSameCapacityAllocator()throws Exception {
        assertTrue(has(all("dev/aitalkstreamer/mc/survival/ResourceMaterialsPlan"),"dev/aitalkstreamer/mc/survival/MaterialAllocation:constrained"));
        assertTrue(has(all("dev/aitalkstreamer/mc/survival/CraftPlan"),"dev/aitalkstreamer/mc/survival/MaterialAllocation:constrained"));
    }
    @Test void acquisitionUsesAnExplicitCatalogueOrConcreteItemWithoutRecursiveUnionTargets()throws Exception {
        var calls=all("dev/aitalkstreamer/mc/survival/ControlledRecipeResourcesTask");
        assertTrue(has(calls,"adris/altoclef/TaskCatalogue:getItemTask(Ljava/lang/String;I)"));
        assertTrue(has(calls,"adris/altoclef/TaskCatalogue:getItemTask(Lnet/minecraft/item/Item;I)"));
        assertFalse(has(calls,"adris/altoclef/TaskCatalogue:getItemTask(Ladris/altoclef/util/ItemTarget;)"));
        assertFalse(has(calls,"dev/aitalkstreamer/mc/survival/SurvivalAuthority:open"));
    }
    @Test void originalRootCountsSelectionsBeforeCreatingAMaterialChildAndChecksQuantityProgress()throws Exception {
        var tick=code.calls("dev/aitalkstreamer/mc/survival/ControlledRecipeResourcesTask").get("onTick()Ladris/altoclef/tasksystem/Task;");
        int count=tick.indexOf("dev/aitalkstreamer/mc/survival/ResourceMaterials:select()V");
        assertTrue(count>=0);assertTrue(count<tick.indexOf("adris/altoclef/TaskCatalogue:getItemTask(Ljava/lang/String;I)Ladris/altoclef/tasks/ResourceTask;"));
        assertTrue(has(tick,"dev/aitalkstreamer/mc/survival/ResourceMaterials:finish"));
    }
    @Test void stoppingMaterialAcquisitionCannotSendInventoryOrStopPackets()throws Exception {
        var stop=code.calls("dev/aitalkstreamer/mc/survival/ControlledRecipeResourcesTask").get("onStop(Ladris/altoclef/tasksystem/Task;)V");
        for(String forbidden:List.of("dev/aitalkstreamer/mc/survival/SurvivalGui:","dev/aitalkstreamer/mc/survival/SurvivalActions:","dev/aitalkstreamer/mc/survival/SurvivalInputs:","net/minecraft/"))assertFalse(has(stop,forbidden));
    }
    @Test void originalRootOwnsAcquisitionStateAndCleanup()throws Exception {
        assertTrue(has(all("dev/aitalkstreamer/mc/survival/ResourceMaterials$State"),"dev/aitalkstreamer/mc/survival/ResourceAcquisitionPlan:<init>"));
        assertTrue(has(all("dev/aitalkstreamer/mc/survival/ResourceMaterials"),"dev/aitalkstreamer/mc/survival/ResourceAcquisitionPlan:clear"));
    }
    @Test void actualAcquisitionSelectionAndResumeUseTheRootPolicy()throws Exception {
        var tick=code.calls("dev/aitalkstreamer/mc/survival/ControlledRecipeResourcesTask").get("onTick()Ladris/altoclef/tasksystem/Task;");
        for(String method:List.of("choose","begin","finish"))assertTrue(has(tick,"dev/aitalkstreamer/mc/survival/ResourceMaterials:"+method));
        assertTrue(Collections.frequency(tick,"dev/aitalkstreamer/mc/survival/ResourceMaterials:begin(Ladris/altoclef/tasksystem/Task;Ldev/aitalkstreamer/mc/survival/ResourceAcquisitionPlan$Source;Ljava/util/List;Ljava/util/List;)V")>=2);
    }
    @Test void cycleRelationCallsTheActualPreparedTaskAncestorPredicate()throws Exception {
        assertTrue(has(all("dev/aitalkstreamer/mc/survival/ResourceMaterials"),"adris/altoclef/tasksystem/Task:thisOrChildSatisfies"));
    }
    @Test void stoppingACollectorReleasesOnlyItsOwnedAcquisitionClaim()throws Exception {
        var stop=code.calls("dev/aitalkstreamer/mc/survival/ControlledRecipeResourcesTask").get("onStop(Ladris/altoclef/tasksystem/Task;)V");
        assertTrue(has(stop,"dev/aitalkstreamer/mc/survival/ResourceMaterials:releaseAcquisition"));
        var release=code.calls("dev/aitalkstreamer/mc/survival/ResourceMaterials").get("releaseAcquisition(Ldev/aitalkstreamer/mc/survival/SurvivalAuthority$Session;Ladris/altoclef/tasksystem/Task;)V");
        assertTrue(has(release,"dev/aitalkstreamer/mc/survival/SurvivalAuthority:requireOwnerScope"));assertTrue(has(release,"dev/aitalkstreamer/mc/survival/ResourceAcquisitionPlan:release"));assertFalse(has(release,"dev/aitalkstreamer/mc/survival/ResourceAcquisitionPlan:clear"));
    }
    @Test void usefulProgressPolicyIsLinkedIntoTheNativeAdapter()throws Exception {
        var methods=code.calls("dev/aitalkstreamer/mc/survival/ResourceAcquisitionPlan");
        assertTrue(has(methods.get("finish(Ljava/lang/Object;Ljava/util/List;)Z"),"dev/aitalkstreamer/mc/survival/ResourceAcquisitionPlan$Source:items"));
        assertTrue(has(all("dev/aitalkstreamer/mc/survival/ResourceAcquisitionPlan"),"dev/aitalkstreamer/mc/survival/ResourceMaterialsPlan:quantities"));
    }
}
