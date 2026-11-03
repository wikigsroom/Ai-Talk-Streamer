package dev.aitalkstreamer.mc.survival;

import adris.altoclef.tasksystem.Task;
import org.junit.jupiter.api.*;
import java.util.concurrent.atomic.AtomicBoolean;
import static org.junit.jupiter.api.Assertions.*;

/** Real task-tree membership and real root expiry, without constructing a Minecraft client. */
class FoodPreparationOwnershipTest {
    static class Plain extends Task {
        protected void onStart(){} protected Task onTick(){return null;} protected void onStop(Task t){}
        protected boolean isEqual(Task other){return other instanceof Plain;} protected String toDebugString(){return "fixture";}
    }
    final AtomicBoolean permitted=new AtomicBoolean(true);
    SurvivalAuthority.Session session;
    ControlledFoodCookingTask preparation;
    static void set(Class<?> type,Object target,String name,Object value)throws Exception {
        var f=type.getDeclaredField(name);f.setAccessible(true);f.set(target,value);
    }
    static void child(Task parent,Task child)throws Exception {set(Task.class,parent,"sub",child);}
    @BeforeEach void setup()throws Exception {
        session=SurvivalAuthority.open(new SurvivalAuthority.Context("task","controller","lease","world",1),new SurvivalAuthority.Boundary(){
            public boolean current(SurvivalAuthority.Context c){return permitted.get();}
            public void actuate(SurvivalAuthority.Context c,java.util.function.BooleanSupplier open,Runnable effect){throw new AssertionError("No game effects in topology checks");}
        });
        // Bypass only the game's constructor: the production within/busy methods and Task traversal are executed unchanged.
        var type=Class.forName("sun.misc.Unsafe");var field=type.getDeclaredField("theUnsafe");field.setAccessible(true);
        preparation=(ControlledFoodCookingTask)type.getMethod("allocateInstance",Class.class).invoke(field.get(null),ControlledFoodCookingTask.class);
        set(ControlledFoodCookingTask.class,preparation,"owner",session);
        set(ControlledFoodCookingTask.class,null,"active",preparation);
    }
    @AfterEach void cleanup()throws Exception {set(ControlledFoodCookingTask.class,null,"active",null);session.close(()->{},()->{});}
    @Test void thePreparationItselfCannotBeRetiredAsAMaterialBranch(){assertTrue(ControlledFoodCookingTask.within(preparation));}
    @Test void aWrapperContainingTheActivePreparationRemainsProtected()throws Exception {
        var root=new Plain();var wrapper=new Plain();child(root,wrapper);child(wrapper,preparation);
        assertTrue(ControlledFoodCookingTask.within(root));assertTrue(ControlledFoodCookingTask.within(wrapper));
    }
    @Test void aMaterialCollectorBelowPreparationCanRetireWithoutRetiringItsParent()throws Exception {
        var collector=new Plain();var source=new Plain();child(preparation,collector);child(collector,source);
        assertFalse(ControlledFoodCookingTask.within(collector));assertFalse(ControlledFoodCookingTask.within(source));
        assertTrue(ControlledFoodCookingTask.busy());assertTrue(ControlledFoodCookingTask.within(preparation));
    }
    @Test void anUnrelatedTaskDoesNotContainTheActivePreparation(){assertFalse(ControlledFoodCookingTask.within(new Plain()));}
    @Test void finishedPreparationDoesNotBlockANewMaterialBranch()throws Exception {
        set(ControlledFoodCookingTask.class,preparation,"finished",true);assertFalse(ControlledFoodCookingTask.within(preparation));assertFalse(ControlledFoodCookingTask.busy());
    }
    @Test void expiryOfTheOriginalRootCannotProtectAnotherTasksBranch(){permitted.set(false);assertFalse(ControlledFoodCookingTask.within(preparation));}
    @Test void nullAndNoActivePreparationAreNotOwnedSubtrees()throws Exception {
        assertFalse(ControlledFoodCookingTask.within(null));set(ControlledFoodCookingTask.class,null,"active",null);assertFalse(ControlledFoodCookingTask.within(preparation));
    }
    @Test void parentRetentionStillExcludesThePreparationItself()throws Exception {
        var root=new Plain();child(root,preparation);assertTrue(ControlledFoodCookingTask.retains(root));
        assertFalse(ControlledFoodCookingTask.retains(preparation));assertTrue(ControlledFoodCookingTask.within(preparation));
    }
}
