package dev.aitalkstreamer.mc.survival;

import org.junit.jupiter.api.Test;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

/** Actual compiled routes, not a substitute for native client/server acceptance. */
class FoodConsumptionBindingTest {
    final HeldNativeProtocolTest code=new HeldNativeProtocolTest();
    List<String> all(String name)throws Exception {return code.calls(name).values().stream().flatMap(List::stream).toList();}
    List<String> method(String name,String prefix)throws Exception {return code.calls(name).entrySet().stream().filter(e->e.getKey().startsWith(prefix)).findFirst().orElseThrow().getValue();}
    boolean has(List<String> calls,String prefix) {return calls.stream().anyMatch(c->c.startsWith(prefix));}
    @Test void actualFoodChoiceUsesConsumableMainStacksInsteadOfTheWholeStorageList()throws Exception {
        var calls=method("adris/altoclef/chains/FoodChain","calculateFood(");
        assertTrue(has(calls,"dev/aitalkstreamer/mc/survival/ControlledSupplyTask:consumableFoods"));
        assertFalse(has(calls,"adris/altoclef/trackers/storage/ItemStorageTracker:getItemStacksPlayerInventory"));
    }
    @Test void eatingChecksCapacityAtSelectionAndAgainAfterTheEquipmentAcknowledgement()throws Exception {
        for(String name:List.of("select(","onTick("))assertTrue(has(method("dev/aitalkstreamer/mc/survival/ControlledEatingTask",name),"dev/aitalkstreamer/mc/survival/ResourceMaterials:consumable"));
    }
    @Test void resourceAndSupplyConversionsBothAllocateExactRawAndFuelTogether()throws Exception {
        for(String name:List.of("ControlledSmeltingTask","ControlledFoodCookingTask")) {
            var calls=all("dev/aitalkstreamer/mc/survival/"+name);
            assertTrue(has(calls,"dev/aitalkstreamer/mc/survival/ResourceMaterials:"+(name.equals("ControlledSmeltingTask")?"conversionFuel":"singleUnits")));
            assertFalse(has(calls,"dev/aitalkstreamer/mc/survival/ResourceMaterials:available"));
        }
        assertTrue(has(all("dev/aitalkstreamer/mc/survival/ResourceMaterialsPlan"),"dev/aitalkstreamer/mc/survival/MaterialAllocation:constrained"));
        assertTrue(has(all("dev/aitalkstreamer/mc/survival/ResourceMaterialsPlan"),"dev/aitalkstreamer/mc/survival/MaterialTargets:limits"));
    }
    @Test void cookingSelectionCreatesPreparationWithoutCapturingTheConversionSlots()throws Exception {
        var calls=method("dev/aitalkstreamer/mc/survival/ControlledCookingTask","select(");
        assertTrue(has(calls,"dev/aitalkstreamer/mc/survival/ControlledFoodCookingTask:<init>"));
        assertFalse(has(calls,"dev/aitalkstreamer/mc/survival/ControlledCookingTask:<init>"));
        assertFalse(has(calls,"adris/altoclef/TaskCatalogue:getItemTask"));
    }
    @Test void preparationUsesTheSameMaterialCollectorActualFuelMapAndOriginalRootBudget()throws Exception {
        var calls=all("dev/aitalkstreamer/mc/survival/ControlledFoodCookingTask");
        for(String prefix:List.of("dev/aitalkstreamer/mc/survival/ControlledRecipeResourcesTask:<init>",
                "net/minecraft/block/entity/AbstractFurnaceBlockEntity:createFuelTimeMap", "dev/aitalkstreamer/mc/survival/ResourceMaterials:select"))assertTrue(has(calls,prefix));
        assertFalse(has(calls,"dev/aitalkstreamer/mc/survival/SurvivalAuthority:open"));
    }
    @Test void preparationWaitsForTheServerBaselineBeforeCreatingItsActualConversion()throws Exception {
        var calls=method("dev/aitalkstreamer/mc/survival/ControlledFoodCookingTask","onTick(");
        int baseline=calls.indexOf("dev/aitalkstreamer/mc/survival/SurvivalGui:furnaceSnapshot()Ldev/aitalkstreamer/mc/survival/SurvivalGui$FurnaceSnapshot;");
        assertTrue(baseline>=0);assertTrue(baseline<calls.indexOf("dev/aitalkstreamer/mc/survival/ResourceMaterials:select()V"));
        assertTrue(has(calls,"dev/aitalkstreamer/mc/survival/ControlledCookingTask:supply"));
    }
    @Test void actualTaskRetentionNowIncludesTheOriginalPreparationAncestorPath()throws Exception {
        for(String name:List.of("adris/altoclef/tasksystem/Task","adris/altoclef/chains/SingleTaskChain"))assertTrue(has(all(name),"dev/aitalkstreamer/mc/survival/ControlledCookingTask:retains"));
        assertTrue(has(method("dev/aitalkstreamer/mc/survival/ControlledCookingTask","retains("),"dev/aitalkstreamer/mc/survival/ControlledFoodCookingTask:retains"));
        assertTrue(has(method("dev/aitalkstreamer/mc/survival/ControlledFoodCookingTask","retains("),"adris/altoclef/tasksystem/Task:thisOrChildSatisfies"));
    }
    @Test void supplyCompletionAndPriorityWaitForPreparationAndItsOriginalCheckpoint()throws Exception {
        for(String name:List.of("adris/altoclef/chains/FoodChain","adris/altoclef/tasks/resources/CollectFoodTask","dev/aitalkstreamer/mc/survival/ControlledSupplyTask"))assertTrue(has(all(name),"dev/aitalkstreamer/mc/survival/ControlledFoodCookingTask:busy"));
        assertTrue(has(method("dev/aitalkstreamer/mc/survival/ControlledCookingTask","checkpoint("),"dev/aitalkstreamer/mc/survival/ControlledFoodCookingTask:checkpoint"));
    }
    @Test void preparationRetainsExactOriginalRecipeOutputAndContextWithoutStopEffects()throws Exception {
        var name="dev/aitalkstreamer/mc/survival/ControlledFoodCookingTask";
        var calls=method(name,"context(");
        assertTrue(has(calls,"dev/aitalkstreamer/mc/survival/ControlledCookingTask:recipe"));
        assertTrue(has(calls,"net/minecraft/item/ItemStack:areEqual"));
        assertEquals(List.of(),method(name,"onStop("));
        assertTrue(has(all(name),"dev/aitalkstreamer/mc/survival/SurvivalAuthority:owned"));
    }
    @Test void foodPotentialAndConsumptionUseJointCapacityWhileReserveAdmissionStillCountsOwnedStock()throws Exception {
        assertTrue(has(method("dev/aitalkstreamer/mc/survival/ControlledCookingTask","foodPotential("),"dev/aitalkstreamer/mc/survival/ResourceMaterials:usable"));
        assertTrue(has(method("dev/aitalkstreamer/mc/survival/ControlledSupplyTask","consumableFoods("),"dev/aitalkstreamer/mc/survival/ResourceMaterials:usable"));
        assertFalse(has(method("dev/aitalkstreamer/mc/survival/ControlledSupplyTask","inventoryNutrition("),"dev/aitalkstreamer/mc/survival/ResourceMaterials:usable"));
    }
}
