package dev.aitalkstreamer.mc.survival;

import org.junit.jupiter.api.Test;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

class AlternativeMaterialConsumersTest {
    ResourceMaterialsPlan.Stock stock(int slot,String item,int count) {return new ResourceMaterialsPlan.Stock(slot,item,count);}
    MaterialTargets target(int count,String... items) {return new MaterialTargets(Map.of(Set.of(items),count));}
    @Test void smeltingCanBurnOneAlternativeWhenOtherStockKeepsTheGoal() {
        var stock=List.of(stock(0,"raw",4),stock(1,"coal",1),stock(2,"charcoal",5));
        assertEquals(1,ResourceMaterialsPlan.conversionFuel(stock,target(5,"coal","charcoal"),0,4,Set.of(1)));
    }
    @Test void oneItemCannotBeCountedAsBothRawAndFuel() {
        assertEquals(-1,ResourceMaterialsPlan.conversionFuel(List.of(stock(0,"wood",4)),target(1,"wood","plank"),0,3,Set.of(0)));
        assertEquals(0,ResourceMaterialsPlan.conversionFuel(List.of(stock(0,"wood",5)),target(1,"wood","plank"),0,3,Set.of(0)));
    }
    @Test void cookingAndEatingCannotConsumeTheLastAcceptableTarget() {
        var stock=List.of(stock(0,"beef",1),stock(1,"coal",2));var t=target(1,"beef","pork");
        assertTrue(ResourceMaterialsPlan.singleUnits(stock,t,Map.of("raw",Set.of(0),"fuel",Set.of(1))).isEmpty());
    }
    @Test void jointSingleUnitsMoveProtectionToAnotherAcceptableStack() {
        var stock=List.of(stock(0,"beef",1),stock(1,"pork",2),stock(2,"coal",1));
        assertEquals(Map.of("raw",0,"fuel",2),ResourceMaterialsPlan.singleUnits(stock,target(2,"beef","pork"),Map.of("raw",Set.of(0),"fuel",Set.of(2))));
    }
    @Test void buildingCountMaximizesAllCandidateStacksTogether() {
        var stock=List.of(stock(0,"oak",3),stock(1,"birch",3));var free=ResourceMaterialsPlan.usable(stock,target(4,"oak","birch"),Set.of(0,1));
        assertEquals(2,free.values().stream().mapToInt(Integer::intValue).sum());
    }
    @Test void wholeStackDisposalRequiresEnoughAlternativeStockElsewhere() {
        var stock=List.of(stock(0,"oak",2),stock(1,"birch",4));var t=target(4,"oak","birch");
        assertTrue(ResourceMaterialsPlan.removable(stock,t,0,2));assertFalse(ResourceMaterialsPlan.removable(stock,t,1,4));
    }
    @Test void cursorAndOffhandCannotBypassAnIncompleteAlternativeGoal() {
        assertEquals(0,ResourceMaterialsPlan.externalUsable(List.of(stock(0,"birch",2)),target(5,"oak","birch"),"oak",2));
        assertEquals(2,ResourceMaterialsPlan.externalUsable(List.of(stock(0,"birch",5)),target(5,"oak","birch"),"oak",2));
    }
    @Test void acquisitionRequestsOnlyTheActualSharedShortage() {
        var stock=List.of(stock(0,"oak",3),stock(1,"birch",3));
        var plan=ResourceMaterialsPlan.materials(Set.of("oak","birch"),3,stock,target(4,"oak","birch"));
        assertFalse(plan.complete());assertEquals(1,plan.requests().getFirst().missing());assertEquals(7,plan.requests().getFirst().targetMatching());
    }
    @Test void cataloguePreparationRetainsItsOwnOutputAlongsideAlternativeAncestors() {
        var stock=List.of(stock(0,"oak",3),stock(1,"birch",3));
        var goal=new ResourceMaterialsPlan.Goal("oak",3,3,1,List.of(Set.of("birch")));
        assertTrue(ResourceMaterialsPlan.prepare(List.of(goal),stock,target(4,"oak","birch")).complete());
        assertEquals(0,ResourceMaterialsPlan.available(stock,target(4,"oak","birch").merge(MaterialTargets.from(Map.of("oak",3,"birch",3)))).values().stream().mapToInt(Integer::intValue).sum());
    }
    @Test void actualRecipePlanCanChooseIngredientsWhilePreservingAlternativeOutputs() {
        var stock=List.of(stock(0,"oak",2),stock(1,"birch",3));var supplies=stock.stream().map(s->new CraftPlan.Supply(s.slot(),s.count())).toList();
        var recipe=new CraftPlan.Recipe("stick",false,0,0,4,List.of(new CraftPlan.Ingredient(false,Set.of(0,1)),new CraftPlan.Ingredient(false,Set.of(0,1))));
        var plan=ResourceRecipePlan.select(List.of(recipe),recipe,supplies,"stick",0,4,List.of(),target(3,"oak","birch").limits(stock));
        assertEquals(2,plan.allocation().stream().mapToInt(CraftPlan.Allocation::count).sum());
        assertThrows(RuntimeException.class,()->ResourceRecipePlan.select(List.of(recipe),recipe,supplies,"stick",0,4,List.of(),target(4,"oak","birch").limits(stock)));
    }
}
