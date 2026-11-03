package dev.aitalkstreamer.mc.survival;

import org.junit.jupiter.api.Test;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

class MaterialAllocationTest {
    CraftPlan.Supply s(int slot,int count) {return new CraftPlan.Supply(slot,count);}
    MaterialAllocation.Need n(String key,int count,Integer... slots) {return new MaterialAllocation.Need(key,count,Set.of(slots),false);}
    MaterialAllocation.Need h(String key,int count,Integer... slots) {return new MaterialAllocation.Need(key,count,Set.of(slots),true);}
    MaterialAllocation.Result plan(List<CraftPlan.Supply> stock,MaterialAllocation.Need... needs) {return MaterialAllocation.allocate(stock,List.of(needs));}
    int used(MaterialAllocation.Result p,String key,int slot) {return p.assignments().stream().filter(a->a.key().equals(key)&&a.slot()==slot).mapToInt(MaterialAllocation.Assigned::count).sum();}
    @Test void oneUnitCannotSatisfyTwoMaterialRequirements() {var p=plan(List.of(s(0,1)),n("a",1,0),n("b",1,0));assertFalse(p.complete());assertEquals(1,p.missing().values().stream().mapToInt(i->i).sum());}
    @Test void flexibleMaterialDoesNotTakeTheOnlyRestrictedStack() {var p=plan(List.of(s(0,1),s(1,1)),n("flex",1,0,1),n("only",1,0));assertTrue(p.complete());assertEquals(1,used(p,"only",0));}
    @Test void splitStacksCanMeetOneQuantity() {var p=plan(List.of(s(0,2),s(8,3)),n("a",5,0,8));assertTrue(p.complete());assertEquals(2,used(p,"a",0));assertEquals(3,used(p,"a",8));}
    @Test void aRetainedOutputCannotBeSpentAsAMaterial() {var p=plan(List.of(s(0,1)),h("hold",1,0),n("a",1,0));assertEquals(Map.of("a",1),p.missing());assertEquals(1,used(p,"hold",0));}
    @Test void surplusBeyondRetainedOutputCanBeSpent() {var p=plan(List.of(s(0,3)),h("hold",1,0),n("a",2,0));assertTrue(p.complete());assertEquals(2,used(p,"a",0));}
    @Test void aHoldMayMoveToAnEquivalentStackToPreserveAComponentRestrictedInput() {var p=plan(List.of(s(0,1),s(1,1)),h("hold",1,0,1),n("component",1,0));assertTrue(p.complete());assertEquals(1,used(p,"hold",1));assertEquals(1,used(p,"component",0));}
    @Test void independentRetainedOutputsAreBothPreserved() {var p=plan(List.of(s(0,2),s(1,2)),h("x",1,0),h("y",1,1),n("a",2,0,1));assertTrue(p.complete());assertEquals(1,used(p,"x",0));assertEquals(1,used(p,"y",1));}
    @Test void missingMatchingSlotsProduceAnExactShortage() {assertEquals(Map.of("a",7),plan(List.of(s(0,9)),n("a",7)).missing());}
    @Test void anEmptyPlanNeedsNoInventory() {assertTrue(plan(List.of()).complete());}
    @Test void zeroQuantityDoesNotProduceAShortage() {assertTrue(plan(List.of(),n("a",0)).complete());}
    @Test void duplicateInventorySlotsAreRejected() {assertThrows(RuntimeException.class,()->plan(List.of(s(0,1),s(0,1)),n("a",1,0)));}
    @Test void duplicateRequirementKeysAreRejected() {assertThrows(RuntimeException.class,()->plan(List.of(s(0,1)),n("a",1,0),n("a",1,0)));}
    @Test void requirementCardinalityIsBounded() {var needs=new ArrayList<MaterialAllocation.Need>();for(int i=0;i<641;i++)needs.add(n("a"+i,1));assertThrows(RuntimeException.class,()->MaterialAllocation.allocate(List.of(),needs));}
    @Test void invalidMatchingSlotsAreRejected() {assertThrows(RuntimeException.class,()->n("a",1,36));assertThrows(RuntimeException.class,()->n("a",1,-1));}
    @Test void aggregateUnitsAreBoundedBeforeGraphConstruction() {assertThrows(RuntimeException.class,()->plan(List.of(),n("a",MaterialAllocation.MAX_UNITS),n("b",1)));}
    @Test void anUnfulfillableHoldIsNotReportedAsAnAcquirableIngredient() {var e=assertThrows(RuntimeException.class,()->plan(List.of(s(0,1)),h("hold",2,0)));assertTrue(e.getMessage().contains("HOLD_UNAVAILABLE"));}
    @Test void resultCollectionsCannotBeChanged() {var p=plan(List.of(),n("a",1));assertThrows(UnsupportedOperationException.class,()->p.missing().put("a",0));assertThrows(UnsupportedOperationException.class,()->p.assignments().clear());}
    @Test void inventoryAndRequirementOrderDoNotChangeTheAllocation() {var a=plan(List.of(s(0,2),s(1,1)),n("b",2,0,1),n("a",1,0));var b=plan(List.of(s(1,1),s(0,2)),n("a",1,0),n("b",2,0,1));assertEquals(a,b);}
    @Test void maximumRecipeSlotCardinalityAllocatesWithoutExpandingEveryUnit() {var stock=new ArrayList<CraftPlan.Supply>();var slots=new HashSet<Integer>();for(int i=0;i<36;i++){stock.add(s(i,64));slots.add(i);}var needs=new ArrayList<MaterialAllocation.Need>();for(int i=0;i<576;i++)needs.add(new MaterialAllocation.Need("m"+i,4,slots,false));assertTrue(MaterialAllocation.allocate(stock,needs).complete());}
    @Test void nativeCraftPlanExcludesHeldOutputsFromItsRealMaterialAllocation() {var recipe=new CraftPlan.Recipe("test:r",false,0,0,1,List.of(new CraftPlan.Ingredient(false,Set.of(0,1))));var p=CraftPlan.prepare(List.of(recipe),List.of(s(0,1),s(1,1)),"minecraft:stick",0,1,List.of(h("hold",1,0)));assertEquals(List.of(new CraftPlan.Allocation(0,1,1)),p.allocation());}
    @Test void nativeCraftPlanReportsMaterialShortageWhenOnlyARetainedOutputMatches() {var recipe=new CraftPlan.Recipe("test:r",false,0,0,1,List.of(new CraftPlan.Ingredient(false,Set.of(0))));var e=assertThrows(RuntimeException.class,()->CraftPlan.prepare(List.of(recipe),List.of(s(0,1)),"minecraft:stick",0,1,List.of(h("hold",1,0))));assertTrue(e.getMessage().contains("MATERIALS_MISSING"));}
}
