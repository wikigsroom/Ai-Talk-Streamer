package dev.aitalkstreamer.mc.core;

import org.junit.jupiter.api.*;
import java.util.concurrent.atomic.AtomicLong;
import static org.junit.jupiter.api.Assertions.*;

class ControlArbiterTest {
    private AtomicLong now;
    private ControlArbiter control;
    @BeforeEach void setup() {
        now = new AtomicLong(10000); control = new ControlArbiter(now::get, () -> {});
        control.world("world-session-test"); released(); control.attach("controller-test"); released(); control.observe(1);
    }
    private void released() { control.release(control.epoch(), () -> {}); }
    private void begin() { control.beginAuto("controller-test", "world-session-test", control.epoch(), true); }
    private void grant() { control.grant("controller-test", control.lease(), control.epoch(), 1, control.heartbeat(), 3000); }
    @Test void autoRequiresFirstGrant() { begin(); assertFalse(control.allowed()); grant(); assertTrue(control.allowed()); }
    @Test void delayedGrantCannotRestartItsTtlAtArrival() {
        begin(); long reference = control.heartbeat(); now.addAndGet(1500); control.observe(2);
        now.addAndGet(1000); control.observe(3);
        control.grant("controller-test", control.lease(), control.epoch(), 1, reference, 3000);
        assertEquals(500, control.remaining()); now.addAndGet(501); assertFalse(control.allowed()); assertTrue(control.expire());
    }
    @Test void expiredReferenceIsRejectedEvenIfNewHeartbeatsExist() {
        begin(); grant(); long old = control.lastHeartbeat(); now.addAndGet(1500); control.observe(2);
        now.addAndGet(1000); control.observe(3);
        control.grant("controller-test", control.lease(), control.epoch(), 2, control.heartbeat(), 3000); now.addAndGet(600);
        assertThrows(Json.Rejected.class, () -> control.grant("controller-test", control.lease(), control.epoch(), 3, old, 3000));
    }
    @Test void oldGrantDoesNotRestoreAuthorityAfterTakeover() {
        begin(); grant(); String lease = control.lease(); long epoch = control.epoch(); long heartbeat = control.lastHeartbeat();
        control.stop(ControlArbiter.Mode.MANUAL_COMMENTARY);
        assertThrows(Json.Rejected.class, () -> control.grant("controller-test", lease, epoch, 2, heartbeat, 3000)); assertFalse(control.allowed());
    }
    @Test void expiredModeCannotReviveBeforeWatchdogRuns() {
        begin(); grant(); now.addAndGet(3001);
        assertThrows(Json.Rejected.class, () -> control.grant("controller-test", control.lease(), control.epoch(), 2, control.heartbeat(), 3000));
    }
    @Test void observationsUseSamplingTime() {
        begin(); grant(); now.addAndGet(1600);
        assertThrows(Json.Rejected.class, () -> control.authorize("controller-test", control.lease(), "world-session-test", control.epoch(), 1, 1500));
        control.observe(2); assertDoesNotThrow(() -> control.authorize("controller-test", control.lease(), "world-session-test", control.epoch(), 2, 1500));
    }
    @Test void oldControllerAndEpochAreRejected() {
        begin(); grant(); assertThrows(Json.Rejected.class, () -> control.authorize("other", control.lease(), "world-session-test", control.epoch(), 1, 1500));
        assertThrows(Json.Rejected.class, () -> control.authorize("controller-test", control.lease(), "world-session-test", control.epoch() - 1, 1, 1500));
    }
    @Test void worldChangeClearsLeaseAndObservationReferences() {
        begin(); grant(); control.world("world-session-new"); released();
        assertFalse(control.allowed()); assertThrows(Json.Rejected.class, () -> control.beginAuto("controller-test", "world-session-new", control.epoch(), true));
    }
    @Test void releaseConfirmationIsSeparateFromStopRequest() {
        begin(); grant(); control.actuate(control.permit(), () -> {}); control.stop(ControlArbiter.Mode.PAUSED);
        assertFalse(control.released()); assertFalse(control.allowed()); released(); assertTrue(control.released());
    }
    @Test void guiAndUnconfirmedReleasePreventAuto() {
        assertThrows(Json.Rejected.class, () -> control.beginAuto("controller-test", "world-session-test", control.epoch(), false));
        control.stop(ControlArbiter.Mode.PAUSED); assertThrows(Json.Rejected.class, this::begin);
    }
    @Test void networkHeartbeatsCannotKeepAStalledClientAuthorized() {
        begin(); control.grant("controller-test", control.lease(), control.epoch(), 1, control.heartbeat(), 10000);
        now.addAndGet(2001); assertFalse(control.allowed());
        assertEquals("GAME_CLIENT_TICK_STALLED", assertThrows(Json.Rejected.class,
                () -> control.grant("controller-test", control.lease(), control.epoch(), 2, control.heartbeat(), 10000)).code);
        var stopped = control.expireAndStop(); assertEquals("GAME_CLIENT_TICK_STALLED", stopped.reason());
        assertEquals(control.epoch(), stopped.epoch()); assertEquals(ControlArbiter.Mode.PAUSED, control.mode());
    }
    @Test void resumingBeforeTheWatchdogRunsStillRevokesTheOldEpoch() {
        begin(); grant(); var permit = control.permit(); now.addAndGet(2001);
        var stopped = control.observe(2); assertNotNull(stopped); assertEquals("GAME_CLIENT_TICK_STALLED", stopped.reason());
        assertFalse(control.allowed()); assertTrue(control.epoch() > permit.epoch());
        assertThrows(Json.Rejected.class, () -> control.actuate(permit, () -> fail("old action ran")));
        control.release(stopped.epoch(), () -> {}); begin(); grant(); assertTrue(control.allowed());
    }
    @Test void progressBoundaryDoesNotRevokeAFreshClient() {
        begin(); grant(); now.addAndGet(2000); assertTrue(control.allowed()); assertNull(control.observe(2));
        now.addAndGet(500); assertTrue(control.allowed());
    }
    @Test void anOldPermitCannotActuateEvenAfterANewAutoLease() {
        begin(); grant(); var old = control.permit(); long stopped = control.stop(ControlArbiter.Mode.MANUAL_COMMENTARY);
        control.release(stopped, () -> {}); control.observe(2); begin(); grant();
        assertTrue(control.allowed()); assertThrows(Json.Rejected.class, () -> control.actuate(old, () -> fail("old input")));
        var fresh = control.permit(); java.util.concurrent.atomic.AtomicInteger effects = new java.util.concurrent.atomic.AtomicInteger();
        control.actuate(fresh, effects::incrementAndGet); assertEquals(1, effects.get()); assertFalse(control.released());
    }
    @Test void permitChecksLeaseControllerAndWorldInAdditionToEpoch() {
        begin(); grant(); var good = control.permit();
        for (var bad : java.util.List.of(new ControlArbiter.Permit("other", good.lease(), good.world(), good.epoch()),
                new ControlArbiter.Permit(good.controller(), "old", good.world(), good.epoch()),
                new ControlArbiter.Permit(good.controller(), good.lease(), "other", good.epoch())))
            assertThrows(Json.Rejected.class, () -> control.actuate(bad, () -> fail("wrong context")));
    }
    @Test void aQueuedOldReleaseDoesNotTouchOrConfirmNewInputs() {
        begin(); grant(); long oldEpoch = control.epoch();
        long stopped = control.stop(ControlArbiter.Mode.PAUSED); control.release(stopped, () -> {}); begin(); grant();
        control.actuate(control.permit(), () -> {});
        assertFalse(control.release(oldEpoch, () -> fail("old release touched new input"))); assertFalse(control.released());
        assertTrue(control.release(control.epoch(), () -> {})); assertTrue(control.released());
    }
    @Test void aFailedPhysicalReleaseIsNotReportedAsConfirmed() {
        begin(); grant(); control.actuate(control.permit(), () -> {});
        assertThrows(IllegalStateException.class, () -> control.release(control.epoch(), () -> { throw new IllegalStateException("fixture"); }));
        assertFalse(control.released());
    }
    @Test void failedReleaseAlsoRevokesAnEarlierReleaseConfirmation() {
        assertTrue(control.released());
        assertThrows(IllegalStateException.class, () -> control.release(control.epoch(), () -> { throw new IllegalStateException("fixture"); }));
        assertFalse(control.released());
    }
    @Test void aReleaseCallbackCannotStartAnotherInput() {
        begin(); grant(); var permit = control.permit();
        var denied = assertThrows(Json.Rejected.class, () -> control.release(permit.epoch(), () -> control.actuate(permit, () -> fail("input during release"))));
        assertEquals("GAME_INPUT_RELEASE_IN_PROGRESS", denied.code); assertFalse(control.released()); released(); assertTrue(control.released());
    }
    @Test void anOuterReleaseCannotConfirmANestedNewStopEpoch() {
        long old = control.epoch();
        assertFalse(control.release(old, () -> control.stop(ControlArbiter.Mode.PAUSED)));
        assertTrue(control.epoch() > old); assertFalse(control.released()); released(); assertTrue(control.released());
    }
    @Test void aFailedWriteRetainsAnUnconfirmedInputState() {
        begin(); grant();
        assertThrows(IllegalStateException.class, () -> control.actuate(control.permit(), () -> { throw new IllegalStateException("fixture"); }));
        assertFalse(control.released());
    }
    @Test void revocationSerializesWithThePermissionAndInputWrite() throws Exception {
        begin(); grant(); var permit = control.permit();
        var entered = new java.util.concurrent.CountDownLatch(1); var finish = new java.util.concurrent.CountDownLatch(1);
        var stopAttempt = new java.util.concurrent.CountDownLatch(1); var stopped = new java.util.concurrent.CountDownLatch(1);
        try (var workers = java.util.concurrent.Executors.newFixedThreadPool(2)) {
            var writing = workers.submit(() -> control.actuate(permit, () -> {
                entered.countDown(); try { assertTrue(finish.await(3, java.util.concurrent.TimeUnit.SECONDS)); }
                catch (InterruptedException e) { Thread.currentThread().interrupt(); throw new AssertionError(e); }
            }));
            assertTrue(entered.await(3, java.util.concurrent.TimeUnit.SECONDS));
            var stopping = workers.submit(() -> { stopAttempt.countDown(); control.stop(ControlArbiter.Mode.PAUSED); stopped.countDown(); });
            assertTrue(stopAttempt.await(3, java.util.concurrent.TimeUnit.SECONDS));
            try { assertFalse(stopped.await(30, java.util.concurrent.TimeUnit.MILLISECONDS)); }
            finally { finish.countDown(); }
            writing.get(3, java.util.concurrent.TimeUnit.SECONDS); stopping.get(3, java.util.concurrent.TimeUnit.SECONDS);
        }
        assertFalse(control.allowed()); assertThrows(Json.Rejected.class, () -> control.actuate(permit, () -> fail("late write")));
    }
    @Test void firstRevocationIsPreservedAcrossAnotherStopAndANewGrant() {
        begin(); grant(); var original = control.permit();
        control.stop(ControlArbiter.Mode.MANUAL_COMMENTARY, "PHYSICAL_INPUT");
        control.stop(ControlArbiter.Mode.PAUSED, "DISCONNECTED"); released(); begin(); grant();
        assertEquals("PHYSICAL_INPUT", control.revocationReason(original)); assertTrue(control.allowed());
        assertThrows(Json.Rejected.class, () -> control.actuate(original, () -> fail("revoked action")));
        assertNull(control.revocationReason(control.permit()));
    }
    @Test void worldChangeKeepsItsCauseBeforeQueuedCleanupRuns() {
        begin(); grant(); var original = control.permit(); control.world("world-session-new");
        assertEquals("GAME_WORLD_CHANGED", control.revocationReason(original)); assertFalse(control.released());
        assertThrows(Json.Rejected.class, () -> control.actuate(original, () -> fail("old world effect")));
    }
    @Test void expiryReasonDoesNotRequireOrExtendTheQueuedWatchdog() {
        begin(); grant(); var original = control.permit(); now.addAndGet(3000);
        assertEquals("LEASE_EXPIRED", control.revocationReason(original)); assertEquals(0, control.remaining()); assertFalse(control.allowed());
        assertEquals("LEASE_EXPIRED", control.expireAndStop().reason());
        assertEquals("LEASE_EXPIRED", control.revocationReason(original)); assertFalse(control.released());
    }
    @Test void evictedRevocationsNeverBorrowALaterStopsCause() {
        begin(); grant(); var original = control.permit();
        for (int i = 0; i < 65; i++) control.stop(ControlArbiter.Mode.PAUSED, "LATER_STOP");
        assertNull(control.revocationReason(original));
        assertThrows(Json.Rejected.class, () -> control.actuate(original, () -> fail("evicted authority")));
    }
}
