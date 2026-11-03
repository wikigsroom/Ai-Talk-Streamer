package dev.aitalkstreamer.mc.survival;

import org.junit.jupiter.api.*;
import java.util.*;
import java.util.concurrent.atomic.*;
import static org.junit.jupiter.api.Assertions.*;

class SurvivalAuthorityTest {
    private static final SurvivalAuthority.Context CONTEXT = new SurvivalAuthority.Context("task-one", "controller-one", "lease-one", "world-one", 7);
    private SurvivalAuthority.Session session;
    private final AtomicBoolean current = new AtomicBoolean(true);
    private final AtomicInteger effects = new AtomicInteger();
    private Runnable beforeActuation = () -> {};
    private final SurvivalAuthority.Boundary boundary = new SurvivalAuthority.Boundary() {
        public boolean current(SurvivalAuthority.Context context) { return current.get() && context.equals(CONTEXT); }
        public synchronized void actuate(SurvivalAuthority.Context context, java.util.function.BooleanSupplier open, Runnable write) {
            beforeActuation.run();
            if (!current(context) || !open.getAsBoolean()) throw new SurvivalAuthority.Denied();
            write.run();
        }
    };
    @BeforeEach void setup() { session = SurvivalAuthority.open(CONTEXT, boundary); }
    @AfterEach void cleanup() { session.close(() -> {}, () -> {}); }
    @Test void inputWithoutAcceptedScopeIsRefused() {
        assertThrows(SurvivalAuthority.Denied.class, () -> SurvivalAuthority.write(effects::incrementAndGet)); assertEquals(0, effects.get());
    }
    @Test void originalContextReachesEveryAtomicWrite() {
        SurvivalAuthority.run(session, () -> { SurvivalAuthority.write(effects::incrementAndGet); SurvivalAuthority.write(effects::incrementAndGet); });
        assertEquals(2, effects.get()); assertFalse(SurvivalAuthority.inScope());
    }
    @Test void revokeBetweenScopeAndActuationRefusesTheEffect() {
        beforeActuation = session::revoke;
        assertThrows(SurvivalAuthority.Denied.class, () -> SurvivalAuthority.run(session, () -> SurvivalAuthority.write(effects::incrementAndGet)));
        assertEquals(0, effects.get());
    }
    @Test void worldOrLeaseChangeBetweenScopeAndActuationRefusesTheEffect() {
        beforeActuation = () -> current.set(false);
        assertThrows(SurvivalAuthority.Denied.class, () -> SurvivalAuthority.run(session, () -> SurvivalAuthority.write(effects::incrementAndGet)));
        assertEquals(0, effects.get());
    }
    @Test void noSecondRootWhileFirstIsActive() { assertThrows(SurvivalAuthority.Denied.class, () -> SurvivalAuthority.open(CONTEXT, boundary)); }
    @Test void revocationAloneDoesNotConfirmCleanup() {
        session.revoke(); assertThrows(SurvivalAuthority.Denied.class, () -> SurvivalAuthority.open(CONTEXT, boundary));
    }
    @Test void cleanupRevokesBeforeTaskStopAndStillReleasesAfterFailure() {
        AtomicBoolean released = new AtomicBoolean();
        assertThrows(IllegalStateException.class, () -> session.close(() -> {
            assertFalse(SurvivalAuthority.inScope());
            assertThrows(SurvivalAuthority.Denied.class, () -> SurvivalAuthority.write(effects::incrementAndGet));
            throw new IllegalStateException("fixture stop failed");
        }, () -> released.set(true)));
        assertTrue(released.get()); assertEquals(0, effects.get());
        assertThrows(SurvivalAuthority.Denied.class, () -> SurvivalAuthority.open(CONTEXT, boundary));
    }
    @Test void failedInputReleaseRetainsOwnershipUntilRetry() {
        assertThrows(IllegalStateException.class, () -> session.close(() -> {}, () -> { throw new IllegalStateException("fixture release failed"); }));
        assertThrows(SurvivalAuthority.Denied.class, () -> SurvivalAuthority.open(CONTEXT, boundary));
        session.close(() -> {}, () -> {}); session = SurvivalAuthority.open(CONTEXT, boundary);
    }
    @Test void bothCleanupFailuresRemainVisible() {
        var error = assertThrows(IllegalStateException.class, () -> session.close(() -> { throw new IllegalStateException("stop"); }, () -> { throw new IllegalArgumentException("release"); }));
        assertEquals("stop", error.getMessage()); assertEquals(1, error.getSuppressed().length);
    }
    @Test void delayedCallbackCannotAcquireANewRoot() {
        List<Runnable> delayed = new ArrayList<>();
        SurvivalAuthority.run(session, () -> delayed.add(SurvivalAuthority.capture(() -> SurvivalAuthority.write(effects::incrementAndGet))));
        session.close(() -> {}, () -> {}); session = SurvivalAuthority.open(CONTEXT, boundary);
        assertThrows(SurvivalAuthority.Denied.class, delayed.getFirst()::run); assertEquals(0, effects.get());
    }
    @Test void oldCloseDoesNotReleaseTheNewRoot() {
        var old = session; old.close(() -> {}, () -> {}); session = SurvivalAuthority.open(CONTEXT, boundary);
        old.close(() -> fail("old stop ran"), () -> fail("old release ran")); assertTrue(session.current());
    }
    @Test void scopeIsRestoredEvenIfPlanningThrows() {
        assertThrows(IllegalArgumentException.class, () -> SurvivalAuthority.run(session, () -> { throw new IllegalArgumentException("fixture planner"); }));
        assertFalse(SurvivalAuthority.inScope()); SurvivalAuthority.run(session, () -> SurvivalAuthority.write(effects::incrementAndGet)); assertEquals(1, effects.get());
    }
    @Test void nestedSameRootReturnsToItsOuterScope() {
        SurvivalAuthority.run(session, () -> { SurvivalAuthority.run(session, () -> SurvivalAuthority.write(effects::incrementAndGet)); assertTrue(SurvivalAuthority.inScope()); });
        assertFalse(SurvivalAuthority.inScope()); assertEquals(1, effects.get());
    }
    @Test void pathWorkerCannotUseClientThreadScopeOrCloseIt() throws InterruptedException {
        AtomicReference<Throwable> failed = new AtomicReference<>(); var original = session;
        Thread thread = new Thread(() -> {
            try { SurvivalAuthority.run(original, () -> SurvivalAuthority.write(effects::incrementAndGet)); }
            catch (Throwable error) { failed.set(error); }
            assertThrows(SurvivalAuthority.Denied.class, () -> original.close(() -> {}, () -> {}));
        });
        thread.start(); thread.join(3000); assertFalse(thread.isAlive()); assertInstanceOf(SurvivalAuthority.Denied.class, failed.get()); assertEquals(0, effects.get());
    }
    @Test void cleanupInsideOldScopeCannotAdoptANewRoot() {
        SurvivalAuthority.run(session, () -> {
            session.close(() -> {}, () -> {});
            assertThrows(SurvivalAuthority.Denied.class, () -> SurvivalAuthority.open(CONTEXT, boundary));
        });
        assertEquals(0, effects.get()); session = SurvivalAuthority.open(CONTEXT, boundary);
    }
    @Test void staleContextCannotOpenEvenWhenThereIsNoOwner() {
        session.close(() -> {}, () -> {}); current.set(false);
        assertThrows(SurvivalAuthority.Denied.class, () -> SurvivalAuthority.open(CONTEXT, boundary));
    }
    @Test void rawCommandsRemainDisabledInsideAValidScope() {
        SurvivalAuthority.run(session, () -> assertFalse(SurvivalAuthority.rawCommandsAllowed()));
    }
    @Test void engineeringCandidateFailsBeforeModInitialization() {
        assertTrue(assertThrows(IllegalStateException.class, () -> new SurvivalLaunchGuard().onPreLaunch()).getMessage().startsWith("GAME_SURVIVAL_RUNTIME_UNACCEPTED"));
    }
}
