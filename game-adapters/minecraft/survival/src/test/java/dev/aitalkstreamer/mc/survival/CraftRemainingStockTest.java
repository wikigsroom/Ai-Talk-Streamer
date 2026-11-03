package dev.aitalkstreamer.mc.survival;

import dev.aitalkstreamer.mc.core.Json.Rejected;
import dev.aitalkstreamer.mc.core.InventoryTarget;
import org.junit.jupiter.api.Test;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

class CraftRemainingStockTest {
    CraftPlan.Plan plan(){return new CraftPlan.Plan("live:a",2,List.of(0,1),new InventoryTarget("minecraft:stick",0,2,1),List.of(new CraftPlan.Allocation(0,4,2),new CraftPlan.Allocation(1,4,2),new CraftPlan.Allocation(0,8,1)));}
    @Test void multipleIngredientsReserveTheirCombinedActualSourceCount(){var required=CraftPlan.remainingBySlot(plan(),new int[]{2,2,1});assertEquals(4,required[4]);assertEquals(1,required[8]);}
    @Test void confirmedBatchesOnlyReduceRemainingRequirements(){var required=CraftPlan.remainingBySlot(plan(),new int[]{1,0,1});assertEquals(1,required[4]);assertEquals(1,required[8]);}
    @Test void unrelatedInventorySlotsHaveNoArtificialCountRequirement(){var required=CraftPlan.remainingBySlot(plan(),new int[]{2,2,1});for(int i=0;i<36;i++)if(i!=4&&i!=8)assertEquals(0,required[i]);}
    @Test void aCompletedAllocationNeedsNoFormerMaterialToRemain(){assertEquals(0,Arrays.stream(CraftPlan.remainingBySlot(plan(),new int[]{0,0,0})).sum());}
    @Test void invalidRemainingCountersCannotExpandOrRewindAnAllocation(){assertThrows(Rejected.class,()->CraftPlan.remainingBySlot(plan(),new int[]{3,0,0}));assertThrows(Rejected.class,()->CraftPlan.remainingBySlot(plan(),new int[]{-1,0,0}));assertThrows(Rejected.class,()->CraftPlan.remainingBySlot(plan(),new int[]{0}));}
}
