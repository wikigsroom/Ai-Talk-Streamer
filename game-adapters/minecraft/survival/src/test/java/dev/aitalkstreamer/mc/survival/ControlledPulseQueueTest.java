package dev.aitalkstreamer.mc.survival;

import adris.altoclef.control.InputControls;
import baritone.api.utils.input.Input;
import dev.aitalkstreamer.mc.core.ControlArbiter;
import org.junit.jupiter.api.*;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

/** The actual patched pulse queue; no client instance, physical input or model is started. */
class ControlledPulseQueueTest {
    private SurvivalAuthority.Session session;
    private final InputControls inputs = new InputControls();
    @BeforeEach void setup() {
        var control = new ControlArbiter(() -> 10000, () -> {});
        control.world("world"); control.attach("controller"); control.release(control.epoch(), () -> {}); control.observe(1);
        control.beginAuto("controller", "world", control.epoch(), true);
        control.grant("controller", control.lease(), control.epoch(), 1, control.heartbeat(), 10000); var permit = control.permit();
        session = SurvivalAuthority.open(new SurvivalAuthority.Context("task", permit.controller(), permit.lease(), permit.world(), permit.epoch()),
                new ArbiterBoundary(control, permit, "task"));
    }
    @SuppressWarnings("unchecked") private <T> T field(String name) {
        try { var field = InputControls.class.getDeclaredField(name); field.setAccessible(true); return (T) field.get(inputs); }
        catch (ReflectiveOperationException error) { throw new AssertionError(error); }
    }
    @AfterEach void cleanup() { session.close(() -> {}, () -> inputs.clearControlledQueue()); }
    @Test void revokedOwnerClearsPendingPulsesWithoutAuthorizingAnotherKeyWrite() {
        Queue<Input> pulses = field("toUnpress"); Set<Input> releases = field("_waitForRelease");
        pulses.add(Input.CLICK_RIGHT); releases.add(Input.CLICK_RIGHT);
        session.close(() -> {}, () -> {
            assertFalse(SurvivalAuthority.inScope()); inputs.clearControlledQueue();
            assertThrows(SurvivalAuthority.Denied.class, () -> SurvivalAuthority.write(() -> fail("revoked write")));
        });
        assertTrue(pulses.isEmpty()); assertTrue(releases.isEmpty());
        // An empty old queue no longer resolves a key binding or emits an old release on the next tick.
        assertDoesNotThrow(inputs::onTickPre);
    }
    @Test void queueResetRequiresTheOwnerAndWorksBeforeTheFirstTaskTick() {
        Queue<Input> pulses = field("toUnpress"); pulses.add(Input.CLICK_LEFT);
        assertThrows(SurvivalAuthority.Denied.class, inputs::clearControlledQueue); assertEquals(1, pulses.size());
        SurvivalAuthority.run(session, inputs::clearControlledQueue); assertTrue(pulses.isEmpty());
    }
}
