package dev.aitalkstreamer.mc.survival;

import org.junit.jupiter.api.Test;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

class AlternativeMaterialBindingTest {
    final HeldNativeProtocolTest code=new HeldNativeProtocolTest();
    List<String> calls(String name)throws Exception {return code.calls("dev/aitalkstreamer/mc/survival/"+name).values().stream().flatMap(List::stream).toList();}
    boolean has(List<String> calls,String prefix) {return calls.stream().anyMatch(s->s.startsWith("dev/aitalkstreamer/mc/survival/"+prefix));}
    @Test void smeltingRegistersTheGroupedTargetsInTheOriginalRoot()throws Exception {
        var methods=code.calls("dev/aitalkstreamer/mc/survival/ControlledSmeltingTask");
        assertTrue(has(methods.get("onStart()V"),"ResourceMaterials:enter(Ladris/altoclef/tasksystem/Task;Ldev/aitalkstreamer/mc/survival/MaterialTargets;)"));
        assertTrue(has(calls("ResourceMaterials"),"MaterialReservations:enter(Ljava/lang/Object;Ldev/aitalkstreamer/mc/survival/MaterialTargets;)"));
    }
    @Test void acquisitionFuelBuildingAndDisposalShareGroupedConstraints()throws Exception {
        var methods=code.calls("dev/aitalkstreamer/mc/survival/ResourceMaterialsPlan");
        for(String name:List.of("singleUnits","conversionFuel","removable","usable","allocate")) {
            assertTrue(methods.entrySet().stream().filter(e->e.getKey().startsWith(name+"(")).anyMatch(e->has(e.getValue(),"ResourceMaterialsPlan:allocate") || has(e.getValue(),"MaterialAllocation:constrained")),name);
        }
        assertTrue(has(calls("ResourceMaterialsPlan"),"MaterialTargets:limits"));
        assertTrue(has(calls("ResourceMaterialsPlan"),"MaterialTargets:externalUsable"));
    }
    @Test void currentRecipeSelectionPassesTheSameGroupsToTheCraftAllocator()throws Exception {
        assertTrue(has(calls("CraftSpec"),"ResourceMaterials:limits"));assertTrue(has(calls("CraftPlan"),"MaterialAllocation:constrained"));
        assertTrue(has(calls("ResourceRecipePlan"),"CraftPlan:prepare(Ljava/util/List;Ljava/util/List;Ljava/lang/String;IILjava/util/List;Ljava/util/List;)"));
    }
    @Test void groupedReservationAndSearchAreStateOnlyWithoutIndependentController()throws Exception {
        for(String name:List.of("MaterialTargets","MaterialAllocation","MaterialReservations")) {
            var all=calls(name);
            for(String forbidden:List.of("SurvivalAuthority:open","SurvivalGui:","SurvivalInputs:","SurvivalActions:"))assertFalse(has(all,forbidden));
        }
    }
}
