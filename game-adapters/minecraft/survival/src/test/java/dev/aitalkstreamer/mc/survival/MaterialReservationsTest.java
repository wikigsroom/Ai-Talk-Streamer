package dev.aitalkstreamer.mc.survival;

import org.junit.jupiter.api.Test;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

class MaterialReservationsTest {
    @Test void ancestorsAndChildrenMergeAbsoluteTargetsByMaximum() {var r=new MaterialReservations();r.enter(new Object(),Map.of("oak",2));r.enter(new Object(),Map.of("oak",3,"stone",1));assertEquals(MaterialTargets.from(Map.of("oak",3,"stone",1)),r.desired());}
    @Test void taskIdentityIsUsedEvenIfTasksCompareEqual() {var r=new MaterialReservations();Object a=new String("same"),b=new String("same");r.enter(a,Map.of("oak",2));r.enter(b,Map.of("stone",1));r.leave(a);assertEquals(MaterialTargets.from(Map.of("stone",1)),r.desired());}
    @Test void reenteringTheSameFrameDoesNotDuplicateItsTargets() {var r=new MaterialReservations();var a=new Object();r.enter(a,Map.of("oak",2));r.enter(a,Map.of("oak",2));assertEquals(MaterialTargets.from(Map.of("oak",2)),r.desired());}
    @Test void changingAnActiveFrameIsRejectedWithoutReplacingItsOldTargets() {var r=new MaterialReservations();var a=new Object();r.enter(a,Map.of("oak",2));assertThrows(RuntimeException.class,()->r.enter(a,Map.of("oak",3)));assertEquals(MaterialTargets.from(Map.of("oak",2)),r.desired());}
    @Test void stoppingOneFrameKeepsTheOtherFrames() {var r=new MaterialReservations();var a=new Object();r.enter(a,Map.of("oak",2));r.enter(new Object(),Map.of("stone",1));r.leave(a);assertEquals(MaterialTargets.from(Map.of("stone",1)),r.desired());}
    @Test void repeatedReleaseIsStateOnlyAndIdempotent() {var r=new MaterialReservations();var a=new Object();r.enter(a,Map.of("oak",2));r.leave(a);r.leave(a);assertTrue(r.desired().goals().isEmpty());}
    @Test void activeFrameCountIsBounded() {var r=new MaterialReservations();for(int i=0;i<64;i++)r.enter(new Object(),Map.of("oak",1));assertThrows(RuntimeException.class,()->r.enter(new Object(),Map.of("oak",1)));}
    @Test void fullBoundedFrameTreeCanRetain4096DistinctOutputKinds() {var r=new MaterialReservations();for(int frame=0;frame<64;frame++){var values=new HashMap<String,Integer>();for(int item=0;item<64;item++)values.put("item"+frame+":"+item,1);r.enter(new Object(),values);}assertEquals(4096,r.desired().goals().size());assertThrows(RuntimeException.class,()->r.enter(new Object(),Map.of("extra",1)));}
    @Test void originalRootSelectionBudgetIsBounded() {var r=new MaterialReservations();for(int i=0;i<256;i++)r.select();assertThrows(RuntimeException.class,r::select);assertEquals(256,r.selections());}
    @Test void stoppingOrClearingFramesCannotResetTheOriginalSelectionBudget() {var r=new MaterialReservations();var a=new Object();r.enter(a,Map.of("oak",1));r.select();r.leave(a);r.enter(a,Map.of("oak",1));r.clear();assertEquals(1,r.selections());assertTrue(r.desired().goals().isEmpty());}
    @Test void callerMutationCannotChangeCapturedTargets() {var r=new MaterialReservations();var input=new HashMap<>(Map.of("oak",2));r.enter(new Object(),input);input.put("oak",99);assertEquals(MaterialTargets.from(Map.of("oak",2)),r.desired());assertThrows(UnsupportedOperationException.class,()->r.desired().goals().clear());}
    @Test void aFreshRootHasItsOwnEmptyFramesAndBudget() {var old=new MaterialReservations();old.enter(new Object(),Map.of("oak",1));old.select();old.clear();var fresh=new MaterialReservations();assertEquals(0,fresh.selections());assertTrue(fresh.desired().goals().isEmpty());}
}
