package dev.aitalkstreamer.mc.survival;

import dev.aitalkstreamer.mc.core.ControlArbiter;
import dev.aitalkstreamer.mc.core.Json;
import org.junit.jupiter.api.*;
import java.util.concurrent.atomic.*;
import static org.junit.jupiter.api.Assertions.*;

/** Real compiled bridge arbiter + real survival authority; only effects and clock are fixtures. */
class ArbiterBoundaryTest {
    private final AtomicLong now = new AtomicLong(10000);
    private final AtomicInteger effects = new AtomicInteger();
    private final ControlArbiter control = new ControlArbiter(now::get, () -> {});
    private SurvivalAuthority.Session session;
    private ArbiterBoundary boundary;
    private SurvivalAuthority.Context context;
    @BeforeEach void setup() {
        control.world("world-one"); control.attach("controller-one"); control.release(control.epoch(), () -> {});
        control.observe(1); begin();
        var permit = control.permit();
        boundary = new ArbiterBoundary(control, permit, "task-one");
        context = new SurvivalAuthority.Context("task-one", permit.controller(), permit.lease(), permit.world(), permit.epoch());
        session = SurvivalAuthority.open(context, boundary);
    }
    private void begin() {
        control.beginAuto("controller-one", "world-one", control.epoch(), true);
        control.grant("controller-one", control.lease(), control.epoch(), 1, control.heartbeat(), 10000);
    }
    @AfterEach void cleanup() { session.close(() -> {}, () -> {}); }
    @Test void boundedEffectUsesTheRealPermitAndMarksInputUnreleased() {
        SurvivalAuthority.run(session, () -> SurvivalAuthority.write(effects::incrementAndGet));
        assertEquals(1, effects.get()); assertFalse(control.released());
    }
    @Test void newAutoGrantCannotMakeTheOldSurvivalRootCurrent() {
        control.stop(ControlArbiter.Mode.PAUSED); control.release(control.epoch(), () -> {}); begin();
        assertFalse(boundary.current(context));
        assertThrows(SurvivalAuthority.Denied.class, () -> SurvivalAuthority.run(session, () -> SurvivalAuthority.write(effects::incrementAndGet)));
        assertEquals(0, effects.get());
    }
    @Test void directOldActuationAlsoFailsAfterRegrant() {
        control.stop(ControlArbiter.Mode.PAUSED); control.release(control.epoch(), () -> {}); begin();
        assertThrows(Json.Rejected.class, () -> boundary.actuate(context, () -> true, effects::incrementAndGet)); assertEquals(0, effects.get());
    }
    @Test void stalledClientCannotActuateEvenWithLongNetworkLease() {
        now.addAndGet(2001);
        assertFalse(boundary.current(context));
        assertThrows(Json.Rejected.class, () -> boundary.actuate(context, () -> true, effects::incrementAndGet)); assertEquals(0, effects.get());
    }
    @Test void changedWorldRefusesTheOriginalSurvivalRoot() {
        control.world("world-two");
        assertFalse(boundary.current(context));
        assertThrows(Json.Rejected.class, () -> boundary.actuate(context, () -> true, effects::incrementAndGet)); assertEquals(0, effects.get());
    }
    @Test void localTaskRevocationIsCheckedInsideTheRealAtomicWrite() {
        session.revoke();
        assertThrows(SurvivalAuthority.Denied.class, () -> boundary.actuate(context, session::current, effects::incrementAndGet)); assertEquals(0, effects.get());
    }
    @Test void mismatchedRootContextCannotUseBoundary() {
        var wrong = new SurvivalAuthority.Context("other-task", context.controller(), context.lease(), context.world(), context.epoch());
        assertFalse(boundary.current(wrong));
        assertThrows(SurvivalAuthority.Denied.class, () -> boundary.actuate(wrong, () -> true, effects::incrementAndGet)); assertEquals(0, effects.get());
    }
    @Test void releaseCriticalSectionCannotBeUsedToRestartAutomation() {
        assertTrue(control.release(control.epoch(), () ->
                assertThrows(Json.Rejected.class, () -> SurvivalAuthority.run(session, () -> SurvivalAuthority.write(effects::incrementAndGet)))));
        assertEquals(0, effects.get());
    }
    @Test void stopAndScopedCleanupCanRunInsideNativeReleaseWithoutLockInversion() {
        control.stop(ControlArbiter.Mode.PAUSED);
        assertTrue(control.release(control.epoch(), () -> session.close(() -> {
            assertFalse(session.current());
        }, () -> {})));
        assertTrue(control.released()); assertEquals(0, effects.get());
    }
}
