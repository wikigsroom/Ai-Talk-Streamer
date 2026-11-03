package dev.aitalkstreamer.mc.neoforge;

import org.junit.jupiter.api.Test;
import java.util.*;
import static dev.aitalkstreamer.mc.neoforge.NativeCraftPlan.*;
import static org.junit.jupiter.api.Assertions.*;

class NativeCraftPlanTest {
    List<Integer> stock(int... counts) { var result = new ArrayList<>(Collections.nCopies(36, 0)); for (int i=0;i<counts.length;i++) result.set(i,counts[i]); return result; }
    Ingredient ingredient(Integer... slots) { return new Ingredient(false, Set.of(slots)); }
    Recipe recipe(int per, Ingredient... ingredients) { return new Recipe("test:recipe",false,0,0,per,List.of(ingredients)); }
    @Test void overlappingIngredientsReserveScarceStacksByResidualReassignment() {
        var p=allocate(recipe(1,ingredient(0,1),ingredient(0)),stock(1,1),"minecraft:stick",0,1);
        assertNotNull(p);assertEquals(List.of(new Allocation(0,1,1),new Allocation(1,0,1)),p.allocations());
    }
    @Test void requestedUnitsRoundUpToRecipeBatches() {
        var p=allocate(recipe(4,ingredient(0)),stock(2),"minecraft:birch_planks",5,5);
        assertEquals(2,p.target().batches());assertEquals(13,p.target().targetTotal());assertEquals(2,p.allocations().getFirst().count());
    }
    @Test void insufficientMaterialsDoNotReturnAPartialAllocation() { assertNull(allocate(recipe(1,ingredient(0),ingredient(0)),stock(1),"minecraft:stick",0,1)); }
    @Test void differentComponentSlotsRemainSeparateAllocations() {
        var p=allocate(recipe(1,ingredient(0,1)),stock(1,2),"minecraft:stick",0,3);
        assertEquals(List.of(new Allocation(0,0,1),new Allocation(0,1,2)),p.allocations());
    }
    @Test void emptyShapedCellsPreserveTheirActualGridPositions() {
        var r=new Recipe("test:shaped",true,1,3,1,List.of(ingredient(0),new Ingredient(true,Set.of()),ingredient(0)));
        var p=allocate(r,stock(2),"minecraft:stick",0,1);assertEquals(3,r.gridSize());assertEquals(List.of(0,3,6),p.positions());
    }
    @Test void twoByTwoShapeUsesPlayerInventoryGrid() {
        var r=new Recipe("test:square",true,2,2,1,Collections.nCopies(4,ingredient(0)));
        assertEquals(2,r.gridSize());assertEquals(List.of(0,1,2,3),allocate(r,stock(4),"minecraft:crafting_table",0,1).positions());
    }
    @Test void fiveShapelessIngredientsRequireAWorkstation() { assertEquals(3,recipe(1,Collections.nCopies(5,ingredient(0)).toArray(Ingredient[]::new)).gridSize()); }
    @Test void ambiguousCraftableRecipesAreRejectedBeforeAnyClicks() {
        var p=allocate(recipe(1,ingredient(0)),stock(1),"minecraft:stick",0,1);
        assertThrows(RuntimeException.class,()->unique(List.of(p,p)));assertSame(p,unique(List.of(p)));
    }
    @Test void plannedAllocationsRemainImmutableAndBounded() {
        var p=allocate(recipe(1,ingredient(0)),stock(1),"minecraft:stick",0,1);
        assertThrows(UnsupportedOperationException.class,()->p.allocations().clear());
        assertThrows(RuntimeException.class,()->new Ingredient(false,Set.of(36)));
        assertThrows(RuntimeException.class,()->allocate(recipe(1,ingredient(0)),stock(100),"minecraft:stick",0,1));
    }
    @Test void remainingMaterialsExcludeAlreadyPlacedUnitsAndRejectNegativeProgress() {
        var p=allocate(recipe(1,ingredient(0),ingredient(0)),stock(6),"minecraft:stick",0,3);
        assertEquals(3,remaining(p,new int[]{1,2})[0]);assertThrows(RuntimeException.class,()->remaining(p,new int[]{-1,2}));
    }
    @Test void emptyOrMalformedRecipesCannotAuthorizeCrafting() {
        assertThrows(RuntimeException.class,()->new Recipe("test:x",true,2,2,1,List.of(ingredient(0))));
        assertThrows(RuntimeException.class,()->new Recipe("test:x",false,0,0,1,List.of(new Ingredient(true,Set.of()))));
    }
}
