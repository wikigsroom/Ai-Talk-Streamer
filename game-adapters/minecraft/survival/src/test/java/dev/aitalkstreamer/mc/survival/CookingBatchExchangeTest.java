package dev.aitalkstreamer.mc.survival;

import java.util.*;
import java.util.concurrent.atomic.*;
import org.junit.jupiter.api.Test;
import dev.aitalkstreamer.mc.core.LocalTaskFailure;
import dev.aitalkstreamer.mc.survival.CraftClicks.Stack;
import static dev.aitalkstreamer.mc.survival.CraftClicks.*;
import static dev.aitalkstreamer.mc.core.LocalTaskFailure.Reason.*;
import static org.junit.jupiter.api.Assertions.*;

class CookingBatchExchangeTest {
    final AtomicLong now=new AtomicLong();final AtomicBoolean current=new AtomicBoolean(true);
    final Stack raw=new Stack(1,1,64),output=new Stack(2,2,64),fuel=new Stack(3,1,64);
    CookingExchange exchange(int inputs) {
        var slots=new ArrayList<>(Collections.nCopies(39,Stack.EMPTY));slots.set(3,raw.count(8));slots.set(4,fuel.count(2));
        return new CookingExchange(new State(slots,Stack.EMPTY),raw,output,fuel,0,now::get,current::get,47500,inputs);
    }
    void send(CookingExchange c,Step step) {c.send(step,c.server(),c.lastRevision(),()->assertEquals(-1,c.revision(0)));}
    void apply(CookingExchange c,Step step) {send(c,step);c.inventory(step.after(),(c.lastRevision()+1)&32767);assertFalse(c.pending());}
    void load(CookingExchange c,int inputs) {
        apply(c,CookingExchange.pickup(c.server(),3,0));
        for(int i=0;i<inputs;i++)apply(c,CookingExchange.pickup(c.server(),0,1));
        apply(c,CookingExchange.pickup(c.server(),3,0));
    }
    void partial(CookingExchange c,int remaining,int produced) {
        c.slot(0,raw.count(remaining),c.lastRevision()+1);c.slot(2,output.count(produced*2),c.lastRevision()+1);
    }
    void diverged(CookingExchange c) {assertEquals(COOKING_SERVER_DIVERGED,assertThrows(LocalTaskFailure.class,c::check).reason);}
    @Test void aPartialResultCannotCompleteOrBeCollectedAsTheWholeBatch() {
        var c=exchange(4);load(c,4);partial(c,3,1);assertFalse(c.cooked());assertFalse(c.pending());
        assertThrows(RuntimeException.class,()->send(c,CookingExchange.pickup(c.server(),2,0)));
        partial(c,0,4);assertTrue(c.cooked());apply(c,CookingExchange.pickup(c.server(),2,0));assertEquals(output.count(8),c.server().cursor());
    }
    @Test void outputFirstPacketsSuspendFurtherClicksUntilTheInputMatches() {
        var c=exchange(4);load(c,4);c.slot(2,output,c.lastRevision()+1);assertTrue(c.pending());
        assertThrows(RuntimeException.class,()->send(c,CookingExchange.pickup(c.server(),4,0)));
        c.slot(0,raw.count(3),c.lastRevision()+1);assertFalse(c.pending());assertFalse(c.cooked());
    }
    @Test void inputFirstPacketsSuspendClicksAndAFullResyncCanCloseTheGap() {
        var c=exchange(4);load(c,4);c.slot(0,raw.count(2),c.lastRevision()+1);assertTrue(c.pending());
        c.inventory(c.server().slot(2,output.count(4)),c.lastRevision()+1);assertFalse(c.pending());assertFalse(c.cooked());
    }
    @Test void coalescedServerUpdatesMayConvertSeveralRawUnitsAtOnce() {
        var c=exchange(4);load(c,4);c.inventory(c.server().slot(0,raw).slot(2,output.count(6)),c.lastRevision()+1);
        assertFalse(c.pending());assertFalse(c.cooked());partial(c,0,4);assertTrue(c.cooked());
    }
    @Test void residualHeatCanCookDuringLoadingWithoutLosingTheRemainingInputs() {
        var c=exchange(4);apply(c,CookingExchange.pickup(c.server(),3,0));
        var first=CookingExchange.pickup(c.server(),0,1);send(c,first);
        c.inventory(first.after().slot(0,Stack.EMPTY).slot(2,output),c.lastRevision()+1);assertFalse(c.pending());assertFalse(c.cooked());
        for(int i=0;i<3;i++)apply(c,CookingExchange.pickup(c.server(),0,1));
        apply(c,CookingExchange.pickup(c.server(),3,0));partial(c,0,4);assertTrue(c.cooked());assertEquals(fuel.count(2),c.server().slots().get(4));
    }
    @Test void aFullAckCannotLoseRawWithoutTheCorrespondingActualOutput() {
        var c=exchange(4);load(c,4);c.inventory(c.server().slot(0,raw.count(3)),c.lastRevision()+1);diverged(c);
    }
    @Test void fullAckCannotInventOutputWhileAllInputsRemain() {
        var c=exchange(4);load(c,4);c.inventory(c.server().slot(2,output),c.lastRevision()+1);diverged(c);
    }
    @Test void outputQuantityMustBeAnExactMultipleOfTheActualRecipeYield() {
        var c=exchange(4);load(c,4);c.slot(2,output.count(3),c.lastRevision()+1);diverged(c);
    }
    @Test void anUninsertedRawUnitCannotProduceEvidenceEarly() {
        var c=exchange(4);apply(c,CookingExchange.pickup(c.server(),3,0));apply(c,CookingExchange.pickup(c.server(),0,1));
        c.slot(2,output.count(4),c.lastRevision()+1);diverged(c);
    }
    @Test void inputOrOutputRollbackAndChangedComponentsAreRejected() {
        var input=exchange(4);load(input,4);partial(input,3,1);input.slot(0,raw.count(4),input.lastRevision()+1);diverged(input);
        var result=exchange(4);load(result,4);partial(result,3,1);result.slot(2,Stack.EMPTY,result.lastRevision()+1);diverged(result);
        var component=exchange(4);load(component,4);component.slot(2,new Stack(8,2,64),component.lastRevision()+1);diverged(component);
    }
    @Test void onlyOneFuelUnitCanBeInsertedEvenAfterThatFuelBurns() {
        var c=exchange(4);load(c,4);for(var step:CookingExchange.moveOne(c.server(),4,1))apply(c,step);
        c.slot(1,Stack.EMPTY,c.lastRevision()+1);apply(c,CookingExchange.pickup(c.server(),4,0));
        assertThrows(RuntimeException.class,()->send(c,CookingExchange.pickup(c.server(),1,1)));
    }
    @Test void aFifthInputCannotBeInsertedIntoAnUnfinishedFourInputBatch() {
        var c=exchange(4);load(c,4);partial(c,3,1);apply(c,CookingExchange.pickup(c.server(),3,0));
        assertThrows(RuntimeException.class,()->send(c,CookingExchange.pickup(c.server(),0,1)));
    }
    @Test void partialProgressDoesNotRenewTheDeadlineAnchoredAtFirstInsertion() {
        var c=exchange(4);load(c,4);now.set(47000);partial(c,3,1);now.set(47500);
        assertEquals(COOKING_SERVER_TIMEOUT,assertThrows(LocalTaskFailure.class,c::check).reason);
    }
    @Test void revocationDuringAPartialBatchDoesNotAcceptLateCompletion() {
        var c=exchange(4);load(c,4);partial(c,3,1);current.set(false);partial(c,0,4);
        assertThrows(RuntimeException.class,c::check);assertFalse(c.sending());
    }
    @Test void invalidInputAndOutputStackBoundsAreRejectedBeforeClicks() {
        assertThrows(RuntimeException.class,()->exchange(0));assertThrows(RuntimeException.class,()->exchange(5));
        var c=exchange(1);assertThrows(RuntimeException.class,()->new CookingExchange(c.server(),raw,output.count(33),fuel,0,now::get,current::get,47500,2));
    }
}
