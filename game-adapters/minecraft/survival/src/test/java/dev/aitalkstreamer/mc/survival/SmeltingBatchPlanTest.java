package dev.aitalkstreamer.mc.survival;

import java.util.*;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class SmeltingBatchPlanTest {
    int limit(int raw,int missing,int output,int stack,int burn,int ticks,int cap) {
        return SmeltingPlan.batchLimit(raw,missing,output,stack,burn,ticks,1200,cap);
    }
    @Test void ordinaryFurnaceAndBlastUseBoundedWholeBatchBudgets() {
        assertEquals(47500,SmeltingPlan.batchMillis(200,4,1200));
        assertEquals(27500,SmeltingPlan.batchMillis(100,4,1200));
        assertEquals(13000,SmeltingPlan.batchMillis(200,1,1200));
    }
    @Test void outputShortfallUsesActualRecipeYieldIncludingTheFinalPartialGoal() {
        assertEquals(2,limit(64,5,3,64,1600,200,4));
        assertEquals(1,limit(64,1,3,64,1600,200,4));
        assertEquals(0,limit(64,0,3,64,1600,200,4));
    }
    @Test void outputStackCapacityLimitsARecipeProducingSeveralItems() {
        assertEquals(2,limit(64,100,3,8,1600,200,4));
        assertEquals(1,limit(64,100,33,64,1600,200,4));
    }
    @Test void oneFuelMustCoverTheEntireBatchAndWeakFuelCannotBePromoted() {
        assertEquals(1,limit(64,64,1,64,300,200,4));
        assertEquals(3,limit(64,64,1,64,600,200,4));
        assertEquals(0,limit(64,64,1,64,199,200,4));
    }
    @Test void availableRawAndSmokerCapAreIndependentLimits() {
        assertEquals(2,limit(2,64,1,64,1600,200,4));
        assertEquals(0,limit(0,64,1,64,1600,200,4));
        assertEquals(1,limit(64,64,1,64,800,100,1));
    }
    @Test void slowDataPackRecipesCannotExtendTheExistingAbsoluteBudget() {
        assertEquals(1,limit(64,64,1,64,20000,1200,4));
        assertEquals(63000,SmeltingPlan.batchMillis(1200,1,1200));
        assertThrows(RuntimeException.class,()->SmeltingPlan.batchMillis(1200,2,1200));
    }
    @Test void invalidCountsAndOverflowingRecipeLimitsAreRejected() {
        assertThrows(RuntimeException.class,()->limit(64,64,0,64,1600,200,4));
        assertThrows(RuntimeException.class,()->limit(64,64,65,64,1600,200,4));
        assertThrows(RuntimeException.class,()->limit(64,64,1,64,1600,200,5));
        assertThrows(RuntimeException.class,()->SmeltingPlan.batchMillis(200,0,1200));
    }
    ResourceMaterialsPlan.Stock stock(int slot,String item,int count) {return new ResourceMaterialsPlan.Stock(slot,item,count);}
    @Test void aSharedRawAndFuelStackNeedsEveryRawUnitPlusTheFuelUnit() {
        assertEquals(-1,ResourceMaterialsPlan.conversionFuel(List.of(stock(0,"wood",4)),Map.of(),0,4,Set.of(0)));
        assertEquals(0,ResourceMaterialsPlan.conversionFuel(List.of(stock(0,"wood",5)),Map.of(),0,4,Set.of(0)));
    }
    @Test void retainedOutputCanMoveWhileCountedRawAndFuelShareTheirExactSlots() {
        var stock=List.of(stock(0,"wood",4),stock(1,"wood",2));
        assertEquals(1,ResourceMaterialsPlan.conversionFuel(stock,Map.of("wood",1),0,4,Set.of(0,1)));
        assertEquals(-1,ResourceMaterialsPlan.conversionFuel(stock,Map.of("wood",2),0,4,Set.of(0,1)));
    }
    @Test void fuelSelectionCannotSpendAProtectedComponentOutsideItsCandidates() {
        var stock=List.of(stock(0,"raw",4),stock(1,"coal",1),stock(2,"coal",8));
        assertEquals(-1,ResourceMaterialsPlan.conversionFuel(stock,Map.of("coal",9),0,4,Set.of(1)));
        assertEquals(1,ResourceMaterialsPlan.conversionFuel(stock,Map.of("coal",8),0,4,Set.of(1)));
        assertEquals(-1,ResourceMaterialsPlan.conversionFuel(stock,Map.of(),0,4,Set.of()));
    }
    @Test void countedAllocationMatchesAnIndependentSmallStockEnumeration() {
        for(int a=0;a<=6;a++)for(int b=0;b<=6;b++)for(int keep=0;keep<=8;keep++)for(int n=1;n<=4;n++)for(int mask=0;mask<4;mask++) {
            var fuels=new HashSet<Integer>();if((mask&1)!=0)fuels.add(0);if((mask&2)!=0)fuels.add(1);
            int retained=Math.min(keep,a+b);boolean feasible=false;
            for(int fuel:fuels) {
                int leftA=a-n-(fuel==0?1:0),leftB=b-(fuel==1?1:0);
                if(leftA>=0 && leftB>=0 && leftA+leftB>=retained)feasible=true;
            }
            int selected=ResourceMaterialsPlan.conversionFuel(List.of(stock(0,"wood",a),stock(1,"wood",b)),Map.of("wood",keep),0,n,fuels);
            assertEquals(feasible,selected>=0,List.of(a,b,keep,n,mask).toString());
            if(selected>=0)assertTrue(fuels.contains(selected));
        }
    }
}
