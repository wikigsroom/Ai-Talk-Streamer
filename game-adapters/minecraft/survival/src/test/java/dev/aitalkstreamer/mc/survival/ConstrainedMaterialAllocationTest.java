package dev.aitalkstreamer.mc.survival;

import org.junit.jupiter.api.Test;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

class ConstrainedMaterialAllocationTest {
    MaterialAllocation.Need need(String key,int n,Integer... slots) {return new MaterialAllocation.Need(key,n,Set.of(slots),false);}
    MaterialAllocation.Limit limit(int maximum,Integer... slots) {return new MaterialAllocation.Limit(Set.of(slots),maximum);}
    List<CraftPlan.Supply> stock(int... counts) {var r=new ArrayList<CraftPlan.Supply>();for(int i=0;i<counts.length;i++)r.add(new CraftPlan.Supply(i,counts[i]));return r;}
    int units(MaterialAllocation.Result r) {return r.assignments().stream().mapToInt(MaterialAllocation.Assigned::count).sum();}
    @Test void oneAlternativeTargetDoesNotReserveEveryCandidate() {
        assertTrue(MaterialAllocation.constrained(stock(3,3),List.of(need("fuel",2,0,1)),List.of(limit(2,0,1))).complete());
    }
    @Test void theSameRetainedItemMaySatisfyTwoOverlappingAbsoluteTargets() {
        assertTrue(MaterialAllocation.constrained(stock(0,2,0),List.of(need("one",1,1)),List.of(limit(1,0,1),limit(1,1,2))).complete());
    }
    @Test void singletonNestedAndDisjointLimitsAllApplyTogether() {
        var r=MaterialAllocation.constrained(stock(4,4,3),List.of(need("all",11,0,1,2)),List.of(limit(2,0),limit(3,0,1),limit(1,2)));
        assertEquals(4,units(r));assertEquals(7,r.missing().get("all"));
    }
    @Test void crossingConditionsSearchForTheJointMaximum() {
        var r=MaterialAllocation.constrained(stock(3,3,3),List.of(need("all",9,0,1,2)),List.of(limit(2,0,1),limit(2,1,2)));
        assertEquals(4,units(r));assertFalse(r.complete());
    }
    @Test void crossingTriangleKeepsIntegerQuantities() {
        var r=MaterialAllocation.constrained(stock(2,2,2),List.of(need("all",6,0,1,2)),List.of(limit(1,0,1),limit(1,1,2),limit(1,0,2)));
        assertEquals(1,units(r));
    }
    @Test void exactIngredientNeedsStillSharePhysicalStackCapacity() {
        var r=MaterialAllocation.constrained(stock(2),List.of(need("raw",2,0),need("fuel",1,0)),List.of(limit(2,0)));
        assertFalse(r.complete());assertEquals(2,units(r));
    }
    @Test void emptyAndUnstockedLimitsCannotCreateNewSupply() {
        var r=MaterialAllocation.constrained(stock(0,1),List.of(need("none",1,0)),List.of(limit(0),limit(0,2)));
        assertFalse(r.complete());assertEquals(0,units(r));
    }
    @Test void malformedRequirementsAndBoundsAreRejected() {
        assertThrows(RuntimeException.class,()->MaterialAllocation.constrained(stock(1),List.of(need("x",1,0),need("x",1,0)),List.of()));
        assertThrows(RuntimeException.class,()->limit(-1,0));assertThrows(RuntimeException.class,()->limit(0,36));
    }
    @Test void resultsDoNotDependOnCallerInventoryAndLimitOrder() {
        var needs=List.of(need("a",2,0,1),need("b",2,1,2));var limits=List.of(limit(2,0,1),limit(2,1,2));
        var a=MaterialAllocation.constrained(stock(3,3,3),needs,limits);var reversed=new ArrayList<>(stock(3,3,3));Collections.reverse(reversed);
        var other=new ArrayList<>(limits);Collections.reverse(other);assertEquals(a,MaterialAllocation.constrained(reversed,needs,other));
    }
    @Test void independentEnumeratedAssignmentsAgreeWithJointSolver() {
        var random=new Random(855014);int checked=0;
        for(int i=0;i<1200;i++) {
            int[] counts={random.nextInt(3),random.nextInt(3),random.nextInt(3)};int[] demand={random.nextInt(4),random.nextInt(4)};
            boolean[][] match=new boolean[2][3];var needs=new ArrayList<MaterialAllocation.Need>();
            for(int n=0;n<2;n++) {var slots=new HashSet<Integer>();for(int s=0;s<3;s++)if(match[n][s]=random.nextBoolean())slots.add(s);needs.add(new MaterialAllocation.Need("n"+n,demand[n],slots,false));}
            var limits=List.of(limit(random.nextInt(5),0,1),limit(random.nextInt(5),1,2),limit(random.nextInt(5),0,2));
            var r=MaterialAllocation.constrained(stock(counts),needs,limits);int expected=oracle(counts,demand,match,limits,0,new int[3]);
            assertEquals(expected,units(r),"scenario "+i);assertEquals(expected==demand[0]+demand[1],r.complete());checked++;
        }
        assertEquals(1200,checked);
    }
    // Exhaustively assign each demanded unit to an eligible remaining slot or leave it missing.
    int oracle(int[] remaining,int[] demand,boolean[][] match,List<MaterialAllocation.Limit> limits,int n,int[] used) {
        if(n==demand[0]+demand[1]) {
            for(var limit:limits) {int count=0;for(int slot:limit.slots())count+=used[slot];if(count>limit.maximum())return -1;}
            return Arrays.stream(used).sum();
        }
        int kind=n<demand[0]?0:1,best=oracle(remaining,demand,match,limits,n+1,used);
        for(int s=0;s<3;s++)if(match[kind][s] && remaining[s]>0) {remaining[s]--;used[s]++;best=Math.max(best,oracle(remaining,demand,match,limits,n+1,used));used[s]--;remaining[s]++;}
        return best;
    }
}
