package dev.aitalkstreamer.mc.survival;

import adris.altoclef.tasksystem.*;
import dev.aitalkstreamer.mc.core.Json.Rejected;
import dev.aitalkstreamer.mc.core.LocalTaskFailure;
import org.junit.jupiter.api.Test;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

/** Executes the actual prepared Task.tick and stop boundary without initializing a Minecraft client. */
class TaskChildFailureTest {
    static class Plain extends Task {
        Task next;RuntimeException failure;Error fatal;int ticks,stops;
        protected void onStart(){}protected Task onTick(){ticks++;if(failure!=null)throw failure;if(fatal!=null)throw fatal;return next;}
        protected void onStop(Task t){stops++;}protected boolean isEqual(Task t){return t==this;}protected String toDebugString(){return "fixture";}
    }
    static class Recovering extends Plain {
        boolean accept=true,stop=true;RuntimeException cleanup;int handled;Task failed;
        protected boolean onChildFailure(Task child,Rejected reason) {
            handled++;failed=child;if(cleanup!=null)throw cleanup;if(!accept)return false;if(stop)child.stop();next=null;return true;
        }
    }
    static class Chain extends TaskChain {
        Chain(){super(new TaskRunner(null));}protected void onTick(){}protected void onStop(){}public void onInterrupt(TaskChain c){}
        public float getPriority(){return 1;}public boolean isActive(){return true;}public String getName(){return "fixture";}
    }
    final Rejected rejected=new Rejected("GAME_RESOURCE_MATERIAL_UNAVAILABLE");
    void running(Task task,Task sub)throws Exception {
        for(var pair:Map.of("first",false,"active",true,"stopped",false).entrySet()){var f=Task.class.getDeclaredField(pair.getKey());f.setAccessible(true);f.setBoolean(task,pair.getValue());}
        var f=Task.class.getDeclaredField("sub");f.setAccessible(true);f.set(task,sub);
    }
    Plain leaf(RuntimeException failure)throws Exception {var p=new Plain();p.failure=failure;running(p,null);return p;}
    <T extends Plain> T parent(T p,Task sub)throws Exception {p.next=sub;running(p,sub);return p;}
    @Test void defaultBoundaryPreservesTheOriginalPlanningFailure()throws Exception {
        var p=parent(new Plain(),leaf(rejected));assertSame(rejected,assertThrows(Rejected.class,()->p.tick(new Chain())));
    }
    @Test void handledFailureStopsAndDetachesOnlyItsFailedChild()throws Exception {
        var child=leaf(rejected);var p=parent(new Recovering(),child);p.tick(new Chain());
        assertEquals(1,p.handled);assertEquals(1,child.stops);assertTrue(child.stopped());assertTrue(p.isActive());assertEquals(0,p.stops);
        assertFalse(p.thisOrChildSatisfies(t->t==child));
    }
    @Test void aDecliningIntermediateAllowsTheOuterCollectorToRecover()throws Exception {
        var child=leaf(rejected);var inner=parent(new Recovering(),child);inner.accept=false;var outer=parent(new Recovering(),inner);
        outer.tick(new Chain());assertEquals(1,inner.handled);assertEquals(1,outer.handled);assertSame(inner,outer.failed);assertTrue(inner.stopped());assertTrue(child.stopped());
    }
    @Test void theNearestAcceptingBoundaryHandlesTheFailureOnce()throws Exception {
        var inner=parent(new Recovering(),leaf(rejected));var outer=parent(new Recovering(),inner);outer.tick(new Chain());
        assertEquals(1,inner.handled);assertEquals(0,outer.handled);assertTrue(inner.isActive());
    }
    @Test void cleanupFailureEndsRecoveryAndRetainsTheOriginalCause()throws Exception {
        var p=parent(new Recovering(),leaf(rejected));p.cleanup=new IllegalStateException("cleanup failed");
        assertSame(p.cleanup,assertThrows(IllegalStateException.class,()->p.tick(new Chain())));assertEquals(List.of(rejected),Arrays.asList(p.cleanup.getSuppressed()));
    }
    @Test void claimingRecoveryWithoutStoppingTheChildIsRejected()throws Exception {
        var p=parent(new Recovering(),leaf(rejected));p.stop=false;
        var error=assertThrows(Rejected.class,()->p.tick(new Chain()));assertEquals("GAME_RESOURCE_MATERIAL_CONTEXT_CHANGED",error.code);assertSame(rejected,error.getSuppressed()[0]);
    }
    @Test void arbitraryExceptionsAreNeverInterpretedThroughTheirCauses()throws Exception {
        var error=new IllegalStateException("wrapped",rejected);var p=parent(new Recovering(),leaf(error));
        assertSame(error,assertThrows(IllegalStateException.class,()->p.tick(new Chain())));assertEquals(0,p.handled);
    }
    @Test void serverTransactionFailuresBypassThePlanningRecoveryBoundary()throws Exception {
        var error=new LocalTaskFailure(LocalTaskFailure.Reason.CRAFT_SERVER_DIVERGED);var p=parent(new Recovering(),leaf(error));
        assertSame(error,assertThrows(LocalTaskFailure.class,()->p.tick(new Chain())));assertEquals(0,p.handled);
    }
    @Test void fatalErrorsBypassThePlanningRecoveryBoundary()throws Exception {
        var child=leaf(null);child.fatal=new AssertionError("fatal");var p=parent(new Recovering(),child);
        assertSame(child.fatal,assertThrows(AssertionError.class,()->p.tick(new Chain())));assertEquals(0,p.handled);
    }
    @Test void anOwnersOwnPlanningFailureBelongsToItsParentBoundary()throws Exception {
        var p=parent(new Recovering(),leaf(null));p.failure=rejected;
        assertSame(rejected,assertThrows(Rejected.class,()->p.tick(new Chain())));assertEquals(0,p.handled);
    }
    @Test void nextTickContinuesTheSameParentWithANewBranch()throws Exception {
        var p=parent(new Recovering(),leaf(rejected));p.tick(new Chain());var next=leaf(null);p.next=next;p.tick(new Chain());
        assertEquals(2,p.ticks);assertEquals(1,next.ticks);assertTrue(p.isActive());assertEquals(0,p.stops);assertTrue(p.thisOrChildSatisfies(t->t==next));
    }
    @Test void failedWrapperStopsItsWholeSubtreeWithoutStoppingTheOwner()throws Exception {
        var deep=leaf(rejected);var wrapper=parent(new Plain(),deep);var p=parent(new Recovering(),wrapper);p.tick(new Chain());
        assertEquals(1,wrapper.stops);assertEquals(1,deep.stops);assertEquals(0,p.stops);assertFalse(p.thisOrChildSatisfies(t->t==wrapper||t==deep));
    }
}
