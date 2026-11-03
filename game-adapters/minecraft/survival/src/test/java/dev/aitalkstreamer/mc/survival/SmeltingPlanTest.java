package dev.aitalkstreamer.mc.survival;

import org.junit.jupiter.api.Test;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

class SmeltingPlanTest {
    ResourceMaterialsPlan.Stock stock(int slot,String item,int count) {return new ResourceMaterialsPlan.Stock(slot,item,count);}
    SmeltingPlan.Goal goal(int total) {return new SmeltingPlan.Goal(Set.of("iron"),Set.of("raw_iron","iron_ore"),total);}
    @Test void targetsAreAbsoluteExistingOutputIsNotSmeltedAgain() {assertEquals(2,SmeltingPlan.missing(goal(5),List.of(stock(0,"iron",3),stock(1,"raw_iron",20))));}
    @Test void extraOutputDoesNotCreateNegativeWork() {assertEquals(0,SmeltingPlan.missing(goal(2),List.of(stock(0,"iron",5))));}
    @Test void alternativeOutputKindsAreCountedAsOneGoal() {var g=new SmeltingPlan.Goal(Set.of("stone","smooth_stone"),Set.of("input"),5);assertEquals(1,SmeltingPlan.missing(g,List.of(stock(0,"stone",2),stock(1,"smooth_stone",2))));}
    @Test void identicalOutputTargetsMergeByMaximum() {assertEquals(MaterialTargets.from(Map.of("iron",5)),SmeltingPlan.desired(List.of(goal(3),goal(5))));}
    @Test void simultaneousOutputsRemainReserved() {var other=new SmeltingPlan.Goal(Set.of("glass"),Set.of("sand"),2);assertEquals(MaterialTargets.from(Map.of("iron",3,"glass",2)),SmeltingPlan.desired(List.of(goal(3),other)));}
    @Test void callerMutationCannotChangeCapturedInputsAndOutputs() {var out=new HashSet<>(Set.of("iron"));var raw=new HashSet<>(Set.of("raw_iron"));var g=new SmeltingPlan.Goal(out,raw,2);out.clear();raw.clear();assertEquals(Set.of("iron"),g.outputs());assertEquals(Set.of("raw_iron"),g.materials());assertThrows(UnsupportedOperationException.class,()->g.outputs().clear());}
    @Test void invalidOrUnboundedGoalsAreRejected() {assertThrows(RuntimeException.class,()->goal(-1));assertThrows(RuntimeException.class,()->goal(4097));assertThrows(RuntimeException.class,()->new SmeltingPlan.Goal(Set.of(),Set.of("raw"),1));assertThrows(RuntimeException.class,()->SmeltingPlan.desired(Collections.nCopies(65,goal(1))));}
    @Test void ordinaryFurnaceReceivesItsActualTenSecondRecipeBudget() {assertEquals(13000,SmeltingPlan.cookMillis(200,1200));}
    @Test void smokerKeepsItsExistingEightSecondConversionLimit() {assertEquals(CookingExchange.COOK_MS,SmeltingPlan.cookMillis(100,120));assertThrows(RuntimeException.class,()->SmeltingPlan.cookMillis(121,120));}
    @Test void invalidOrExcessiveCookingTimesCannotCreateUnboundedWaits() {assertEquals(63000,SmeltingPlan.cookMillis(1200,1200));assertThrows(RuntimeException.class,()->SmeltingPlan.cookMillis(0,1200));assertThrows(RuntimeException.class,()->SmeltingPlan.cookMillis(1201,1200));}
    @Test void fuelMustLastForTheWholeCapturedRecipe() {assertFalse(SmeltingPlan.fuel(100,200,false,true,false));assertTrue(SmeltingPlan.fuel(300,200,false,true,false));}
    @Test void remainderFuelAndCustomizedOrProtectedStacksAreExcluded() {assertFalse(SmeltingPlan.fuel(20000,200,true,true,false));assertFalse(SmeltingPlan.fuel(1600,200,false,false,false));assertFalse(SmeltingPlan.fuel(1600,200,false,true,true));}
    @Test void aSharedInputAndFuelStackNeedsTwoUnreservedUnits() {assertFalse(SmeltingPlan.available(Map.of(0,1),0,0));assertTrue(SmeltingPlan.available(Map.of(0,2),0,0));}
    @Test void separateSlotsEachNeedAnAvailableUnit() {assertTrue(SmeltingPlan.available(Map.of(0,1,1,1),0,1));assertFalse(SmeltingPlan.available(Map.of(0,1,1,0),0,1));}
    @Test void fuelCannotBorrowAReservedRawUnitFromAnotherSlot() {assertFalse(SmeltingPlan.available(Map.of(0,0,1,64),0,1));assertFalse(SmeltingPlan.available(Map.of(0,64),0,1));}
}
