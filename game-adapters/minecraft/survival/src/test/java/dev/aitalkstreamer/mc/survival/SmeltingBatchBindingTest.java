package dev.aitalkstreamer.mc.survival;

import java.util.*;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Guards the compiled native call path; gameplay still requires real client/server acceptance. */
class SmeltingBatchBindingTest {
    final HeldNativeProtocolTest code=new HeldNativeProtocolTest();
    List<String> method(String name,String prefix)throws Exception {return code.calls("dev/aitalkstreamer/mc/survival/"+name).entrySet().stream().filter(e->e.getKey().startsWith(prefix)).findFirst().orElseThrow().getValue();}
    boolean has(List<String> calls,String prefix) {return calls.stream().anyMatch(c->c.startsWith(prefix));}
    int index(List<String> calls,String prefix) {for(int i=0;i<calls.size();i++)if(calls.get(i).startsWith(prefix))return i;return -1;}
    @Test void resourcePreparationWaitsForTheFullPacketBeforeMakingStockDecisions()throws Exception {
        var calls=method("ControlledSmeltingTask","onTick(");
        int snapshot=index(calls,"dev/aitalkstreamer/mc/survival/SurvivalGui:furnaceSnapshot");
        assertTrue(snapshot>=0 && snapshot<index(calls,"dev/aitalkstreamer/mc/survival/ResourceMaterials:stock"));
    }
    @Test void supplyPreparationWaitsBeforeDeclaringItsNutritionTargetAlreadySatisfied()throws Exception {
        var calls=method("ControlledFoodCookingTask","onTick(");
        int snapshot=index(calls,"dev/aitalkstreamer/mc/survival/SurvivalGui:furnaceSnapshot");
        assertTrue(snapshot>=0 && snapshot<index(calls,"dev/aitalkstreamer/mc/survival/ControlledSupplyTask:inventoryNutrition"));
    }
    @Test void nativeBatchSelectionUsesActualRecipeCapacityAndJointCountedFuel()throws Exception {
        var calls=method("ControlledSmeltingTask","onTick(");
        for(String prefix:List.of("SmeltingPlan:batchLimit","ResourceMaterials:usable","ResourceMaterials:conversionFuel"))assertTrue(has(calls,"dev/aitalkstreamer/mc/survival/"+prefix));
        assertTrue(has(calls,"dev/aitalkstreamer/mc/survival/ControlledCookingTask:resource(Ldev/aitalkstreamer/mc/survival/CookingWorkstation;Lnet/minecraft/recipe/RecipeEntry;III)"));
    }
    @Test void actualTransactionUsesTheBatchDeadlineAndRechecksCountedMaterials()throws Exception {
        var calls=method("ControlledCookingTask","onTick(");
        assertTrue(has(calls,"dev/aitalkstreamer/mc/survival/SmeltingPlan:batchMillis"));
        assertTrue(has(calls,"dev/aitalkstreamer/mc/survival/ResourceMaterials:conversionFuel"));
        assertTrue(has(calls,"dev/aitalkstreamer/mc/survival/CookingExchange:<init>(Ldev/aitalkstreamer/mc/survival/CraftClicks$State;Ldev/aitalkstreamer/mc/survival/CraftClicks$Stack;Ldev/aitalkstreamer/mc/survival/CraftClicks$Stack;Ldev/aitalkstreamer/mc/survival/CraftClicks$Stack;ILjava/util/function/LongSupplier;Ljava/util/function/BooleanSupplier;JI)"));
    }
}
