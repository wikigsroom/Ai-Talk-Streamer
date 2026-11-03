package dev.aitalkstreamer.mc.survival;

import adris.altoclef.tasksystem.*;
import org.junit.jupiter.api.Test;
import java.lang.reflect.*;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

/** Executes the actual prepared Task's interruption decision; no game or debug tick is initialized. */
class TaskForceContinuityTest {
    static class Plain extends Task {protected void onStart(){}protected Task onTick(){return null;}protected void onStop(Task t){}protected boolean isEqual(Task t){return t==this;}protected String toDebugString(){return "fixture";}}
    static class Forced extends Plain implements ITaskCanForce {boolean force=true;Task observed;public boolean shouldForce(Task next){observed=next;return force;}}
    void child(Task parent,Task next)throws Exception{var f=Task.class.getDeclaredField("sub");f.setAccessible(true);f.set(parent,next);}
    boolean admits(Task sub,Task next)throws Exception{var m=Task.class.getDeclaredMethod("canBeInterrupted",Task.class,Task.class);m.setAccessible(true);return (boolean)m.invoke(new Plain(),sub,next);}
    @Test void noChildCanBeReplaced()throws Exception{assertTrue(admits(null,new Plain()));}
    @Test void aPlainChildCanBeReplaced()throws Exception{assertTrue(admits(new Plain(),new Plain()));}
    @Test void aForcingChildCannotBeReplaced()throws Exception{assertFalse(admits(new Forced(),new Plain()));}
    @Test void aPlainAncestorDoesNotEraseAForcingDescendant()throws Exception{var p=new Plain();child(p,new Forced());assertFalse(admits(p,new Plain()));}
    @Test void severalPlainAncestorsStillRespectTheDeepestForcedChild()throws Exception{var a=new Plain();var b=new Plain();child(a,b);child(b,new Forced());assertFalse(admits(a,null));}
    @Test void eachForcingTaskReceivesTheActualCandidate()throws Exception{var f=new Forced();var next=new Plain();assertFalse(admits(f,next));assertSame(next,f.observed);}
    @Test void aNonForcingIntermediateCannotOverrideAnotherForce()throws Exception{var a=new Forced();a.force=false;child(a,new Forced());assertFalse(admits(a,new Plain()));}
    @Test void releasingTheForceAllowsLaterInterruption()throws Exception{var f=new Forced();assertFalse(admits(f,null));f.force=false;assertTrue(admits(f,null));}
    @Test void materialCycleUsesTheActualPreparedTasksAncestorPath()throws Exception {
        var ancestor=new Plain();var descendant=new Plain();child(ancestor,descendant);
        var plan=new ResourceAcquisitionPlan();var source=new ResourceAcquisitionPlan.Source(ResourceAcquisitionPlan.Kind.ITEM,"oak",Set.of("oak"));
        plan.begin(ancestor,source,List.of(),List.of(),a->false);
        assertTrue(plan.choose(descendant,List.of(source),List.of(),a->((Task)a).thisOrChildSatisfies(t->t==descendant)).blockedByCycle());
    }
    @Test void anActualUnrelatedPreparedTaskDoesNotBlockMaterialChoice()throws Exception {
        var ancestor=new Plain();child(ancestor,new Plain());var other=new Plain();
        var plan=new ResourceAcquisitionPlan();var source=new ResourceAcquisitionPlan.Source(ResourceAcquisitionPlan.Kind.ITEM,"oak",Set.of("oak"));
        plan.begin(ancestor,source,List.of(),List.of(),a->false);
        assertEquals(source,plan.choose(other,List.of(source),List.of(),a->((Task)a).thisOrChildSatisfies(t->t==other)).source());
    }
    @Test void inventoryProgressAllowsARevisitOnTheActualAncestorPath()throws Exception {
        var ancestor=new Plain();var descendant=new Plain();child(ancestor,descendant);
        var plan=new ResourceAcquisitionPlan();var source=new ResourceAcquisitionPlan.Source(ResourceAcquisitionPlan.Kind.ITEM,"oak",Set.of("oak"));
        plan.begin(ancestor,source,List.of(),List.of(),a->false);
        assertEquals(source,plan.choose(descendant,List.of(source),List.of(new ResourceMaterialsPlan.Stock(0,"pickaxe",1)),a->((Task)a).thisOrChildSatisfies(t->t==descendant)).source());
    }
}
