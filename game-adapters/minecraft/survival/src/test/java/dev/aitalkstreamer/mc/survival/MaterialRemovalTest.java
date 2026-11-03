package dev.aitalkstreamer.mc.survival;

import java.util.*;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class MaterialRemovalTest {
    ResourceMaterialsPlan.Stock stock(int slot,String item,int count) {return new ResourceMaterialsPlan.Stock(slot,item,count);}
    boolean remove(List<ResourceMaterialsPlan.Stock> stock,Map<String,Integer> desired,int slot,int count) {return ResourceMaterialsPlan.removable(stock,desired,slot,count);}
    @Test void aWholeStackContainingSomeRetainedUnitsCannotBeDiscarded() {
        var stock=List.of(stock(0,"wood",5));assertFalse(remove(stock,Map.of("wood",2),0,5));assertTrue(remove(stock,Map.of("wood",2),0,3));
    }
    @Test void aTargetBelowItsRequestedQuantityRetainsEveryExistingUnit() {
        assertFalse(remove(List.of(stock(0,"wood",2)),Map.of("wood",5),0,1));
    }
    @Test void retainedUnitsCanMoveToAnotherEqualItemStackBeforeAWholeStackIsRemoved() {
        var stock=List.of(stock(0,"wood",3),stock(1,"wood",2));assertTrue(remove(stock,Map.of("wood",2),0,3));assertFalse(remove(stock,Map.of("wood",3),0,3));
    }
    @Test void anotherItemCannotSubstituteForTheReservedItem() {
        assertFalse(remove(List.of(stock(0,"wood",2),stock(1,"stone",64)),Map.of("wood",2),0,1));
    }
    @Test void aReadmittedDropMustRecheckNewerInventoryAndReservations() {
        var before=List.of(stock(0,"wood",3));assertTrue(remove(before,Map.of("wood",2),0,1));
        assertFalse(remove(List.of(stock(0,"wood",2)),Map.of("wood",2),0,1));assertFalse(remove(before,Map.of("wood",3),0,1));
    }
    @Test void cursorPickupDoesNotMakeItsRetainedUnitsDisappearFromTheDropDecision() {
        assertEquals(3,ResourceMaterialsPlan.externalUsable(List.of(),Map.of("wood",2),"wood",5));
        assertEquals(0,ResourceMaterialsPlan.externalUsable(List.of(),Map.of("wood",2),"wood",2));
    }
    @Test void offhandOrCursorCanBeUsedOnceTheMainInventoryAlreadyCoversTheTarget() {
        assertEquals(4,ResourceMaterialsPlan.externalUsable(List.of(stock(0,"wood",2)),Map.of("wood",2),"wood",4));
    }
    @Test void partlySatisfiedMainInventoryRetainsTheMissingQuantityOutsideIt() {
        assertEquals(2,ResourceMaterialsPlan.externalUsable(List.of(stock(0,"wood",1)),Map.of("wood",3),"wood",4));
        assertEquals(0,ResourceMaterialsPlan.externalUsable(List.of(stock(0,"wood",1)),Map.of("wood",8),"wood",4));
    }
    @Test void unrelatedTargetsDoNotRetainAnExternalStack() {
        assertEquals(4,ResourceMaterialsPlan.externalUsable(List.of(stock(0,"stone",5)),Map.of("stone",8),"wood",4));
    }
    @Test void invalidRemovalQuantitiesAndForeignMainSlotsAreRejected() {
        var stock=List.of(stock(0,"wood",5));
        assertThrows(RuntimeException.class,()->remove(stock,Map.of(),0,0));assertThrows(RuntimeException.class,()->remove(stock,Map.of(),0,100));
        assertThrows(RuntimeException.class,()->remove(stock,Map.of(),36,1));assertThrows(RuntimeException.class,()->ResourceMaterialsPlan.externalUsable(stock,Map.of(),"wood",100));
    }
    @Test void mainAndExternalRemovalMatchAnIndependentStockConservationEnumeration() {
        for(int a=0;a<=6;a++)for(int b=0;b<=6;b++)for(int keep=0;keep<=12;keep++)for(int n=1;n<=6;n++) {
            var stock=List.of(stock(0,"wood",a),stock(1,"wood",b));
            boolean expected=n<=a && a+b-n>=Math.min(keep,a+b);
            assertEquals(expected,remove(stock,Map.of("wood",keep),0,n));
            int safe=0;for(int removed=0;removed<=n;removed++)if(a+b+n-removed>=Math.min(keep,a+b+n))safe=removed;
            assertEquals(safe,ResourceMaterialsPlan.externalUsable(stock,Map.of("wood",keep),"wood",n));
        }
    }
}
