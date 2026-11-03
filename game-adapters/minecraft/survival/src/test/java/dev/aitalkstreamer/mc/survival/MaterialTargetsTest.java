package dev.aitalkstreamer.mc.survival;

import org.junit.jupiter.api.Test;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

class MaterialTargetsTest {
    ResourceMaterialsPlan.Stock stock(int slot,String item,int count) {return new ResourceMaterialsPlan.Stock(slot,item,count);}
    MaterialTargets target(Set<String> items,int count) {return new MaterialTargets(Map.of(items,count));}
    @Test void alternativesRemainOneAbsoluteQuantityInsteadOfOneTargetPerItem() {
        var r=SmeltingPlan.desired(List.of(new SmeltingPlan.Goal(Set.of("coal","charcoal"),Set.of("log"),5)));
        assertEquals(Map.of(Set.of("coal","charcoal"),5),r.goals());
    }
    @Test void equalAlternativeGroupsMergeByMaximum() {
        assertEquals(target(Set.of("a","b"),4),target(Set.of("a","b"),2).merge(target(Set.of("b","a"),4)));
    }
    @Test void intersectingGroupsKeepBothAbsoluteConditions() {
        var r=target(Set.of("a","b"),3).merge(target(Set.of("b","c"),4));assertEquals(2,r.goals().size());
        assertEquals(2,r.limits(List.of(stock(0,"b",5))).size());
    }
    @Test void singletonAndAlternativeGoalsCoexist() {
        var r=target(Set.of("a","b"),4).merge(MaterialTargets.from(Map.of("a",2)));
        assertEquals(2,r.goals().size());assertFalse(ResourceMaterialsPlan.removable(List.of(stock(0,"a",2),stock(1,"b",5)),r,0,1));
    }
    @Test void missingFutureStockDoesNotCreateAnImpossibleHold() {
        var r=target(Set.of("a","b"),9);assertTrue(r.limits(List.of()).isEmpty());
        assertEquals(0,r.limits(List.of(stock(0,"b",2))).getFirst().maximum());
    }
    @Test void existingTargetsKeepOnlyTheirCombinedQuantity() {
        var r=target(Set.of("a","b"),4);assertEquals(2,r.limits(List.of(stock(0,"a",3),stock(1,"b",3))).getFirst().maximum());
    }
    @Test void callerMutationCannotChangeGroupMembershipOrTargets() {
        var group=new HashSet<>(Set.of("a","b"));var input=new HashMap<Set<String>,Integer>();input.put(group,3);
        var r=new MaterialTargets(input);group.add("c");input.clear();assertEquals(target(Set.of("a","b"),3),r);
        assertThrows(UnsupportedOperationException.class,()->r.goals().clear());
        assertThrows(UnsupportedOperationException.class,()->r.goals().keySet().iterator().next().clear());
    }
    @Test void invalidEmptyNegativeAndOversizedGroupsAreRejected() {
        assertThrows(RuntimeException.class,()->target(Set.of(),1));assertThrows(RuntimeException.class,()->target(Set.of("a"),-1));
        var items=new HashSet<String>();for(int i=0;i<257;i++)items.add("i"+i);assertThrows(RuntimeException.class,()->target(items,1));
    }
    @Test void reservationFramesReleaseOnlyTheirOwnAlternativeConditions() {
        var r=new MaterialReservations();var a=new Object();r.enter(a,target(Set.of("a","b"),3));r.enter(new Object(),MaterialTargets.from(Map.of("b",1)));
        r.leave(a);assertEquals(MaterialTargets.from(Map.of("b",1)),r.desired());
    }
    @Test void changedAlternativeMembershipCannotReplaceAnActiveFrame() {
        var r=new MaterialReservations();var a=new Object();r.enter(a,target(Set.of("a","b"),3));
        assertThrows(RuntimeException.class,()->r.enter(a,target(Set.of("a","c"),3)));assertEquals(target(Set.of("a","b"),3),r.desired());
    }
    @Test void externalCursorCountsAgainstEveryIntersectingCondition() {
        var r=target(Set.of("a","b"),4).merge(target(Set.of("b","c"),5));
        assertEquals(1,r.externalUsable(List.of(stock(0,"a",4),stock(1,"c",3)),"b",3));
    }
    @Test void alternativeInventoryAndCompletionUseTheSameQuantityMeaning() {
        var goal=new SmeltingPlan.Goal(Set.of("a","b"),Set.of("raw"),5);var inventory=List.of(stock(0,"a",2),stock(1,"b",4));
        assertEquals(0,SmeltingPlan.missing(goal,inventory));assertEquals(1,ResourceMaterialsPlan.usable(inventory,SmeltingPlan.desired(List.of(goal)),Set.of(0,1)).values().stream().mapToInt(Integer::intValue).sum());
    }
}
