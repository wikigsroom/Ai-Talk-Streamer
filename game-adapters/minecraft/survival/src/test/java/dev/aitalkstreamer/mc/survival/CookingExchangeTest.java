package dev.aitalkstreamer.mc.survival;

import java.util.*;
import java.util.concurrent.atomic.*;
import org.junit.jupiter.api.Test;
import dev.aitalkstreamer.mc.core.LocalTaskFailure;
import dev.aitalkstreamer.mc.survival.CraftClicks.Stack;
import static dev.aitalkstreamer.mc.survival.CraftClicks.*;
import static dev.aitalkstreamer.mc.core.LocalTaskFailure.Reason.*;
import static org.junit.jupiter.api.Assertions.*;

class CookingExchangeTest {
    final AtomicLong now = new AtomicLong(); final AtomicBoolean current = new AtomicBoolean(true);
    final Stack raw = new Stack(1, 1, 64), cooked = new Stack(2, 1, 64), fuel = new Stack(3, 1, 64);
    State initial() {
        var slots = new ArrayList<>(Collections.nCopies(39, Stack.EMPTY)); slots.set(3, raw.count(2)); slots.set(4, fuel.count(2));
        return new State(slots, Stack.EMPTY);
    }
    CookingExchange exchange() { return new CookingExchange(initial(), raw, cooked, fuel, 0, now::get, current::get); }
    void send(CookingExchange c, Step step) { c.send(step, c.server(), c.lastRevision(), () -> assertEquals(-1, c.revision(0))); }
    void apply(CookingExchange c, Step step) { send(c, step); c.inventory(step.after(), (c.lastRevision() + 1) & 32767); assertFalse(c.pending()); }
    CookingExchange heated(boolean burn) {
        var c = exchange();
        for (var step : CookingExchange.moveOne(c.server(), 3, 0)) apply(c, step);
        apply(c, CookingExchange.pickup(c.server(), 4, 0));
        var load = CookingExchange.pickup(c.server(), 1, 1); send(c, load);
        c.inventory(burn ? load.after().slot(1, Stack.EMPTY) : load.after(), c.lastRevision() + 1);
        apply(c, CookingExchange.pickup(c.server(), 4, 0)); return c;
    }
    void finish(CookingExchange c) {
        c.slot(0, Stack.EMPTY, c.lastRevision() + 1); c.slot(2, cooked, c.lastRevision() + 1); assertTrue(c.cooked());
    }
    @Test void occupiedContainerOrCursorIsRejectedBeforeAnyWrite() {
        assertThrows(RuntimeException.class, () -> new CookingExchange(initial().slot(0, raw), raw, cooked, fuel, 0, now::get, current::get));
        assertThrows(RuntimeException.class, () -> new CookingExchange(new State(initial().slots(), raw), raw, cooked, fuel, 0, now::get, current::get));
    }
    @Test void oneInputIsSplitWithoutChangingComponentsOrTheOtherSlots() {
        var c = exchange(); for (var step : CookingExchange.moveOne(c.server(), 3, 0)) apply(c, step);
        assertEquals(raw, c.server().slots().get(0)); assertEquals(raw, c.server().slots().get(3));
        assertEquals(fuel.count(2), c.server().slots().get(4)); assertTrue(c.server().cursor().empty());
    }
    @Test void localClickPredictionDoesNotConfirmAnyOperation() {
        var c = exchange(); var step = CookingExchange.pickup(c.server(), 3, 0); send(c, step);
        assertTrue(c.pending()); assertEquals(initial(), c.server()); assertFalse(c.cooked());
    }
    @Test void completeCookingReturnsTheExactServerConfirmedOutput() {
        var c = heated(true); finish(c); apply(c, CookingExchange.pickup(c.server(), 2, 0));
        for (var step : CraftClicks.storeCursor(c.server(), List.of(3, 4, 5))) apply(c, step);
        assertEquals(cooked, c.server().slots().get(5)); assertTrue(c.server().cursor().empty());
        assertTrue(c.server().slots().subList(0, 3).stream().allMatch(Stack::empty));
    }
    @Test void outputAloneCannotCompleteTheInputConversion() {
        var c = heated(true); c.slot(2, cooked, c.lastRevision() + 1); assertFalse(c.cooked());
        c.slot(0, Stack.EMPTY, c.lastRevision() + 1); assertTrue(c.cooked());
    }
    @Test void consumedInputAloneCannotAuthorizeCollectingAnOutput() {
        var c = heated(true); c.slot(0, Stack.EMPTY, c.lastRevision() + 1); assertFalse(c.cooked());
    }
    @Test void aFullSnapshotCanFinishAfterTheFirstPartialInputUpdate() {
        var c = heated(true); c.slot(0, Stack.EMPTY, c.lastRevision() + 1);
        c.inventory(c.server().slot(2, cooked), c.lastRevision() + 1); assertTrue(c.cooked());
    }
    @Test void burningDuringTheFuelCursorReturnIsAValidServerTransition() {
        var c = exchange(); for (var step : CookingExchange.moveOne(c.server(), 3, 0)) apply(c, step);
        apply(c, CookingExchange.pickup(c.server(), 4, 0)); apply(c, CookingExchange.pickup(c.server(), 1, 1));
        var step = CookingExchange.pickup(c.server(), 4, 0); send(c, step);
        c.inventory(step.after().slot(1, Stack.EMPTY), c.lastRevision() + 1); assertFalse(c.pending());
    }
    @Test void existingHeatCanFinishBeforeAnyNewFuelHasBeenInserted() {
        var c = exchange(); for (var step : CookingExchange.moveOne(c.server(), 3, 0)) apply(c, step);
        c.slot(0, Stack.EMPTY, c.lastRevision() + 1); c.slot(2, cooked, c.lastRevision() + 1);
        assertTrue(c.cooked()); assertEquals(fuel.count(2), c.server().slots().get(4));
    }
    @Test void unusedFuelCanBeReturnedAfterResidualHeatCooksTheFood() {
        var c = heated(false); finish(c); apply(c, CookingExchange.pickup(c.server(), 2, 0));
        for (var step : CraftClicks.storeCursor(c.server(), List.of(3, 4, 5))) apply(c, step);
        apply(c, CookingExchange.pickup(c.server(), 1, 0));
        for (var step : CraftClicks.storeCursor(c.server(), List.of(3, 4, 5))) apply(c, step);
        assertEquals(fuel.count(2), c.server().slots().get(4)); assertTrue(c.server().cursor().empty());
    }
    @Test void aDifferentComponentTokenIsNeverAcceptedAsTheExpectedCookedFood() {
        var c = heated(true); c.slot(2, new Stack(4, 1, 64), c.lastRevision() + 1);
        assertEquals(COOKING_SERVER_DIVERGED, assertThrows(LocalTaskFailure.class, c::check).reason);
    }
    @Test void additionalOutputQuantityCannotCreateExtraFoodEvidence() {
        var c = heated(true); c.slot(2, cooked.count(2), c.lastRevision() + 1);
        assertEquals(COOKING_SERVER_DIVERGED, assertThrows(LocalTaskFailure.class, c::check).reason);
    }
    @Test void unrelatedInventoryChangesFailTheTransaction() {
        var c = heated(true); c.slot(5, cooked, c.lastRevision() + 1);
        assertEquals(COOKING_SERVER_DIVERGED, assertThrows(LocalTaskFailure.class, c::check).reason);
    }
    @Test void aFullAckWithAnUnexpectedCursorFails() {
        var c = exchange(); var step = CookingExchange.pickup(c.server(), 3, 0); send(c, step);
        c.inventory(new State(step.after().slots(), fuel), 1);
        assertEquals(COOKING_SERVER_DIVERGED, assertThrows(LocalTaskFailure.class, c::check).reason);
    }
    @Test void anotherClickCannotOvertakeThePendingServerAck() {
        var c = exchange(); var step = CookingExchange.pickup(c.server(), 3, 0); send(c, step);
        assertThrows(RuntimeException.class, () -> c.send(step, initial(), 0, () -> fail("unexpected write")));
    }
    @Test void clickTimeoutDoesNotRetryOrTurnIntoSuccess() {
        var c = exchange(); var step = CookingExchange.pickup(c.server(), 3, 0); send(c, step); now.set(1500);
        c.inventory(step.after(), 1); assertEquals(COOKING_SERVER_TIMEOUT, assertThrows(LocalTaskFailure.class, c::check).reason);
    }
    @Test void aCookedPacketAtTheDeadlineCannotRescueAnOverdueAttempt() {
        var c = heated(true); now.set(8000); c.slot(0, Stack.EMPTY, c.lastRevision() + 1); c.slot(2, cooked, c.lastRevision() + 1);
        assertEquals(COOKING_SERVER_TIMEOUT, assertThrows(LocalTaskFailure.class, c::check).reason);
    }
    @Test void interruptingTheTaskDoesNotResetTheCookingDeadline() {
        var c = heated(true); now.set(7999); c.check(); now.set(8000);
        assertEquals(COOKING_SERVER_TIMEOUT, assertThrows(LocalTaskFailure.class, c::check).reason);
    }
    @Test void staleAckIsIgnoredAndFifteenBitRevisionWrapIsSupported() {
        var c = new CookingExchange(initial(), raw, cooked, fuel, 32767, now::get, current::get);
        var step = CookingExchange.pickup(c.server(), 3, 0); send(c, step);
        c.inventory(step.after(), 32766); assertTrue(c.pending()); c.inventory(step.after(), 0); assertFalse(c.pending());
    }
    @Test void revocationIgnoresLatePacketsAndCannotProduceAnotherWrite() {
        var c = heated(true); current.set(false); c.slot(0, Stack.EMPTY, 100); c.inventory(initial(), 100);
        assertThrows(RuntimeException.class, c::check); assertThrows(RuntimeException.class,
                () -> c.send(CookingExchange.pickup(initial(), 3, 0), initial(), 0, () -> fail("revoked write")));
    }
    @Test void cancellationDoesNotSendCleanupClicksAndCannotBeReopened() {
        var c = heated(true); c.cancel(); current.set(true); c.inventory(initial(), 100);
        assertThrows(RuntimeException.class, c::check); assertFalse(c.sending());
    }
    @Test void packetObservationOnAnotherThreadCannotMutateTheTransaction() throws Exception {
        var c = heated(true); var error = new AtomicReference<Throwable>();
        var t = new Thread(() -> { try { c.slot(0, Stack.EMPTY, 100); } catch (Throwable ex) { error.set(ex); } });
        t.start(); t.join(); assertNotNull(error.get()); assertFalse(c.cooked());
    }

    @Test void furnaceBudgetUsesItsCapturedDurationInsteadOfTheSmokerDefault() {
        var c=new CookingExchange(initial(),raw,cooked,fuel,0,now::get,current::get,13000);
        for(var step:CookingExchange.moveOne(c.server(),3,0))apply(c,step);
        now.set(10000);c.check();finish(c);assertTrue(c.cooked());
    }
    @Test void aFurnaceResultAtItsOwnDeadlineIsRejected() {
        var c=new CookingExchange(initial(),raw,cooked,fuel,0,now::get,current::get,13000);
        for(var step:CookingExchange.moveOne(c.server(),3,0))apply(c,step);
        now.set(13000);c.slot(0,Stack.EMPTY,c.lastRevision()+1);c.slot(2,cooked,c.lastRevision()+1);
        assertEquals(COOKING_SERVER_TIMEOUT,assertThrows(LocalTaskFailure.class,c::check).reason);
    }
    @Test void arbitraryCookingDurationsCannotDisableTheDeadline() {
        assertThrows(RuntimeException.class,()->new CookingExchange(initial(),raw,cooked,fuel,0,now::get,current::get,0));
        assertThrows(RuntimeException.class,()->new CookingExchange(initial(),raw,cooked,fuel,0,now::get,current::get,65001));
    }
    @Test void theSameComponentMayBeRawMaterialAndFuelInDifferentSlots() {
        var initial=initial().slot(4,raw.count(2));var c=new CookingExchange(initial,raw,cooked,raw,0,now::get,current::get);
        for(var step:CookingExchange.moveOne(c.server(),3,0))apply(c,step);
        for(var step:CookingExchange.moveOne(c.server(),4,1))apply(c,step);
        c.slot(1,Stack.EMPTY,c.lastRevision()+1);finish(c);assertEquals(raw,c.server().slots().get(3));assertEquals(raw,c.server().slots().get(4));
    }
    @Test void oneStackCanSupplyTwoDistinctRawAndFuelUnitsWithoutDuplication() {
        var initial=initial().slot(3,raw.count(3)).slot(4,Stack.EMPTY);var c=new CookingExchange(initial,raw,cooked,raw,0,now::get,current::get);
        for(var step:CookingExchange.moveOne(c.server(),3,0))apply(c,step);
        for(var step:CookingExchange.moveOne(c.server(),3,1))apply(c,step);
        c.slot(1,Stack.EMPTY,c.lastRevision()+1);finish(c);assertEquals(raw,c.server().slots().get(3));
    }
    @Test void capturedOutputCanHaveTheSameComponentAsTheFuel() {
        var c=new CookingExchange(initial(),raw,fuel,fuel,0,now::get,current::get);
        for(var step:CookingExchange.moveOne(c.server(),3,0))apply(c,step);
        c.slot(0,Stack.EMPTY,c.lastRevision()+1);c.slot(2,fuel,c.lastRevision()+1);assertTrue(c.cooked());
    }
    @Test void actualRecipeBatchOutputIsConfirmedAtItsExactQuantity() {
        var batch=cooked.count(3);var c=new CookingExchange(initial(),raw,batch,fuel,0,now::get,current::get);
        for(var step:CookingExchange.moveOne(c.server(),3,0))apply(c,step);
        c.slot(0,Stack.EMPTY,c.lastRevision()+1);c.slot(2,batch,c.lastRevision()+1);assertTrue(c.cooked());
        apply(c,CookingExchange.pickup(c.server(),2,0));assertEquals(batch,c.server().cursor());
    }
    @Test void anExtraUnitStillCannotMasqueradeAsTheCapturedRecipeBatch() {
        var c=new CookingExchange(initial(),raw,cooked.count(3),fuel,0,now::get,current::get);
        for(var step:CookingExchange.moveOne(c.server(),3,0))apply(c,step);
        c.slot(2,cooked.count(4),c.lastRevision()+1);assertEquals(COOKING_SERVER_DIVERGED,assertThrows(LocalTaskFailure.class,c::check).reason);
    }

}
