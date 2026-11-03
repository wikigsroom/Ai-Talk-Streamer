package dev.aitalkstreamer.mc.survival;

import org.junit.jupiter.api.Test;
import java.util.*;
import java.util.concurrent.atomic.*;
import dev.aitalkstreamer.mc.survival.CraftClicks.Stack;
import static dev.aitalkstreamer.mc.survival.CraftClicks.*;
import static org.junit.jupiter.api.Assertions.*;

/** Component tokens and game/packet effects are explicit fixtures; no Minecraft is initialized. */
class CraftClicksTest {
    final AtomicLong clock = new AtomicLong(1000);
    final AtomicBoolean current = new AtomicBoolean(true);
    final Confirmation sync = new Confirmation(clock::get, current::get);
    Stack item(int type, int count) { return new Stack(type, count, 64); }
    State initial() {
        var slots = new ArrayList<>(Collections.nCopies(10, Stack.EMPTY)); slots.set(5, item(1, 3)); return new State(slots, Stack.EMPTY);
    }
    Step step() { return pickup(initial(), 5, 0); }
    void send(Step step) { sync.send(step, step.before(), 0, () -> assertEquals(-1, sync.revision(0))); }
    @Test void oneUnitTransferReturnsTheOriginalComponentStackAndLeavesTheCursorEmpty() {
        var steps = moveOne(initial(), 5, 1); assertEquals(3, steps.size()); var end = steps.getLast().after();
        assertEquals(item(1, 2), end.slots().get(5)); assertEquals(item(1, 1), end.slots().get(1)); assertTrue(end.cursor().empty());
    }
    @Test void singleUnitSourceDoesNotProduceAnUnnecessaryReturnClick() {
        assertEquals(2, moveOne(initial().slot(5, item(1, 1)), 5, 1).size());
    }
    @Test void differentComponentsNeverSwapOrMerge() {
        var before = new State(initial().slot(6, item(2, 1)).slots(), item(1, 1));
        assertThrows(RuntimeException.class, () -> pickup(before, 6, 0));
        assertThrows(RuntimeException.class, () -> moveOne(initial().slot(1, item(2, 1)), 5, 1));
    }
    @Test void storageUsesOnlyProvidedInventoryAndSplitsAtStackCapacity() {
        var before = new State(initial().slot(5, item(2, 63)).slots(), item(2, 3));
        var steps = storeCursor(before, List.of(5, 6)); assertEquals(2, steps.size());
        assertEquals(item(2, 64), steps.getLast().after().slots().get(5)); assertEquals(item(2, 2), steps.getLast().after().slots().get(6));
    }
    @Test void insufficientSpaceFailsWhileOnlyPlanningAndNeverDropsItems() {
        var before = new State(initial().slots(), item(2, 64)); assertThrows(RuntimeException.class, () -> storeCursor(before, List.of(5)));
        assertEquals(item(2, 64), before.cursor());
    }
    @Test void outputStepConsumesExactUnitsAndPreservesRemainderComponents() {
        var before = new State(initial().slot(0, item(3, 4)).slot(1, item(1, 1)).slots(), Stack.EMPTY);
        var step = output(before, item(3, 4), List.of(1, 2, 3, 4), List.of(item(4, 1), Stack.EMPTY, Stack.EMPTY, Stack.EMPTY));
        assertTrue(step.craft()); assertEquals(item(4, 1), step.after().slots().get(1)); assertEquals(item(3, 4), step.after().cursor());
        assertEquals(before.slots().get(5), step.after().slots().get(5));
    }
    @Test void outputCannotConsumeAnUnplannedExtraUnitOrDifferentResult() {
        var before = initial().slot(0, item(3, 4)).slot(1, item(1, 2));
        assertThrows(RuntimeException.class, () -> output(before, item(3, 4), List.of(1), List.of(Stack.EMPTY)));
        assertThrows(RuntimeException.class, () -> output(before, item(2, 4), List.of(1), List.of(Stack.EMPTY)));
    }
    @Test void snapshotsAndStepsDoNotRetainMutableLists() {
        var slots = new ArrayList<>(initial().slots()); var state = new State(slots, Stack.EMPTY); slots.set(5, Stack.EMPTY);
        assertEquals(3, state.slots().get(5).count()); assertThrows(UnsupportedOperationException.class, () -> state.slots().clear());
    }
    @Test void clientPredictionAloneCannotConfirmTheStep() {
        send(step()); assertTrue(sync.pending()); assertEquals(0, sync.crafts());
    }
    @Test void oneOutstandingClickPreventsDuplicatesAndUnsolicitedRevisionChanges() {
        send(step()); assertThrows(RuntimeException.class, () -> send(step())); assertThrows(RuntimeException.class, () -> sync.revision(0));
    }
    @Test void aMissingActualMixinHookStopsTheTransaction() {
        assertThrows(RuntimeException.class, () -> sync.send(step(), initial(), 0, () -> {})); assertThrows(RuntimeException.class, sync::check);
    }
    @Test void authoritativeFullSnapshotMustMatchAllMaterialsCursorAndOtherSlots() {
        send(step()); sync.confirm(step().after().slot(9, item(7, 1)), 1); assertThrows(RuntimeException.class, sync::check);
        assertEquals(0, sync.crafts());
    }
    @Test void sameRevisionIsNotAnAcknowledgementAndCorrectSnapshotEndsPending() {
        send(step()); sync.confirm(step().after(), 0); assertTrue(sync.pending()); sync.confirm(step().after(), 1);
        assertFalse(sync.pending()); assertEquals(1, sync.lastRevision());
    }
    @Test void resultDisplayRecomputationIsNotConfusedWithMaterialOrCursorDivergence() {
        send(step()); sync.confirm(step().after().slot(0, item(4, 1)), 1); assertFalse(sync.pending());
    }
    @Test void lateOrCancelledConfirmationCannotReviveOrCountACraft() {
        send(step()); sync.cancel(); sync.confirm(step().after(), 1); assertEquals(0, sync.crafts()); assertThrows(RuntimeException.class, sync::check);
    }
    @Test void originalOwnerRevocationRejectsTheNextStepAndLatePackets() {
        send(step()); current.set(false); sync.confirm(step().after(), 1); assertThrows(RuntimeException.class, sync::check); assertEquals(-1, sync.lastRevision());
    }
    @Test void timeoutAtTheExactDeadlineDoesNotResendOrAcceptALateSnapshot() {
        send(step()); clock.addAndGet(Confirmation.TIMEOUT_MS); sync.confirm(step().after(), 1);
        assertThrows(RuntimeException.class, sync::check); assertEquals(-1, sync.lastRevision());
    }
    @Test void aServerMismatchSurfacesTheFixedPublicFailureOnTheNextTaskTick() {
        send(step());sync.confirm(step().after().slot(9,item(7,1)),1);
        var error=assertThrows(dev.aitalkstreamer.mc.core.Json.Rejected.class,sync::check);
        assertEquals("GAME_CRAFT_SERVER_DIVERGED",dev.aitalkstreamer.mc.core.LocalTaskFailure.executionReason(error));
        assertEquals(0,sync.crafts());
    }
    @Test void aLateServerReplyKeepsTheTimeoutReasonAndDoesNotCountTheCraft() {
        send(step());clock.addAndGet(Confirmation.TIMEOUT_MS);sync.confirm(step().after(),1);
        var error=assertThrows(dev.aitalkstreamer.mc.core.Json.Rejected.class,sync::check);
        assertEquals("GAME_CRAFT_SERVER_TIMEOUT",dev.aitalkstreamer.mc.core.LocalTaskFailure.executionReason(error));
        assertEquals(0,sync.crafts());assertEquals(-1,sync.lastRevision());
    }
    @Test void aFailedClickKeepsPrivateExceptionTextOutOfTheLaterFailureReason() {
        assertThrows(IllegalStateException.class,()->sync.send(step(),initial(),0,()->{sync.revision(0);throw new IllegalStateException("private path");}));
        var error=assertThrows(dev.aitalkstreamer.mc.core.Json.Rejected.class,sync::check);
        assertEquals("GAME_CRAFT_CLICK_FAILED",dev.aitalkstreamer.mc.core.LocalTaskFailure.executionReason(error));
        assertFalse(error.getMessage().contains("private"));
    }
    @Test void onlyAnActualOutputStepWithMatchingConsumptionAndCursorCountsAsACraft() {
        var before = initial().slot(0, item(3, 4)).slot(1, item(1, 1));
        var craft = output(before, item(3, 4), List.of(1), List.of(Stack.EMPTY)); send(craft);
        sync.confirm(craft.after(), 1); assertEquals(1, sync.crafts());
        sync.confirm(craft.after(), 2); assertEquals(1, sync.crafts());
    }
    @Test void aPacketArrivingDuringTheClickCannotConfirmBeforeTheHookReturns() {
        var step = step(); sync.send(step, initial(), 0, () -> { sync.revision(0); sync.confirm(step.after(), 1); });
        assertTrue(sync.pending()); sync.confirm(step.after(), 1); assertFalse(sync.pending());
    }
    @Test void wrongThreadCannotUseOrCompleteTheTransaction() throws Exception {
        send(step()); var caught = new AtomicReference<Throwable>();
        var thread = new Thread(() -> { try { sync.confirm(step().after(), 1); } catch (Throwable error) { caught.set(error); } });
        thread.start(); thread.join(); assertNotNull(caught.get()); assertTrue(sync.pending());
    }
}
