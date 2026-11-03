package dev.aitalkstreamer.mc.survival;

import org.junit.jupiter.api.Test;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

class ResourceMaterialsPlanTest {
    Set<String> oak=Set.of("minecraft:oak_planks"),planks=Set.of("minecraft:oak_planks","minecraft:spruce_planks");
    ResourceMaterialsPlan.Stock s(int slot,String item,int count) {return new ResourceMaterialsPlan.Stock(slot,"minecraft:"+item,count);}
    ResourceMaterialsPlan.Goal g(String out,int baseline,int target,int batch,Set<String>... ingredients) {return new ResourceMaterialsPlan.Goal("minecraft:"+out,baseline,target,batch,List.of(ingredients));}
    ResourceMaterialsPlan.Plan plan(List<ResourceMaterialsPlan.Stock> stock,ResourceMaterialsPlan.Goal... goals) {return ResourceMaterialsPlan.prepare(List.of(goals),stock,Map.of());}
    int missing(ResourceMaterialsPlan.Plan p) {return p.requests().stream().mapToInt(ResourceMaterialsPlan.Request::missing).sum();}
    @Test void overlappingRecipeRequirementsDoNotReuseTheSamePlank() {var p=plan(List.of(s(0,"oak_planks",1)),g("stick",0,1,1,planks),g("bowl",0,1,1,oak));assertFalse(p.complete());assertEquals(1,missing(p));}
    @Test void flexibleStockIsReassignedForTheRestrictedRecipe() {assertTrue(plan(List.of(s(0,"oak_planks",1),s(1,"spruce_planks",1)),g("stick",0,1,1,planks),g("bowl",0,1,1,oak)).complete());}
    @Test void identicalMaterialGroupsAcrossRecipesAreSummed() {var p=plan(List.of(s(0,"oak_planks",1)),g("stick",0,1,1,planks),g("bowl",0,1,1,planks));assertEquals(1,p.requests().size());assertEquals(2,p.requests().getFirst().targetMatching());}
    @Test void completedSiblingOutputIsRetainedAndAdditionalMaterialIsRequested() {var p=plan(List.of(s(0,"oak_planks",1),s(1,"spruce_planks",1)),g("oak_planks",1,1,1,Set.of("minecraft:oak_log")),g("stick",0,4,4,planks,planks));assertEquals(1,missing(p));assertEquals(3,p.requests().getFirst().targetMatching());}
    @Test void allCompletedOutputsNeedNoNewIngredients() {assertTrue(plan(List.of(s(0,"stick",4)),g("stick",4,4,4,planks,planks)).complete());}
    @Test void aPartialFinalBatchRoundsUp() {assertEquals(4,missing(plan(List.of(),g("stick",0,5,4,planks,planks))));}
    @Test void actualExistingOutputReducesTheNumberOfBatches() {assertEquals(2,missing(plan(List.of(s(0,"stick",4)),g("stick",4,5,4,planks,planks))));}
    @Test void holdsUseOnlyActuallyPresentMainInventoryStock() {var stock=List.of(s(0,"stick",1));var p=plan(stock,g("stick",2,2,4,planks,planks));assertTrue(p.complete());assertTrue(p.allocation().assignments().isEmpty());assertFalse(ResourceMaterialsPlan.removable(stock,Map.of("minecraft:stick",2),0,1));}
    @Test void anAncestorOutputCannotBecomeAChildsIngredient() {var p=ResourceMaterialsPlan.prepare(List.of(g("stick",0,1,1,oak)),List.of(s(0,"oak_planks",1)),Map.of("minecraft:oak_planks",1));assertEquals(1,missing(p));}
    @Test void alreadyMetGoalsDoNotCollectTheirRecipeMaterials() {var p=plan(List.of(),g("stick",20,4,4,planks,planks));assertTrue(p.complete());}
    @Test void partialExistingOutputIsAlsoRetained() {var p=plan(List.of(s(0,"stick",1)),g("stick",1,2,1,Set.of("minecraft:stick")));assertEquals(1,missing(p));}
    @Test void duplicateIdenticalOutputGoalsUseTheirMaximumAbsoluteTotal() {assertEquals(3,missing(plan(List.of(),g("stick",0,2,1,oak),g("stick",0,3,1,oak))));}
    @Test void conflictingRecipesForTheSameOutputAreRejected() {assertThrows(RuntimeException.class,()->plan(List.of(),g("stick",0,1,1,oak),g("stick",0,1,2,planks)));}
    @Test void negativeStockIsRejected() {assertThrows(RuntimeException.class,()->s(0,"stick",-1));}
    @Test void anAbsoluteTargetMayExceed4096WhenOnlyASmallIncrementIsMissing() {assertEquals(1,missing(plan(List.of(),g("stick",6000,6001,1,oak))));}
    @Test void theMissingOutputIncrementIsBounded() {assertThrows(RuntimeException.class,()->plan(List.of(),g("stick",0,4097,1,oak)));}
    @Test void duplicateInventorySlotsAreRejected() {assertThrows(RuntimeException.class,()->plan(List.of(s(0,"oak_planks",1),s(0,"spruce_planks",1)),g("stick",0,1,1,planks)));}
    @Test void emptyRecipeCellsDoNotBecomeAcquisitionRequirements() {assertEquals(1,missing(plan(List.of(),g("stick",0,1,1,Set.of(),oak))));}
    @Test void requestCollectionsAreImmutable() {var p=plan(List.of(),g("stick",0,1,1,oak));assertThrows(UnsupportedOperationException.class,()->p.requests().clear());assertThrows(UnsupportedOperationException.class,()->p.requests().getFirst().items().clear());}
    @Test void movingTheSameStockBetweenSlotsIsNotMaterialProgress() {assertEquals(ResourceMaterialsPlan.quantities(List.of(s(0,"oak_planks",2))),ResourceMaterialsPlan.quantities(List.of(s(9,"oak_planks",1),s(12,"oak_planks",1))));}
    @Test void actualQuantityOrItemChangesAreObservable() {var a=ResourceMaterialsPlan.quantities(List.of(s(0,"oak_planks",2)));assertNotEquals(a,ResourceMaterialsPlan.quantities(List.of(s(0,"oak_planks",1))));assertNotEquals(a,ResourceMaterialsPlan.quantities(List.of(s(0,"spruce_planks",2))));}
    @Test void combinedAncestorAndChildOutputCardinalityIsBounded() {var inherited=new HashMap<String,Integer>();for(int i=0;i<4096;i++)inherited.put("test:item"+i,1);assertThrows(RuntimeException.class,()->ResourceMaterialsPlan.prepare(List.of(g("stick",0,1,1,oak)),List.of(),inherited));}
    @Test void aChildOfA64OutputParentCanStillAcquireItsOwnMaterials() {var inherited=new HashMap<String,Integer>();for(int i=0;i<63;i++)inherited.put("test:item"+i,1);inherited.put("minecraft:oak_planks",1);var p=ResourceMaterialsPlan.prepare(List.of(g("stick",0,1,1,oak)),List.of(s(0,"oak_planks",1)),inherited);assertEquals(1,missing(p));}


    @Test void explicitSmeltingInputCannotConsumeAnAncestorReservedOutput() {
        var p=ResourceMaterialsPlan.materials(Set.of("minecraft:charcoal"),1,List.of(s(0,"charcoal",1)),Map.of("minecraft:charcoal",1));
        assertEquals(1,missing(p));assertFalse(p.complete());
    }
    @Test void explicitFuelCanUseAnUnreservedAlternative() {
        var p=ResourceMaterialsPlan.materials(Set.of("minecraft:charcoal","minecraft:oak_planks"),1,List.of(s(0,"charcoal",1),s(1,"oak_planks",1)),Map.of("minecraft:charcoal",1));
        assertTrue(p.complete());
    }
    @Test void freeSlotCapacitySubtractsReservedUnitsWithoutMovingInventory() {
        var free=ResourceMaterialsPlan.available(List.of(s(0,"charcoal",1),s(1,"charcoal",2),s(2,"oak_planks",2)),Map.of("minecraft:charcoal",2));
        assertEquals(1,free.get(0)+free.get(1));assertEquals(2,free.get(2));assertThrows(UnsupportedOperationException.class,()->free.clear());
    }
    @Test void futureOutputsDoNotReserveUnrelatedCurrentFuel() {
        assertEquals(Map.of(0,2),ResourceMaterialsPlan.available(List.of(s(0,"oak_planks",2)),Map.of("minecraft:iron_ingot",10)));
    }
    @Test void aSingleFreeLogCannotSupplyBothInputAndFuel() {
        var free=ResourceMaterialsPlan.available(List.of(s(0,"oak_log",2)),Map.of("minecraft:oak_log",1));assertFalse(SmeltingPlan.available(free,0,0));
    }
    @Test void explicitMaterialCountStillHonorsAllocationAndInventoryLimits() {
        assertThrows(RuntimeException.class,()->ResourceMaterialsPlan.materials(oak,0,List.of(),Map.of()));
        assertThrows(RuntimeException.class,()->ResourceMaterialsPlan.materials(oak,4097,List.of(),Map.of()));
        assertThrows(RuntimeException.class,()->ResourceMaterialsPlan.materials(oak,1,List.of(s(0,"oak_planks",1),s(0,"oak_planks",1)),Map.of()));
    }
    @Test void acquiringOneFuelUsesAnIncrementAboveTheActualMatchingStock() {
        var p=ResourceMaterialsPlan.materials(oak,1,List.of(s(0,"oak_planks",2)),Map.of("minecraft:oak_planks",2));
        assertEquals(1,p.requests().getFirst().missing());assertEquals(3,p.requests().getFirst().targetMatching());
    }
    @Test void fuelAcquisitionKeepsTheRawUnitAndRequestsAnotherUsableUnit() {
        var fuels=Set.of("minecraft:oak_planks","minecraft:charcoal");
        var p=ResourceMaterialsPlan.materials(fuels,SmeltingPlan.fuelUnits(true),List.of(s(0,"oak_planks",1),s(1,"charcoal",2)),Map.of("minecraft:charcoal",2));
        assertFalse(p.complete());assertEquals(1,missing(p));assertEquals(4,p.requests().getFirst().targetMatching());
        assertTrue(ResourceMaterialsPlan.materials(fuels,SmeltingPlan.fuelUnits(true),List.of(s(0,"oak_planks",2)),Map.of()).complete());
        assertTrue(ResourceMaterialsPlan.materials(fuels,SmeltingPlan.fuelUnits(false),List.of(s(0,"charcoal",1)),Map.of()).complete());
    }

}
