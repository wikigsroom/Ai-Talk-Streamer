package dev.aitalkstreamer.mc.core;

import org.junit.jupiter.api.Test;
import java.util.*;
import java.util.concurrent.atomic.*;
import static org.junit.jupiter.api.Assertions.*;

class HotbarSelectionTest {
    private final AtomicInteger local = new AtomicInteger(2);
    private final AtomicBoolean context = new AtomicBoolean(true);
    private final List<Integer> packets = new ArrayList<>();
    private Runnable beforeWrite = () -> {}, afterWrite = () -> {}, beforeSend = () -> {};
    private final HotbarSelection selection = new HotbarSelection(local::get, value -> {
        beforeWrite.run(); local.set(value); afterWrite.run();
    }, value -> { beforeSend.run(); packets.add(value); }, context::get);
    private static void failure() { throw new IllegalStateException("fixture"); }
    @Test void repeatedSelectionRestoresTheOriginalAndSendsItToTheSameConnection() {
        selection.select(4); selection.select(8); selection.release();
        assertEquals(2,local.get()); assertEquals(List.of(4,8,2),packets); assertFalse(selection.owned());
    }
    @Test void releaseWithoutOwnershipDoesNotWriteOrSend() {
        beforeWrite = HotbarSelectionTest::failure; beforeSend = HotbarSelectionTest::failure;
        selection.release(); assertFalse(selection.owned());
    }
    @Test void invalidSlotsCannotAcquireOwnershipOrSendPackets() {
        assertThrows(IllegalArgumentException.class, () -> selection.select(-1));
        assertThrows(IllegalArgumentException.class, () -> selection.select(9));
        assertEquals(2,local.get()); assertTrue(packets.isEmpty()); assertFalse(selection.owned());
    }
    @Test void anotherSourcesSelectionIsNeitherOverwrittenNorRestored() {
        selection.select(4); local.set(6);
        assertEquals("GAME_INPUT_OWNER_CHANGED",assertThrows(IllegalStateException.class,()->selection.select(8)).getMessage());
        selection.release(); assertEquals(6,local.get()); assertEquals(List.of(4),packets); assertFalse(selection.owned());
    }
    @Test void missingOriginalContextRejectsNewSelectionBeforeAnyEffect() {
        context.set(false); assertThrows(IllegalStateException.class,()->selection.select(4));
        assertEquals(2,local.get()); assertTrue(packets.isEmpty()); assertFalse(selection.owned());
    }
    @Test void changedPlayerWorldOrConnectionPreventsOldRestoration() {
        selection.select(4); context.set(false); local.set(7); selection.release();
        assertEquals(7,local.get()); assertEquals(List.of(4),packets); assertFalse(selection.owned());
    }
    @Test void aSecondLocalWriteFailingBeforeMutationStillRestoresTheFirstSelection() {
        selection.select(4); beforeWrite = HotbarSelectionTest::failure;
        assertThrows(IllegalStateException.class,()->selection.select(8)); assertEquals(4,local.get());
        beforeWrite = () -> {}; selection.release(); assertEquals(2,local.get()); assertEquals(List.of(4,2),packets);
    }
    @Test void aSecondLocalWriteMutatingThenFailingStillRestoresTheOriginal() {
        selection.select(4); afterWrite = HotbarSelectionTest::failure;
        assertThrows(IllegalStateException.class,()->selection.select(8)); assertEquals(8,local.get());
        afterWrite = () -> {}; selection.release(); assertEquals(2,local.get()); assertEquals(List.of(4,2),packets);
    }
    @Test void failedSelectionPacketLeavesOwnedStateForCleanup() {
        beforeSend = HotbarSelectionTest::failure;
        assertThrows(IllegalStateException.class,()->selection.select(4)); assertTrue(selection.owned());
        assertEquals(4,local.get()); beforeSend = () -> {}; selection.release();
        assertEquals(2,local.get()); assertEquals(List.of(2),packets);
    }
    @Test void aRestoreSetterFailingBeforeMutationCanBeRetried() {
        selection.select(4); beforeWrite = HotbarSelectionTest::failure;
        assertThrows(IllegalStateException.class,selection::release); assertEquals(4,local.get()); assertTrue(selection.owned());
        beforeWrite = () -> {}; selection.release(); assertEquals(2,local.get()); assertEquals(List.of(4,2),packets);
    }
    @Test void aRestoreSetterMutatingThenFailingMustStillSendOnRetry() {
        selection.select(4); afterWrite = HotbarSelectionTest::failure;
        assertThrows(IllegalStateException.class,selection::release); assertEquals(2,local.get()); assertTrue(selection.owned());
        afterWrite = () -> {}; selection.release(); assertEquals(List.of(4,2),packets); assertFalse(selection.owned());
    }
    @Test void failedRestorePacketIsRetriedDespiteLocalSlotAlreadyBeingOriginal() {
        selection.select(4); beforeSend = HotbarSelectionTest::failure;
        assertThrows(IllegalStateException.class,selection::release); assertEquals(2,local.get()); assertTrue(selection.owned());
        assertEquals("GAME_INPUT_RESTORE_PENDING",assertThrows(IllegalStateException.class,()->selection.select(8)).getMessage());
        beforeSend = () -> {}; selection.release(); assertEquals(List.of(4,2),packets); assertFalse(selection.owned());
    }
    @Test void aForeignSelectionDuringFailedRestorationIsPreservedWithoutResending() {
        selection.select(4); beforeSend = HotbarSelectionTest::failure;
        assertThrows(IllegalStateException.class,selection::release); local.set(6); beforeSend = () -> {};
        selection.release(); assertEquals(6,local.get()); assertEquals(List.of(4),packets); assertFalse(selection.owned());
    }
    @Test void anOldGenerationCannotWriteOrRestoreTheNextTasksSelection() {
        var fence = new InputLeaseFence(selection::release); var old = fence.ticket();
        old.check(); selection.select(4); old.release();
        var next = fence.ticket(); next.check(); selection.select(8);
        assertThrows(IllegalStateException.class,old::check); old.release();
        assertEquals(8,local.get()); assertEquals(List.of(4,2,8),packets);
        next.release(); assertEquals(2,local.get()); assertEquals(List.of(4,2,8,2),packets);
    }
    @Test void aFailedRestorationCannotAdvanceTheGenerationUntilRetrySucceeds() {
        var fence = new InputLeaseFence(selection::release); var ticket = fence.ticket(); selection.select(4);
        beforeSend = HotbarSelectionTest::failure; assertThrows(IllegalStateException.class,ticket::release); ticket.check();
        beforeSend = () -> {}; ticket.release(); assertThrows(IllegalStateException.class,ticket::check);
        assertEquals(List.of(4,2),packets); assertFalse(selection.owned());
    }
    @Test void revokedOriginalPermitCannotChangeSelectionButOwnedCleanupCanRestoreIt() {
        var clock = new AtomicLong(10000); var control = new ControlArbiter(clock::get,()->{});
        control.world("world"); control.attach("controller"); control.release(control.epoch(),()->{});
        control.observe(1); control.beginAuto("controller","world",control.epoch(),true);
        control.grant("controller",control.lease(),control.epoch(),1,control.heartbeat(),10000);
        var permit = control.permit(); var ticket = new InputLeaseFence(selection::release).ticket();
        control.actuate(permit,()->{ ticket.check(); selection.select(4); }); control.stop(ControlArbiter.Mode.PAUSED);
        assertThrows(Json.Rejected.class,()->control.actuate(permit,()->selection.select(8)));
        assertEquals(4,local.get()); ticket.release(); assertEquals(2,local.get()); assertEquals(List.of(4,2),packets);
    }
    @Test void aNewOwnerCapturesTheCurrentHumanSelectionAsItsOwnBaseline() {
        selection.select(4); selection.release(); local.set(6);
        selection.select(8); selection.release(); assertEquals(6,local.get()); assertEquals(List.of(4,2,8,6),packets);
    }
}
